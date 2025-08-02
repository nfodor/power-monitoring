#!/usr/bin/env python3

import time
import csv
import smbus
import psutil
import os
from datetime import datetime
from bypass_notifier import BypassNotifier

class X1200BatteryMonitor:
    """Monitor Geekworm X1200 UPS using MAX17040G+ fuel gauge"""
    
    def __init__(self):
        self.bus = None
        self.connected = False
        self.device_addr = 0x36  # MAX17040G+ fuel gauge address
        
        # MAX17040G+ register addresses
        self.VCELL_REG = 0x02    # Battery voltage
        self.SOC_REG = 0x04      # State of charge (%)
        self.MODE_REG = 0x06     # Mode register
        self.VERSION_REG = 0x08  # Version register
        self.CONFIG_REG = 0x0C   # Configuration register
        self.COMMAND_REG = 0xFE  # Command register
        
        # Initialize bypass notifier for WireGuard integration
        self.bypass_notifier = BypassNotifier()
        
        self.connect()
    
    def connect(self):
        """Connect to X1200 MAX17040G+ fuel gauge"""
        # Try different I2C buses where X1200 might be connected
        for bus_num in [1, 11, 4]:
            try:
                print(f"Trying X1200 MAX17040G+ on I2C bus {bus_num} at address 0x{self.device_addr:02x}")
                bus = smbus.SMBus(bus_num)
                
                # Test communication by reading version register
                version = bus.read_word_data(self.device_addr, self.VERSION_REG)
                version = ((version & 0xFF) << 8) | ((version & 0xFF00) >> 8)  # Swap bytes
                
                print(f"✅ Connected to X1200 MAX17040G+ (version: 0x{version:04x})")
                self.bus = bus
                self.bus_num = bus_num
                self.connected = True
                return True
                
            except Exception as e:
                if bus:
                    bus.close()
                continue
        
        print("❌ Could not connect to X1200 MAX17040G+ fuel gauge")
        return False
    
    def read_word_swapped(self, register):
        """Read word data with byte swapping for MAX17040G+"""
        if not self.connected:
            return None
            
        try:
            data = self.bus.read_word_data(self.device_addr, register)
            # MAX17040G+ returns MSB first, but SMBus expects LSB first
            return ((data & 0xFF) << 8) | ((data & 0xFF00) >> 8)
        except:
            return None
    
    def get_battery_voltage(self):
        """Get battery voltage in volts"""
        vcell = self.read_word_swapped(self.VCELL_REG)
        if vcell is not None:
            # VCELL register: voltage = value * 1.25mV / 16
            return (vcell >> 4) * 1.25 / 1000.0
        return None
    
    def get_battery_percentage(self):
        """Get battery state of charge as percentage"""
        soc = self.read_word_swapped(self.SOC_REG)
        if soc is not None:
            # SOC register: percentage = value / 256
            return soc / 256.0
        return None
    
    def get_power_data(self):
        """Get comprehensive power data"""
        if not self.connected:
            return None
            
        data = {
            'timestamp': datetime.now().isoformat(),
            'battery_voltage': self.get_battery_voltage(),
            'battery_percentage': self.get_battery_percentage(),
            'cpu_percent': 0,
            'cpu_temp': 0,
            'memory_percent': 0,
            'load_avg': 0,
            'external_power': True,  # TODO: Add GPIO6 detection for actual external power status
            'estimated_runtime_minutes': None
        }
        
        # Add system metrics for power consumption correlation
        try:
            data['cpu_percent'] = psutil.cpu_percent()
            data['memory_percent'] = psutil.virtual_memory().percent
            data['load_avg'] = os.getloadavg()[0]
            
            # CPU temperature
            try:
                with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                    data['cpu_temp'] = float(f.read().strip()) / 1000.0
            except:
                pass
                
        except Exception as e:
            print(f"Warning: Could not read system metrics: {e}")
        
        return data
    
    def detect_power_issues(self, data, history):
        """Detect power-related issues and potential crash conditions"""
        alerts = []
        
        if data['battery_voltage'] is not None:
            # Critical voltage levels for Li-ion batteries
            if data['battery_voltage'] < 3.0:
                alerts.append("CRITICAL_LOW_VOLTAGE")
            elif data['battery_voltage'] < 3.3:
                alerts.append("LOW_VOLTAGE_WARNING")
            elif data['battery_voltage'] > 4.3:
                alerts.append("HIGH_VOLTAGE_WARNING")
        
        if data['battery_percentage'] is not None:
            # Battery percentage alerts
            if data['battery_percentage'] < 10:
                alerts.append("CRITICAL_LOW_BATTERY")
            elif data['battery_percentage'] < 20:
                alerts.append("LOW_BATTERY_WARNING")
        
        # System load alerts (high CPU = high power draw)
        if data['cpu_percent'] > 80:
            alerts.append(f"HIGH_CPU_LOAD_{data['cpu_percent']:.0f}%")
        
        if data['cpu_temp'] > 70:
            alerts.append(f"HIGH_TEMPERATURE_{data['cpu_temp']:.1f}C")
        
        # Rapid battery drain detection
        if len(history) >= 10:
            old_percentage = history[-10]['battery_percentage']
            current_percentage = data['battery_percentage']
            
            if old_percentage and current_percentage:
                drain_rate = (old_percentage - current_percentage) / 10  # % per reading
                if drain_rate > 1.0:  # More than 1% per reading (5 seconds)
                    alerts.append(f"RAPID_BATTERY_DRAIN_{drain_rate:.1f}%_per_5s")
        
        return alerts
    
    def close(self):
        """Close I2C connection"""
        if self.bus:
            self.bus.close()

def main():
    """Main X1200 monitoring function"""
    monitor = X1200BatteryMonitor()
    
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