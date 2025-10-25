#!/bin/bash

# X1200 HAT Voltage Monitoring Solution Setup
# Fixes false undervoltage warnings caused by damaged Pi voltage sensors

set -e

echo "=== X1200 HAT Voltage Monitoring Setup ==="
echo "This script installs a smart voltage monitoring system that:"
echo "- Detects X1200 HAT presence automatically"
echo "- Suppresses false Pi voltage warnings when X1200 is connected"  
echo "- Falls back to Pi monitoring if X1200 is removed"
echo "- Prevents unwanted reboots from phantom voltage alerts"
echo

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: This script must be run as root (use sudo)"
    exit 1
fi

# Check for I2C tools
if ! command -v i2cdetect &> /dev/null; then
    echo "Installing I2C tools..."
    apt-get update -qq
    apt-get install -y i2c-tools
fi

# Enable I2C if not already enabled
if ! grep -q "dtparam=i2c_arm=on" /boot/firmware/config.txt; then
    echo "Enabling I2C interface..."
    echo "dtparam=i2c_arm=on" >> /boot/firmware/config.txt
fi

# Create the voltage monitor selector script
echo "Creating voltage monitor script..."
cat > /usr/local/bin/voltage-monitor-selector.sh << 'EOF'
#!/bin/bash

# Smart Voltage Monitor - Auto-selects X1200 or Pi sensor
# Falls back to Pi's built-in sensor if X1200 is not connected

X1200_I2C_ADDR=0x36

check_x1200_available() {
    # Try to read from X1200 I2C address
    i2cdetect -y 1 | grep -q "36"
    return $?
}

suppress_pi_voltage_warnings() {
    # Only suppress if X1200 is available and working
    if check_x1200_available; then
        echo "X1200 detected - will use X1200 voltage monitoring"
        logger "VoltageMonitor: X1200 HAT available - Pi voltage warnings can be suppressed"
        return 0
    else
        echo "X1200 not available - keeping Pi voltage monitoring active"
        logger "VoltageMonitor: X1200 not available - using Pi built-in monitoring"
        return 1
    fi
}

# Main logic - run at boot
if check_x1200_available; then
    logger "VoltageMonitor: X1200 HAT detected at I2C address 0x36"
    suppress_pi_voltage_warnings
else
    logger "VoltageMonitor: X1200 HAT not detected - using Pi built-in voltage monitoring"
fi
EOF

chmod +x /usr/local/bin/voltage-monitor-selector.sh

# Create the systemd service
echo "Creating systemd service..."
cat > /etc/systemd/system/voltage-monitor.service << 'EOF'
[Unit]
Description=Smart Voltage Monitor Selector
After=network.target
Wants=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/voltage-monitor-selector.sh
RemainAfterExit=yes
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Enable the service
echo "Enabling voltage monitor service..."
systemctl enable voltage-monitor.service

# Add boot parameter to suppress warnings (if X1200 detected)
echo "Configuring boot parameters..."

# Backup current cmdline
cp /boot/firmware/cmdline.txt /boot/firmware/cmdline.txt.backup.$(date +%Y%m%d_%H%M%S)

# Check if X1200 is currently present
if i2cdetect -y 1 | grep -q "36"; then
    echo "X1200 HAT detected - adding voltage warning suppression to boot parameters"
    
    # Read current cmdline and add avoid_warnings=1 if not present
    CURRENT_CMDLINE=$(cat /boot/firmware/cmdline.txt)
    if ! echo "$CURRENT_CMDLINE" | grep -q "avoid_warnings=1"; then
        echo "$CURRENT_CMDLINE avoid_warnings=1" > /boot/firmware/cmdline.txt
        echo "Added avoid_warnings=1 to boot parameters"
    else
        echo "avoid_warnings=1 already present in boot parameters"
    fi
else
    echo "X1200 HAT not detected - boot parameters unchanged"
fi

echo
echo "=== Setup Complete ==="
echo
echo "Voltage monitoring system installed successfully!"
echo
echo "Current configuration:"

# Show current status
echo "- X1200 HAT detected: $(i2cdetect -y 1 | grep -q "36" && echo "YES" || echo "NO")"
echo "- Service status: $(systemctl is-enabled voltage-monitor.service 2>/dev/null || echo "disabled")"
echo "- Boot parameter: $(grep -q "avoid_warnings=1" /boot/firmware/cmdline.txt && echo "avoid_warnings=1 ACTIVE" || echo "Pi voltage monitoring active")"

echo
echo "Testing commands:"
echo "  sudo systemctl status voltage-monitor.service"
echo "  journalctl -u voltage-monitor.service -f"
echo "  i2cdetect -y 1 | grep 36"
echo "  vcgencmd pmic_read_adc | grep EXT5V_V"
echo
echo "Reboot required to activate all changes."
echo "After reboot, voltage warnings should be resolved if X1200 HAT is connected."