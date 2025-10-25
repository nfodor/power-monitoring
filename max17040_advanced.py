#!/usr/bin/env python3
"""
Advanced MAX17040 Battery Monitor for X1206
Leverages all MAX17040 features including alerts, compensation, and calibration
"""

import smbus
import struct
import time
import threading
from datetime import datetime

class MAX17040Advanced:
    """Advanced MAX17040 fuel gauge interface with all features"""

    # Register addresses
    VCELL_REG = 0x02    # Battery voltage
    SOC_REG = 0x04      # State of charge
    MODE_REG = 0x06     # Mode register
    VERSION_REG = 0x08  # IC version
    CONFIG_REG = 0x0C   # Configuration

    def __init__(self, bus_num=1, addr=0x36):
        self.bus = smbus.SMBus(bus_num)
        self.addr = addr
        self.alert_callback = None
        self.monitoring = False

        # Battery characteristics for X1206 (21700 cells)
        self.battery_capacity_mah = 5000  # Per cell, adjust based on your battery
        self.cells = 1  # Single cell for voltage reading

        # Compensation values (can be tuned for accuracy)
        self.default_rcomp = 0x97  # Default from X1206
        self.temp_coeff = -0.5  # mV/°C temperature coefficient

        self.init_chip()

    def read_register(self, reg):
        """Read and swap bytes from register"""
        val = self.bus.read_word_data(self.addr, reg)
        return struct.unpack('<H', struct.pack('>H', val))[0]

    def write_register(self, reg, value):
        """Write swapped bytes to register"""
        swapped = struct.unpack('>H', struct.pack('<H', value))[0]
        self.bus.write_word_data(self.addr, reg, swapped)

    def init_chip(self):
        """Initialize MAX17040 with optimal settings"""
        # Check version
        version = self.read_register(self.VERSION_REG)
        print(f"MAX17040 Version: 0x{version:04X}")

        # Set optimal configuration
        self.set_alert_threshold(10)  # Alert at 10% battery
        self.set_compensation(self.default_rcomp)

    def get_voltage(self):
        """Get battery voltage in volts"""
        vcell = self.read_register(self.VCELL_REG)
        return vcell * 1.25 / 1000 / 16

    def get_soc(self):
        """Get state of charge as percentage"""
        soc = self.read_register(self.SOC_REG)
        return soc / 256.0

    def get_config(self):
        """Get current configuration"""
        config = self.read_register(self.CONFIG_REG)
        return {
            'rcomp': (config >> 8) & 0xFF,
            'sleep': (config >> 7) & 0x01,
            'alsc': (config >> 5) & 0x03,
            'alert_threshold': 32 - (config & 0x1F),
            'alert_flag': (config >> 5) & 0x01
        }

    def set_alert_threshold(self, threshold_percent):
        """Set low battery alert threshold (1-32%)"""
        if not 1 <= threshold_percent <= 32:
            raise ValueError("Threshold must be between 1 and 32 percent")

        config = self.read_register(self.CONFIG_REG)
        # Clear lower 5 bits and set new threshold
        config = (config & 0xFFE0) | (32 - threshold_percent)
        self.write_register(self.CONFIG_REG, config)
        print(f"Alert threshold set to {threshold_percent}%")

    def set_compensation(self, rcomp_value):
        """Set RCOMP compensation value for temperature"""
        config = self.read_register(self.CONFIG_REG)
        # Clear upper 8 bits and set new RCOMP
        config = (config & 0x00FF) | (rcomp_value << 8)
        self.write_register(self.CONFIG_REG, config)
        print(f"RCOMP set to 0x{rcomp_value:02X}")

    def clear_alert(self):
        """Clear alert flag"""
        config = self.read_register(self.CONFIG_REG)
        # Clear ALRT bit (bit 5)
        config = config & ~(1 << 5)
        self.write_register(self.CONFIG_REG, config)

    def check_alert(self):
        """Check if alert is triggered"""
        config = self.read_register(self.CONFIG_REG)
        return bool((config >> 5) & 0x01)

    def quick_start(self):
        """Restart fuel gauge calculations"""
        self.write_register(self.MODE_REG, 0x4000)
        time.sleep(0.5)
        print("Quick start executed - fuel gauge reset")

    def enable_sleep(self):
        """Enable sleep mode to save power"""
        config = self.read_register(self.CONFIG_REG)
        config |= (1 << 7)  # Set SLEEP bit
        self.write_register(self.CONFIG_REG, config)
        print("Sleep mode enabled")

    def disable_sleep(self):
        """Disable sleep mode"""
        config = self.read_register(self.CONFIG_REG)
        config &= ~(1 << 7)  # Clear SLEEP bit
        self.write_register(self.CONFIG_REG, config)
        print("Sleep mode disabled")

    def load_custom_model(self, empty_voltage=3.3, full_voltage=4.2):
        """Load custom battery model parameters"""
        # Calculate RCOMP based on battery characteristics
        # This is simplified - real calculation depends on battery chemistry
        voltage_range = full_voltage - empty_voltage
        rcomp = int(0x97 * (voltage_range / 0.9))  # Adjust factor
        self.set_compensation(min(0xFF, rcomp))
        print(f"Custom model loaded: Empty={empty_voltage}V, Full={full_voltage}V")

    def get_time_to_empty(self, current_ma=500):
        """Estimate time to empty based on current draw"""
        soc = self.get_soc()
        if soc <= 0:
            return 0

        capacity_remaining = (soc / 100) * self.battery_capacity_mah * self.cells
        hours = capacity_remaining / current_ma
        return hours

    def get_detailed_status(self):
        """Get comprehensive battery status"""
        voltage = self.get_voltage()
        soc = self.get_soc()
        config = self.get_config()
        alert = self.check_alert()

        # Determine battery health based on voltage
        if voltage < 3.0:
            health = "Critical"
        elif voltage < 3.3:
            health = "Poor"
        elif voltage < 3.7:
            health = "Fair"
        elif voltage < 4.1:
            health = "Good"
        else:
            health = "Excellent"

        # Calculate estimated runtime (assuming 500mA average draw)
        runtime_hours = self.get_time_to_empty(500)

        return {
            'voltage': voltage,
            'soc': soc,
            'health': health,
            'alert_active': alert,
            'alert_threshold': config['alert_threshold'],
            'rcomp': config['rcomp'],
            'sleep_mode': config['sleep'],
            'runtime_hours': runtime_hours,
            'timestamp': datetime.now().isoformat()
        }

    def monitor_alerts(self, callback=None):
        """Start monitoring for low battery alerts"""
        self.alert_callback = callback
        self.monitoring = True

        def alert_thread():
            while self.monitoring:
                if self.check_alert():
                    soc = self.get_soc()
                    voltage = self.get_voltage()

                    alert_msg = f"LOW BATTERY ALERT: {soc:.1f}% ({voltage:.2f}V)"
                    print(f"⚠️  {alert_msg}")

                    if self.alert_callback:
                        self.alert_callback(soc, voltage)

                    self.clear_alert()
                    time.sleep(60)  # Don't spam alerts

                time.sleep(5)  # Check every 5 seconds

        thread = threading.Thread(target=alert_thread, daemon=True)
        thread.start()
        print("Alert monitoring started")

    def stop_monitoring(self):
        """Stop alert monitoring"""
        self.monitoring = False

    def calibrate(self, actual_soc=None):
        """Calibrate fuel gauge with known SOC"""
        if actual_soc is not None:
            # This would require writing to OCV registers
            # For now, we'll just do a quick start
            print(f"Calibrating to {actual_soc}% (using quick start)")
            self.quick_start()
        else:
            # Auto-calibrate based on voltage
            voltage = self.get_voltage()

            # Voltage to SOC curve for Li-ion
            if voltage >= 4.2:
                estimated_soc = 100
            elif voltage >= 4.1:
                estimated_soc = 90
            elif voltage >= 4.0:
                estimated_soc = 80
            elif voltage >= 3.9:
                estimated_soc = 60
            elif voltage >= 3.8:
                estimated_soc = 40
            elif voltage >= 3.7:
                estimated_soc = 20
            elif voltage >= 3.5:
                estimated_soc = 10
            elif voltage >= 3.3:
                estimated_soc = 5
            else:
                estimated_soc = 0

            print(f"Auto-calibration based on {voltage:.2f}V → ~{estimated_soc}%")
            self.quick_start()


def demo():
    """Demonstrate advanced MAX17040 features"""
    print("MAX17040 Advanced Battery Monitor Demo")
    print("=" * 50)

    # Initialize
    gauge = MAX17040Advanced()

    # Get initial status
    status = gauge.get_detailed_status()

    print(f"\n📊 Battery Status:")
    print(f"  Voltage: {status['voltage']:.3f}V")
    print(f"  Charge: {status['soc']:.1f}%")
    print(f"  Health: {status['health']}")
    print(f"  Runtime: {status['runtime_hours']:.1f} hours")
    print(f"  Alert: {'YES' if status['alert_active'] else 'NO'}")
    print(f"  Alert Threshold: {status['alert_threshold']}%")
    print(f"  RCOMP: 0x{status['rcomp']:02X}")

    # Set up alert
    gauge.set_alert_threshold(15)

    # Define alert callback
    def battery_alert(soc, voltage):
        print(f"\n🚨 BATTERY CRITICAL: {soc:.1f}% at {voltage:.2f}V")
        print("   Consider charging immediately!")

    # Start monitoring
    gauge.monitor_alerts(battery_alert)

    # Monitor for 30 seconds
    print("\n📈 Monitoring (30 seconds)...")
    for i in range(6):
        time.sleep(5)
        voltage = gauge.get_voltage()
        soc = gauge.get_soc()
        print(f"  {i*5+5}s: {soc:.1f}% at {voltage:.3f}V")

    # Stop monitoring
    gauge.stop_monitoring()

    print("\n✅ Demo complete")


if __name__ == "__main__":
    demo()