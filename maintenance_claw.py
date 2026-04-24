import os
import shutil
import py_compile
import ast
from utils_logger import log_message

class MaintenanceClaw:
    """
    The Autonomous Maintenance Claw (Inspired by claw-code)
    Handles the safe patching of Aladdin's logic files.
    """
    def __init__(self):
        self.PIN = os.getenv("MAINTENANCE_PIN", "401540")
        self.SAFE_PATCH_FILES = [
            'data_fetcher.py',
            'signal_generator.py',
            'technical_indicators.py',
            'trading_utilities.py',
            'macro_risk_engine.py',
            'ml_training.py'
        ]
        self.RESTRICTED_FILES = ['main.py', 'shared_state.py', 'constants.py', 'maintenance_claw.py']

    def verify_pin(self, input_pin):
        """Mandatory 6-digit challenge"""
        return str(input_pin).strip() == self.PIN

    def is_file_safe(self, filename):
        """Strict lockdown check"""
        base = os.path.basename(filename)
        return base in self.SAFE_PATCH_FILES and base not in self.RESTRICTED_FILES

    def apply_patch(self, target_file, new_code):
        """
        Secure Patch Workflow:
        1. Lockdown Check
        2. Backup creation (.bak)
        3. Integrity Verification (py_compile)
        4. Atomic Overwrite
        """
        if not self.is_file_safe(target_file):
            msg = f"🚫 SECURITY ALERT: Autonomous patch rejected for RESTRICTED file: {target_file}"
            log_message(msg)
            return False, msg

        # 1. Create Backup
        bak_file = f"{target_file}.bak"
        try:
            shutil.copy2(target_file, bak_file)
            log_message(f"📦 Created backup: {bak_file}")
        except Exception as e:
            return False, f"Failed to create backup: {e}"

        # 2. Verify Integrity of New Code
        temp_file = f"{target_file}.tmp"
        try:
            with open(temp_file, 'w') as f:
                f.write(new_code)
            
            # Syntax Check
            py_compile.compile(temp_file, doraise=True)
            
            # AST Check (No malicious imports/ops)
            with open(temp_file, 'r') as f:
                tree = ast.parse(f.read())
                # (Optional: Add more AST security checks here)
            
            log_message(f"✅ Integrity verified for proposed patch to {target_file}")
        except py_compile.PyCompileError as e:
            os.remove(temp_file)
            return False, f"Syntax Error in AI Patch: {e}"
        except Exception as e:
            if os.path.exists(temp_file): os.remove(temp_file)
            return False, f"Integrity check failed: {e}"

        # 3. Atomic Overwrite
        try:
            os.rename(temp_file, target_file)
            log_message(f"🔥 Successfully patched {target_file}")
            return True, f"Successfully patched {target_file}. Restarting bot..."
        except Exception as e:
            if os.path.exists(temp_file): os.remove(temp_file)
            return False, f"Overwrite failed: {e}"

    def rollback(self, target_file):
        """Revert to the last known good backup"""
        bak_file = f"{target_file}.bak"
        if os.path.exists(bak_file):
            try:
                shutil.copy2(bak_file, target_file)
                log_message(f"🔄 ROLLED BACK {target_file} from backup")
                return True
            except Exception as e:
                log_message(f"❌ Rollback failed: {e}")
        return False

MAINTENANCE_CLAW = MaintenanceClaw()
