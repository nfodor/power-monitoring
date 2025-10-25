#!/usr/bin/env python3

import csv
import json
import os
import time
import socket
import qrcode
import io
import base64
import subprocess
import re
import glob
import uuid
import hashlib
import threading
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template_string, send_from_directory, request, session, redirect, url_for
from flask_cors import CORS
from functools import wraps
import psutil
import smbus
from bypass_notifier import BypassNotifier
from max17040_advanced import MAX17040Advanced
try:
    import pushover
    PUSHOVER_AVAILABLE = True
except ImportError:
    PUSHOVER_AVAILABLE = False

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'power-dashboard-secret-key-change-in-production')

# Configure session for security and persistence
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True for HTTPS in production
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# Configure CORS with credentials support
CORS(app, supports_credentials=True, origins=['http://localhost:9434', 'http://127.0.0.1:9434'])

# Authentication configuration
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = os.environ.get('DASHBOARD_PASSWORD', 'power123')  # Default password, change via env variable

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session or not session['logged_in']:
            if request.is_json:
                return jsonify({'error': 'Authentication required', 'login_required': True}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

class UnitIDManager:
    def __init__(self, config_file="/home/pi/dev/power/unit_config.json"):
        self.config_file = config_file
        self.unit_data = self.load_unit_data()
    
    def generate_unique_unit_id(self):
        """Generate a unique unit ID based on system info and location data"""
        try:
            # Collect system identifiers
            system_info = []
            
            # MAC addresses
            try:
                import netifaces
                for interface in netifaces.interfaces():
                    if interface != 'lo':  # Skip loopback
                        try:
                            mac = netifaces.ifaddresses(interface).get(netifaces.AF_LINK)
                            if mac:
                                system_info.append(mac[0]['addr'])
                        except:
                            pass
            except ImportError:
                # Fallback to ip command
                try:
                    result = subprocess.run(['ip', 'link', 'show'], capture_output=True, text=True)
                    for line in result.stdout.split('\n'):
                        if 'link/ether' in line:
                            mac = line.split('link/ether')[1].split()[0]
                            system_info.append(mac)
                except:
                    pass
            
            # CPU serial (Pi specific)
            try:
                with open('/proc/cpuinfo', 'r') as f:
                    for line in f:
                        if line.startswith('Serial'):
                            serial = line.split(':')[1].strip()
                            system_info.append(serial)
                            break
            except:
                pass
            
            # Hostname
            try:
                hostname = socket.gethostname()
                system_info.append(hostname)
            except:
                pass
            
            # Current timestamp for uniqueness
            timestamp = str(int(time.time()))
            system_info.append(timestamp)
            
            # Generate GUID
            guid = str(uuid.uuid4())
            system_info.append(guid)
            
            # Create hash from all system info
            combined = ''.join(system_info)
            hash_obj = hashlib.sha256(combined.encode())
            base_hash = hash_obj.hexdigest()[:16]  # 16 chars
            
            # Format as readable unit ID: METAL-XXXX-XXXX-XXXX
            unit_id = f"METAL-{base_hash[:4].upper()}-{base_hash[4:8].upper()}-{base_hash[8:12].upper()}"
            
            return {
                'unit_id': unit_id,
                'generated_at': datetime.now().isoformat(),
                'system_fingerprint': base_hash,
                'hostname': hostname if 'hostname' in locals() else 'unknown',
                'guid': guid
            }
            
        except Exception as e:
            # Fallback ID generation
            fallback_guid = str(uuid.uuid4())[:8].upper()
            return {
                'unit_id': f"METAL-{fallback_guid[:4]}-{fallback_guid[4:]}-XXXX",
                'generated_at': datetime.now().isoformat(),
                'system_fingerprint': 'fallback',
                'hostname': 'unknown',
                'guid': fallback_guid,
                'error': str(e)
            }
    
    def load_unit_data(self):
        """Load unit data from JSON file"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            else:
                # Generate new unit data
                unit_data = self.generate_unique_unit_id()
                self.save_unit_data(unit_data)
                return unit_data
        except Exception as e:
            print(f"Error loading unit data: {e}")
            # Generate fallback data
            return self.generate_unique_unit_id()
    
    def save_unit_data(self, unit_data):
        """Save unit data to JSON file"""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            
            with open(self.config_file, 'w') as f:
                json.dump(unit_data, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving unit data: {e}")
            return False
    
    def get_unit_id(self):
        """Get current unit ID"""
        return self.unit_data.get('unit_id', 'METAL-UNKNOWN')
    
    def reset_unit_id(self):
        """Generate and save new unit ID"""
        self.unit_data = self.generate_unique_unit_id()
        self.save_unit_data(self.unit_data)
        return self.unit_data
    
    def get_unit_info(self):
        """Get complete unit information"""
        return self.unit_data

# Initialize Unit ID Manager
unit_manager = UnitIDManager()

class X1200PowerMonitor:
    def __init__(self):
        self.bus = None
        self.device_addr = None
        self.connected = False
        
        # Power management IC addresses (including detected hardware)
        self.possible_configs = [
            {'bus': 13, 'addr': 0x54, 'name': 'Detected UPS HAT (bus 13)'},
            {'bus': 14, 'addr': 0x54, 'name': 'Detected UPS HAT (bus 14)'},
            {'bus': 13, 'addr': 0x36, 'name': 'X1200 MAX17040G+ (bus 13)'},
            {'bus': 14, 'addr': 0x36, 'name': 'X1200 MAX17040G+ (bus 14)'},
            {'bus': 11, 'addr': 0x36, 'name': 'X1200 MAX17040G+ (bus 11)'},
            {'bus': 1, 'addr': 0x36, 'name': 'X1200 MAX17040G+ (bus 1)'},
            {'bus': 4, 'addr': 0x36, 'name': 'X1200 MAX17040G+ (bus 4)'},
            {'bus': 13, 'addr': 0x17, 'name': 'Waveshare UPS (bus 13)'},
            {'bus': 13, 'addr': 0x14, 'name': 'PiJuice HAT (bus 13)'},
            {'bus': 1, 'addr': 0x40, 'name': 'Standard INA219'},
        ]
        
        # GPIO pins for X1200
        self.GPIO_CHARGING = 16   # Battery charging control
        self.GPIO_POWER_LOSS = 6  # Power loss detection
        
        self.connect()
        self.setup_gpio()
    
    def connect(self):
        """Try to connect to X1200 power monitoring device"""
        for config in self.possible_configs:
            try:
                bus = smbus.SMBus(config['bus'])
                bus.read_word_data(config['addr'], 0)
                self.bus = bus
                self.device_addr = config['addr']
                self.connected = True
                print(f"✅ Connected to {config['name']}")
                return True
            except Exception as e:
                continue
        
        print("❌ Could not connect to X1200 power monitor")
        return False
    
    def setup_gpio(self):
        """Setup GPIO monitoring"""
        try:
            # Try to setup GPIO access
            for gpio in [self.GPIO_CHARGING, self.GPIO_POWER_LOSS]:
                if not os.path.exists(f"/sys/class/gpio/gpio{gpio}"):
                    try:
                        with open("/sys/class/gpio/export", "w") as f:
                            f.write(str(gpio))
                        time.sleep(0.1)
                        with open(f"/sys/class/gpio/gpio{gpio}/direction", "w") as f:
                            f.write("in")
                    except:
                        pass
        except Exception as e:
            print(f"GPIO setup warning: {e}")
    
    def get_gpio_state(self, gpio):
        """Read GPIO state"""
        try:
            with open(f"/sys/class/gpio/gpio{gpio}/value", "r") as f:
                return int(f.read().strip())
        except:
            try:
                result = subprocess.run(['gpioget', 'gpiochip0', str(gpio)], 
                                      capture_output=True, text=True, timeout=1)
                if result.returncode == 0:
                    return int(result.stdout.strip())
            except:
                pass
        return None
    
    def read_power_data(self):
        """Read power data from X1200"""
        if not self.connected:
            return None
            
        try:
            # Check if we're connected to detected UPS device (0x54)
            if self.device_addr == 0x54:
                # Generic UPS device - try standard power monitoring registers
                try:
                    # Try reading various registers to determine capabilities
                    reg_00 = self.bus.read_byte_data(self.device_addr, 0x00)
                    reg_01 = self.bus.read_byte_data(self.device_addr, 0x01)
                    reg_02 = self.bus.read_byte_data(self.device_addr, 0x02)
                    reg_03 = self.bus.read_byte_data(self.device_addr, 0x03)
                    
                    # Check GPIO states for power management
                    charging_gpio = self.get_gpio_state(self.GPIO_CHARGING)
                    power_loss_gpio = self.get_gpio_state(self.GPIO_POWER_LOSS)
                    
                    return {
                        'bus_voltage': reg_02 * 0.1 if reg_02 > 0 else 12.0,  # Estimate
                        'battery_percentage': reg_01 if reg_01 <= 100 else None,
                        'is_charging': charging_gpio == 0 if charging_gpio is not None else None,
                        'has_external_power': power_loss_gpio == 1 if power_loss_gpio is not None else True,
                        'power_source': 'External' if power_loss_gpio == 1 else 'Battery',
                        'shunt_voltage': 0,
                        'current': reg_03 * 10 if reg_03 > 0 else 0,  # Estimate
                        'power': (reg_02 * 0.1 * reg_03 * 10) if (reg_02 > 0 and reg_03 > 0) else 0,
                        'device_type': 'Generic UPS HAT'
                    }
                except Exception as e:
                    print(f"Error reading UPS device at 0x54: {e}")
                    return {
                        'bus_voltage': 12.0,  # Default estimate
                        'battery_percentage': None,
                        'is_charging': None,
                        'has_external_power': True,
                        'power_source': 'External',
                        'shunt_voltage': 0,
                        'current': 0,
                        'power': 0,
                        'device_type': 'Generic UPS HAT (limited data)'
                    }
                    
            # Check if we're connected to MAX17040G+ (0x36)
            elif self.device_addr == 0x36:
                # MAX17040G+ registers
                vcell_raw = self.bus.read_word_data(self.device_addr, 0x02)
                vcell_raw = ((vcell_raw & 0xFF) << 8) | ((vcell_raw & 0xFF00) >> 8)
                bus_voltage = (vcell_raw >> 4) * 1.25 / 1000.0
                
                soc_raw = self.bus.read_word_data(self.device_addr, 0x04)
                soc_raw = ((soc_raw & 0xFF) << 8) | ((soc_raw & 0xFF00) >> 8)
                raw_percentage = soc_raw / 256.0
                # Calibration correction: hardware LEDs show 100% when software shows ~75%
                battery_percentage = min(100.0, raw_percentage * 1.327)
                
                # Check GPIO states
                charging_gpio = self.get_gpio_state(self.GPIO_CHARGING)
                power_loss_gpio = self.get_gpio_state(self.GPIO_POWER_LOSS)
                
                return {
                    'bus_voltage': bus_voltage,
                    'battery_percentage': battery_percentage,
                    'is_charging': charging_gpio == 0 if charging_gpio is not None else None,
                    'has_external_power': power_loss_gpio == 1 if power_loss_gpio is not None else None,
                    'power_source': 'External USB-C' if power_loss_gpio == 1 else 'Battery',
                    'shunt_voltage': 0,
                    'current': 0,
                    'power': bus_voltage * 1000  # Rough estimate
                }
            else:
                # Original INA219-style reading
                bus_voltage_raw = self.bus.read_word_data(self.device_addr, 0x02)
                bus_voltage = ((bus_voltage_raw >> 3) & 0x1FFF) * 0.004
                
                shunt_voltage_raw = self.bus.read_word_data(self.device_addr, 0x01)
                if shunt_voltage_raw > 32767:
                    shunt_voltage_raw -= 65536
                shunt_voltage = shunt_voltage_raw * 0.01
                
                current_raw = self.bus.read_word_data(self.device_addr, 0x04)
                if current_raw > 32767:
                    current_raw -= 65536
                current = current_raw * 1.0
                
                power_raw = self.bus.read_word_data(self.device_addr, 0x03)
                power = power_raw * 20.0
                
                return {
                    'bus_voltage': bus_voltage,
                    'shunt_voltage': shunt_voltage,
                    'current': current,
                    'power': power,
                    'battery_percentage': None,
                    'is_charging': None,
                    'has_external_power': None,
                    'power_source': 'Unknown'
                }
            
        except Exception as e:
            print(f"Error reading power data: {e}")
            return None

class PowerDataAPI:
    def __init__(self):
        self.csv_file = "/home/pi/system_power_log.csv"
        self.x1200 = X1200PowerMonitor()
        self.enhanced_log_file = "/home/pi/x1200_enhanced_log.csv"

        # Initialize advanced MAX17040 monitoring
        try:
            self.max17040 = MAX17040Advanced()
            print("✅ MAX17040 Advanced monitoring initialized")
        except Exception as e:
            print(f"⚠️  MAX17040 Advanced not available: {e}")
            self.max17040 = None
        
    def get_x1200_safe_data(self):
        """CORRECT X1200 method using MAX17040 fuel gauge via smbus2"""
        try:
            import subprocess
            import struct
            
            # Read Pi's power data using vcgencmd
            result = subprocess.run(['vcgencmd', 'pmic_read_adc'], 
                                  capture_output=True, text=True, timeout=5)
            
            ext5v_voltage = 0
            total_current = 0
            
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'EXT5V_V volt(24)' in line:
                        try:
                            ext5v_voltage = float(line.split('=')[1].replace('V', ''))
                        except:
                            pass
                    elif 'current(' in line and ')=' in line:
                        try:
                            current_val = float(line.split('=')[1].replace('A', ''))
                            total_current += current_val
                        except:
                            pass
            
            # Read ACTUAL battery data from MAX17040 fuel gauge via I2C
            actual_battery_voltage = None
            battery_percentage = None
            fuel_gauge_detected = False
            
            try:
                import smbus2
                
                # ERRATIC READINGS: Bus 13:0x37 gives unstable data (30%-179% jumps)
                # Disabling until real fuel gauge location found
                for bus_num, address in [(1, 0x36), (13, 0x37), (14, 0x36)]:  # Re-enable bus 13:0x37 despite erratic readings
                    try:
                        print(f"Trying fuel gauge on I2C bus {bus_num} at address 0x{address:02x}")
                        bus = smbus2.SMBus(bus_num)
                        
                        # Read VCELL register (0x02) - battery voltage
                        print(f"Reading VCELL register (0x02) on bus {bus_num} at 0x{address:02x}")
                        read = bus.read_word_data(address, 2)
                        # Correct formula from x120x project: swap bytes then multiply
                        swapped = struct.unpack("<H", struct.pack(">H", read))[0]
                        actual_battery_voltage = swapped * 1.25 / 1000 / 16
                        print(f"Raw VCELL: {read:04x}, Swapped: {swapped:04x}, Voltage: {actual_battery_voltage:.3f}V")
                        
                        # Read SOC register (0x04) - state of charge
                        print(f"Reading SOC register (0x04) on bus {bus_num} at 0x{address:02x}")
                        read = bus.read_word_data(address, 4)
                        swapped = struct.unpack("<H", struct.pack(">H", read))[0]
                        raw_battery_percentage = swapped / 256
                        # Apply calibration correction
                        battery_percentage = min(100.0, raw_battery_percentage * 1.327)
                        print(f"Raw SOC: {read:04x}, Swapped: {swapped:04x}, Percentage: {battery_percentage:.1f}%")
                        
                        bus.close()
                        fuel_gauge_detected = True
                        print(f"SUCCESS: Fuel gauge detected on bus {bus_num}")
                        break
                        
                    except Exception as e:
                        print(f"ERROR on bus {bus_num}: {type(e).__name__}: {e}")
                        try:
                            bus.close()
                        except:
                            pass
                        continue
                        
            except ImportError:
                print("smbus2 not available - install with: sudo apt install python3-smbus2")
            except Exception as e:
                print(f"Error reading MAX17040 fuel gauge: {e}")
            
            # Fuel gauge not accessible via I2C - hardware issue or different implementation
            if not fuel_gauge_detected:
                print("FUEL GAUGE NOT ACCESSIBLE - No device at I2C address 0x36 (Remote I/O error)")
                print("Hardware LEDs work (show 100%) but fuel gauge chip not readable via I2C")
                print("Battery percentage unavailable until correct hardware interface is found")
            
            # Check GPIO6 for power loss detection using gpiod
            external_power_present = True
            try:
                import gpiod
                chip = gpiod.Chip('gpiochip0')
                gpio6_line = chip.get_line(6)
                gpio6_line.request(consumer="power_monitor", type=gpiod.LINE_REQ_DIR_IN)
                gpio6_value = gpio6_line.get_value()
                gpio6_line.release()
                chip.close()
                # GPIO6 HIGH = external power present, LOW = power loss detected
                external_power_present = (gpio6_value == 1)
            except:
                # Fallback to pinctrl method
                try:
                    gpio6_result = subprocess.run(['pinctrl', 'get', '6'], 
                                                capture_output=True, text=True, timeout=2)
                    if gpio6_result.returncode == 0:
                        external_power_present = '| hi' in gpio6_result.stdout
                except:
                    # If all GPIO methods fail, use voltage as indicator
                    external_power_present = ext5v_voltage > 4.0
            
            # Check GPIO16 for charging control status
            charging_enabled = False
            try:
                import gpiod
                chip = gpiod.Chip('gpiochip0')
                gpio16_line = chip.get_line(16)
                gpio16_line.request(consumer="power_monitor", type=gpiod.LINE_REQ_DIR_IN)
                gpio16_value = gpio16_line.get_value()
                gpio16_line.release()
                chip.close()
                # GPIO16 LOW = charging enabled
                charging_enabled = (gpio16_value == 0)
            except:
                # Fallback to pinctrl method
                try:
                    gpio16_result = subprocess.run(['pinctrl', 'get', '16'], 
                                                 capture_output=True, text=True, timeout=2)
                    if gpio16_result.returncode == 0:
                        charging_enabled = '| lo' in gpio16_result.stdout
                except:
                    charging_enabled = False
            
            # Determine battery status
            has_battery_installed = (fuel_gauge_detected and 
                                   actual_battery_voltage is not None and 
                                   actual_battery_voltage > 2.5)
            
            # Use fuel gauge battery percentage if available, otherwise calculate
            if not fuel_gauge_detected and has_battery_installed and actual_battery_voltage:
                # Fallback calculation for 18650 Li-ion (3.2V-4.2V range)
                if actual_battery_voltage >= 4.2:
                    battery_percentage = 100
                elif actual_battery_voltage <= 3.2:
                    battery_percentage = 0
                else:
                    battery_percentage = ((actual_battery_voltage - 3.2) / (4.2 - 3.2)) * 100
                    battery_percentage = min(100, max(0, battery_percentage))
            
            # Determine power source based on GPIO6 (most reliable)
            power_source = 'External Power' if external_power_present else 'Battery Power'
            
            # Charging logic - if external power + charging enabled = charging
            # The X1200 handles battery detection internally, so if external power is present 
            # and charging is enabled (GPIO16 low), assume we're charging
            is_actually_charging = external_power_present and charging_enabled
            
            charging_ready = external_power_present and charging_enabled
            charging_current = total_current * 1000 if is_actually_charging else 0
            
            # When external power is present, stabilize battery percentage to prevent fluctuations
            # The fuel gauge may show consumption-based readings, but with external power
            # we should show actual stored charge or maintain a stable reading
            stable_battery_percentage = battery_percentage
            if external_power_present and battery_percentage is not None:
                # When external power is connected, smooth out fluctuations
                # Real UPS behavior: battery % should be stable or slowly increasing (charging)
                if hasattr(self, '_last_stable_battery') and self._last_stable_battery is not None:
                    # Only allow slow increases (charging) or maintain same level
                    if battery_percentage > self._last_stable_battery + 2:  # Allow slow charging increase
                        stable_battery_percentage = self._last_stable_battery + 1
                    elif battery_percentage < self._last_stable_battery - 1:  # Prevent drops when external power present
                        stable_battery_percentage = self._last_stable_battery
                    else:
                        stable_battery_percentage = battery_percentage
                else:
                    stable_battery_percentage = battery_percentage
                self._last_stable_battery = stable_battery_percentage
            else:
                # On battery power, use actual readings (allow fluctuations)
                stable_battery_percentage = battery_percentage
                self._last_stable_battery = None
            
            return {
                'bus_voltage': ext5v_voltage,  # Regulated voltage to Pi
                'battery_voltage': actual_battery_voltage if actual_battery_voltage else 0.0,
                'battery_percentage': stable_battery_percentage,
                'is_charging': is_actually_charging,
                'charging_enabled': charging_enabled,
                'charging_ready': charging_ready,
                'has_external_power': external_power_present,
                'power_loss_detected': not external_power_present,
                'power_source': power_source,
                'input_current': total_current * 1000,
                'charging_current': charging_current,
                'current': total_current * 1000,
                'power': ext5v_voltage * total_current * 1000,
                'device_type': 'X1200 UPS HAT (MAX17040)',
                'ext5v_voltage': ext5v_voltage,
                'batt_voltage': actual_battery_voltage if actual_battery_voltage else 0.0,
                'has_battery_installed': has_battery_installed,
                'fuel_gauge_detected': fuel_gauge_detected
            }
                
        except Exception as e:
            print(f"Error reading X1200: {e}")
            return None

    def get_enhanced_monitor_status(self):
        """Read the latest record from the enhanced X1206 monitor log"""
        log_path = getattr(self, 'enhanced_log_file', None)
        if not log_path or not os.path.exists(log_path):
            return None

        try:
            last_row = None
            with open(log_path, 'r') as csv_file:
                reader = csv.DictReader(csv_file)
                for row in reader:
                    last_row = row

            if not last_row:
                return None

            def parse_float(value):
                if value is None:
                    return None
                value = value.strip()
                if not value or value.upper() == 'N/A':
                    return None
                try:
                    return float(value)
                except ValueError:
                    return None

            def parse_bool(value):
                if value is None:
                    return None
                value = value.strip().lower()
                if value in ('yes', 'true', '1'):
                    return True
                if value in ('no', 'false', '0'):
                    return False
                return None

            events_raw = (last_row.get('Events') or '').strip()
            events = [event for event in events_raw.split() if event]

            notes = (last_row.get('Notes') or '').strip()

            return {
                'timestamp': last_row.get('Timestamp'),
                'battery_voltage': parse_float(last_row.get('Battery Voltage (V)')),
                'battery_percentage': parse_float(last_row.get('Battery %')),
                'power_source': last_row.get('Power Source') or None,
                'is_charging': parse_bool(last_row.get('Is Charging')),
                'has_external_power': parse_bool(last_row.get('Has External Power')),
                'estimated_current_ma': parse_float(last_row.get('Estimated Current (mA)')),
                'cpu_temp': parse_float(last_row.get('CPU Temp (C)')),
                'load_avg': parse_float(last_row.get('Load Avg')),
                'events': events,
                'notes': notes if notes else None
            }
        except Exception as e:
            print(f"Error reading enhanced monitor log: {e}")
            return None

    def get_latest_data(self):
        """Get the most recent power data"""
        try:
            # First try SAFE X1200 method
            x1200_safe_data = self.get_x1200_safe_data()
            
            # If safe method fails, try traditional I2C (but only if no crash history)
            if x1200_safe_data is None:
                x1200_data = self.x1200.read_power_data()
            else:
                x1200_data = x1200_safe_data
            
            live_data = {
                'timestamp': datetime.now().isoformat(),
                'cpu_percent': psutil.cpu_percent(),
                'cpu_percent_per_core': psutil.cpu_percent(percpu=True),
                'cpu_cores': psutil.cpu_count() or 4,
                'memory_percent': psutil.virtual_memory().percent,
                'load_avg': os.getloadavg()[0],
                'cpu_temp': self.get_cpu_temperature(),
                'fan_speed': self.get_fan_speed(),
                'x1200_data': x1200_data,
                'system_stats': self.get_system_stats(),
                'x1200_enhanced': self.get_enhanced_monitor_status()
            }
            
            # Try to get data from CSV file for comparison
            if os.path.exists(self.csv_file):
                csv_data = self.get_latest_from_csv()
                if csv_data:
                    # Use CSV data if it's recent (within last 30 seconds)
                    csv_time = datetime.fromisoformat(csv_data['timestamp'])
                    if datetime.now() - csv_time < timedelta(seconds=30):
                        # Ensure cpu_cores is always present
                        csv_data['cpu_cores'] = psutil.cpu_count() or 4
                        return csv_data
            
            return live_data
            
        except Exception as e:
            print(f"Error getting latest data: {e}")
            return None
    
    def get_latest_from_csv(self):
        """Get the latest entry from CSV file"""
        try:
            with open(self.csv_file, 'r', newline='') as file:
                reader = csv.DictReader(file)
                rows = list(reader)
                if rows:
                    latest = rows[-1]
                    return {
                        'timestamp': latest['Timestamp'],
                        'cpu_percent': float(latest['CPU %']) if latest['CPU %'] != 'N/A' else 0,
                        'cpu_temp': float(latest['CPU Temp (C)']) if latest['CPU Temp (C)'] != 'N/A' else 0,
                        'memory_percent': float(latest['Memory %']) if latest['Memory %'] != 'N/A' else 0,
                        'load_avg': float(latest['Load Avg']) if latest['Load Avg'] != 'N/A' else 0,
                        'alerts': latest.get('Alerts', ''),
                        'notes': latest.get('Notes', '')
                    }
        except Exception as e:
            print(f"Error reading CSV: {e}")
        return None
    
    def get_historical_data(self, hours=1):
        """Get historical data for the specified number of hours"""
        try:
            if not os.path.exists(self.csv_file):
                return []
                
            cutoff_time = datetime.now() - timedelta(hours=hours)
            data = []
            
            with open(self.csv_file, 'r', newline='') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    try:
                        row_time = datetime.fromisoformat(row['Timestamp'])
                        if row_time >= cutoff_time:
                            data.append({
                                'timestamp': row['Timestamp'],
                                'cpu_percent': float(row['CPU %']) if row['CPU %'] != 'N/A' else 0,
                                'cpu_temp': float(row['CPU Temp (C)']) if row['CPU Temp (C)'] != 'N/A' else 0,
                                'memory_percent': float(row['Memory %']) if row['Memory %'] != 'N/A' else 0,
                                'load_avg': float(row['Load Avg']) if row['Load Avg'] != 'N/A' else 0,
                                'alerts': row.get('Alerts', ''),
                                'notes': row.get('Notes', '')
                            })
                    except (ValueError, KeyError) as e:
                        continue
                        
            return data[-100:]  # Return last 100 readings max
            
        except Exception as e:
            print(f"Error getting historical data: {e}")
            return []
    
    def get_cpu_temperature(self):
        """Get CPU temperature"""
        try:
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                temp = float(f.read().strip()) / 1000.0
                return temp
        except:
            return 0
    
    def get_fan_speed(self):
        """Get fan speed in RPM"""
        try:
            with open('/sys/class/hwmon/hwmon2/fan1_input', 'r') as f:
                return int(f.read().strip())
        except:
            return 0
    
    def get_top_processes(self, limit=10):
        """Get top CPU and memory consuming processes"""
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'create_time']):
                try:
                    proc_info = proc.info
                    if proc_info['cpu_percent'] is None:
                        proc_info['cpu_percent'] = 0
                    if proc_info['memory_percent'] is None:
                        proc_info['memory_percent'] = 0
                    
                    # Calculate process age
                    proc_age = time.time() - proc_info['create_time']
                    proc_info['age_hours'] = proc_age / 3600
                    
                    processes.append(proc_info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            # Sort by CPU usage
            cpu_top = sorted(processes, key=lambda x: x['cpu_percent'], reverse=True)[:limit]
            # Sort by memory usage
            mem_top = sorted(processes, key=lambda x: x['memory_percent'], reverse=True)[:limit]
            
            return {
                'cpu_intensive': cpu_top,
                'memory_intensive': mem_top
            }
        except Exception as e:
            print(f"Error getting top processes: {e}")
            return {'cpu_intensive': [], 'memory_intensive': []}
    
    def get_syslog_errors(self, hours=1, limit=50):
        """Get recent syslog errors and warnings"""
        try:
            errors = []
            cutoff_time = datetime.now() - timedelta(hours=hours)
            
            # Common syslog locations
            syslog_files = [
                '/var/log/syslog',
                '/var/log/messages',
                '/var/log/kern.log',
                '/var/log/daemon.log'
            ]
            
            for log_file in syslog_files:
                if not os.path.exists(log_file):
                    continue
                    
                try:
                    # Use tail to get recent entries efficiently
                    result = subprocess.run(['tail', '-1000', log_file], 
                                          capture_output=True, text=True, timeout=5)
                    
                    for line in result.stdout.split('\n'):
                        if not line.strip():
                            continue
                            
                        # Parse syslog format
                        # Example: Jan 21 17:30:45 hostname service[1234]: error message
                        match = re.match(r'(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(\S+)\s+(.+?):\s*(.+)', line)
                        if not match:
                            continue
                            
                        timestamp_str, hostname, service, message = match.groups()
                        
                        # Check for error/warning keywords
                        error_keywords = ['error', 'fail', 'critical', 'emergency', 'alert', 'warning', 'segfault', 'kernel panic', 'oops', 'bug', 'crash']
                        message_lower = message.lower()
                        
                        severity = None
                        for keyword in error_keywords:
                            if keyword in message_lower:
                                if keyword in ['critical', 'emergency', 'alert', 'segfault', 'kernel panic', 'oops', 'crash']:
                                    severity = 'critical'
                                elif keyword in ['error', 'fail']:
                                    severity = 'error'
                                elif keyword in ['warning', 'bug']:
                                    severity = 'warning'
                                break
                        
                        if severity:
                            # Convert timestamp to current year
                            try:
                                current_year = datetime.now().year
                                log_time = datetime.strptime(f"{current_year} {timestamp_str}", "%Y %b %d %H:%M:%S")
                                
                                if log_time >= cutoff_time:
                                    errors.append({
                                        'timestamp': log_time.isoformat(),
                                        'hostname': hostname,
                                        'service': service,
                                        'message': message.strip(),
                                        'severity': severity,
                                        'log_file': os.path.basename(log_file)
                                    })
                            except ValueError:
                                continue
                                
                except subprocess.TimeoutExpired:
                    continue
                except Exception as e:
                    print(f"Error reading {log_file}: {e}")
                    continue
            
            # Sort by timestamp and limit results
            errors.sort(key=lambda x: x['timestamp'], reverse=True)
            return errors[:limit]
            
        except Exception as e:
            print(f"Error getting syslog errors: {e}")
            return []
    
    def get_kernel_messages(self, limit=20):
        """Get recent kernel messages from dmesg"""
        try:
            result = subprocess.run(['dmesg', '-T', '--level=err,crit,alert,emerg'], 
                                  capture_output=True, text=True, timeout=5)
            
            messages = []
            for line in result.stdout.split('\n')[-limit:]:
                if line.strip():
                    # Parse dmesg timestamp format
                    match = re.match(r'\[([^\]]+)\]\s*(.+)', line)
                    if match:
                        timestamp_str, message = match.groups()
                        try:
                            # Convert kernel timestamp to datetime
                            timestamp = datetime.strptime(timestamp_str, "%a %b %d %H:%M:%S %Y")
                            messages.append({
                                'timestamp': timestamp.isoformat(),
                                'message': message.strip(),
                                'source': 'kernel'
                            })
                        except ValueError:
                            # Fallback for different timestamp formats
                            messages.append({
                                'timestamp': datetime.now().isoformat(),
                                'message': line.strip(),
                                'source': 'kernel'
                            })
            
            return messages
            
        except Exception as e:
            print(f"Error getting kernel messages: {e}")
            return []
    
    def get_system_stats(self):
        """Get comprehensive system statistics"""
        try:
            # Get disk usage
            disk = psutil.disk_usage('/')
            
            # Get network stats
            net = psutil.net_io_counters()
            
            # Get uptime
            boot_time = psutil.boot_time()
            uptime_seconds = time.time() - boot_time
            
            # Get swap usage
            swap = psutil.swap_memory()
            swap_percent = (swap.used / swap.total * 100) if swap.total > 0 else 0
            
            return {
                'disk_usage_percent': (disk.used / disk.total) * 100,
                'disk_free_gb': disk.free / (1024**3),
                'network_bytes_sent': net.bytes_sent,
                'network_bytes_recv': net.bytes_recv,
                'uptime_hours': uptime_seconds / 3600,
                'processes_count': len(psutil.pids()),
                'cpu_count': psutil.cpu_count(),
                'swap_usage_percent': swap_percent,
                'swap_total_gb': swap.total / (1024**3),
                'swap_used_gb': swap.used / (1024**3)
            }
        except Exception as e:
            print(f"Error getting system stats: {e}")
            return {}
    
    def get_network_status(self):
        """Get comprehensive network connectivity and interface status"""
        try:
            import statistics
            import threading
            
            network_info = {
                'connected': False,
                'primary_interface': None,
                'interfaces': {},
                'internet_latency': None,
                'dns_latency': None,
                'bandwidth': {
                    'download_mbps': 0,
                    'upload_mbps': 0
                },
                'connection_quality': 'Unknown'
            }
            
            # Get network interfaces
            interfaces = psutil.net_if_addrs()
            interface_stats = psutil.net_if_stats()
            
            # Find active interfaces with IP addresses
            active_interfaces = []
            for iface, addrs in interfaces.items():
                if iface == 'lo':  # Skip loopback
                    continue
                    
                iface_info = {
                    'name': iface,
                    'up': interface_stats[iface].isup if iface in interface_stats else False,
                    'addresses': []
                }
                
                for addr in addrs:
                    if addr.family == socket.AF_INET:  # IPv4
                        iface_info['addresses'].append({
                            'type': 'IPv4',
                            'address': addr.address,
                            'netmask': addr.netmask
                        })
                    elif addr.family == socket.AF_INET6:  # IPv6
                        iface_info['addresses'].append({
                            'type': 'IPv6',
                            'address': addr.address
                        })
                
                if iface_info['up'] and iface_info['addresses']:
                    active_interfaces.append(iface_info)
                    network_info['interfaces'][iface] = iface_info
            
            # Test internet connectivity and measure latency
            test_hosts = [
                ('8.8.8.8', 53),      # Google DNS
                ('1.1.1.1', 53),      # Cloudflare DNS
                ('208.67.222.222', 53) # OpenDNS
            ]
            
            latencies = []
            for host, port in test_hosts:
                try:
                    start_time = time.time()
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(2)
                    result = sock.connect_ex((host, port))
                    sock.close()
                    
                    if result == 0:
                        latency = (time.time() - start_time) * 1000  # Convert to ms
                        latencies.append(latency)
                        network_info['connected'] = True
                except:
                    pass
            
            if latencies:
                network_info['internet_latency'] = statistics.mean(latencies)
            
            # Test DNS resolution
            try:
                start_time = time.time()
                socket.gethostbyname('www.google.com')
                network_info['dns_latency'] = (time.time() - start_time) * 1000
            except:
                network_info['dns_latency'] = None
            
            # Determine primary interface (one with default route)
            try:
                # Get default gateway
                result = subprocess.run(['ip', 'route', 'show', 'default'], 
                                      capture_output=True, text=True, timeout=2)
                if result.returncode == 0:
                    # Parse output like: "default via 192.168.1.1 dev eth0"
                    match = re.search(r'default.*dev\s+(\S+)', result.stdout)
                    if match:
                        primary_iface = match.group(1)
                        if primary_iface in network_info['interfaces']:
                            network_info['primary_interface'] = primary_iface
            except:
                pass
            
            # Get bandwidth statistics (rate over last second)
            try:
                # First reading
                net1 = psutil.net_io_counters()
                time.sleep(1)
                # Second reading
                net2 = psutil.net_io_counters()
                
                # Calculate rates in Mbps
                download_bytes = net2.bytes_recv - net1.bytes_recv
                upload_bytes = net2.bytes_sent - net1.bytes_sent
                
                network_info['bandwidth']['download_mbps'] = (download_bytes * 8) / (1024 * 1024)
                network_info['bandwidth']['upload_mbps'] = (upload_bytes * 8) / (1024 * 1024)
            except:
                pass
            
            # Determine connection quality based on latency
            if network_info['connected'] and network_info['internet_latency']:
                latency = network_info['internet_latency']
                if latency < 20:
                    network_info['connection_quality'] = 'Excellent'
                elif latency < 50:
                    network_info['connection_quality'] = 'Good'
                elif latency < 100:
                    network_info['connection_quality'] = 'Fair'
                elif latency < 200:
                    network_info['connection_quality'] = 'Poor'
                else:
                    network_info['connection_quality'] = 'Very Poor'
            elif not network_info['connected']:
                network_info['connection_quality'] = 'Offline'
            
            return network_info
            
        except Exception as e:
            print(f"Error getting network status: {e}")
            return {
                'connected': False,
                'error': str(e)
            }

class AlertManager:
    def __init__(self, config_file="/home/pi/dev/power/alert_config.json"):
        self.config_file = config_file
        self.config = self.load_config()
        self.pushover_client = None
        self.setup_pushover()

    def load_config(self):
        """Load alert configuration from file"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading alert config: {e}")

        # Return default config
        return {
            "pushover": {
                "api_token": "",
                "user_key": "",
                "enabled": False
            },
            "thresholds": {
                "battery_low": {"enabled": True, "value": 20, "unit": "%"},
                "battery_critical": {"enabled": True, "value": 10, "unit": "%"},
                "cpu_temp_high": {"enabled": True, "value": 70, "unit": "°C"},
                "cpu_usage_high": {"enabled": True, "value": 80, "unit": "%"},
                "memory_high": {"enabled": True, "value": 90, "unit": "%"},
                "power_loss": {"enabled": True, "value": 1, "unit": "boolean"}
            },
            "alert_history": [],
            "last_alert_times": {}
        }

    def save_config(self):
        """Save configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"Error saving alert config: {e}")

    def setup_pushover(self):
        """Initialize Pushover client if configured"""
        if not PUSHOVER_AVAILABLE:
            return

        pushover_config = self.config.get("pushover", {})
        if (pushover_config.get("enabled") and
            pushover_config.get("api_token") and
            pushover_config.get("user_key")):
            try:
                import pushover
                # Initialize module with API token
                pushover.init(pushover_config["api_token"])
                # Create client with user key
                self.pushover_client = pushover.Client(pushover_config["user_key"])
                print(f"Pushover notifications enabled for user: {pushover_config['user_key'][:8]}...")
            except Exception as e:
                print(f"Error setting up Pushover: {e}")
                self.pushover_client = None

    def update_pushover_config(self, api_token, user_key, enabled=True):
        """Update Pushover configuration"""
        self.config["pushover"] = {
            "api_token": api_token,
            "user_key": user_key,
            "enabled": enabled
        }
        self.save_config()
        self.setup_pushover()

    def send_alert(self, title, message, priority=0):
        """Send alert via Pushover"""
        if not self.pushover_client or not self.config["pushover"]["enabled"]:
            return False

        try:
            # Token is already set during init, no need to pass it again
            self.pushover_client.send_message(
                message,
                title=title,
                priority=priority
            )

            # Log to alert history
            alert_entry = {
                "timestamp": datetime.now().isoformat(),
                "title": title,
                "message": message,
                "priority": priority,
                "status": "sent"
            }
            self.config["alert_history"].append(alert_entry)

            # Keep only last 100 alerts
            if len(self.config["alert_history"]) > 100:
                self.config["alert_history"] = self.config["alert_history"][-100:]

            self.save_config()
            return True

        except Exception as e:
            print(f"Error sending Pushover alert: {e}")
            return False

    def check_thresholds(self, power_data, system_data):
        """Check all configured thresholds and send alerts"""
        current_time = datetime.now()
        cooldown_minutes = 5  # Minimum time between same alert types

        # Check battery thresholds
        battery_percent = power_data.get('battery_percentage', 100)

        # Battery low
        if (self.config["thresholds"]["battery_low"]["enabled"] and
            battery_percent <= self.config["thresholds"]["battery_low"]["value"]):
            self._send_throttled_alert(
                "battery_low",
                "Battery Low Warning",
                f"Battery at {battery_percent:.1f}% - consider charging soon",
                current_time,
                cooldown_minutes
            )

        # Battery critical
        if (self.config["thresholds"]["battery_critical"]["enabled"] and
            battery_percent <= self.config["thresholds"]["battery_critical"]["value"]):
            self._send_throttled_alert(
                "battery_critical",
                "CRITICAL: Battery Very Low",
                f"Battery at {battery_percent:.1f}% - charge immediately!",
                current_time,
                cooldown_minutes,
                priority=1
            )

        # CPU temperature
        cpu_temp = system_data.get('cpu_temp', 0)
        if (self.config["thresholds"]["cpu_temp_high"]["enabled"] and
            cpu_temp >= self.config["thresholds"]["cpu_temp_high"]["value"]):
            self._send_throttled_alert(
                "cpu_temp_high",
                "High CPU Temperature",
                f"CPU temperature at {cpu_temp:.1f}°C - check cooling",
                current_time,
                cooldown_minutes
            )

        # CPU usage
        cpu_usage = system_data.get('cpu_percent', 0)
        if (self.config["thresholds"]["cpu_usage_high"]["enabled"] and
            cpu_usage >= self.config["thresholds"]["cpu_usage_high"]["value"]):
            self._send_throttled_alert(
                "cpu_usage_high",
                "High CPU Usage",
                f"CPU usage at {cpu_usage:.1f}% - system under heavy load",
                current_time,
                cooldown_minutes
            )

        # Memory usage
        memory_usage = system_data.get('memory_percent', 0)
        if (self.config["thresholds"]["memory_high"]["enabled"] and
            memory_usage >= self.config["thresholds"]["memory_high"]["value"]):
            self._send_throttled_alert(
                "memory_high",
                "High Memory Usage",
                f"Memory usage at {memory_usage:.1f}% - system may slow down",
                current_time,
                cooldown_minutes
            )

        # Power loss
        external_power = power_data.get('external_power', True)
        if (self.config["thresholds"]["power_loss"]["enabled"] and not external_power):
            self._send_throttled_alert(
                "power_loss",
                "ALERT: External Power Lost",
                f"System running on battery power ({battery_percent:.1f}% remaining)",
                current_time,
                cooldown_minutes,
                priority=1
            )

    def _send_throttled_alert(self, alert_type, title, message, current_time, cooldown_minutes, priority=0):
        """Send alert with throttling to prevent spam"""
        last_alert_time = self.config["last_alert_times"].get(alert_type)

        if last_alert_time:
            last_time = datetime.fromisoformat(last_alert_time)
            time_diff = (current_time - last_time).total_seconds() / 60

            if time_diff < cooldown_minutes:
                return  # Skip, too soon

        # Send alert
        if self.send_alert(title, message, priority):
            self.config["last_alert_times"][alert_type] = current_time.isoformat()
            self.save_config()

# Initialize API
power_api = PowerDataAPI()
alert_manager = AlertManager()

# Background monitoring thread for automatic threshold checking
import time as time_module

class BackgroundMonitor:
    def __init__(self):
        self.running = False
        self.thread = None
        self.check_interval = 60  # Check every 60 seconds

    def start(self):
        """Start background monitoring thread"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.thread.start()
            print("✅ Background monitoring started - checking thresholds every 60 seconds")

    def stop(self):
        """Stop background monitoring"""
        self.running = False
        if self.thread:
            self.thread.join()
            print("🛑 Background monitoring stopped")

    def _monitor_loop(self):
        """Main monitoring loop"""
        while self.running:
            try:
                # Get latest data
                latest_data = power_api.get_latest_data()
                if latest_data:
                    # Check thresholds and send Pushover alerts if needed
                    alert_manager.check_thresholds(latest_data, latest_data)
            except Exception as e:
                print(f"⚠️ Background monitor error: {e}")

            # Wait for next check (sleep in small chunks to allow clean shutdown)
            for _ in range(self.check_interval):
                if not self.running:
                    break
                time_module.sleep(1)

def get_local_ip():
    """Get the local IP address"""
    try:
        # Connect to a remote address to determine local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "localhost"

def generate_qr_code(url):
    """Generate QR code as base64 image"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    
    return base64.b64encode(buffer.getvalue()).decode()

def calculate_crash_risk(system_data, syslog_errors, kernel_messages, top_processes):
    """Calculate crash risk percentage based on multiple factors"""
    risk_score = 0
    
    if not system_data:
        return 0
    
    # Get CPU core count for load average normalization
    cpu_cores = system_data.get('cpu_cores', psutil.cpu_count() or 4)  # Use from data or detect
    
    # Temperature risk (thermal throttling leads to crashes)
    if system_data['cpu_temp'] > 80:
        risk_score += 30
    elif system_data['cpu_temp'] > 75:
        risk_score += 20
    elif system_data['cpu_temp'] > 70:
        risk_score += 10
    
    # CPU usage risk (sustained high usage)
    if system_data['cpu_percent'] > 95:
        risk_score += 25
    elif system_data['cpu_percent'] > 85:
        risk_score += 15
    elif system_data['cpu_percent'] > 75:
        risk_score += 5
    
    # Memory pressure risk
    if system_data['memory_percent'] > 95:
        risk_score += 20
    elif system_data['memory_percent'] > 90:
        risk_score += 10
    
    # System load risk (normalized by CPU cores)
    load_per_core = system_data['load_avg'] / cpu_cores
    if load_per_core > 2.0:  # 2x CPU cores is critical
        risk_score += 20
    elif load_per_core > 1.25:  # 1.25x CPU cores is high
        risk_score += 15
    elif load_per_core > 0.75:  # 0.75x CPU cores is moderate
        risk_score += 5
    
    # Critical system errors
    if syslog_errors:
        critical_errors = [e for e in syslog_errors if e['severity'] == 'critical']
        recent_critical = [e for e in critical_errors if 
                          (datetime.now() - datetime.fromisoformat(e['timestamp'])).seconds < 300]  # Last 5 minutes
        
        risk_score += len(recent_critical) * 15
        
        # Look for specific crash indicators in error messages
        crash_keywords = ['segfault', 'kernel panic', 'oops', 'hung task', 'out of memory', 'oom']
        for error in syslog_errors:
            message_lower = error['message'].lower()
            for keyword in crash_keywords:
                if keyword in message_lower:
                    risk_score += 25
                    break
    
    # Kernel messages (these are serious)
    if kernel_messages:
        recent_kernel = [m for m in kernel_messages if 
                        (datetime.now() - datetime.fromisoformat(m['timestamp'])).seconds < 600]  # Last 10 minutes
        risk_score += len(recent_kernel) * 10
    
    # Process anomalies
    if top_processes and top_processes['cpu_intensive']:
        # Multiple high-CPU processes competing for resources
        high_cpu_count = len([p for p in top_processes['cpu_intensive'] if p['cpu_percent'] > 80])
        if high_cpu_count > 2:
            risk_score += high_cpu_count * 8
        
        # Look for processes known to cause issues
        problematic_processes = ['chrome', 'firefox', 'node', 'python', 'java']
        for proc in top_processes['cpu_intensive'][:3]:  # Top 3 CPU users
            if any(prob in proc['name'].lower() for prob in problematic_processes) and proc['cpu_percent'] > 70:
                risk_score += 10
    
    # Power-related risks (if we have X1200 data in the future)
    # This would include battery voltage drops, power spikes, etc.
    
    return min(100, max(0, risk_score))

@app.route('/login')
def login():
    """Serve the login page"""
    if 'logged_in' in session and session['logged_in']:
        return redirect(url_for('dashboard'))

    login_html = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - Project Rhotko</title>
    <link href="https://fonts.googleapis.com/css2?family=Source+Sans+Pro:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Source Sans Pro', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #333;
        }

        .login-container {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            width: 100%;
            max-width: 400px;
            text-align: center;
        }

        .login-title {
            font-size: 32px;
            font-weight: 700;
            margin-bottom: 10px;
            color: #2c3e50;
        }

        .login-subtitle {
            font-size: 16px;
            color: #7f8c8d;
            margin-bottom: 30px;
        }

        .form-group {
            margin-bottom: 20px;
            text-align: left;
        }

        .form-label {
            display: block;
            font-weight: 600;
            margin-bottom: 8px;
            color: #34495e;
        }

        .form-input {
            width: 100%;
            padding: 12px 16px;
            border: 2px solid #ecf0f1;
            border-radius: 10px;
            font-size: 16px;
            transition: border-color 0.3s ease;
            background: #f8f9fa;
        }

        .form-input:focus {
            outline: none;
            border-color: #667eea;
            background: #fff;
        }

        .remember-me {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 25px;
        }

        .remember-me input[type="checkbox"] {
            width: 18px;
            height: 18px;
            accent-color: #667eea;
        }

        .login-btn {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }

        .login-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 30px rgba(102, 126, 234, 0.4);
        }

        .login-btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }

        .error-message {
            background: #e74c3c;
            color: white;
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-size: 14px;
        }

        .system-info {
            margin-top: 20px;
            padding-top: 20px;
            border-top: 1px solid #ecf0f1;
            font-size: 12px;
            color: #95a5a6;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <h1 class="login-title">Project Rhotko</h1>
        <p class="login-subtitle">Power Monitoring Dashboard</p>

        <div id="errorMessage" class="error-message" style="display: none;"></div>

        <form id="loginForm">
            <div class="form-group">
                <label class="form-label" for="username">Username</label>
                <input type="text" id="username" name="username" class="form-input" value="admin" required>
            </div>

            <div class="form-group">
                <label class="form-label" for="password">Password</label>
                <input type="password" id="password" name="password" class="form-input" required>
            </div>

            <div class="remember-me">
                <input type="checkbox" id="rememberMe" name="rememberMe">
                <label for="rememberMe">Remember me for 30 days</label>
            </div>

            <button type="submit" class="login-btn" id="loginBtn">Sign In</button>
        </form>

        <div class="system-info">
            X1200 UPS Power Monitoring System<br>
            Secure Access Portal
        </div>
    </div>

    <script>
        document.getElementById('loginForm').addEventListener('submit', async function(e) {
            e.preventDefault();

            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            const rememberMe = document.getElementById('rememberMe').checked;
            const loginBtn = document.getElementById('loginBtn');
            const errorMsg = document.getElementById('errorMessage');

            loginBtn.disabled = true;
            loginBtn.textContent = 'Signing in...';
            errorMsg.style.display = 'none';

            try {
                const response = await fetch('/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password, remember_me: rememberMe })
                });

                const result = await response.json();

                if (result.success) {
                    window.location.href = '/';
                } else {
                    errorMsg.textContent = result.error || 'Login failed';
                    errorMsg.style.display = 'block';
                }
            } catch (error) {
                errorMsg.textContent = 'Connection error. Please try again.';
                errorMsg.style.display = 'block';
            } finally {
                loginBtn.disabled = false;
                loginBtn.textContent = 'Sign In';
            }
        });

        // Focus password field if username is pre-filled
        if (document.getElementById('username').value) {
            document.getElementById('password').focus();
        }
    </script>
</body>
</html>
    '''
    return login_html

@app.route('/api/login', methods=['POST'])
def api_login():
    """Handle login authentication"""
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    remember_me = data.get('remember_me', False)

    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        session['logged_in'] = True
        session['username'] = username
        session['login_time'] = datetime.now().isoformat()

        if remember_me:
            # Set session to expire in 30 days
            session.permanent = True
            app.permanent_session_lifetime = timedelta(days=30)
        else:
            # Session expires when browser closes
            session.permanent = False

        return jsonify({
            'success': True,
            'message': 'Login successful',
            'username': username
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Invalid username or password'
        }), 401

@app.route('/api/logout', methods=['POST'])
@login_required
def api_logout():
    """Handle logout"""
    session.clear()
    return jsonify({'success': True, 'message': 'Logged out successfully'})

@app.route('/api/auth-status')
def auth_status():
    """Check authentication status"""
    if 'logged_in' in session and session['logged_in']:
        return jsonify({
            'authenticated': True,
            'username': session.get('username'),
            'login_time': session.get('login_time')
        })
    else:
        return jsonify({'authenticated': False})

@app.route('/')
@login_required
def dashboard():
    """Serve the dashboard HTML"""
    try:
        with open('/home/pi/dev/power/dashboard.html', 'r') as f:
            return f.read()
    except FileNotFoundError:
        return jsonify({'error': 'Dashboard file not found'}), 404

@app.route('/<path:filename>')
def serve_static(filename):
    """Serve static files from the power directory"""
    if filename.endswith(('.png', '.jpg', '.jpeg', '.svg', '.gif', '.ico', '.css', '.js')):
        return send_from_directory('/home/pi/dev/power', filename)
    return "File not found", 404

@app.route('/api/power-data')
@login_required
def get_power_data():
    """API endpoint for latest power data"""
    data = power_api.get_latest_data()
    if data:
        return jsonify(data)
    else:
        return jsonify({'error': 'No data available'}), 500

@app.route('/api/historical-data')
@login_required
def get_historical_data():
    """API endpoint for historical power data"""
    hours = request.args.get('hours', 1, type=int)
    data = power_api.get_historical_data(hours)
    return jsonify(data)

@app.route('/api/stream')
@login_required
def stream_data():
    """Server-Sent Events endpoint for real-time data streaming"""
    from flask import Response
    import json
    import time as time_module

    def generate():
        try:
            while True:
                # Get latest power and system data
                latest_data = power_api.get_latest_data()
                if latest_data:
                    # Format as SSE data
                    json_data = json.dumps(latest_data)
                    yield f"data: {json_data}\n\n"

                # Send heartbeat every 5 seconds
                time_module.sleep(5)
        except GeneratorExit:
            # Client disconnected
            pass

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Credentials': 'true'
        }
    )

@app.route('/api/system-stats')
@login_required
def get_system_stats():
    """API endpoint for system statistics"""
    stats = power_api.get_system_stats()
    return jsonify(stats)

@app.route('/api/alerts')
@login_required
def get_alerts():
    """API endpoint for current alerts"""
    latest_system = power_api.get_latest_data()
    latest_power = latest_system  # Same data source
    alerts = []

    # Check thresholds and send Pushover alerts if configured
    if latest_power and latest_system:
        alert_manager.check_thresholds(latest_power, latest_system)

    # Generate alerts for dashboard display using configured thresholds
    thresholds = alert_manager.config["thresholds"]

    if latest_system:
        # CPU usage alert
        if (thresholds["cpu_usage_high"]["enabled"] and
            latest_system['cpu_percent'] > thresholds["cpu_usage_high"]["value"]):
            alerts.append({
                'type': 'warning',
                'message': f"High CPU Usage: {latest_system['cpu_percent']:.1f}%",
                'timestamp': latest_system['timestamp']
            })

        # CPU temperature alert
        if (thresholds["cpu_temp_high"]["enabled"] and
            latest_system['cpu_temp'] > thresholds["cpu_temp_high"]["value"]):
            alerts.append({
                'type': 'critical',
                'message': f"High Temperature: {latest_system['cpu_temp']:.1f}°C",
                'timestamp': latest_system['timestamp']
            })

        # Memory usage alert
        if (thresholds["memory_high"]["enabled"] and
            latest_system['memory_percent'] > thresholds["memory_high"]["value"]):
            alerts.append({
                'type': 'warning',
                'message': f"High Memory Usage: {latest_system['memory_percent']:.1f}%",
                'timestamp': latest_system['timestamp']
            })

        # System load alert
        cpu_cores = latest_system.get('cpu_cores', psutil.cpu_count() or 4)
        load_per_core = latest_system['load_avg'] / cpu_cores
        if load_per_core > 0.75:  # 0.75x per core threshold
            alerts.append({
                'type': 'critical',
                'message': f"High System Load: {latest_system['load_avg']:.1f} ({load_per_core:.2f} per core)",
                'timestamp': latest_system['timestamp']
            })

    # Battery alerts
    if latest_power:
        battery_percent = latest_power.get('battery_percentage', 100)

        # Battery critical alert
        if (thresholds["battery_critical"]["enabled"] and
            battery_percent <= thresholds["battery_critical"]["value"]):
            alerts.append({
                'type': 'critical',
                'message': f"CRITICAL: Battery at {battery_percent:.1f}% - charge immediately!",
                'timestamp': latest_power.get('timestamp', datetime.now().isoformat())
            })
        # Battery low alert (only if not critical)
        elif (thresholds["battery_low"]["enabled"] and
              battery_percent <= thresholds["battery_low"]["value"]):
            alerts.append({
                'type': 'warning',
                'message': f"Battery Low: {battery_percent:.1f}% - consider charging",
                'timestamp': latest_power.get('timestamp', datetime.now().isoformat())
            })

        # Power loss alert
        if (thresholds["power_loss"]["enabled"] and
            not latest_power.get('external_power', True)):
            alerts.append({
                'type': 'critical',
                'message': f"External Power Lost - Running on battery ({battery_percent:.1f}%)",
                'timestamp': latest_power.get('timestamp', datetime.now().isoformat())
            })

    return jsonify(alerts)

@app.route('/api/qr-code')
def get_qr_code():
    """Generate QR code for dashboard access"""
    local_ip = get_local_ip()
    url = f"http://{local_ip}:9434"
    qr_base64 = generate_qr_code(url)
    
    return jsonify({
        'url': url,
        'qr_code': qr_base64,
        'local_ip': local_ip
    })

@app.route('/qr')
def show_qr():
    """Show QR code page for easy phone scanning"""
    local_ip = get_local_ip()
    url = f"http://{local_ip}:9434"
    qr_base64 = generate_qr_code(url)
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>📱 Connect Your Phone</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                text-align: center;
                padding: 20px;
                min-height: 100vh;
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
            }}
            .qr-container {{
                background: white;
                border-radius: 20px;
                padding: 30px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.3);
                margin: 20px;
                max-width: 400px;
            }}
            .qr-code {{
                max-width: 100%;
                height: auto;
            }}
            h1 {{
                margin-bottom: 20px;
                text-shadow: 2px 2px 4px rgba(0,0,0,0.5);
            }}
            .url-info {{
                background: rgba(255,255,255,0.1);
                border-radius: 10px;
                padding: 15px;
                margin: 20px 0;
                backdrop-filter: blur(10px);
            }}
            .url {{
                font-family: monospace;
                font-size: 1.2em;
                color: #fff;
                background: rgba(0,0,0,0.2);
                padding: 10px;
                border-radius: 5px;
                word-break: break-all;
            }}
            .instructions {{
                margin-top: 20px;
                opacity: 0.9;
            }}
            .feature-list {{
                text-align: left;
                background: rgba(255,255,255,0.1);
                border-radius: 10px;
                padding: 20px;
                margin: 20px 0;
                backdrop-filter: blur(10px);
            }}
            .feature-list li {{
                margin: 10px 0;
                list-style: none;
            }}
            .feature-list li:before {{
                content: "✅ ";
                margin-right: 10px;
            }}
            .back-link {{
                margin-top: 30px;
            }}
            .back-link a {{
                color: #fff;
                text-decoration: none;
                background: rgba(255,255,255,0.2);
                padding: 10px 20px;
                border-radius: 25px;
                backdrop-filter: blur(10px);
                transition: all 0.3s ease;
            }}
            .back-link a:hover {{
                background: rgba(255,255,255,0.3);
                transform: translateY(-2px);
            }}
        </style>
    </head>
    <body>
        <h1>📱 X1200 Power Monitor</h1>
        <p>Scan QR code with your phone to access the dashboard</p>
        
        <div class="qr-container">
            <img src="data:image/png;base64,{qr_base64}" alt="QR Code" class="qr-code">
        </div>
        
        <div class="url-info">
            <p><strong>Dashboard URL:</strong></p>
            <div class="url">{url}</div>
        </div>
        
        <div class="feature-list">
            <h3>📊 Dashboard Features</h3>
            <ul>
                <li>Real-time CPU and temperature monitoring</li>
                <li>System load and memory usage tracking</li>
                <li>Interactive charts and graphs</li>
                <li>Power consumption estimates</li>
                <li>Crash detection alerts</li>
                <li>Historical data analysis</li>
                <li>X1200 UPS battery monitoring (when connected)</li>
            </ul>
        </div>
        
        <div class="instructions">
            <p>📲 <strong>Instructions:</strong></p>
            <p>1. Open your phone's camera app</p>
            <p>2. Point it at the QR code above</p>
            <p>3. Tap the notification to open the dashboard</p>
            <p>4. Monitor your system in real-time!</p>
        </div>
        
        <div class="back-link">
            <a href="/">🖥️ Open Dashboard on This Device</a>
        </div>
        
        <script>
            // Auto-refresh QR code every 30 seconds in case IP changes
            setTimeout(function() {{
                window.location.reload();
            }}, 30000);
        </script>
    </body>
    </html>
    """
    
    return html

@app.route('/api/top-processes')
def get_top_processes():
    """API endpoint for top CPU/memory processes"""
    processes = power_api.get_top_processes()
    return jsonify(processes)

@app.route('/api/syslog-errors')
def get_syslog_errors():
    """API endpoint for recent syslog errors"""
    hours = request.args.get('hours', 1, type=int)
    errors = power_api.get_syslog_errors(hours=hours)
    return jsonify(errors)

@app.route('/api/kernel-messages')
def get_kernel_messages():
    """API endpoint for kernel error messages"""
    messages = power_api.get_kernel_messages()
    return jsonify(messages)

@app.route('/api/network-status')
def get_network_status():
    """API endpoint for network connectivity and interface status"""
    network_status = power_api.get_network_status()
    return jsonify(network_status)

@app.route('/api/critical-indicators')
def get_critical_indicators():
    """API endpoint for all critical system indicators"""
    try:
        # Get all critical data
        latest_data = power_api.get_latest_data()
        top_processes = power_api.get_top_processes(limit=5)
        syslog_errors = power_api.get_syslog_errors(hours=1, limit=10)
        kernel_messages = power_api.get_kernel_messages(limit=10)
        
        # Calculate critical score
        critical_score = 100
        warnings = []
        
        if latest_data:
            if latest_data['cpu_percent'] > 80:
                critical_score -= 20
                warnings.append(f"High CPU usage: {latest_data['cpu_percent']:.1f}%")
            
            if latest_data['cpu_temp'] > 70:
                critical_score -= 25
                warnings.append(f"High temperature: {latest_data['cpu_temp']:.1f}°C")
            
            if latest_data['memory_percent'] > 85:
                critical_score -= 15
                warnings.append(f"High memory usage: {latest_data['memory_percent']:.1f}%")
            
            cpu_cores = latest_data.get('cpu_cores', psutil.cpu_count() or 4)
            load_per_core = latest_data['load_avg'] / cpu_cores
            if load_per_core > 0.75:  # 0.75x per core threshold
                critical_score -= 20
                warnings.append(f"High system load: {latest_data['load_avg']:.1f} ({load_per_core:.2f} per core)")
        
        # Check for recent errors
        if syslog_errors:
            critical_errors = [e for e in syslog_errors if e['severity'] == 'critical']
            if critical_errors:
                critical_score -= 30
                warnings.append(f"{len(critical_errors)} critical system errors")
        
        if kernel_messages:
            critical_score -= len(kernel_messages) * 5
            warnings.append(f"{len(kernel_messages)} kernel error messages")
        
        # Check for problematic processes
        if top_processes['cpu_intensive']:
            high_cpu_procs = [p for p in top_processes['cpu_intensive'] if p['cpu_percent'] > 50]
            if high_cpu_procs:
                critical_score -= len(high_cpu_procs) * 10
                warnings.append(f"{len(high_cpu_procs)} high-CPU processes")
        
        # Crash prediction algorithm
        crash_risk = calculate_crash_risk(latest_data, syslog_errors, kernel_messages, top_processes)
        if crash_risk > 70:
            critical_score -= 40
            warnings.append(f"HIGH CRASH RISK: {crash_risk}%")
        elif crash_risk > 40:
            critical_score -= 20
            warnings.append(f"Moderate crash risk: {crash_risk}%")
        
        critical_score = max(0, critical_score)
        
        return jsonify({
            'critical_score': critical_score,
            'warnings': warnings,
            'crash_risk': crash_risk,
            'latest_data': latest_data,
            'top_processes': top_processes,
            'recent_errors': syslog_errors[:5],
            'kernel_messages': kernel_messages[:5],
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/health-check')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'server': 'X1200 Power Monitor Dashboard'
    })

@app.route('/api/unit-info')
def get_unit_info():
    """Get unit ID and information"""
    return jsonify(unit_manager.get_unit_info())

@app.route('/api/unit-id/reset', methods=['POST'])
def reset_unit_id():
    """Reset unit ID and generate new one"""
    try:
        new_unit_data = unit_manager.reset_unit_id()
        return jsonify({
            'success': True,
            'unit_data': new_unit_data,
            'message': 'Unit ID reset successfully'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': 'Failed to reset unit ID'
        }), 500

@app.route('/api/health')
def health_endpoint():
    """Comprehensive health data for ELK stack monitoring"""
    try:
        # Get current power data
        current_data = power_api.get_latest_data()
        
        # Calculate health metrics
        health_score = 100
        alerts = []
        
        # System health checks
        if current_data['cpu_percent'] > 80:
            health_score -= (current_data['cpu_percent'] - 80) * 2
            alerts.append(f"High CPU: {current_data['cpu_percent']:.1f}%")
            
        if current_data['cpu_temp'] > 70:
            health_score -= (current_data['cpu_temp'] - 70) * 3
            alerts.append(f"High Temperature: {current_data['cpu_temp']:.1f}°C")
            
        if current_data['memory_percent'] > 85:
            health_score -= (current_data['memory_percent'] - 85) * 2
            alerts.append(f"High Memory: {current_data['memory_percent']:.1f}%")
            
        cpu_cores = current_data.get('cpu_cores', psutil.cpu_count() or 4)
        load_per_core = current_data['load_avg'] / cpu_cores
        if load_per_core > 1.5:  # 1.5x per core threshold for health scoring
            excess_load = (load_per_core - 1.5) * cpu_cores
            health_score -= excess_load * 10
            alerts.append(f"High Load: {current_data['load_avg']:.1f} ({load_per_core:.2f} per core)")
            
        # X1200 health checks
        x1200_healthy = False
        if current_data['x1200_data']:
            x1200_healthy = True
            if current_data['x1200_data']['battery_percentage'] and current_data['x1200_data']['battery_percentage'] < 15:
                health_score -= 30
                alerts.append(f"Critical Battery: {current_data['x1200_data']['battery_percentage']:.1f}%")
            elif current_data['x1200_data']['battery_percentage'] and current_data['x1200_data']['battery_percentage'] < 30:
                health_score -= 15
                alerts.append(f"Low Battery: {current_data['x1200_data']['battery_percentage']:.1f}%")
                
            if not current_data['x1200_data']['has_external_power']:
                alerts.append("Running on Battery Power")
                
            power_watts = current_data['x1200_data']['power'] / 1000
            if power_watts > 18:
                health_score -= 25
                alerts.append(f"Critical Power Draw: {power_watts:.1f}W")
                
        health_score = max(0, health_score)
        
        # Determine overall status
        if health_score >= 80:
            status = "healthy"
        elif health_score >= 60:
            status = "warning"
        else:
            status = "critical"
            
        return jsonify({
            "timestamp": datetime.now().isoformat(),
            "status": status,
            "health_score": round(health_score, 1),
            "alerts": alerts,
            "metrics": {
                "cpu_percent": current_data['cpu_percent'],
                "cpu_temp": current_data['cpu_temp'],
                "memory_percent": current_data['memory_percent'],
                "load_avg": current_data['load_avg'],
                "fan_speed": current_data['fan_speed'],
                "x1200_connected": x1200_healthy,
                "battery_percentage": current_data['x1200_data']['battery_percentage'] if current_data['x1200_data'] else None,
                "power_watts": current_data['x1200_data']['power'] / 1000 if current_data['x1200_data'] else None,
                "has_external_power": current_data['x1200_data']['has_external_power'] if current_data['x1200_data'] else None,
                "is_charging": current_data['x1200_data']['is_charging'] if current_data['x1200_data'] else None
            }
        })
        
    except Exception as e:
        return jsonify({
            "timestamp": datetime.now().isoformat(),
            "status": "error",
            "health_score": 0,
            "error": str(e),
            "alerts": ["Health endpoint error"]
        }), 500

@app.route('/api/bypass-servers')
def get_bypass_servers():
    """Get bypass server configuration and status"""
    try:
        notifier = BypassNotifier()
        
        # Get current configuration
        servers = []
        for server in notifier.config.get("bypass_servers", []):
            server_info = server.copy()
            
            # Calculate success rate
            total = server_info.get("total_notifications", 0)
            success = server_info.get("success_count", 0)
            server_info["success_rate"] = (success / total * 100) if total > 0 else 0
            
            # Format last success/error times
            if server_info.get("last_success"):
                try:
                    dt = datetime.fromisoformat(server_info["last_success"].replace('Z', '+00:00'))
                    server_info["last_success_ago"] = f"{(datetime.utcnow() - dt).total_seconds():.0f}s ago"
                except:
                    pass
            
            servers.append(server_info)
        
        return jsonify({
            "unit_id": notifier.config.get("unit_id"),
            "auth_key": notifier.config.get("auth_key", "")[:16] + "...",  # Truncated for security
            "health_heartbeat_interval": notifier.config.get("health_heartbeat_interval", 60),
            "notification_timeout": notifier.config.get("notification_timeout", 5),
            "last_health_broadcast": notifier.config.get("last_health_broadcast"),
            "servers": servers,
            "wireguard_status": notifier.get_wireguard_status()
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/bypass-servers', methods=['POST'])
def update_bypass_servers():
    """Update bypass server configuration"""
    try:
        data = request.get_json()
        notifier = BypassNotifier()
        
        # Update configuration
        if 'health_heartbeat_interval' in data:
            notifier.config['health_heartbeat_interval'] = int(data['health_heartbeat_interval'])
        
        if 'notification_timeout' in data:
            notifier.config['notification_timeout'] = int(data['notification_timeout'])
        
        if 'servers' in data:
            # Validate and update servers
            updated_servers = []
            for server_data in data['servers']:
                server = {
                    "url": server_data.get("url", "").strip(),
                    "priority": int(server_data.get("priority", 1)),
                    "enabled": bool(server_data.get("enabled", True)),
                    "registration_status": server_data.get("registration_status", "pending"),
                    "last_success": server_data.get("last_success"),
                    "last_error": server_data.get("last_error"),
                    "total_notifications": int(server_data.get("total_notifications", 0)),
                    "success_count": int(server_data.get("success_count", 0))
                }
                if server["url"]:  # Only add servers with valid URLs
                    updated_servers.append(server)
            
            notifier.config['bypass_servers'] = updated_servers
        
        # Save configuration
        notifier.save_config(notifier.config)
        
        return jsonify({"status": "success", "message": "Configuration updated"})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/bypass-servers/test')
def test_bypass_servers():
    """Test connectivity to all bypass servers"""
    try:
        notifier = BypassNotifier()
        
        # Get current power data for test
        power_data = power_api.get_current_data()
        
        # Send test health heartbeat
        health_data = notifier.get_comprehensive_health_data(power_data)
        health_data["health_type"] = "test"
        
        results = notifier.notify_bypass_servers(health_data, "health")
        
        return jsonify({
            "test_timestamp": datetime.utcnow().isoformat(),
            "total_servers": results["total_servers"],
            "successful": results["successful"],
            "failed": results["failed"],
            "server_results": results["server_results"]
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/bypass-servers/force-register')
def force_register_bypass_servers():
    """Force re-registration with all bypass servers"""
    try:
        notifier = BypassNotifier()
        
        # Reset registration status
        for server in notifier.config.get("bypass_servers", []):
            server["registration_status"] = "pending"
        
        # Attempt registration
        success = notifier.auto_register_with_bypass_servers()
        
        return jsonify({
            "registration_attempted": True,
            "success": success,
            "timestamp": datetime.utcnow().isoformat()
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/battery-advanced')
def get_battery_advanced():
    """API endpoint for advanced MAX17040 battery data"""
    if not power_api.max17040:
        return jsonify({"error": "MAX17040 Advanced not available"}), 503

    try:
        status = power_api.max17040.get_detailed_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/battery-config')
def get_battery_config():
    """API endpoint for battery configuration"""
    if not power_api.max17040:
        return jsonify({"error": "MAX17040 Advanced not available"}), 503

    try:
        config = power_api.max17040.get_config()
        return jsonify(config)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/battery-alert-threshold', methods=['POST'])
def set_battery_alert_threshold():
    """API endpoint to set battery alert threshold"""
    if not power_api.max17040:
        return jsonify({"error": "MAX17040 Advanced not available"}), 503

    try:
        data = request.get_json()
        threshold = data.get('threshold', 10)

        if not 1 <= threshold <= 32:
            return jsonify({"error": "Threshold must be between 1 and 32 percent"}), 400

        power_api.max17040.set_alert_threshold(threshold)
        return jsonify({"success": True, "threshold": threshold})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/battery-calibrate', methods=['POST'])
def calibrate_battery():
    """API endpoint to calibrate battery fuel gauge"""
    if not power_api.max17040:
        return jsonify({"error": "MAX17040 Advanced not available"}), 503

    try:
        data = request.get_json() if request.get_json() else {}
        actual_soc = data.get('actual_soc')

        power_api.max17040.calibrate(actual_soc)
        return jsonify({"success": True, "calibrated": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/battery-runtime')
def get_battery_runtime():
    """API endpoint for battery runtime estimation"""
    if not power_api.max17040:
        return jsonify({"error": "MAX17040 Advanced not available"}), 503

    try:
        current_ma = request.args.get('current', 500, type=int)
        runtime_hours = power_api.max17040.get_time_to_empty(current_ma)

        return jsonify({
            "runtime_hours": runtime_hours,
            "runtime_minutes": runtime_hours * 60,
            "current_draw_ma": current_ma,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/logs')
def view_logs():
    """View recent log entries"""
    try:
        data = power_api.get_historical_data(hours=24)
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Power Monitor Logs</title>
            <style>
                body { font-family: monospace; background: #1a1a1a; color: #00ff00; padding: 20px; }
                table { width: 100%; border-collapse: collapse; }
                th, td { border: 1px solid #333; padding: 8px; text-align: left; }
                th { background: #333; }
                .alert { color: #ff4444; font-weight: bold; }
                .warning { color: #ffaa00; }
            </style>
        </head>
        <body>
            <h1>🔋 X1200 Power Monitor Logs</h1>
            <p>Last 24 hours of monitoring data</p>
            <table>
                <tr>
                    <th>Timestamp</th>
                    <th>CPU %</th>
                    <th>Temp °C</th>
                    <th>Memory %</th>
                    <th>Load</th>
                    <th>Alerts</th>
                    <th>Notes</th>
                </tr>
        """
        
        for entry in data[-100:]:  # Show last 100 entries
            alert_class = ""
            if entry.get('alerts'):
                alert_class = ' class="alert"' if 'CRITICAL' in entry['alerts'] else ' class="warning"'
            
            html += f"""
                <tr{alert_class}>
                    <td>{entry['timestamp']}</td>
                    <td>{entry['cpu_percent']:.1f}</td>
                    <td>{entry['cpu_temp']:.1f}</td>
                    <td>{entry['memory_percent']:.1f}</td>
                    <td>{entry['load_avg']:.2f}</td>
                    <td>{entry.get('alerts', '')}</td>
                    <td>{entry.get('notes', '')}</td>
                </tr>
            """
        
        html += """
            </table>
            <p><a href="/" style="color: #00aaff;">← Back to Dashboard</a></p>
        </body>
        </html>
        """
        
        return html
        
    except Exception as e:
        return f"Error loading logs: {e}", 500

@app.route('/api/alert-config', methods=['GET'])
def get_alert_config():
    """Get current alert configuration"""
    return jsonify(alert_manager.config)

@app.route('/api/alert-config/pushover', methods=['POST'])
def update_pushover_config():
    """Update Pushover configuration"""
    try:
        data = request.json
        api_token = data.get('api_token', '')
        user_key = data.get('user_key', '')
        enabled = data.get('enabled', True)

        alert_manager.update_pushover_config(api_token, user_key, enabled)

        return jsonify({
            'success': True,
            'message': 'Pushover configuration updated'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400

@app.route('/api/alert-config/thresholds', methods=['POST'])
def update_thresholds():
    """Update alert thresholds"""
    try:
        data = request.json

        for threshold_name, threshold_data in data.items():
            if threshold_name in alert_manager.config["thresholds"]:
                alert_manager.config["thresholds"][threshold_name].update(threshold_data)

        alert_manager.save_config()

        return jsonify({
            'success': True,
            'message': 'Thresholds updated'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400

@app.route('/api/alert-test', methods=['POST'])
def test_alert():
    """Send a test alert"""
    try:
        data = request.json
        title = data.get('title', 'Test Alert')
        message = data.get('message', 'This is a test notification from your power monitoring system')

        success = alert_manager.send_alert(title, message)

        return jsonify({
            'success': success,
            'message': 'Test alert sent' if success else 'Failed to send test alert'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400

@app.route('/api/alert-history')
def get_alert_history():
    """Get alert history"""
    history = alert_manager.config.get("alert_history", [])
    # Return last 50 alerts, most recent first
    return jsonify(history[-50:][::-1])

@app.route('/api/usb-power', methods=['GET'])
@login_required
def get_usb_power_status():
    """Get current USB power configuration"""
    try:
        # Check boot config for USB settings
        with open('/boot/firmware/config.txt', 'r') as f:
            config_content = f.read()

        # Check command line for avoid_warnings
        with open('/boot/firmware/cmdline.txt', 'r') as f:
            cmdline_content = f.read()

        usb_enabled = 'max_usb_current=1' in config_content
        usb_max_current = 'usb_max_current_enable=1' in config_content
        avoid_warnings = 'avoid_warnings' in cmdline_content

        return jsonify({
            'usb_power_enabled': usb_enabled and usb_max_current,
            'high_current_mode': usb_enabled,
            'warnings_disabled': avoid_warnings,
            'requires_reboot': False
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/usb-power', methods=['POST'])
@login_required
def set_usb_power():
    """Enable/disable USB power for iPhone charging"""
    try:
        data = request.get_json()
        enable_usb = data.get('enable', True)

        # Read current config
        with open('/boot/firmware/config.txt', 'r') as f:
            config_lines = f.readlines()

        # Update USB settings
        usb_settings = [
            'max_usb_current=1\n' if enable_usb else '#max_usb_current=1\n',
            'usb_max_current_enable=1\n' if enable_usb else '#usb_max_current_enable=1\n'
        ]

        # Remove existing USB lines and add new ones
        config_lines = [line for line in config_lines if not any(setting.strip().lstrip('#') in line for setting in ['max_usb_current', 'usb_max_current_enable'])]

        # Add USB settings section
        config_lines.append('\n# USB Power Settings\n')
        config_lines.extend(usb_settings)

        # Write updated config
        with open('/boot/firmware/config.txt', 'w') as f:
            f.writelines(config_lines)

        return jsonify({
            'success': True,
            'message': f'USB power {"enabled" if enable_usb else "disabled"}. Reboot required to take effect.',
            'requires_reboot': True
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/throttling', methods=['GET'])
@login_required
def get_throttling_status():
    """Get current system throttling/power level"""
    try:
        # Get current CPU governor
        try:
            with open('/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor', 'r') as f:
                governor = f.read().strip()
        except:
            governor = 'unknown'

        # Get current CPU frequencies
        try:
            with open('/sys/devices/system/cpu/cpu0/cpufreq/scaling_min_freq', 'r') as f:
                min_freq = int(f.read().strip())
            with open('/sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq', 'r') as f:
                max_freq = int(f.read().strip())
        except:
            min_freq = max_freq = 0

        # Determine power level based on governor and frequencies
        power_level = 2  # default
        if governor == 'powersave':
            power_level = 1
        elif governor == 'performance':
            power_level = 3
        elif governor == 'ondemand':
            power_level = 2

        return jsonify({
            'power_level': power_level,
            'governor': governor,
            'min_freq_khz': min_freq,
            'max_freq_khz': max_freq,
            'description': {
                1: 'Power Save - Minimum performance, maximum battery life',
                2: 'Balanced - Automatic scaling between performance and efficiency',
                3: 'Performance - Maximum performance, higher power consumption'
            }.get(power_level, 'Unknown')
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/throttling', methods=['POST'])
@login_required
def set_throttling_level():
    """Set system power/throttling level (1-3)"""
    try:
        data = request.get_json()
        level = data.get('level', 2)

        if level not in [1, 2, 3]:
            return jsonify({'error': 'Power level must be 1, 2, or 3'}), 400

        # Map power levels to CPU governors
        governor_map = {
            1: 'powersave',    # Power Level 1: Maximum battery life
            2: 'ondemand',     # Power Level 2: Balanced performance
            3: 'performance'   # Power Level 3: Maximum performance
        }

        governor = governor_map[level]

        # Set CPU governor for all cores
        result = subprocess.run([
            'sudo', 'bash', '-c',
            f'echo {governor} | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor'
        ], capture_output=True, text=True)

        if result.returncode != 0:
            return jsonify({'error': f'Failed to set governor: {result.stderr}'}), 500

        # Optional: Set frequency limits for power save mode
        if level == 1:
            # Limit max frequency for power save
            subprocess.run([
                'sudo', 'bash', '-c',
                'echo 800000 | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq'
            ], capture_output=True)

        descriptions = {
            1: 'Power Save mode activated - CPU frequency limited for maximum battery life',
            2: 'Balanced mode activated - CPU scales automatically based on load',
            3: 'Performance mode activated - CPU runs at maximum frequency'
        }

        return jsonify({
            'success': True,
            'power_level': level,
            'governor': governor,
            'message': descriptions[level],
            'requires_reboot': False
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    local_ip = get_local_ip()
    print("🚀 Starting X1200 Power Monitor Dashboard Server")
    print("📊 Dashboard: http://localhost:9434")
    print(f"📱 Phone QR Code: http://{local_ip}:9434/qr")
    print("📝 Logs: http://localhost:9434/logs")
    print("🔌 API: http://localhost:9434/api/power-data")
    print(f"🌐 Network Access: http://{local_ip}:9434")
    print()

    # Initialize and start background monitoring
    background_monitor = BackgroundMonitor()
    background_monitor.start()

    # Check if power monitor is running
    try:
        latest = power_api.get_latest_data()
        if latest:
            print(f"✅ Power monitoring active - CPU: {latest['cpu_percent']:.1f}%, Temp: {latest['cpu_temp']:.1f}°C")
        else:
            print("⚠️  No power data available - start system_power_logger.py")
    except Exception as e:
        print(f"⚠️  Warning: {e}")
    
    print("\nPress Ctrl+C to stop server")

    try:
        app.run(host='0.0.0.0', port=9434, debug=False)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down server...")
        background_monitor.stop()
        print("👋 Goodbye!")
