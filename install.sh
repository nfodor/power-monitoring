#!/bin/bash

# X1200 Power Monitor Installation Script

echo "🔧 X1200 Power Monitor Installation"
echo "==================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "❌ Please run as root (use sudo)"
    exit 1
fi

# Install Python dependencies
echo "📦 Installing Python dependencies..."
pip3 install flask flask-cors psutil smbus qrcode pillow

# Optional: Install INA219 support
read -p "Install INA219 support? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    pip3 install adafruit-circuitpython-ina219
fi

# Check if power-dashboard.service exists
if systemctl list-unit-files | grep -q "power-dashboard.service"; then
    echo "⚠️  Existing power-dashboard.service found"
    echo "   Current status:"
    systemctl status power-dashboard.service --no-pager
    
    read -p "Restart service with new configuration? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "🔄 Restarting power-dashboard.service..."
        systemctl restart power-dashboard.service
        sleep 2
        systemctl status power-dashboard.service --no-pager
    fi
else
    echo "📝 Creating systemd service..."
    cat > /etc/systemd/system/power-dashboard.service << EOF
[Unit]
Description=X1200 Power Monitor Dashboard
After=network.target

[Service]
Type=simple
User=pi
Group=pi
WorkingDirectory=/home/pi/dev/power
ExecStart=/usr/bin/python3 /home/pi/dev/power/dashboard_server.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
EOF

    echo "🚀 Enabling and starting service..."
    systemctl daemon-reload
    systemctl enable power-dashboard.service
    systemctl start power-dashboard.service
    sleep 2
    systemctl status power-dashboard.service --no-pager
fi

# Get IP address
IP=$(hostname -I | awk '{print $1}')

echo ""
echo "✅ Installation complete!"
echo ""
echo "📊 Dashboard Access:"
echo "   Local: http://localhost:9434"
echo "   Network: http://$IP:9434"
echo "   Mobile QR: http://$IP:9434/qr"
echo ""
echo "🔧 Service Management:"
echo "   sudo systemctl status power-dashboard.service"
echo "   sudo systemctl restart power-dashboard.service"
echo "   sudo journalctl -u power-dashboard.service -f"
echo ""
echo "📝 To start power logging:"
echo "   python3 /home/pi/dev/power/x1200_power_logger.py"
echo "   python3 /home/pi/dev/power/system_power_logger.py"
echo ""