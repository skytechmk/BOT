import os

def extract_module(source_file, target_file, start_str, end_str, imports):
    with open(source_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    start_idx = -1
    end_idx = -1
    
    for i, line in enumerate(lines):
        if line.startswith(start_str) and start_idx == -1:
            start_idx = i
        if line.startswith(end_str) and start_idx != -1 and end_idx == -1:
            end_idx = i
            break
            
    if start_idx == -1 or end_idx == -1:
        print(f"Could not find boundaries for {target_file}")
        return False
        
    # Extract the chunk
    extracted_lines = lines[start_idx:end_idx]
    
    # Create the new module
    with open(target_file, 'w', encoding='utf-8') as f:
        f.write(imports + '\n\n')
        f.writelines(extracted_lines)
        
    # Remove from source and add import
    new_lines = lines[:start_idx] + lines[end_idx:]
    
    import_stmt = f"from {target_file.replace('.py', '')} import *\n"
    
    # Find a good place to put it - after the last import
    last_import_idx = 0
    for i, line in enumerate(new_lines):
        if line.startswith('import ') or line.startswith('from '):
            last_import_idx = i
    
    new_lines.insert(last_import_idx + 1, import_stmt)
    
    with open(source_file, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
        
    print(f"Successfully extracted {target_file} ({end_idx - start_idx} lines)")
    return True

if __name__ == "__main__":
    main_file = "main.py"
    
    ml_imports = '''import pandas as pd
import numpy as np
import xgboost as xgb
import torch
import os
import time
from joblib import dump, load
from utils_logger import log_message
from technical_indicators import *'''

    success = extract_module(
        main_file, 
        "ml_training.py", 
        "def prepare_ml_features", 
        "def calculate_base_signal", 
        ml_imports
    )
