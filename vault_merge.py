from pathlib import Path
from datetime import datetime
import os
import shutil
import obsidiantools.api as otools
import pandas as pd
import shlex


def connect_and_report_vault(vault_dir: Path):
    """Connects to an Obsidian vault and prints connection status and recent notes."""
    vault = otools.Vault(vault_dir).connect().gather()
    print(f"Connected?: {vault.is_connected}")
    print(f"Gathered?:  {vault.is_gathered}")

    df = vault.get_note_metadata()
    current_time = datetime.now()
    time_24_hours_ago = pd.to_datetime(current_time - pd.Timedelta(hours=24))
    filtered_df = df.query('modified_time > @time_24_hours_ago')

    for row in filtered_df.itertuples(index=False):
        if row.note_exists:
            print(row.abs_filepath, row.modified_time)


def gather_files(base_dir):
    """Return a dict mapping relative file paths to (absolute path, mod time)."""
    files = {}
    for root, _, filenames in os.walk(base_dir):
        for fname in filenames:
            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, base_dir)
            mod_time = os.path.getmtime(full_path)
            files[rel_path] = (full_path, mod_time)
    return files


def ensure_dir(path):
    """Ensure the directory for the given path exists."""
    # accept either Path or string
    print(f"Ensuring directory for {path}")
    parent = Path(path).parent
    parent.mkdir(parents=True, exist_ok=True)


def copy_file(source_path, dest_path):
    """Copy a file to the destination, creating directories as needed."""
    # Convert paths to strings and quote them to handle spaces
    # source_path = shlex.quote(str(Path(source_path).as_posix()))
    # dest_path = shlex.quote(str(Path(dest_path).as_posix()))

    # Skip any path that contains a .obsidian directory (handles both ".obsidian" and "/.obsidian")
    src_str = str(source_path)
    if ".obsidian" in src_str or ".trash" in src_str:
        print(f"Skipping .obsidian file: {source_path}")
        return
    ensure_dir(dest_path)
    print(f"Copying {source_path} to {dest_path}")
    shutil.copy2(source_path, dest_path)


def merge_directories(pc_dir, phone_dir):
    """Merge files bi-directionally between PC and phone directories."""
    phone_files = gather_files(phone_dir)
    pc_files = gather_files(pc_dir)
    copied_from_phone = 0
    copied_to_phone = 0
    skipped = 0

    # Split into separate key sets
    pc_keys = set(pc_files.keys())
    phone_keys = set(phone_files.keys())
    
    # Files in both locations
    common_keys = pc_keys.intersection(phone_keys)
    # Files only on phone
    phone_only_keys = phone_keys - pc_keys
    # Files only on PC
    pc_only_keys = pc_keys - phone_keys

    # Handle files that exist in both locations
    for rel_path in sorted(common_keys):
        phone_path, phone_mtime = phone_files[rel_path]
        pc_path, pc_mtime = pc_files[rel_path]
        
        if phone_mtime > pc_mtime:
            # Phone has newer version -> update PC
            copy_file(phone_path, pc_path)
            copied_from_phone += 1
            print(f"Copied newer Phone file to PC: {rel_path}")
        elif pc_mtime > phone_mtime:
            # PC has newer version -> update Phone
            copy_file(pc_path, phone_path)
            copied_to_phone += 1
            print(f"Copied newer PC file to Phone: {rel_path}")
        else:
            skipped += 1

    # Handle phone-only files
    for rel_path in sorted(phone_only_keys):
        phone_path, _ = phone_files[rel_path]
        target_pc_path = os.path.join(str(pc_dir), rel_path)
        copy_file(phone_path, target_pc_path)
        copied_from_phone += 1
        print(f"Copied new file from Phone to PC: {rel_path}")

    # Handle PC-only files
    for rel_path in sorted(pc_only_keys):
        pc_path, _ = pc_files[rel_path]
        target_phone_path = os.path.join(str(phone_dir), rel_path)
        copy_file(pc_path, target_phone_path)
        copied_to_phone += 1
        print(f"Copied new file from PC to Phone: {rel_path}")

    print(f"Files copied from Phone to PC: {copied_from_phone}")
    print(f"Files copied from PC to Phone: {copied_to_phone}")
    print(f"Files skipped (same in both): {skipped}")


def main():
    PHONE_DIR = Path("/home/tinker/Android/Internal storage/Documents/Martin PKM")
    PC_DIR = Path("/mnt/saphira/PKM")

    print("Merging new/updated files from Phone directly into PC directory...")
    print("Phone Directory:", PHONE_DIR)
    print("PC Directory:", PC_DIR)

    merge_directories(PC_DIR, PHONE_DIR)


if __name__ == "__main__":
    main()