from pathlib import Path
from datetime import datetime
import os
import shutil
import obsidiantools.api as otools
import pandas as pd


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
    os.makedirs(os.path.dirname(path), exist_ok=True)


def copy_file(source_path, dest_path):
    """Copy a file to the destination, creating directories as needed."""
    ensure_dir(dest_path)
    shutil.copy2(source_path, dest_path)


def merge_directories(time_cutoff, pc_dir, phone_dir, merged_dir):
    """Merge files from PC and Phone directories into a merged directory."""
    phone_files = gather_files(phone_dir)
    pc_files = gather_files(pc_dir)
    pc_count = 0
    phone_count = 0

    print(f"Time Check: {datetime.fromtimestamp(time_cutoff)} ({time_cutoff})")

    all_keys = set(phone_files.keys()).union(pc_files.keys())

    for rel_path in all_keys:
        src_file = None
        phone_info = phone_files.get(rel_path)
        pc_info = pc_files.get(rel_path)

        if phone_info and pc_info:
            # File exists in both — compare mod time
            if pc_info[1] > time_cutoff and pc_info[1] > phone_info[1]:
                src_file = pc_info[0]
                pc_count += 1
                print(f"PC file updated since last phone copy: {rel_path} "
                      f"(modified at {datetime.fromtimestamp(pc_info[1])})")
            else:
                src_file = phone_info[0]
                phone_count += 1
        elif phone_info:
            src_file = phone_info[0]
            phone_count += 1
            print(f"New file from Phone: {rel_path} (modified at {datetime.fromtimestamp(phone_info[1])})")
        elif pc_info:
            src_file = pc_info[0]
            pc_count += 1
            print(f"New file from PC: {rel_path} (modified at {datetime.fromtimestamp(pc_info[1])})")

        if src_file:
            target_path = os.path.join(merged_dir, rel_path)
            copy_file(src_file, target_path)

    print(f"Files from PC: {pc_count}, Files from Phone: {phone_count}")


def main():
    PHONE_DIR = Path("C:\\Users\\Martin\\Local_Stage\\Martin PKM")
    PC_DIR = Path("C:\\Users\\Martin\\OneDrive\\Martin PKM")
    MERGE_DIR = Path("C:\\Users\\Martin\\Local_Stage\\Merged\\Martin PKM")

    # Find the oldest file modification time in the phone vault
    time_cutoff = min(
        os.path.getmtime(os.path.join(root, fname))
        for root, _, filenames in os.walk(PHONE_DIR)
        for fname in filenames
    )
    print("Oldest file in Phone Vault is from:", datetime.fromtimestamp(time_cutoff))
    print("Checking for PC files modified after this time...")

    merge_directories(time_cutoff, PC_DIR, PHONE_DIR, MERGE_DIR)


if __name__ == "__main__":
    main()