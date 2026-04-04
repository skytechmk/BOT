
#!/usr/bin/env python3
"""
Monitor free model usage and rotation
"""

import time
import json
from datetime import datetime

def monitor_usage():
    """Monitor free model usage"""
    try:
        from free_model_rotator import FREE_OPENROUTER_INTEL
        
        while True:
            stats = FREE_OPENROUTER_INTEL.get_stats()
            
            print(f"📊 {{datetime.now().strftime('%H:%M:%S')}} - Model: {{stats['current_model']}}")
            print(f"   Usage: {{sum(stats['usage_count'].values())}} requests")
            print(f"   Failures: {{sum(stats['failure_count'].values())}}")
            
            time.sleep(300)  # Check every 5 minutes
            
    except KeyboardInterrupt:
        print("\n🛑 Monitoring stopped")

if __name__ == "__main__":
    monitor_usage()
