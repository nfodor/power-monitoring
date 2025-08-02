
#!/usr/bin/env python3

import time
import csv
from datetime import datetime
import board
import busio
from adafruit_ina219 import INA219

# Setup I2C for Geekworm X1200 UPS
# X1200 has INA219 sensors, need to find the correct bus and address
import busio

def try_ina219_connection(bus_num, address):
    """Try to connect to INA219 on specific bus and address"""
    try:
        # Use SMBus directly for different I2C buses
        import smbus
        bus = smbus.SMBus(bus_num)
        
        # Test if device responds at this address
        try:
            bus.read_byte(address)
            bus.close()
        except:
            bus.close()
            return None, None
            
        # If device responds, create CircuitPython I2C interface
        if bus_num == 1:
            i2c = busio.I2C(board.SCL, board.SDA)
        else:
            # For other buses, we'll use a workaround
            import os
            os.environ['BLINKA_I2C'] = str(bus_num)
            i2c = busio.I2C(board.SCL, board.SDA)
            
        ina = INA219(i2c, addr=address)
        # Test connection by reading voltage
        test_voltage = ina.bus_voltage
        return i2c, ina
    except Exception as e:
        return None, None

# Try different bus/address combinations for X1200
connection_attempts = [
    (11, 0x45),  # X1200 common config
    (4, 0x45),   # Alternative bus
    (11, 0x5d),  # Other detected address
    (4, 0x5d),   # Other detected address  
    (1, 0x40),   # Standard config
    (11, 0x40),  # Standard address on X1200 bus
]

i2c_bus = None
ina219 = None

for bus_num, addr in connection_attempts:
    print(f"Trying bus {bus_num}, address 0x{addr:02x}...")
    i2c_bus, ina219 = try_ina219_connection(bus_num, addr)
    if ina219 is not None:
        print(f"✅ Connected to INA219 on bus {bus_num} at address 0x{addr:02x}")
        break

if ina219 is None:
    print("❌ Could not connect to any INA219 sensor on X1200")
    print("Make sure:")
    print("1. X1200 is properly connected and powered")
    print("2. I2C is enabled in raspi-config")
    print("3. X1200 firmware is up to date")
    exit(1)

# CSV file setup with crash detection headers
csv_filename = "/home/pi/power_log.csv"
with open(csv_filename, mode='a') as file:
    writer = csv.writer(file)
    if file.tell() == 0:
        writer.writerow(["Timestamp", "Bus Voltage (V)", "Shunt Voltage (mV)", "Current (mA)", "Power (mW)", "Low Voltage Alert", "High Current Alert", "Notes"])

# Crash detection thresholds for X1200
LOW_VOLTAGE_THRESHOLD = 10.5  # Volts - typical shutdown voltage
HIGH_CURRENT_THRESHOLD = 4000  # mA - unusually high current draw
voltage_drops = 0  # Track consecutive voltage drops

# Logging loop with crash detection
try:
    print("Logging X1200 power data with crash detection. Press Ctrl+C to stop.")
    print(f"Monitoring for voltage drops below {LOW_VOLTAGE_THRESHOLD}V and current spikes above {HIGH_CURRENT_THRESHOLD}mA")
    
    while True:
        try:
            now = datetime.now().isoformat()
            bus_voltage = ina219.bus_voltage
            shunt_voltage = ina219.shunt_voltage
            current = ina219.current
            power = ina219.power
            
            # Crash detection logic
            low_voltage_alert = "YES" if bus_voltage < LOW_VOLTAGE_THRESHOLD else "NO"
            high_current_alert = "YES" if current > HIGH_CURRENT_THRESHOLD else "NO"
            
            notes = ""
            if low_voltage_alert == "YES":
                voltage_drops += 1
                notes += f"LOW_VOLTAGE_DROP_{voltage_drops} "
                print(f"⚠️  WARNING: Low voltage detected: {bus_voltage:.2f}V")
            else:
                voltage_drops = 0
                
            if high_current_alert == "YES":
                notes += "HIGH_CURRENT_SPIKE "
                print(f"⚠️  WARNING: High current detected: {current:.0f}mA")
                
            if voltage_drops >= 3:
                notes += "CRITICAL_VOLTAGE_DROPS "
                print(f"🚨 CRITICAL: {voltage_drops} consecutive voltage drops - potential crash imminent!")

            with open(csv_filename, mode='a', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([now, bus_voltage, shunt_voltage, current, power, low_voltage_alert, high_current_alert, notes.strip()])

            # Enhanced display with alerts
            alert_indicator = "🚨" if (low_voltage_alert == "YES" or high_current_alert == "YES") else "✅"
            print(f"{alert_indicator} {now}: {bus_voltage:.2f}V, {current:.0f}mA, {power:.0f}mW")
            
        except Exception as sensor_error:
            error_time = datetime.now().isoformat()
            print(f"❌ Sensor read error at {error_time}: {sensor_error}")
            with open(csv_filename, mode='a', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([error_time, "ERROR", "ERROR", "ERROR", "ERROR", "ERROR", "ERROR", f"SENSOR_ERROR: {sensor_error}"])
            
        time.sleep(5)  # Faster logging for crash detection

except KeyboardInterrupt:
    print("\n📊 Power logging stopped by user.")
    print(f"📁 Log file saved: {csv_filename}")
except Exception as e:
    print(f"❌ Fatal error: {e}")
    with open(csv_filename, mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([datetime.now().isoformat(), "FATAL", "FATAL", "FATAL", "FATAL", "FATAL", "FATAL", f"FATAL_ERROR: {e}"])
