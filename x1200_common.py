
#!/usr/bin/env python3
"""
Common module for X1200/X1206 UPS detection and monitoring
Supports both X1200 and X1206 models with battery presence detection
"""

import smbus
import time
import subprocess
import os

class X1200Monitor:
    def __init__(self):
        self.bus = None
        self.connected = False
        self.device_addr = 0x36  # MAX17040G+ fuel gauge address
        self.model = None  # Will be "X1200" or "X1206"
        self.has_battery = None

        # MAX17040G+ register addresses
        self.VCELL_REG = 0x02    # Battery voltage
        self.SOC_REG = 0x04      # State of charge (%)
        self.MODE_REG = 0x06     # Mode register
        self.VERSION_REG = 0x08  # Version register
        self.CONFIG_REG = 0x0C   # Configuration register
        self.COMMAND_REG = 0xFE  # Command register

        # GPIO pins for X1200/X1206
        self.GPIO_CHARGING = 16   # Battery charging control
        self.GPIO_POWER_LOSS = 6  # Power loss detection

        self.connect()
        self.setup_gpio()

    def connect(self):
        """Connect to X1200/X1206 MAX17040G+ fuel gauge"""
        # Try different I2C buses where X1200/X1206 might be connected
        for bus_num in [1, 11, 4]:
            try:
                print(f"Trying X1200/X1206 MAX17040G+ on I2C bus {bus_num} at address 0x{self.device_addr:02x}")
                bus = smbus.SMBus(bus_num)

                # Test communication by reading version register
                version = bus.read_word_data(self.device_addr, self.VERSION_REG)
                version = ((version & 0xFF) << 8) | ((version & 0xFF00) >> 8)  # Swap bytes

                # Detect model based on version
                # X1206 models can have different version codes
                if version == 0x0036:
                    self.model = "X1206"
                elif version == 0x0002:
                    # Could be X1200 or X1206 v1.1
                    # X1206 v1.1 also reports 0x0002
                    # Will determine based on battery behavior
                    self.model = "X1206 v1.1"
                else:
                    self.model = "X1200"

                print(f"✅ Connected to {self.model} MAX17040G+ (version: 0x{version:04x})")
                self.bus = bus
                self.bus_num = bus_num
                self.connected = True

                # Check battery presence
                self.detect_battery()

                return True

            except Exception as e:
                if bus:
                    bus.close()
                continue

        print("❌ Could not connect to X1200/X1206 MAX17040G+ fuel gauge")
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

    def detect_battery(self):
        """Detect if battery is installed"""
        if not self.connected:
            self.has_battery = False
            return False

        try:
            # Read battery percentage and voltage
            soc = self.read_word_swapped(self.SOC_REG)
            vcell = self.read_word_swapped(self.VCELL_REG)

            if soc is not None and vcell is not None:
                percentage = soc / 256.0
                voltage = (vcell >> 4) * 1.25 / 1000.0

                # Battery detection for X1206 v1.1:
                # - No battery: ~4.20V with 38-42% SOC
                # - Low battery: <3.7V with low SOC
                # - Normal battery: 3.7-4.2V with varying SOC

                if voltage >= 4.19 and voltage <= 4.21 and 36 <= percentage <= 43:
                    # X1206 v1.1 specific no-battery signature
                    self.has_battery = False
                    print(f"   Battery: Not installed (X1206 reads V={voltage:.2f}V, SOC={percentage:.1f}%)")
                elif percentage < 0.1 or voltage < 2.5:
                    # Generic no-battery condition
                    self.has_battery = False
                    print(f"   Battery: Not installed (V={voltage:.2f}V, SOC={percentage:.1f}%)")
                else:
                    self.has_battery = True
                    if percentage < 10:
                        print(f"   Battery: Installed - CRITICALLY LOW (V={voltage:.2f}V, SOC={percentage:.1f}%)")
                    else:
                        print(f"   Battery: Installed (V={voltage:.2f}V, SOC={percentage:.1f}%)")
            else:
                self.has_battery = False

            return self.has_battery
        except:
            self.has_battery = False
            return False

    def get_battery_voltage(self):
        """Get battery voltage in volts"""
        vcell = self.read_word_swapped(self.VCELL_REG)
        if vcell is not None:
            # VCELL register: voltage = value * 1.25mV / 16
            voltage = (vcell >> 4) * 1.25 / 1000.0
            # Return None if no battery installed
            if not self.has_battery and voltage < 2.5:
                return None
            return voltage
        return None

    def get_battery_percentage(self):
        """Get battery state of charge as percentage"""
        soc = self.read_word_swapped(self.SOC_REG)
        if soc is not None:
            # SOC register: percentage = value / 256
            percentage = soc / 256.0
            # Return None if no battery installed
            if not self.has_battery and percentage < 0.1:
                return None
            return percentage
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

    def get_status(self):
        """Get comprehensive UPS status"""
        if not self.connected:
            return {
                'connected': False,
                'model': None,
                'has_battery': False,
                'battery_voltage': None,
                'battery_percentage': None,
                'power_source': 'Unknown',
                'is_charging': None,
                'status': 'Disconnected'
            }

        # Re-check battery presence
        self.detect_battery()

        voltage = self.get_battery_voltage()
        percentage = self.get_battery_percentage()
        power_source = self.get_power_source()
        is_charging = self.is_charging()

        # Determine overall status
        if not self.has_battery:
            status = 'External Power Only (No Battery)'
        elif percentage and percentage > 100:
            status = 'Charging (X1200 V1.2)'
        elif is_charging:
            status = 'Charging'
        elif percentage and percentage < 20:
            status = 'Critical - Low Battery'
        elif percentage and percentage < 50:
            status = 'Battery Power'
        elif power_source == "External USB-C":
            status = 'External Power'
        else:
            status = 'Good'

        return {
            'connected': True,
            'model': self.model,
            'has_battery': self.has_battery,
            'battery_voltage': voltage,
            'battery_percentage': percentage,
            'power_source': power_source,
            'is_charging': is_charging,
            'status': status
        }

    def close(self):
        """Close I2C connection"""
        if self.bus:
            self.bus.close()


# Test function
if __name__ == "__main__":
    print("🔍 Testing X1200/X1206 UPS Connection...")
    print("-" * 50)

    monitor = X1200Monitor()

    if monitor.connected:
        print("\n📊 UPS Status:")
        status = monitor.get_status()

        print(f"Model: {status['model']}")
        print(f"Battery Installed: {status['has_battery']}")

        if status['has_battery']:
            if status['battery_voltage']:
                print(f"Battery Voltage: {status['battery_voltage']:.2f}V")
            if status['battery_percentage']:
                print(f"Battery Level: {status['battery_percentage']:.1f}%")

        print(f"Power Source: {status['power_source']}")
        print(f"Charging: {status['is_charging']}")
        print(f"Overall Status: {status['status']}")

        # Monitor for 10 seconds
        print("\n📈 Monitoring for 10 seconds...")
        for i in range(5):
            time.sleep(2)
            status = monitor.get_status()
            if status['has_battery'] and status['battery_percentage']:
                print(f"   {i*2+2}s: {status['battery_percentage']:.1f}% ({status['battery_voltage']:.2f}V) - {status['power_source']}")
            else:
                print(f"   {i*2+2}s: No battery - {status['power_source']}")

        monitor.close()
    else:
        print("❌ No UPS detected on any I2C bus")
        print("\nTroubleshooting:")
        print("1. Check if X1200/X1206 is properly connected to GPIO")
        print("2. Verify I2C is enabled: sudo raspi-config")
        print("3. Check connections with: sudo i2cdetect -y 1")
        print("4. Ensure UPS is powered on")
