#!/bin/bash

# X1200 Power Monitor Management Script

case "$1" in
    start)
        echo "🚀 Starting power monitoring..."
        python3 /home/pi/dev/power/system_power_logger.py &
        echo "✅ Power logger started in background"
        ;;
    
    stop)
        echo "🛑 Stopping power monitoring..."
        pkill -f "system_power_logger.py"
        pkill -f "x1200_power_logger.py"
        pkill -f "x1200_battery_logger.py"
        echo "✅ Power loggers stopped"
        ;;
    
    status)
        echo "📊 Power Monitor Status"
        echo "======================"
        echo ""
        echo "Dashboard Service:"
        systemctl status power-dashboard.service --no-pager | grep -E "Active:|Main PID:"
        echo ""
        echo "Running Loggers:"
        ps aux | grep -E "power_logger|battery_logger" | grep -v grep || echo "  None running"
        echo ""
        echo "Dashboard URL: http://$(hostname -I | awk '{print $1}'):9434"
        ;;
    
    logs)
        echo "📝 Recent Dashboard Logs:"
        journalctl -u power-dashboard.service -n 50 --no-pager
        ;;
    
    restart)
        echo "🔄 Restarting dashboard service..."
        sudo systemctl restart power-dashboard.service
        sleep 2
        systemctl status power-dashboard.service --no-pager | grep -E "Active:|Main PID:"
        ;;
    
    diagnose)
        echo "🔍 Running X1200 diagnostics..."
        python3 /home/pi/dev/power/x1200_diagnostics.py
        ;;
    
    *)
        echo "X1200 Power Monitor Control"
        echo "Usage: $0 {start|stop|status|logs|restart|diagnose}"
        echo ""
        echo "Commands:"
        echo "  start    - Start power logging in background"
        echo "  stop     - Stop all power loggers"
        echo "  status   - Show current status"
        echo "  logs     - View recent dashboard logs"
        echo "  restart  - Restart dashboard service"
        echo "  diagnose - Run I2C diagnostics"
        ;;
esac