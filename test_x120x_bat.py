#!/usr/bin/env python3
#This python script is only suitable for UPS Shield X1200, X1201 and X1202

import struct
import smbus2
import time
from subprocess import call

def readVoltage(bus):
     address = 0x36
     read = bus.read_word_data(address, 2)
     swapped = struct.unpack("<H", struct.pack(">H", read))[0]
     voltage = swapped * 1.25 /1000/16
     return voltage

def readCapacity(bus):
     address = 0x36
     read = bus.read_word_data(address, 4)
     swapped = struct.unpack("<H", struct.pack(">H", read))[0]
     capacity = swapped/256
     return capacity

bus = smbus2.SMBus(1)

try:
    print ("Testing X120x battery script...")
    print ("******************")
    voltage = readVoltage(bus)
    capacity = readCapacity(bus)
    
    print ("Voltage:%5.2fV" % voltage)
    print ("Battery:%5i%%" % capacity)

    if capacity == 100:
            print ("Battery FULL")

    if capacity < 20:
            print ("Battery Low")

    if voltage < 3.20:
            print ("Battery LOW!!!")
            print ("Would shutdown in 5 seconds (disabled for testing)")

except Exception as e:
    print(f"Error: {e}")
    print("X120x battery script failed - trying alternative buses...")
    
    # Test other buses like we found before
    for bus_num in [11, 13, 14]:
        try:
            test_bus = smbus2.SMBus(bus_num)
            print(f"\nTesting Bus {bus_num}:")
            voltage = readVoltage(test_bus)
            capacity = readCapacity(test_bus)
            print(f"Bus {bus_num} - Voltage: {voltage:.2f}V, Capacity: {capacity}%")
            test_bus.close()
        except Exception as bus_error:
            print(f"Bus {bus_num} failed: {bus_error}")

bus.close()