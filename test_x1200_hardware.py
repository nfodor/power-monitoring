#!/usr/bin/env python3
"""Test X1200 hardware connectivity"""

import os
import sys
import time

print("X1200 Hardware Test")
print("==================")

# Test GPIO setup
print("\n1. Testing GPIO pins...")
GPIO_CHARGING = 16  # GPIO16
GPIO_POWER_LOSS = 6  # GPIO6
GPIO_BASE = 512  # Raspberry Pi 5 GPIO base

for gpio_num, name in [(GPIO_CHARGING, "Charging"), (GPIO_POWER_LOSS, "Power Loss")]:
    gpio_path = f"/sys/class/gpio/gpio{GPIO_BASE + gpio_num}"
    if os.path.exists(gpio_path):
        try:
            with open(f"{gpio_path}/value", "r") as f:
                value = f.read().strip()
                print(f"   GPIO{gpio_num} ({name}): {value}")
        except Exception as e:
            print(f"   GPIO{gpio_num} ({name}): Error reading - {e}")
    else:
        print(f"   GPIO{gpio_num} ({name}): Not exported")

# Test I2C buses
print("\n2. Testing I2C buses...")
i2c_buses = []
for i in range(20):
    if os.path.exists(f"/dev/i2c-{i}"):
        i2c_buses.append(i)
print(f"   Available I2C buses: {i2c_buses}")

# Test specific addresses
print("\n3. Testing known X1200 addresses...")
test_addresses = [
    (1, 0x36, "MAX17040G+ Fuel Gauge"),
    (13, 0x37, "Alternative Fuel Gauge"),
    (1, 0x54, "Generic UPS"),
    (1, 0x40, "INA219 Power Monitor"),
]

for bus, addr, desc in test_addresses:
    if bus in i2c_buses:
        cmd = f"i2cget -y {bus} 0x{addr:02x} 0x00 2>/dev/null"
        result = os.system(cmd)
        if result == 0:
            print(f"   Bus {bus}, 0x{addr:02x} ({desc}): FOUND")
        else:
            print(f"   Bus {bus}, 0x{addr:02x} ({desc}): Not found")

# Check kernel messages
print("\n4. Recent I2C errors...")
os.system("dmesg | grep -i i2c | tail -5")

print("\n5. Power status via other means...")
# Check if running on battery
try:
    with open("/sys/class/power_supply/BAT0/status", "r") as f:
        print(f"   Battery status: {f.read().strip()}")
except:
    print("   No standard battery interface found")

# Check USB power
usb_power_ok = False
for i in range(4):
    path = f"/sys/bus/usb/devices/usb{i}/power/level"
    if os.path.exists(path):
        usb_power_ok = True
        break
print(f"   USB power detected: {usb_power_ok}")

print("\nDiagnosis:")
print("- If GPIO pins not exported, X1200 GPIO may not be initialized")
print("- If I2C devices not found, check X1200 HAT seating")
print("- 'SDA stuck at low' errors indicate I2C bus conflict or hardware issue")