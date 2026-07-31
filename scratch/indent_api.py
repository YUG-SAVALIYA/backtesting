import sys
from pathlib import Path

def main():
    api_path = Path("src/rsi_supertrend_backtester/api.py")
    if not api_path.exists():
        print("api.py not found!")
        sys.exit(1)

    lines = api_path.read_text(encoding="utf-8").splitlines()
    
    # We want to indent lines between start_dt (around line 513) and yield final_data (around line 677)
    # Let's locate the start line: "        start_dt = pd.to_datetime(req.start_date)"
    # and the end line: "        yield f\"data: {json.dumps(final_data, default=str)}\\n\\n\""
    
    start_idx = None
    end_idx = None
    
    for idx, line in enumerate(lines):
        if "start_dt = pd.to_datetime(req.start_date)" in line and line.startswith("        start_dt"):
            start_idx = idx
        if 'yield f"data: {json.dumps(final_data, default=str)}\\n\\n"' in line and line.startswith("        yield"):
            end_idx = idx
            
    if start_idx is None or end_idx is None:
        print(f"Could not find markers: start_idx={start_idx}, end_idx={end_idx}")
        sys.exit(1)
        
    print(f"Indenting lines {start_idx + 1} to {end_idx + 1}")
    
    for idx in range(start_idx, end_idx + 1):
        if lines[idx].strip() == "":
            lines[idx] = ""
        else:
            lines[idx] = "    " + lines[idx]
            
    api_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Indentation fixed successfully!")

if __name__ == "__main__":
    main()
