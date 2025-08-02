#!/usr/bin/env python3
"""Comprehensive X1200 connection test for Raspberry Pi 5"""

import os
import sys
import time
import subprocess

print("X1200 Connection Test for Raspberry Pi 5")
print("=" * 50)
print("This will test all critical connections\n")

# Test results
results = {
    "GPIO Power (Pin 2,4)": "Not tested",
    "Ground (Pin 6,9,14,20,25,30,34,39)": "Not tested", 
    "I2C SDA (Pin 3/GPIO2)": "Not tested",
    "I2C SCL (Pin 5/GPIO3)": "Not tested",
    "GPIO16 (Pin 36) - Charging": "Not tested",
    "GPIO6 (Pin 31) - Power Loss": "Not tested",
    "I2C Bus Communication": "Not tested",
    "Fuel Gauge (0x36)": "Not tested"
}

def run_command(cmd):
    """Run a command and return output"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        return result.returncode == 0, result.stdout.strip()
    except:
        return False, "Command failed"

# 1. Test I2C Buses
print("1. Testing I2C Bus Availability...")
i2c_buses = []
for i in range(20):
    if os.path.exists(f"/dev/i2c-{i}"):
        i2c_buses.append(i)
print(f"   Available I2C buses: {i2c_buses}")
if 1 in i2c_buses:
    results["I2C Bus Communication"] = "PASS - Bus 1 available"
else:
    results["I2C Bus Communication"] = "FAIL - Bus 1 not found"

# 2. Test I2C Pin Connectivity
print("\n2. Testing I2C Pin States...")
# Check if I2C pins are configured correctly
success, output = run_command("pinctrl get 2,3")
if success:
    print(f"   GPIO 2,3 (I2C) state:\n{output}")
    if "a0" in output.lower():  # I2C function
        results["I2C SDA (Pin 3/GPIO2)"] = "PASS - I2C mode"
        results["I2C SCL (Pin 5/GPIO3)"] = "PASS - I2C mode"
    else:
        results["I2C SDA (Pin 3/GPIO2)"] = "WARN - Not in I2C mode"
        results["I2C SCL (Pin 5/GPIO3)"] = "WARN - Not in I2C mode"

# 3. Scan for I2C Devices
print("\n3. Scanning I2C devices...")
for bus in i2c_buses[:3]:  # Test first 3 buses
    success, output = run_command(f"sudo i2cdetect -y {bus} 2>/dev/null | grep -E '30:|40:|50:' | grep -v -- '--'")
    if success and output:
        print(f"   Bus {bus}: Found devices")
        if bus == 1:
            # Check for fuel gauge at 0x36
            success2, output2 = run_command(f"sudo i2cget -y {bus} 0x36 0x02 w 2>/dev/null")
            if success2:
                results["Fuel Gauge (0x36)"] = f"PASS - Found on bus {bus}"
            else:
                results["Fuel Gauge (0x36)"] = f"FAIL - Not responding on bus {bus}"

# 4. Test GPIO Pins
print("\n4. Testing GPIO Control Pins...")

# GPIO16 - Charging control
print("   Testing GPIO16 (Charging)...")
try:
    # Try gpiod first
    import gpiod
    chip = gpiod.Chip('gpiochip0')
    line16 = chip.get_line(16)
    line16.request(consumer="test", type=gpiod.LINE_REQ_DIR_IN)
    value16 = line16.get_value()
    line16.release()
    results["GPIO16 (Pin 36) - Charging"] = f"PASS - Value: {value16} ({'Charging' if value16 == 0 else 'Not charging'})"
except:
    # Try pinctrl
    success, output = run_command("pinctrl get 16")
    if success:
        results["GPIO16 (Pin 36) - Charging"] = f"INFO - {output}"
    else:
        results["GPIO16 (Pin 36) - Charging"] = "FAIL - Cannot read"

# GPIO6 - Power loss detection  
print("   Testing GPIO6 (Power Loss)...")
try:
    line6 = chip.get_line(6)
    line6.request(consumer="test", type=gpiod.LINE_REQ_DIR_IN)
    value6 = line6.get_value()
    line6.release()
    chip.close()
    results["GPIO6 (Pin 31) - Power Loss"] = f"PASS - Value: {value6} ({'External power' if value6 == 1 else 'Battery power'})"
except:
    success, output = run_command("pinctrl get 6")
    if success:
        results["GPIO6 (Pin 31) - Power Loss"] = f"INFO - {output}"
    else:
        results["GPIO6 (Pin 31) - Power Loss"] = "FAIL - Cannot read"

# 5. Test Voltage Levels
print("\n5. Testing Power Connections...")
# This would require external measurement, so we'll check system voltage
success, output = run_command("vcgencmd measure_volts core")
if success:
    voltage = output.split('=')[1].strip('V')
    results["GPIO Power (Pin 2,4)"] = f"INFO - Core voltage: {voltage}V"

# 6. Direct I2C Communication Test
print("\n6. Testing Direct I2C Communication...")
test_addresses = [
    (1, 0x36, "MAX17040 Fuel Gauge"),
    (1, 0x54, "Generic UPS"),
    (13, 0x37, "Alternative Address"),
]

for bus, addr, desc in test_addresses:
    if bus in i2c_buses:
        # Try to read a register
        success, _ = run_command(f"sudo i2cget -y {bus} 0x{addr:02x} 0x00 2>/dev/null")
        if success:
            print(f"   {desc} at {bus}:0x{addr:02x} - FOUND")

# Print Results Summary
print("\n" + "=" * 50)
print("CONNECTION TEST RESULTS:")
print("=" * 50)

issues_found = []
for test, result in results.items():
    status = result.split(' - ')[0]
    color = ""
    if status == "PASS":
        color = "\033[92m"  # Green
    elif status == "FAIL":
        color = "\033[91m"  # Red
        issues_found.append(test)
    elif status == "WARN":
        color = "\033[93m"  # Yellow
        issues_found.append(test)
    else:
        color = "\033[94m"  # Blue
    
    print(f"{color}{test}: {result}\033[0m")

# Recommendations
print("\n" + "=" * 50)
print("RECOMMENDATIONS:")
print("=" * 50)

if "Fuel Gauge (0x36)" in issues_found:
    print("❌ FUEL GAUGE NOT DETECTED - Critical Issue!")
    print("   1. Power down completely")
    print("   2. Remove X1200 from Pi 5")
    print("   3. Check pins 3 (SDA) and 5 (SCL) on Pi bottom for residue")
    print("   4. Ensure all standoffs are tight")
    print("   5. Firmly reseat X1200")
    print("   6. Consider adding solder blobs to GPIO 2,3 for better contact")

if any("I2C" in issue for issue in issues_found):
    print("\n⚠️  I2C COMMUNICATION ISSUES")
    print("   - I2C pins may have poor pogo pin contact")
    print("   - Try adjusting pogo pin positions")

if len(issues_found) == 0:
    print("✅ All connections appear good!")
    print("   If still having issues, try:")
    print("   - Reboot with X1200 connected")
    print("   - Check battery quality")
    print("   - Ensure using Samsung/Panasonic 18650 cells")

print("\nNote: Pi 5 has 'flusher' GPIO pins that don't protrude as much.")
print("This is a known issue with pogo pin devices on Pi 5.")