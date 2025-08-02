# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

X1200 UPS Power Monitoring System for Raspberry Pi - A comprehensive power monitoring suite designed to detect and prevent system crashes by monitoring voltage drops, current spikes, and system health metrics.

## Architecture

The system consists of multiple monitoring scripts and a web dashboard:

1. **x1200_power_logger.py** - Main power monitoring for X1200 UPS via I2C
2. **x1200_battery_logger.py** - Battery-specific monitoring using MAX17040G+ fuel gauge
3. **system_power_logger.py** - System-level power and performance monitoring
4. **log_power_ina219.py** - Alternative INA219-based power monitoring
5. **dashboard_server.py** - Flask web server providing real-time dashboard
6. **dashboard.html** - Interactive web dashboard with charts and alerts
7. **x1200_diagnostics.py** - Diagnostic tool for troubleshooting I2C connections
8. **x1200_enhanced_monitor.py** - Complete X1200 monitoring with GPIO integration

## Common Development Tasks

### Running the Power Monitor
```bash
# Start X1200 power monitoring
python3 x1200_power_logger.py

# Start battery monitoring
python3 x1200_battery_logger.py

# Start system monitoring (fallback if X1200 not connected)  
python3 system_power_logger.py

# Start enhanced X1200 monitoring (with GPIO integration)
python3 x1200_enhanced_monitor.py

# Start web dashboard
python3 dashboard_server.py
# Then access: http://localhost:9434 or http://<pi-ip>:9434
```

### Systemd Service Management
```bash
# The dashboard is installed as a systemd service
sudo systemctl status power-dashboard.service
sudo systemctl restart power-dashboard.service
sudo systemctl enable power-dashboard.service

# View logs
sudo journalctl -u power-dashboard.service -f
```

### Running Diagnostics
```bash
# Check I2C configuration and scan for devices
python3 x1200_diagnostics.py

# Check I2C devices manually
sudo i2cdetect -y 1
sudo i2cdetect -y 11
```

### Installing Dependencies
```bash
# Core dependencies
pip3 install flask flask-cors psutil smbus qrcode

# For INA219 monitoring (optional)
pip3 install adafruit-circuitpython-ina219
```

## High-Level Architecture

### I2C Communication
- X1200 UPS uses I2C for communication
- Multiple I2C bus configurations supported (buses 1, 4, 11)
- **Primary**: 0x36 (MAX17040G+ fuel gauge)
- **Secondary**: 0x40-0x45 (INA219), 0x5d, 0x65

### GPIO Integration
- **GPIO16**: Battery charging control/status (0=charging, 1=not charging)
- **GPIO6**: Power loss detection (0=power lost, 1=external power present)
- **Automatic Setup**: Configures GPIO via sysfs or gpiod tools

### Data Flow
1. Hardware sensors → Python monitoring scripts → CSV log files
2. CSV files + Live data → Flask API → JSON responses
3. Web dashboard polls API every 5 seconds → Real-time charts

### Key Monitoring Thresholds
- **Low Voltage**: < 10.5V (critical for crash prevention)
- **High Current**: > 4000mA (indicates power spike)
- **CPU Temperature**: > 70°C (thermal throttling risk)
- **CPU Usage**: > 80% (high load indicator)
- **Memory Usage**: > 90% (system stress)

### Web Dashboard Features
- Real-time metrics display
- Historical data charts (CPU, memory, temperature, power)
- **Enhanced X1200 Support**:
  - Battery percentage and voltage
  - Power source (External USB-C vs Battery)
  - Charging status indicator
  - Power loss event detection
- Critical indicators panel (appears when issues detected)
- Process monitoring (top CPU/memory consumers)
- System error log analysis
- Kernel message monitoring
- QR code for mobile access
- **Default Port**: 9434 (changed from 8080 to avoid conflicts)

### API Endpoints (dashboard_server.py:9434)
- `/api/power-data` - Latest power readings
- `/api/historical-data?hours=N` - Historical data
- `/api/system-stats` - System statistics
- `/api/alerts` - Current alerts
- `/api/critical-indicators` - Comprehensive health check
- `/api/top-processes` - Resource-intensive processes
- `/api/syslog-errors` - Recent system errors
- `/api/kernel-messages` - Kernel error messages

### Crash Detection Algorithm
The system uses multiple indicators to predict potential crashes:
1. Consecutive voltage drops (3+ readings below 10.5V)
2. High CPU temperature (>80°C = 30% risk increase)
3. High system load (>8 = 20% risk increase)
4. Critical system errors in logs
5. Kernel panic/segfault messages
6. Rapid battery drain detection

### Log File Locations
- `/home/pi/x1200_power_log.csv` - X1200 power data
- `/home/pi/x1200_battery_log.csv` - Battery monitoring data
- `/home/pi/x1200_enhanced_log.csv` - Enhanced monitoring with GPIO data
- `/home/pi/system_power_log.csv` - System performance data
- `/home/pi/power_log.csv` - INA219 power data

## Important Notes

- Always check I2C is enabled: `sudo raspi-config` → Interface Options → I2C
- X1200 must be properly seated on GPIO pins
- Some monitoring scripts require root/sudo for hardware access
- Dashboard server runs on port 9434 by default
- Mobile access via QR code at `/qr` endpoint
- Dashboard service is managed by systemd as `power-dashboard.service`

## UI/UX Guidelines

- **NEVER use square emoji icons** in web interfaces - they render as empty squares on Linux browsers
- Use text indicators, Unicode symbols, or proper HTML entities instead
- Examples:
  - Bad: 🔋 (square emoji)
  - Good: "Battery", "BATT", "●" (bullet), "▲" (triangle), "+", "-", "ON", "OFF"
- Linux browser compatibility is essential for headless Pi systems
- Prefer CSS symbols, Font Awesome, or simple text over emoji icons