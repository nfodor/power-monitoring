import time
import csv
import psutil
import os
from datetime import datetime
from bypass_notifier import BypassNotifier
from x1200_common import X1200Monitor

def main():
    """Main X1200 monitoring function"""
    monitor = X1200Monitor()
    
    if not monitor.connected:
        print("❌ Failed to connect to X1200. Check:")
        print("1. X1200 is properly connected to GPIO")
        print("2. I2C is enabled (sudo raspi-config)")
        print("3. X1200 is powered on")
        return
    
    # Setup CSV logging
    csv_filename = "/home/pi/x1200_battery_log.csv"
    
    # Write header if file is new
    try:
        with open(csv_filename, 'x', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([
                "Timestamp", "Battery Voltage (V)", "Battery %", "CPU %", 
                "CPU Temp (C)", "Memory %", "Load Avg", "Alerts", "Notes"
            ])
    except FileExistsError:
        pass
    
    print(f"🔋 X1200 UPS Battery Monitor")
    print(f"📊 Logging to: {csv_filename}")
    print(f"🔌 Connected via I2C bus {monitor.bus_num}")
    print("⚠️  Monitoring for voltage drops, rapid drain, and system load")
    print("🚨 Will alert on critical battery levels and potential crash conditions")
    print("Press Ctrl+C to stop logging")
    
    history = []
    
    try:
        while True:
            data = monitor.get_power_data()
            
            if data is None:
                print("❌ Failed to read X1200 data")
                time.sleep(5)
                continue
            
            history.append(data)
            if len(history) > 50:  # Keep last 50 readings (4+ minutes)
                history.pop(0)
            
            # Detect issues
            alerts = monitor.detect_power_issues(data, history)
            alert_str = " ".join(alerts) if alerts else ""
            
            # Generate notes
            notes = ""
            if data['battery_percentage'] and data['battery_percentage'] < 30:
                notes += "LOW_BATTERY_MODE "
            if data['cpu_temp'] > 60:
                notes += "THERMAL_CONCERN "
            if data['battery_voltage'] and data['battery_voltage'] < 3.5:
                notes += "VOLTAGE_CONCERN "
            
            # Log to CSV
            with open(csv_filename, 'a', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([
                    data['timestamp'],
                    f"{data['battery_voltage']:.3f}" if data['battery_voltage'] else "N/A",
                    f"{data['battery_percentage']:.1f}" if data['battery_percentage'] else "N/A",
                    f"{data['cpu_percent']:.1f}",
                    f"{data['cpu_temp']:.1f}",
                    f"{data['memory_percent']:.1f}",
                    f"{data['load_avg']:.2f}",
                    alert_str,
                    notes.strip()
                ])
            
            # Console output with status indicators
            if alerts:
                status = "🚨"
            elif notes:
                status = "⚠️"
            else:
                status = "✅"
            
            voltage_str = f"{data['battery_voltage']:.2f}V" if data['battery_voltage'] else "N/A"
            battery_str = f"{data['battery_percentage']:.0f}%" if data['battery_percentage'] else "N/A"
            
            print(f"{status} {data['timestamp']}: "
                  f"🔋 {battery_str} ({voltage_str}), "
                  f"💻 CPU {data['cpu_percent']:.0f}%, "
                  f"🌡️ {data['cpu_temp']:.1f}°C")
            
            # Print alerts on separate line for visibility
            if alerts:
                print(f"   🚨 ALERTS: {', '.join(alerts)}")
            
            # Estimate runtime based on current drain
            if len(history) >= 5 and data['battery_percentage']:
                recent_drain = []
                for i in range(1, min(6, len(history))):
                    if history[-i]['battery_percentage'] and history[-i-1]['battery_percentage']:
                        drain = history[-i-1]['battery_percentage'] - history[-i]['battery_percentage']
                        recent_drain.append(drain)
                
                if recent_drain:
                    avg_drain_per_5s = sum(recent_drain) / len(recent_drain)
                    if avg_drain_per_5s > 0:
                        remaining_time_minutes = (data['battery_percentage'] / avg_drain_per_5s) * 5 / 60
                        data['estimated_runtime_minutes'] = remaining_time_minutes
                        if remaining_time_minutes < 60:
                            print(f"   ⏱️  Estimated runtime: {remaining_time_minutes:.0f} minutes")
            
            # Monitor WireGuard and notify bypass server
            try:
                monitor.bypass_notifier.monitor_wireguard_status(data)
                monitor.bypass_notifier.track_battery_runtime(data)
            except Exception as e:
                print(f"   ⚠️  Bypass notification error: {e}")
            
            time.sleep(5)  # Log every 5 seconds
            
    except KeyboardInterrupt:
        print("\n📊 X1200 monitoring stopped by user.")
        print(f"📁 Log file saved: {csv_filename}")
        
        # Print session summary
        if history:
            voltages = [h['battery_voltage'] for h in history if h['battery_voltage']]
            percentages = [h['battery_percentage'] for h in history if h['battery_percentage']]
            
            if voltages and percentages:
                print(f"📈 Session summary:")
                print(f"   Battery voltage: {min(voltages):.2f}V - {max(voltages):.2f}V")
                print(f"   Battery level: {min(percentages):.0f}% - {max(percentages):.0f}%")
                print(f"   Readings logged: {len(history)}")
                
                if len(history) > 1:
                    total_drain = percentages[0] - percentages[-1]
                    time_span = len(history) * 5 / 60  # minutes
                    print(f"   Battery drain: {total_drain:.1f}% over {time_span:.1f} minutes")
        
    except Exception as e:
        print(f"❌ Fatal error: {e}")
    finally:
        monitor.close()

if __name__ == "__main__":
    main()

