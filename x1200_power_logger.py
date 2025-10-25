import time
import csv
from datetime import datetime
from x1200_common import X1200Monitor

class X1200PowerMonitor(X1200Monitor):
    def __init__(self):
        super().__init__()

    def read_power_data(self):
        """Read power data from X1200"""
        if not self.connected:
            return None
            
        try:
            bus_voltage = self.get_battery_voltage()
            shunt_voltage = self.bus.read_word_data(self.device_addr, 0x01)
            if shunt_voltage > 32767:
                shunt_voltage -= 65536  # Convert from unsigned to signed
            shunt_voltage = shunt_voltage * 0.01  # Convert to mV

            current = self.bus.read_word_data(self.device_addr, 0x04)
            if current > 32767:
                current -= 65536
            current = current * 1.0  # mA (depends on shunt resistor)

            power = self.bus.read_word_data(self.device_addr, 0x03)
            power = power * 20.0  # mW (depends on shunt resistor)
            
            return {
                'bus_voltage': bus_voltage,
                'shunt_voltage': shunt_voltage,
                'current': current,
                'power': power,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"Error reading power data: {e}")
            return None

def main():
    """Main power logging function"""
    monitor = X1200PowerMonitor()
    
    if not monitor.connected:
        print("Failed to connect to X1200. Check connections and try again.")
        return
    
    # Setup CSV logging
    csv_filename = "/home/pi/x1200_power_log.csv"
    
    # Write header if file is new
    try:
        with open(csv_filename, 'x', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([
                "Timestamp", "Bus Voltage (V)", "Shunt Voltage (mV)", 
                "Current (mA)", "Power (mW)", "Low Voltage Alert", 
                "High Current Alert", "Notes"
            ])
    except FileExistsError:
        pass  # File already exists, append to it
    
    print(f"📊 Logging X1200 power data to {csv_filename}")
    print(f"🔌 Connected to: {monitor.device_name}")
    print("⚠️  Monitoring for voltage drops below 10.5V and current spikes above 4000mA")
    print("Press Ctrl+C to stop logging")
    
    voltage_drops = 0
    
    try:
        while True:
            data = monitor.read_power_data()
            
            if data is None:
                print("❌ Failed to read power data")
                time.sleep(5)
                continue
            
            # Crash detection thresholds
            LOW_VOLTAGE_THRESHOLD = 10.5
            HIGH_CURRENT_THRESHOLD = 4000
            
            low_voltage_alert = "YES" if data['bus_voltage'] < LOW_VOLTAGE_THRESHOLD else "NO"
            high_current_alert = "YES" if abs(data['current']) > HIGH_CURRENT_THRESHOLD else "NO"
            
            notes = ""
            if low_voltage_alert == "YES":
                voltage_drops += 1
                notes += f"LOW_VOLTAGE_DROP_{voltage_drops} "
                print(f"⚠️  WARNING: Low voltage detected: {data['bus_voltage']:.2f}V")
            else:
                voltage_drops = 0
                
            if high_current_alert == "YES":
                notes += "HIGH_CURRENT_SPIKE "
                print(f"⚠️  WARNING: High current detected: {data['current']:.0f}mA")
                
            if voltage_drops >= 3:
                notes += "CRITICAL_VOLTAGE_DROPS "
                print(f"🚨 CRITICAL: {voltage_drops} consecutive voltage drops - potential crash imminent!")
            
            # Log to CSV
            with open(csv_filename, 'a', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([
                    data['timestamp'], 
                    f"{data['bus_voltage']:.3f}",
                    f"{data['shunt_voltage']:.2f}",
                    f"{data['current']:.0f}",
                    f"{data['power']:.0f}",
                    low_voltage_alert,
                    high_current_alert,
                    notes.strip()
                ])
            
            # Console output
            alert_indicator = "🚨" if (low_voltage_alert == "YES" or high_current_alert == "YES") else "✅"
            print(f"{alert_indicator} {data['timestamp']}: {data['bus_voltage']:.2f}V, {data['current']:.0f}mA, {data['power']:.0f}mW")
            
            time.sleep(5)  # Log every 5 seconds
            
    except KeyboardInterrupt:
        print("\n📊 Power logging stopped by user.")
        print(f"📁 Log file saved: {csv_filename}")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
    finally:
        monitor.close()

if __name__ == "__main__":
    main()
