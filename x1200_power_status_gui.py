#!/usr/bin/env python3

import tkinter as tk
from tkinter import ttk
import smbus
import threading
import time

class X1200PowerStatusGUI:
    """GUI application to display X1200/X1206 UPS power status"""

    def __init__(self, root):
        self.root = root
        self.root.title("X1200/X1206 Power Status")
        self.root.geometry("300x200")
        self.root.resizable(False, False)

        # Try to set window icon if possible
        try:
            self.root.iconbitmap('/usr/share/icons/hicolor/48x48/apps/battery.png')
        except:
            pass

        # UPS connection status
        self.bus = None
        self.device_addr = 0x36  # MAX17040G+ fuel gauge address
        self.model_name = "Unknown"

        # Create GUI elements
        self.create_widgets()

        # Connect to UPS
        self.connect_to_ups()

        # Start update thread
        self.update_thread = threading.Thread(target=self.update_loop, daemon=True)
        self.update_thread.start()

    def create_widgets(self):
        """Create GUI widgets"""
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Model label
        self.model_label = ttk.Label(main_frame, text="Connecting...", font=('Arial', 12, 'bold'))
        self.model_label.grid(row=0, column=0, columnspan=2, pady=5)

        # Status frame
        status_frame = ttk.LabelFrame(main_frame, text="Power Status", padding="10")
        status_frame.grid(row=1, column=0, columnspan=2, pady=10, sticky=(tk.W, tk.E))

        # Battery percentage
        ttk.Label(status_frame, text="Battery:").grid(row=0, column=0, sticky=tk.W)
        self.battery_label = ttk.Label(status_frame, text="--", font=('Arial', 14, 'bold'))
        self.battery_label.grid(row=0, column=1, padx=10)

        # Battery voltage
        ttk.Label(status_frame, text="Voltage:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.voltage_label = ttk.Label(status_frame, text="--", font=('Arial', 12))
        self.voltage_label.grid(row=1, column=1, padx=10, pady=5)

        # Power status
        ttk.Label(status_frame, text="Status:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.status_label = ttk.Label(status_frame, text="--", font=('Arial', 10))
        self.status_label.grid(row=2, column=1, padx=10, pady=5)

        # Progress bar for battery level
        self.battery_progress = ttk.Progressbar(main_frame, length=250, mode='determinate')
        self.battery_progress.grid(row=2, column=0, columnspan=2, pady=10)

        # Refresh button
        self.refresh_button = ttk.Button(main_frame, text="Refresh", command=self.manual_refresh)
        self.refresh_button.grid(row=3, column=0, pady=5)

        # Close button
        self.close_button = ttk.Button(main_frame, text="Close", command=self.root.quit)
        self.close_button.grid(row=3, column=1, pady=5)

    def connect_to_ups(self):
        """Try to connect to X1200/X1206 UPS"""
        # Try different I2C buses
        for bus_num in [1, 11, 4]:
            try:
                bus = smbus.SMBus(bus_num)
                # Test communication
                version = bus.read_word_data(self.device_addr, 0x08)  # VERSION_REG
                self.bus = bus

                # Determine model based on version or other characteristics
                # X1206 might have different version numbers
                version_swapped = ((version & 0xFF) << 8) | ((version & 0xFF00) >> 8)
                if version_swapped == 0x0036:
                    self.model_name = "X1206 UPS"
                else:
                    self.model_name = "X1200 UPS"

                self.model_label.config(text=f"Connected: {self.model_name}")
                return True
            except:
                if bus:
                    try:
                        bus.close()
                    except:
                        pass

        self.model_label.config(text="No UPS Detected")
        return False

    def read_battery_data(self):
        """Read battery data from UPS"""
        if not self.bus:
            return None

        try:
            # Read voltage (VCELL register at 0x02)
            vcell_raw = self.bus.read_word_data(self.device_addr, 0x02)
            vcell_swapped = ((vcell_raw & 0xFF) << 8) | ((vcell_raw & 0xFF00) >> 8)
            voltage = (vcell_swapped >> 4) * 1.25 / 1000.0

            # Read state of charge (SOC register at 0x04)
            soc_raw = self.bus.read_word_data(self.device_addr, 0x04)
            soc_swapped = ((soc_raw & 0xFF) << 8) | ((soc_raw & 0xFF00) >> 8)
            percentage = soc_swapped / 256.0

            return {
                'voltage': voltage,
                'percentage': percentage
            }
        except Exception as e:
            return None

    def update_display(self):
        """Update the GUI display with current data"""
        data = self.read_battery_data()

        if data:
            # Update battery percentage
            pct = data['percentage']
            if pct > 100:
                # X1200 V1.2 can report >100% when charging
                self.battery_label.config(text=f"{pct:.1f}% (Charging)")
                self.battery_progress['value'] = 100
            elif pct < 0.1:
                # No battery installed
                self.battery_label.config(text="No Battery")
                self.battery_progress['value'] = 0
                self.status_label.config(text="External Power Only")
            else:
                self.battery_label.config(text=f"{pct:.1f}%")
                self.battery_progress['value'] = min(100, pct)

            # Update voltage
            self.voltage_label.config(text=f"{data['voltage']:.2f}V")

            # Update status based on values
            if pct < 0.1:
                status = "No Battery Installed"
                color = "gray"
            elif pct > 100:
                status = "Charging"
                color = "blue"
            elif pct < 20:
                status = "Critical - Low Battery"
                color = "red"
            elif pct < 50:
                status = "Battery Power"
                color = "orange"
            else:
                status = "Good"
                color = "green"

            self.status_label.config(text=status)

            # Color the battery label based on status
            if color == "red":
                self.battery_label.config(foreground="red")
            elif color == "orange":
                self.battery_label.config(foreground="orange")
            elif color == "green":
                self.battery_label.config(foreground="green")
            elif color == "blue":
                self.battery_label.config(foreground="blue")
            else:
                self.battery_label.config(foreground="gray")
        else:
            # No data available
            if not self.bus:
                self.battery_label.config(text="Disconnected", foreground="red")
                self.voltage_label.config(text="--")
                self.status_label.config(text="UPS Not Connected")
                self.battery_progress['value'] = 0
            else:
                self.battery_label.config(text="Read Error", foreground="red")

    def update_loop(self):
        """Background thread to update display"""
        while True:
            try:
                self.root.after(0, self.update_display)
                time.sleep(2)  # Update every 2 seconds
            except:
                break

    def manual_refresh(self):
        """Manual refresh button handler"""
        # Try to reconnect if disconnected
        if not self.bus:
            self.connect_to_ups()
        self.update_display()

def main():
    """Main entry point"""
    root = tk.Tk()
    app = X1200PowerStatusGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()