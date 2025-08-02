#!/usr/bin/env python3

import os
import time
import smbus

def check_i2c_setup():
    """Check I2C configuration"""
    print("🔍 X1200 UPS Diagnostics")
    print("=" * 40)
    
    # Check if I2C is enabled
    print("1. Checking I2C configuration...")
    try:
        with open('/boot/config.txt', 'r') as f:
            config = f.read()
            if 'dtparam=i2c_arm=on' in config:
                print("   ✅ I2C is enabled in /boot/config.txt")
            else:
                print("   ❌ I2C not enabled - run: sudo raspi-config")
    except:
        print("   ⚠️  Could not check /boot/config.txt")
    
    # Check I2C devices
    print("\n2. Available I2C buses:")
    for i in range(20):
        try:
            bus = smbus.SMBus(i)
            bus.close()
            print(f"   ✅ I2C bus {i} available")
        except:
            pass
    
    # Scan all buses for devices
    print("\n3. Scanning for I2C devices...")
    for bus_num in [0, 1, 4, 11, 13, 14]:
        try:
            bus = smbus.SMBus(bus_num)
            print(f"\n   Bus {bus_num}:")
            found_devices = False
            
            for addr in range(0x08, 0x78):
                try:
                    bus.read_byte(addr)
                    print(f"     📡 Device found at 0x{addr:02x}")
                    found_devices = True
                except:
                    pass
            
            if not found_devices:
                print("     (No devices found)")
            bus.close()
            
        except Exception as e:
            print(f"   ❌ Bus {bus_num}: {e}")

def check_x1200_power():
    """Check if X1200 is providing power readings"""
    print("\n4. Checking X1200 power status...")
    
    # Check for X1200 specific files/interfaces
    x1200_paths = [
        '/sys/class/power_supply/battery',
        '/sys/class/power_supply/ups',
        '/proc/device-tree/hat',
    ]
    
    for path in x1200_paths:
        if os.path.exists(path):
            print(f"   ✅ Found: {path}")
            try:
                if 'power_supply' in path:
                    for file in os.listdir(path):
                        if file in ['voltage_now', 'current_now', 'power_now']:
                            with open(os.path.join(path, file)) as f:
                                value = f.read().strip()
                                print(f"      {file}: {value}")
            except Exception as e:
                print(f"      Error reading {path}: {e}")
        else:
            print(f"   ❌ Not found: {path}")

def test_direct_register_access():
    """Test direct register access on detected devices"""
    print("\n5. Testing direct register access...")
    
    # Test known X1200 configurations
    test_configs = [
        (11, 0x45), (4, 0x45), (11, 0x5d), (4, 0x5d),
        (1, 0x40), (11, 0x40)
    ]
    
    for bus_num, addr in test_configs:
        try:
            bus = smbus.SMBus(bus_num)
            print(f"\n   Testing bus {bus_num}, address 0x{addr:02x}")
            
            # Try to read common registers
            for reg in [0x00, 0x01, 0x02, 0x03, 0x04, 0x05]:
                try:
                    value = bus.read_word_data(addr, reg)
                    print(f"     Register 0x{reg:02x}: 0x{value:04x} ({value})")
                except Exception as e:
                    print(f"     Register 0x{reg:02x}: ❌ {e}")
            
            bus.close()
            
        except Exception as e:
            print(f"   ❌ Bus {bus_num}: {e}")

if __name__ == "__main__":
    check_i2c_setup()
    check_x1200_power()
    test_direct_register_access()
    
    print("\n" + "=" * 40)
    print("🔧 Troubleshooting Tips:")
    print("1. Ensure X1200 is properly seated on GPIO pins")
    print("2. Check power connections to X1200")
    print("3. Verify X1200 firmware is up to date")
    print("4. Try: sudo i2cdetect -y 1")
    print("5. Reboot after enabling I2C if needed")