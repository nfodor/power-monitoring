#!/usr/bin/env python3

import time
import csv
import smbus
import psutil
import os
import json
from datetime import datetime, timedelta
from statistics import mean

class X1200RuntimeEstimator:
    """Estimates remaining runtime for X1200 UPS based on battery level and power consumption"""
    
    def __init__(self):
        self.bus = None
        self.connected = False
        self.device_addr = 0x36  # MAX17040G+ fuel gauge address
        
        # MAX17040G+ registers
        self.VCELL_REG = 0x02    # Battery voltage
        self.SOC_REG = 0x04      # State of charge (%)
        
        # Battery capacity estimates for X1200
        self.battery_capacity_wh = 25.0  # Approximate Wh for X1200 battery
        self.min_battery_voltage = 3.0   # Cutoff voltage
        self.safe_discharge_limit = 0.1  # Don't discharge below 10%
        
        self.connect()
    
    def connect(self):
        """Connect to X1200 MAX17040G+ fuel gauge"""
        for bus_num in [1, 11, 4]:
            try:
                bus = smbus.SMBus(bus_num)
                # Test communication
                version = bus.read_word_data(self.device_addr, 0x08)  # VERSION_REG
                self.bus = bus
                self.bus_num = bus_num
                self.connected = True
                return True
            except:
                if bus:
                    bus.close()
                continue
        return False
    
    def get_battery_data(self):
        """Get current battery voltage and percentage"""
        if not self.connected:
            return None
            
        try:
            # Read voltage (VCELL register)
            vcell_raw = self.bus.read_word_data(self.device_addr, self.VCELL_REG)
            vcell_swapped = ((vcell_raw & 0xFF) << 8) | ((vcell_raw & 0xFF00) >> 8)
            voltage = (vcell_swapped >> 4) * 1.25 / 1000.0
            
            # Read state of charge (SOC register)  
            soc_raw = self.bus.read_word_data(self.device_addr, self.SOC_REG)
            soc_swapped = ((soc_raw & 0xFF) << 8) | ((soc_raw & 0xFF00) >> 8)
            percentage = soc_swapped / 256.0
            
            return {
                'voltage': voltage,
                'percentage': percentage,
                'timestamp': datetime.now()
            }
        except:
            return None
    
    def get_system_power_consumption(self):
        """Estimate current system power consumption"""
        try:
            # CPU utilization affects power draw significantly
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # Memory usage (higher memory = higher power)
            memory_percent = psutil.virtual_memory().percent
            
            # CPU temperature (indicator of thermal load)
            cpu_temp = 0
            try:
                with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                    cpu_temp = float(f.read().strip()) / 1000.0
            except:
                pass
            
            # Load average
            load_avg = os.getloadavg()[0]
            
            # Estimate power consumption based on system metrics
            # Base Raspberry Pi power consumption: ~2-3W
            base_power = 2.5  # Watts
            
            # Additional power based on CPU load (Pi can use up to ~8W under full load)
            cpu_power = (cpu_percent / 100.0) * 5.5  # 0-5.5W additional
            
            # Memory power (minimal but non-zero)
            memory_power = (memory_percent / 100.0) * 0.5  # 0-0.5W additional
            
            # Temperature-based adjustment (higher temp = higher power)
            temp_factor = 1.0
            if cpu_temp > 50:
                temp_factor = 1.1 + (cpu_temp - 50) / 100.0  # Up to 30% increase at 80°C
            
            estimated_watts = (base_power + cpu_power + memory_power) * temp_factor
            
            return {
                'estimated_watts': estimated_watts,
                'cpu_percent': cpu_percent,
                'memory_percent': memory_percent,
                'cpu_temp': cpu_temp,
                'load_avg': load_avg
            }
            
        except Exception as e:
            print(f"Error estimating power consumption: {e}")
            return {'estimated_watts': 4.0}  # Default estimate
    
    def calculate_runtime_estimates(self, battery_data, power_data):
        """Calculate multiple runtime estimates using different methods"""
        if not battery_data:
            return None
            
        estimates = {}
        
        # Method 1: Simple percentage-based estimate
        if battery_data['percentage'] > self.safe_discharge_limit * 100:
            usable_percentage = battery_data['percentage'] - (self.safe_discharge_limit * 100)
            # Assume typical X1200 runtime is ~2-4 hours at 100%
            typical_full_runtime_hours = 2.5
            estimates['percentage_based'] = (usable_percentage / 100.0) * typical_full_runtime_hours
        
        # Method 2: Voltage-based estimate (more accurate for Li-ion)
        voltage = battery_data['voltage']
        if voltage > self.min_battery_voltage:
            # Li-ion discharge curve approximation
            if voltage >= 3.7:
                voltage_percentage = min(100, ((voltage - 3.0) / 1.2) * 100)  # 3.0V to 4.2V range
            else:
                # Below 3.7V, discharge accelerates
                voltage_percentage = max(0, ((voltage - 3.0) / 0.7) * 20)  # 3.0V to 3.7V = 0-20%
            
            if voltage_percentage > self.safe_discharge_limit * 100:
                usable_voltage_percentage = voltage_percentage - (self.safe_discharge_limit * 100)
                estimates['voltage_based'] = (usable_voltage_percentage / 100.0) * 2.5
        
        # Method 3: Power consumption-based estimate
        if power_data and self.battery_capacity_wh > 0:
            current_watts = power_data['estimated_watts']
            if current_watts > 0:
                usable_capacity = self.battery_capacity_wh * (battery_data['percentage'] / 100.0 - self.safe_discharge_limit)
                if usable_capacity > 0:
                    estimates['power_based'] = usable_capacity / current_watts
        
        # Method 4: Historical drain rate (if available)
        historical_runtime = self.calculate_historical_runtime()
        if historical_runtime:
            estimates['historical'] = historical_runtime
        
        return estimates
    
    def calculate_historical_runtime(self):
        """Calculate runtime based on recent battery drain history"""
        try:
            # Read recent battery log to calculate drain rate
            csv_filename = "/home/pi/x1200_battery_log.csv"
            
            if not os.path.exists(csv_filename):
                return None
            
            # Read last 20 entries (up to 2 minutes of data)
            recent_data = []
            with open(csv_filename, 'r') as file:
                reader = csv.DictReader(file)
                rows = list(reader)
                recent_data = rows[-20:] if len(rows) >= 20 else rows
            
            if len(recent_data) < 10:
                return None
            
            # Calculate drain rate
            drain_rates = []
            for i in range(1, len(recent_data)):
                try:
                    prev_pct = float(recent_data[i-1]['Battery %'])
                    curr_pct = float(recent_data[i]['Battery %'])
                    
                    if prev_pct > 0 and curr_pct > 0:
                        drain_rate = prev_pct - curr_pct  # % per 5-second interval
                        if drain_rate > 0:  # Only positive drain rates
                            drain_rates.append(drain_rate)
                except:
                    continue
            
            if drain_rates:
                avg_drain_per_5s = mean(drain_rates)
                if avg_drain_per_5s > 0:
                    # Calculate remaining time in hours
                    current_battery = self.get_battery_data()
                    if current_battery:
                        usable_percentage = current_battery['percentage'] - (self.safe_discharge_limit * 100)
                        if usable_percentage > 0:
                            remaining_intervals = usable_percentage / avg_drain_per_5s
                            remaining_hours = (remaining_intervals * 5) / 3600  # Convert to hours
                            return remaining_hours
            
            return None
            
        except Exception as e:
            print(f"Error calculating historical runtime: {e}")
            return None
    
    def get_runtime_estimate(self):
        """Get comprehensive runtime estimate"""
        battery_data = self.get_battery_data()
        power_data = self.get_system_power_consumption()
        
        if not battery_data:
            return None
        
        estimates = self.calculate_runtime_estimates(battery_data, power_data)
        
        # Calculate confidence-weighted average
        final_estimate = None
        if estimates:
            # Weight estimates by confidence
            weights = {
                'percentage_based': 0.2,  # Least accurate
                'voltage_based': 0.3,     # Better for Li-ion
                'power_based': 0.3,       # Good if power estimate is accurate
                'historical': 0.5         # Most accurate if available
            }
            
            weighted_sum = 0
            total_weight = 0
            
            for method, estimate in estimates.items():
                if estimate and estimate > 0:
                    weight = weights.get(method, 0.25)
                    weighted_sum += estimate * weight
                    total_weight += weight
            
            if total_weight > 0:
                final_estimate = weighted_sum / total_weight
        
        return {
            'battery_voltage': battery_data['voltage'],
            'battery_percentage': battery_data['percentage'],
            'estimated_watts': power_data.get('estimated_watts', 0) if power_data else 0,
            'cpu_percent': power_data.get('cpu_percent', 0) if power_data else 0,
            'cpu_temp': power_data.get('cpu_temp', 0) if power_data else 0,
            'individual_estimates': estimates or {},
            'final_estimate_hours': final_estimate,
            'timestamp': datetime.now().isoformat()
        }
    
    def format_runtime_display(self, runtime_hours):
        """Format runtime for human-readable display"""
        if not runtime_hours or runtime_hours <= 0:
            return "Unable to estimate"
        
        if runtime_hours < 1:
            minutes = int(runtime_hours * 60)
            return f"{minutes} minutes"
        elif runtime_hours < 24:
            hours = int(runtime_hours)
            minutes = int((runtime_hours - hours) * 60)
            if minutes > 0:
                return f"{hours}h {minutes}m"
            else:
                return f"{hours} hours"
        else:
            days = int(runtime_hours / 24)
            remaining_hours = int(runtime_hours % 24)
            return f"{days} days {remaining_hours} hours"
    
    def close(self):
        """Close I2C connection"""
        if self.bus:
            self.bus.close()

def main():
    """Main runtime estimation function"""
    estimator = X1200RuntimeEstimator()
    
    if not estimator.connected:
        print("❌ Could not connect to X1200. Using system-only estimates.")
        print("Check X1200 connection and ensure I2C is enabled.")
        return
    
    print("🔋 X1200 Runtime Estimator")
    print("=" * 50)
    
    try:
        result = estimator.get_runtime_estimate()
        
        if not result:
            print("❌ Failed to get battery data")
            return
        
        # Display current status
        print(f"📊 Current Status:")
        print(f"   Battery: {result['battery_percentage']:.1f}% ({result['battery_voltage']:.2f}V)")
        print(f"   System Load: CPU {result['cpu_percent']:.0f}%, Temp {result['cpu_temp']:.1f}°C")
        print(f"   Estimated Power: {result['estimated_watts']:.1f}W")
        print()
        
        # Display individual estimates
        if result['individual_estimates']:
            print("📈 Runtime Estimates by Method:")
            for method, estimate in result['individual_estimates'].items():
                if estimate:
                    formatted = estimator.format_runtime_display(estimate)
                    method_name = method.replace('_', ' ').title()
                    print(f"   {method_name:15}: {formatted}")
            print()
        
        # Display final estimate
        if result['final_estimate_hours']:
            formatted_runtime = estimator.format_runtime_display(result['final_estimate_hours'])
            print(f"⏱️  Final Estimate: {formatted_runtime}")
            
            # Add warnings based on remaining time
            if result['final_estimate_hours'] < 0.5:  # Less than 30 minutes
                print("🚨 CRITICAL: Less than 30 minutes remaining!")
            elif result['final_estimate_hours'] < 1:  # Less than 1 hour
                print("⚠️  WARNING: Less than 1 hour remaining")
            elif result['final_estimate_hours'] < 2:  # Less than 2 hours
                print("ℹ️  NOTICE: Less than 2 hours remaining")
        else:
            print("❌ Unable to calculate reliable runtime estimate")
        
        # Save result to JSON for other tools
        with open('/home/pi/runtime_estimate.json', 'w') as f:
            json.dump(result, f, indent=2)
            
        print(f"\n💾 Detailed results saved to /home/pi/runtime_estimate.json")
        
    except KeyboardInterrupt:
        print("\n👋 Runtime estimation stopped by user")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        estimator.close()

if __name__ == "__main__":
    main()