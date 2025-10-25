import os
import time
import smbus
import subprocess

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

    # Check I2C permissions
    print("\n2. Checking I2C permissions...")
    if os.path.exists('/dev/i2c-1'):
        if os.access('/dev/i2c-1', os.R_OK | os.W_OK):
            print("   ✅ R/W permissions are OK for /dev/i2c-1")
        else:
            print("   ❌ R/W permissions are NOT OK for /dev/i2c-1. Try running as root or adding user to i2c group.")
    else:
        print("   ⚠️  /dev/i2c-1 not found.")

    # Check kernel modules
    print("\n3. Checking kernel modules...")
    try:
        lsmod = subprocess.check_output(["lsmod"]).decode("utf-8")
        if "i2c_bcm2708" in lsmod or "i2c_bcm2835" in lsmod:
            print("   ✅ I2C kernel module is loaded.")
        else:
            print("   ❌ I2C kernel module is not loaded. Add 'i2c-dev' to /etc/modules.")
    except:
        print("   ⚠️  Could not check kernel modules.")

    # Check I2C devices
    print("\n4. Available I2C buses:")
    for i in range(20):
        try:
            bus = smbus.SMBus(i)
            bus.close()
            print(f"   ✅ I2C bus {i} available")
        except:
            pass
    
    # Scan all buses for devices
    print("\n5. Scanning for I2C devices...")
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
    print("\n6. Checking X1200 power status...")
    
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
    print("\n7. Testing direct register access...")
    
    # Test known X1200 configurations
    test_configs = [
        (1, 0x36, "MAX17040G+ Fuel Gauge"),
        (11, 0x45, "X1200 INA219 Primary"),
        (4, 0x45, "X1200 INA219 Secondary"),
        (11, 0x5d, "X1200 MCU/Controller"),
        (4, 0x5d, "X1200 MCU/Controller Alt"),
        (1, 0x40, "Standard INA219"),
    ]
    
    for bus_num, addr, name in test_configs:
        try:
            bus = smbus.SMBus(bus_num)
            print(f"\n   Testing {name} on bus {bus_num}, address 0x{addr:02x}")
            
            # Try to read common registers
            for reg in [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x08]:
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
    print("6. If you see errors like '[Errno 121] Remote I/O error', it may be a hardware issue.")
    print("7. If you see no devices, check the physical connections and power supply.")
