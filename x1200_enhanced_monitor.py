import time
import csv
import os
from datetime import datetime
import subprocess
from x1200_common import X1200Monitor

class X1200EnhancedMonitor(X1200Monitor):
    """Enhanced X1200 UPS monitoring with GPIO indicators"""
    
    def __init__(self):
        super().__init__()

    def estimate_battery_current(self, voltage, percentage, prev_data, time_delta):
        """Estimate battery current based on voltage and capacity changes"""
        if not prev_data or time_delta <= 0:
            return None
            
        # Estimate based on percentage change
        # Assuming 2x 18650 batteries with ~2500mAh each = 5000mAh total
        total_capacity_mah = 5000
        
        percentage_change = percentage - prev_data['battery_percentage']
        capacity_change_mah = (percentage_change / 100) * total_capacity_mah
        
        # Current in mA = capacity change / time in hours
        current_ma = (capacity_change_mah / time_delta) * 3600
        
        return current_ma
    
    def get_comprehensive_data(self, prev_data=None):
        """Get all available power data"""
        data = {
            'timestamp': datetime.now().isoformat(),
            'battery_voltage': self.get_battery_voltage(),
            'battery_percentage': self.get_battery_percentage(),
            'is_charging': self.is_charging(),
            'has_external_power': self.has_external_power(),
            'power_source': self.get_power_source(),
            'estimated_current': None
        }
        
        # Estimate current if we have previous data
        if prev_data and data['battery_voltage'] and data['battery_percentage']:
            time_delta = (datetime.fromisoformat(data['timestamp']) - 
                         datetime.fromisoformat(prev_data['timestamp'])).total_seconds()
            data['estimated_current'] = self.estimate_battery_current(
                data['battery_voltage'], 
                data['battery_percentage'],
                prev_data, 
                time_delta
            )
        
        # Add system metrics
        try:
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                data['cpu_temp'] = float(f.read().strip()) / 1000.0
        except:
            data['cpu_temp'] = None
        
        # Get system load
        try:
            data['load_avg'] = os.getloadavg()[0]
        except:
            data['load_avg'] = None
        
        return data
    
    def detect_critical_events(self, data, history):
        """Detect critical power events"""
        events = []
        
        # Power loss event
        if data['has_external_power'] == False:
            events.append("POWER_LOSS_DETECTED")
        
        # Charging state changes
        if len(history) > 0:
            prev = history[-1]
            if prev['is_charging'] != data['is_charging']:
                if data['is_charging']:
                    events.append("CHARGING_STARTED")
                else:
                    events.append("CHARGING_STOPPED")
            
            if prev['has_external_power'] != data['has_external_power']:
                if data['has_external_power']:
                    events.append("EXTERNAL_POWER_CONNECTED")
                else:
                    events.append("EXTERNAL_POWER_LOST")
        
        # Battery critical levels
        if data['battery_percentage'] is not None:
            if data['battery_percentage'] < 10:
                events.append("CRITICAL_BATTERY_LEVEL")
            elif data['battery_percentage'] < 20:
                events.append("LOW_BATTERY_WARNING")
        
        # Voltage issues
        if data['battery_voltage'] is not None:
            if data['battery_voltage'] < 3.0:
                events.append("CRITICAL_LOW_VOLTAGE")
            elif data['battery_voltage'] > 4.3:
                events.append("OVER_VOLTAGE_WARNING")
        
        # High discharge rate
        if data['estimated_current'] is not None and data['estimated_current'] < -2000:
            events.append(f"HIGH_DISCHARGE_RATE_{abs(data['estimated_current']):.0f}mA")
        
        return events

def main():
    """Main enhanced monitoring function"""
    monitor = X1200EnhancedMonitor()
    
    if not monitor.connected:
        print("❌ Failed to connect to X1200")
        return
    
    # Setup CSV logging
    csv_filename = "/home/pi/x1200_enhanced_log.csv"
    
    # Write header if file is new
    try:
        with open(csv_filename, 'x', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([
                "Timestamp", "Battery Voltage (V)", "Battery %", "Power Source",
                "Is Charging", "Has External Power", "Estimated Current (mA)",
                "CPU Temp (C)", "Load Avg", "Events", "Notes"
            ])
    except FileExistsError:
        pass
    
    print(f"🔋 X1200 Enhanced UPS Monitor")
    print(f"📊 Logging to: {csv_filename}")
    print(f"🔌 Connected via I2C bus {monitor.bus_num}")
    print("⚡ Monitoring power source, charging status, and critical events")
    print("Press Ctrl+C to stop logging")
    
    history = []
    prev_data = None
    
    try:
        while True:
            data = monitor.get_comprehensive_data(prev_data)
            
            if data is None:
                print("❌ Failed to read X1200 data")
                time.sleep(5)
                continue
            
            history.append(data)
            if len(history) > 50:
                history.pop(0)
            
            # Detect critical events
            events = monitor.detect_critical_events(data, history)
            event_str = " ".join(events) if events else ""
            
            # Generate notes
            notes = ""
            if data['power_source'] == "Battery":
                notes += "RUNNING_ON_BATTERY "
            if data['is_charging'] and data['battery_percentage'] and data['battery_percentage'] > 95:
                notes += "TRICKLE_CHARGE "
            if data['cpu_temp'] and data['cpu_temp'] > 70:
                notes += "HIGH_TEMPERATURE "
            
            # Log to CSV
            with open(csv_filename, 'a', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([
                    data['timestamp'],
                    f"{data['battery_voltage']:.3f}" if data['battery_voltage'] else "N/A",
                    f"{data['battery_percentage']:.1f}" if data['battery_percentage'] else "N/A",
                    data['power_source'],
                    "Yes" if data['is_charging'] else "No",
                    "Yes" if data['has_external_power'] else "No",
                    f"{data['estimated_current']:.0f}" if data['estimated_current'] else "N/A",
                    f"{data['cpu_temp']:.1f}" if data['cpu_temp'] else "N/A",
                    f"{data['load_avg']:.2f}" if data['load_avg'] else "N/A",
                    event_str,
                    notes.strip()
                ])
            
            # Console output with enhanced status
            if events:
                status = "🚨"
            elif notes:
                status = "⚠️"
            else:
                status = "✅"
            
            voltage_str = f"{data['battery_voltage']:.2f}V" if data['battery_voltage'] else "N/A"
            battery_str = f"{data['battery_percentage']:.0f}%" if data['battery_percentage'] else "N/A"
            
            print(f"{status} {data['timestamp']}: "
                  f"🔋 {battery_str} ({voltage_str}), "
                  f"⚡ {data['power_source']}, "
                  f"{('🔌 Charging' if data['is_charging'] else '🔋 Discharging')}")
            
            # Print events on separate line for visibility
            if events:
                print(f"   🚨 EVENTS: {', '.join(events)}")
            
            # Update previous data for next iteration
            prev_data = data
            
            time.sleep(5)  # Log every 5 seconds
            
    except KeyboardInterrupt:
        print("\n📊 Enhanced monitoring stopped by user.")
        print(f"📁 Log file saved: {csv_filename}")
        
    except Exception as e:
        print(f"❌ Fatal error: {e}")
    finally:
        if monitor.bus:
            monitor.bus.close()

if __name__ == "__main__":
    main()
