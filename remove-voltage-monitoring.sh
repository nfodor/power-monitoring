#!/bin/bash

# X1200 HAT Voltage Monitoring Solution Removal
# Removes voltage monitoring system and restores Pi default behavior

set -e

echo "=== X1200 HAT Voltage Monitoring Removal ==="
echo "This script will:"
echo "- Remove smart voltage monitoring system"
echo "- Restore Pi's default voltage monitoring behavior"
echo "- Clean up systemd service and boot parameters"
echo

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: This script must be run as root (use sudo)"
    exit 1
fi

read -p "Are you sure you want to remove the voltage monitoring system? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Removal cancelled."
    exit 0
fi

echo "Removing voltage monitoring system..."

# Stop and disable the service
if systemctl is-active --quiet voltage-monitor.service; then
    echo "Stopping voltage monitor service..."
    systemctl stop voltage-monitor.service
fi

if systemctl is-enabled --quiet voltage-monitor.service; then
    echo "Disabling voltage monitor service..."
    systemctl disable voltage-monitor.service
fi

# Remove systemd service file
if [ -f "/etc/systemd/system/voltage-monitor.service" ]; then
    echo "Removing systemd service file..."
    rm -f /etc/systemd/system/voltage-monitor.service
    systemctl daemon-reload
fi

# Remove voltage monitor script
if [ -f "/usr/local/bin/voltage-monitor-selector.sh" ]; then
    echo "Removing voltage monitor script..."
    rm -f /usr/local/bin/voltage-monitor-selector.sh
fi

# Restore boot parameters (remove avoid_warnings=1)
echo "Restoring boot parameters..."
if [ -f "/boot/firmware/cmdline.txt" ]; then
    # Backup current cmdline
    cp /boot/firmware/cmdline.txt /boot/firmware/cmdline.txt.backup.$(date +%Y%m%d_%H%M%S)
    
    # Remove avoid_warnings=1 from cmdline
    CURRENT_CMDLINE=$(cat /boot/firmware/cmdline.txt)
    NEW_CMDLINE=$(echo "$CURRENT_CMDLINE" | sed 's/ avoid_warnings=1//g' | sed 's/avoid_warnings=1 //g' | sed 's/avoid_warnings=1//g')
    echo "$NEW_CMDLINE" > /boot/firmware/cmdline.txt
    
    echo "Removed avoid_warnings=1 from boot parameters"
fi

echo
echo "=== Removal Complete ==="
echo
echo "Voltage monitoring system removed successfully!"
echo
echo "System status:"
echo "- Voltage monitor service: REMOVED"
echo "- Boot parameter: Pi default voltage monitoring restored"
echo "- I2C interface: $(grep -q "dtparam=i2c_arm=on" /boot/firmware/config.txt && echo "still enabled (kept for other uses)" || echo "not configured")"

echo
echo "After reboot, the system will use Pi's default voltage monitoring behavior."
echo "If X1200 HAT voltage regulator is faulty, you may see voltage warnings again."
echo
echo "Reboot required to fully activate changes."