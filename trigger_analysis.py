import sys
import json
import asyncio
from dotenv import load_dotenv

load_dotenv()

from ai_auto_healer import AUTO_HEAL_ENGINE
from shared_state import SIGNAL_REGISTRY

async def main():
    print("Loading signal registry...", flush=True)
    try:
        with open("signal_registry.json", "r") as f:
            data = json.load(f)
            
        SIGNAL_REGISTRY.update(data)
        
        # Find signal to analyze
        target_sid = None
        for sid, sdata in data.items():
            if sdata.get("status") == "CLOSED":
                target_sid = sid
                break
                
        if not target_sid:
            print("No CLOSED signals found.")
            return
            
        print(f"Triggering Post-Mortem Analysis for Signal: {target_sid}", flush=True)
        # We manually change the status in our memory just for the prompt context
        SIGNAL_REGISTRY[target_sid]["status"] = "SL_HIT"
        SIGNAL_REGISTRY[target_sid]["signal"] = SIGNAL_REGISTRY[target_sid].get("signal", "UNKNOWN")
        
        await AUTO_HEAL_ENGINE.perform_post_mortem(target_sid)
        print("Analysis generated and sent to Ops Chat successfully.", flush=True)
        
    except Exception as e:
        print(f"Error: {e}", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
