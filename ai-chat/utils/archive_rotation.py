import os
from datetime import datetime

ARCHIVE_DIR = "ai-chat/archive"
MAX_LINES = 1000
KEEP_LINES = 200

def rotate_file(filepath):
    if not os.path.exists(filepath):
        return False
        
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    if len(lines) > MAX_LINES:
        # Create archive directory if it doesn't exist
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        
        # Generate archive name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        basename = os.path.basename(filepath)
        name, ext = os.path.splitext(basename)
        archive_name = f"{name}_archive_{timestamp}{ext}"
        archive_path = os.path.join(ARCHIVE_DIR, archive_name)
        
        # Write to archive
        with open(archive_path, 'w', encoding='utf-8') as f:
            f.writelines(lines[:-KEEP_LINES])
            
        # Keep recent content with header
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"> Archived {datetime.now().strftime('%Y-%m-%d')}: Content prior to line {len(lines) - KEEP_LINES} moved to archive/{archive_name}\n\n")
            f.writelines(lines[-KEEP_LINES:])
        
        print(f"Archived {filepath} to {archive_path}")
        return True
    return False

if __name__ == "__main__":
    files_to_check = [
        "ai-chat/issues.md",
        "ai-chat/changelog.md",
        "ai-chat/decisions.md"
    ]
    
    for f in files_to_check:
        rotate_file(f)
