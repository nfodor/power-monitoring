#!/usr/bin/env python3
"""Scan for fuel gauge on all detected I2C addresses"""

import struct
import smbus2
import time

def readVoltage(bus, address):
    """Try to read voltage register (0x02) from given address"""
    try:
        read = bus.read_word_data(address, 2)
        swapped = struct.unpack("<H", struct.pack(">H", read))[0]
        voltage = swapped * 1.25 / 1000 / 16
        return voltage
    except:
        return None

def readCapacity(bus, address):
    """Try to read capacity register (0x04) from given address"""
    try:
        read = bus.read_word_data(address, 4)
        swapped = struct.unpack("<H", struct.pack(">H", read))[0]
        capacity = swapped / 256
        return capacity
    except:
        return None

# Test addresses found on bus 13
test_addresses = {
    13: [0x38, 0x39, 0x3a, 0x3b, 0x3c, 0x3d, 0x3e, 0x3f],
    1: [0x36],  # Traditional address
}

print("Scanning for X1200 fuel gauge...")
print("=" * 40)

for bus_num, addresses in test_addresses.items():
    try:
        bus = smbus2.SMBus(bus_num)
        print(f"\nBus {bus_num}:")
        
        for addr in addresses:
            voltage = readVoltage(bus, addr)
            capacity = readCapacity(bus, addr)
            
            if voltage is not None or capacity is not None:
                print(f"  0x{addr:02x}: Voltage={voltage:.2f}V, Capacity={capacity:.1f}%")
                
                # Try reading all registers 0-16 to identify chip
                print(f"    Register dump for 0x{addr:02x}:")
                for reg in range(0, 16, 2):
                    try:
                        val = bus.read_word_data(addr, reg)
                        swapped = struct.unpack("<H", struct.pack(">H", val))[0]
                        print(f"      Reg 0x{reg:02x}: 0x{val:04x} (swapped: 0x{swapped:04x})")
                    except:
                        pass
                        
        bus.close()
    except Exception as e:
        print(f"  Error accessing bus {bus_num}: {e}")

print("\nNote: X1200 fuel gauge should respond at registers 0x02 (voltage) and 0x04 (capacity)")