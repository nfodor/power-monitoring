#!/usr/bin/env python3

import time
import csv
import smbus
from datetime import datetime

# X1200 UPS Power Monitor
# Geekworm X1200 uses specific I2C registers for power monitoring

class X1200PowerMonitor:
    def __init__(self):
        self.bus = None
        self.device_addr = None
        self.connected = False
        
        # X1200 specific addresses and registers
        self.possible_configs = [
            {'bus': 11, 'addr': 0x65, 'name': 'X1200 Power Monitor (detected)'},
            {'bus': 4, 'addr': 0x65, 'name': 'X1200 Power Monitor Alt (detected)'},
            {'bus': 11, 'addr': 0x45, 'name': 'X1200 INA219 Primary'},
            {'bus': 4, 'addr': 0x45, 'name': 'X1200 INA219 Secondary'},
            {'bus': 11, 'addr': 0x5d, 'name': 'X1200 MCU/Controller'},
            {'bus': 4, 'addr': 0x5d, 'name': 'X1200 MCU/Controller Alt'},
            {'bus': 1, 'addr': 0x40, 'name': 'Standard INA219'},
        ]
        
        self.connect()
    
    def connect(self):
        """Try to connect to X1200 power monitoring device"""
        for config in self.possible_configs:
            try:
                print(f"Trying {config['name']} on bus {config['bus']}, address 0x{config['addr']:02x}")
                bus = smbus.SMBus(config['bus'])
                
                # Test basic communication
                try:
                    # Try to read a register (register 0 is usually safe)
                    data = bus.read_word_data(config['addr'], 0)
                    self.bus = bus
                    self.device_addr = config['addr']
                    self.bus_num = config['bus']
                    self.device_name = config['name']
                    self.connected = True
                    print(f"✅ Connected to {config['name']}")
                    return True
                except Exception as e:
                    bus.close()
                    continue
                    
            except Exception as e:
                continue
        
        print("❌ Could not connect to X1200 power monitor")
        return False
    
    def read_power_data(self):
        """Read power data from X1200"""
        if not self.connected:
            return None
            
        try:
            # Standard INA219 registers
            # Register 0x01: Configuration
            # Register 0x02: Shunt Voltage
            # Register 0x04: Bus Voltage
            # Register 0x05: Power
            # Register 0x06: Current
            
            # Read bus voltage (register 0x02)
            bus_voltage_raw = self.bus.read_word_data(self.device_addr, 0x02)
            bus_voltage = ((bus_voltage_raw >> 3) & 0x1FFF) * 0.004  # Convert to volts
            
            # Read shunt voltage (register 0x01) 
            shunt_voltage_raw = self.bus.read_word_data(self.device_addr, 0x01)
            if shunt_voltage_raw > 32767:
                shunt_voltage_raw -= 65536  # Convert from unsigned to signed
            shunt_voltage = shunt_voltage_raw * 0.01  # Convert to mV
            
            # Read current (register 0x04)
            current_raw = self.bus.read_word_data(self.device_addr, 0x04)
            if current_raw > 32767:
                current_raw -= 65536
            current = current_raw * 1.0  # mA (depends on shunt resistor)
            
            # Read power (register 0x03)
            power_raw = self.bus.read_word_data(self.device_addr, 0x03)
            power = power_raw * 20.0  # mW (depends on shunt resistor)
            
            return {
                'bus_voltage': bus_voltage,
                'shunt_voltage': shunt_voltage,
                'current': current,
                'power': power,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"Error reading power data: {e}")
            return None
    
    def close(self):
        """Close the I2C connection"""
        if self.bus:
            self.bus.close()

def main():
    """Main power logging function"""
    monitor = X1200PowerMonitor()
    
    if not monitor.connected:
        print("Failed to connect to X1200. Check connections and try again.")
        return
    
    # Setup CSV logging
    csv_filename = "/home/pi/x1200_power_log.csv"
    
    # Write header if file is new
    try:
        with open(csv_filename, 'x', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([
                "Timestamp", "Bus Voltage (V)", "Shunt Voltage (mV)", 
                "Current (mA)", "Power (mW)", "Low Voltage Alert", 
                "High Current Alert", "Notes"
            ])
    except FileExistsError:
        pass  # File already exists, append to it
    
    print(f"📊 Logging X1200 power data to {csv_filename}")
    print(f"🔌 Connected to: {monitor.device_name}")
    print("⚠️  Monitoring for voltage drops below 10.5V and current spikes above 4000mA")
    print("Press Ctrl+C to stop logging")
    
    voltage_drops = 0
    
    try:
        while True:
            data = monitor.read_power_data()
            
            if data is None:
                print("❌ Failed to read power data")
                time.sleep(5)
                continue
            
            # Crash detection thresholds
            LOW_VOLTAGE_THRESHOLD = 10.5
            HIGH_CURRENT_THRESHOLD = 4000
            
            low_voltage_alert = "YES" if data['bus_voltage'] < LOW_VOLTAGE_THRESHOLD else "NO"
            high_current_alert = "YES" if abs(data['current']) > HIGH_CURRENT_THRESHOLD else "NO"
            
            notes = ""
            if low_voltage_alert == "YES":
                voltage_drops += 1
                notes += f"LOW_VOLTAGE_DROP_{voltage_drops} "
                print(f"⚠️  WARNING: Low voltage detected: {data['bus_voltage']:.2f}V")
            else:
                voltage_drops = 0
                
            if high_current_alert == "YES":
                notes += "HIGH_CURRENT_SPIKE "
                print(f"⚠️  WARNING: High current detected: {data['current']:.0f}mA")
                
            if voltage_drops >= 3:
                notes += "CRITICAL_VOLTAGE_DROPS "
                print(f"🚨 CRITICAL: {voltage_drops} consecutive voltage drops - potential crash imminent!")
            
            # Log to CSV
            with open(csv_filename, 'a', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([
                    data['timestamp'], 
                    f"{data['bus_voltage']:.3f}",
                    f"{data['shunt_voltage']:.2f}",
                    f"{data['current']:.0f}",
                    f"{data['power']:.0f}",
                    low_voltage_alert,
                    high_current_alert,
                    notes.strip()
                ])
            
            # Console output
            alert_indicator = "🚨" if (low_voltage_alert == "YES" or high_current_alert == "YES") else "✅"
            print(f"{alert_indicator} {data['timestamp']}: {data['bus_voltage']:.2f}V, {data['current']:.0f}mA, {data['power']:.0f}mW")
            
            time.sleep(5)  # Log every 5 seconds
            
    except KeyboardInterrupt:
        print("\n📊 Power logging stopped by user.")
        print(f"📁 Log file saved: {csv_filename}")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
    finally:
        monitor.close()

if __name__ == "__main__":
    main()