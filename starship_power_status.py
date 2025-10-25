#!/usr/bin/env python3
"""
Simple X1206 power status for Starship prompt
Returns: power_symbol battery_percentage
"""

import sys
import os
import io
sys.path.append('/home/pi/dev/power')

try:
    from x1200_common import X1200Monitor
    
    def get_power_status():
        try:
            # Suppress diagnostic output for prompt use
            old_stdout = sys.stdout
            sys.stdout = io.StringIO()
            
            monitor = X1200Monitor()
            
            # Restore stdout
            sys.stdout = old_stdout
            
            if not monitor.connected:
                return "❓ Unknown"
            
            # Get power source
            has_external = monitor.has_external_power()
            is_charging = monitor.is_charging()
            battery_pct = monitor.get_battery_percentage()
            
            # Determine power symbol
            if has_external:
                if is_charging:
                    power_symbol = "⚡"  # Charging
                else:
                    power_symbol = "🔌"  # AC powered, not charging (full)
            else:
                power_symbol = "🔋"  # On battery
            
            # Format battery percentage
            if battery_pct is not None:
                return f"{power_symbol} {battery_pct:.0f}%"
            else:
                return f"{power_symbol} ?%"
                
        except Exception as e:
            return f"❓ {str(e)[:10]}"
            
    if __name__ == "__main__":
        print(get_power_status())
        
except ImportError:
    # Fallback if X1200 module not available
    print("🔋 Unknown")