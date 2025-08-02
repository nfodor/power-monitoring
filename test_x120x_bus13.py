#!/usr/bin/env python3
# Test X120x battery script on Bus 13:0x37 (where we found a device)

import struct
import smbus2
import time

def readVoltage(bus, address=0x37):
     read = bus.read_word_data(address, 2)
     swapped = struct.unpack("<H", struct.pack(">H", read))[0]
     voltage = swapped * 1.25 /1000/16
     return voltage

def readCapacity(bus, address=0x37):
     read = bus.read_word_data(address, 4)
     swapped = struct.unpack("<H", struct.pack(">H", read))[0]
     capacity = swapped/256
     return capacity

try:
    bus = smbus2.SMBus(13)
    print("Testing X120x script on Bus 13:0x37...")
    
    for i in range(5):
        print(f"\n--- Reading #{i+1} ---")
        voltage = readVoltage(bus)
        capacity = readCapacity(bus)
        
        print(f"Voltage: {voltage:.2f}V")
        print(f"Battery: {capacity:.1f}%")
        
        if capacity == 100:
            print("Battery FULL")
        elif capacity < 20:
            print("Battery Low")
            
        if voltage < 3.20:
            print("Battery LOW!!!")
            
        time.sleep(1)
    
    bus.close()
    
except Exception as e:
    print(f"Error reading Bus 13:0x37: {e}")