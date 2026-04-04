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
    
    # Add import at the top of the file (after standard imports but before logic)
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
    
    # 1. Extract technical indicators
    indicators_imports = '''import pandas as pd
import numpy as np
import talib
from utils_logger import log_message'''

    success = extract_module(
        main_file, 
        "technical_indicators.py", 
        "def calculate_rsi", 
        "def prepare_ml_features", 
        indicators_imports
    )
