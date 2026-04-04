import os

def extract_module(source_file, target_file, start_str, end_str):
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
        print(f"Could not find boundaries for {target_file}: start_idx={start_idx}, end_idx={end_idx}")
        return False
        
    # include the # comment on the line before start_idx if it exists
    if start_idx > 0 and lines[start_idx-1].startswith('#'):
        start_idx -= 2 # Take the blank line + comment
        if start_idx < 0: start_idx = i
            
    extracted_lines = lines[start_idx:end_idx]
    
    with open(target_file, 'a', encoding='utf-8') as f:
        f.writelines(extracted_lines)
        
    new_lines = lines[:start_idx] + lines[end_idx:]
    
    with open(source_file, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
        
    print(f"Successfully appended {end_idx - start_idx} lines to {target_file}")
    return True

if __name__ == "__main__":
    main_file = "main.py"
    
    success = extract_module(
        main_file, 
        "performance_tracker.py", 
        "def track_signal_performance", 
        "async def process_pair"
    )
