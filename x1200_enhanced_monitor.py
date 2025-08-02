#!/usr/bin/env python3

import time
import csv
import smbus
import os
from datetime import datetime
import subprocess

class X1200EnhancedMonitor:
    """Enhanced X1200 UPS monitoring with GPIO indicators"""
    
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
        
        # GPIO pins for X1200
        self.GPIO_CHARGING = 16   # Battery charging control
        self.GPIO_POWER_LOSS = 6  # Power loss detection
        
        self.connect()
        self.setup_gpio()
    
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
    
    def setup_gpio(self):
        """Setup GPIO monitoring using gpiod"""
        try:
            # Export GPIOs if not already exported
            for gpio in [self.GPIO_CHARGING, self.GPIO_POWER_LOSS]:
                if not os.path.exists(f"/sys/class/gpio/gpio{gpio}"):
                    with open("/sys/class/gpio/export", "w") as f:
                        f.write(str(gpio))
                    time.sleep(0.1)
                
                # Set as input
                with open(f"/sys/class/gpio/gpio{gpio}/direction", "w") as f:
                    f.write("in")
            
            print("✅ GPIO setup complete")
        except Exception as e:
            print(f"⚠️  GPIO setup warning: {e}")
            print("   Trying gpiod tools instead...")
    
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
    
    def get_gpio_state(self, gpio):
        """Read GPIO state"""
        try:
            # Try sysfs method first
            with open(f"/sys/class/gpio/gpio{gpio}/value", "r") as f:
                return int(f.read().strip())
        except:
            # Fallback to gpiod
            try:
                result = subprocess.run(['gpioget', 'gpiochip0', str(gpio)], 
                                      capture_output=True, text=True, timeout=1)
                if result.returncode == 0:
                    return int(result.stdout.strip())
            except:
                pass
        return None
    
    def is_charging(self):
        """Check if battery is charging (GPIO16)"""
        state = self.get_gpio_state(self.GPIO_CHARGING)
        if state is not None:
            # GPIO16 low = charging, high = not charging
            return state == 0
        return None
    
    def has_external_power(self):
        """Check if external power is connected (GPIO6)"""
        state = self.get_gpio_state(self.GPIO_POWER_LOSS)
        if state is not None:
            # GPIO6 high = external power present, low = power loss
            return state == 1
        return None
    
    def get_power_source(self):
        """Determine current power source"""
        has_power = self.has_external_power()
        if has_power is None:
            return "Unknown"
        elif has_power:
            return "External USB-C"
        else:
            return "Battery"
    
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
                  f"{'🔌 Charging' if data['is_charging'] else '🔋 Discharging'}")
            
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