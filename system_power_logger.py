#!/usr/bin/env python3

import time
import csv
import os
import psutil
from datetime import datetime

class SystemPowerMonitor:
    """Monitor system power using available system interfaces"""
    
    def __init__(self):
        self.power_sources = []
        self.find_power_sources()
        
    def find_power_sources(self):
        """Find available power monitoring interfaces"""
        print("🔍 Scanning for power monitoring interfaces...")
        
        # Check /sys/class/power_supply
        power_supply_path = "/sys/class/power_supply"
        if os.path.exists(power_supply_path):
            for device in os.listdir(power_supply_path):
                device_path = os.path.join(power_supply_path, device)
                if os.path.isdir(device_path):
                    self.power_sources.append({
                        'name': device,
                        'path': device_path,
                        'type': 'power_supply'
                    })
                    print(f"   📡 Found power device: {device}")
        
        # Check for thermal data (can indicate power consumption)
        thermal_path = "/sys/class/thermal"
        if os.path.exists(thermal_path):
            for device in os.listdir(thermal_path):
                if device.startswith('thermal_zone'):
                    device_path = os.path.join(thermal_path, device)
                    self.power_sources.append({
                        'name': device,
                        'path': device_path,
                        'type': 'thermal'
                    })
                    print(f"   🌡️  Found thermal zone: {device}")
        
        # Add CPU and system monitoring
        self.power_sources.append({
            'name': 'system_cpu',
            'path': '/proc/stat',
            'type': 'cpu'
        })
        print(f"   💻 Added CPU monitoring")
        
        if not self.power_sources:
            print("   ⚠️  No power monitoring interfaces found")
            
    def read_file_value(self, filepath):
        """Safely read a value from a file"""
        try:
            with open(filepath, 'r') as f:
                return f.read().strip()
        except:
            return None
    
    def get_power_data(self):
        """Collect power data from all available sources"""
        data = {
            'timestamp': datetime.now().isoformat(),
            'cpu_percent': 0,
            'memory_percent': 0,
            'cpu_temp': 0,
            'load_avg': 0,
            'voltage': 0,
            'current': 0,
            'power': 0
        }
        
        # System performance metrics (indirect power indicators)
        try:
            data['cpu_percent'] = psutil.cpu_percent()
            data['memory_percent'] = psutil.virtual_memory().percent
            data['load_avg'] = os.getloadavg()[0]
        except:
            pass
        
        # Check power supply devices
        for source in self.power_sources:
            if source['type'] == 'power_supply':
                # Read voltage, current, power if available
                voltage_file = os.path.join(source['path'], 'voltage_now')
                current_file = os.path.join(source['path'], 'current_now')
                power_file = os.path.join(source['path'], 'power_now')
                
                voltage = self.read_file_value(voltage_file)
                current = self.read_file_value(current_file)
                power = self.read_file_value(power_file)
                
                if voltage:
                    data['voltage'] = float(voltage) / 1000000  # Convert µV to V
                if current:
                    data['current'] = float(current) / 1000  # Convert µA to mA
                if power:
                    data['power'] = float(power) / 1000  # Convert µW to mW
                    
            elif source['type'] == 'thermal':
                # Read temperature
                temp_file = os.path.join(source['path'], 'temp')
                temp = self.read_file_value(temp_file)
                if temp and 'cpu' in source['name'].lower():
                    data['cpu_temp'] = float(temp) / 1000  # Convert milli-C to C
        
        # Raspberry Pi specific CPU temperature
        try:
            cpu_temp = self.read_file_value('/sys/class/thermal/thermal_zone0/temp')
            if cpu_temp:
                data['cpu_temp'] = float(cpu_temp) / 1000
        except:
            pass
            
        return data
    
    def detect_issues(self, data, history):
        """Detect potential power/performance issues"""
        alerts = []
        
        # High CPU usage (potential power draw)
        if data['cpu_percent'] > 80:
            alerts.append(f"HIGH_CPU_{data['cpu_percent']:.0f}%")
        
        # High temperature (indicates high power consumption)
        if data['cpu_temp'] > 70:
            alerts.append(f"HIGH_TEMP_{data['cpu_temp']:.1f}C")
        
        # High system load
        if data['load_avg'] > 2.0:
            alerts.append(f"HIGH_LOAD_{data['load_avg']:.1f}")
        
        # Low voltage (if available)
        if data['voltage'] > 0 and data['voltage'] < 4.8:
            alerts.append(f"LOW_VOLTAGE_{data['voltage']:.2f}V")
        
        # Memory pressure
        if data['memory_percent'] > 90:
            alerts.append(f"HIGH_MEMORY_{data['memory_percent']:.0f}%")
        
        # Check for sudden changes if we have history
        if len(history) > 5:
            recent_cpu = [h['cpu_percent'] for h in history[-5:]]
            if max(recent_cpu) - min(recent_cpu) > 50:
                alerts.append("CPU_SPIKE")
        
        return alerts

def main():
    """Main power monitoring function"""
    monitor = SystemPowerMonitor()
    
    if not monitor.power_sources:
        print("⚠️  Limited power monitoring available - using system metrics only")
    
    # Setup CSV logging
    csv_filename = "/home/pi/system_power_log.csv"
    
    # Write header if file is new
    try:
        with open(csv_filename, 'x', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([
                "Timestamp", "CPU %", "Memory %", "CPU Temp (C)", "Load Avg",
                "Voltage (V)", "Current (mA)", "Power (mW)", "Alerts", "Notes"
            ])
    except FileExistsError:
        pass  # File already exists, append to it
    
    print(f"📊 Logging system power data to {csv_filename}")
    print("🖥️  Monitoring CPU, memory, temperature, and available power metrics")
    print("⚠️  Watching for high CPU, temperature, and system load issues")
    print("Press Ctrl+C to stop logging")
    
    history = []
    
    try:
        while True:
            data = monitor.get_power_data()
            history.append(data)
            
            # Keep only last 20 readings for trend analysis
            if len(history) > 20:
                history.pop(0)
            
            # Detect issues
            alerts = monitor.detect_issues(data, history)
            alert_str = " ".join(alerts) if alerts else ""
            
            # Generate notes based on system state
            notes = ""
            if data['cpu_temp'] > 60:
                notes += "THERMAL_CONCERN "
            if data['load_avg'] > 1.5:
                notes += "SYSTEM_LOAD "
            if data['voltage'] > 0 and data['voltage'] < 5.0:
                notes += "VOLTAGE_CONCERN "
                
            # Log to CSV
            with open(csv_filename, 'a', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([
                    data['timestamp'],
                    f"{data['cpu_percent']:.1f}",
                    f"{data['memory_percent']:.1f}",
                    f"{data['cpu_temp']:.1f}",
                    f"{data['load_avg']:.2f}",
                    f"{data['voltage']:.3f}" if data['voltage'] > 0 else "N/A",
                    f"{data['current']:.0f}" if data['current'] > 0 else "N/A",
                    f"{data['power']:.0f}" if data['power'] > 0 else "N/A",
                    alert_str,
                    notes.strip()
                ])
            
            # Console output with color coding
            alert_indicator = "🚨" if alerts else ("⚠️" if notes else "✅")
            voltage_str = f"{data['voltage']:.2f}V" if data['voltage'] > 0 else "N/A"
            power_str = f"{data['power']:.0f}mW" if data['power'] > 0 else "N/A"
            
            print(f"{alert_indicator} {data['timestamp']}: "
                  f"CPU {data['cpu_percent']:.0f}%, "
                  f"Temp {data['cpu_temp']:.1f}°C, "
                  f"Load {data['load_avg']:.1f}, "
                  f"V:{voltage_str}, P:{power_str}")
            
            if alerts:
                print(f"   🚨 ALERTS: {', '.join(alerts)}")
            
            time.sleep(5)  # Log every 5 seconds
            
    except KeyboardInterrupt:
        print("\n📊 System power logging stopped by user.")
        print(f"📁 Log file saved: {csv_filename}")
        
        # Print summary
        if history:
            avg_cpu = sum(h['cpu_percent'] for h in history) / len(history)
            max_temp = max(h['cpu_temp'] for h in history)
            print(f"📈 Session summary:")
            print(f"   Average CPU usage: {avg_cpu:.1f}%")
            print(f"   Peak temperature: {max_temp:.1f}°C")
            print(f"   Readings logged: {len(history)}")
            
    except Exception as e:
        print(f"❌ Fatal error: {e}")

if __name__ == "__main__":
    main()