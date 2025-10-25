#!/usr/bin/env python3
"""
Get X1206 battery runtime estimate
Usage: ./get_runtime.py
"""

import sys
import os
sys.path.append('/home/pi/dev/power')

try:
    from runtime_estimator import RuntimeEstimator
    
    estimator = RuntimeEstimator()
    result = estimator.get_runtime_estimate()
    
    if result and result.get('final_estimate_hours'):
        runtime_hours = result['final_estimate_hours']
        if runtime_hours < 1:
            minutes = int(runtime_hours * 60)
            print(f"{minutes}m remaining")
        else:
            hours = int(runtime_hours)
            minutes = int((runtime_hours - hours) * 60)
            if minutes > 0:
                print(f"{hours}h{minutes}m remaining")
            else:
                print(f"{hours}h remaining")
    else:
        print("Unable to estimate runtime")
        
except Exception as e:
    print(f"Error: {e}")