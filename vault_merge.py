from pathlib import Path
from datetime import datetime
import os
import shutil
import hashlib
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
    """Return a dict mapping relative file paths to (absolute path, mod time, size)."""
    files = {}
    for root, _, filenames in os.walk(base_dir):
        for fname in filenames:
            full_path = os.path.join(root, fname)
            # Skip .obsidian and .trash paths entirely
            if ".obsidian" in full_path or ".trash" in full_path:
                continue
            rel_path = os.path.relpath(full_path, base_dir)
            try:
                stat = os.stat(full_path)
            except OSError:
                continue
            mod_time = stat.st_mtime
            size = stat.st_size
            files[rel_path] = (full_path, mod_time, size)
    return files


def get_file_hash(path):
    """Compute SHA1 hash for a file."""
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def detect_moved_files(pc_files, phone_files, pc_dir, phone_dir):
    """Detect renamed/moved duplicates (same content, different rel_path) and prompt user."""
    print("Checking for moved/renamed matches across PC and Phone...")

    # pre-filter by size to reduce hash work
    pc_by_size = {}
    phone_by_size = {}
    for rel, (_path, _mtime, size) in pc_files.items():
        pc_by_size.setdefault(size, []).append(rel)
    for rel, (_path, _mtime, size) in phone_files.items():
        phone_by_size.setdefault(size, []).append(rel)

    # only compute hashes for sizes that exist in both vaults
    candidate_sizes = set(pc_by_size).intersection(phone_by_size)
    pc_hash_map = {}
    phone_hash_map = {}

    for size in candidate_sizes:
        for rel in pc_by_size[size]:
            abs_path, mtime, _ = pc_files[rel]
            try:
                h = get_file_hash(abs_path)
            except OSError:
                continue
            pc_hash_map.setdefault(h, []).append((rel, abs_path, mtime, size))

        for rel in phone_by_size[size]:
            abs_path, mtime, _ = phone_files[rel]
            try:
                h = get_file_hash(abs_path)
            except OSError:
                continue
            phone_hash_map.setdefault(h, []).append((rel, abs_path, mtime, size))

    handled_hashes = set()
    for h in set(pc_hash_map).intersection(phone_hash_map):
        # for same content in both vaults, check if path changed
        pc_entries = pc_hash_map[h]
        phone_entries = phone_hash_map[h]

        for pc_entry in pc_entries:
            for phone_entry in phone_entries:
                pc_rel, pc_abs, pc_mtime, pc_size = pc_entry
                phone_rel, phone_abs, phone_mtime, phone_size = phone_entry

                if pc_rel == phone_rel:
                    continue

                if h in handled_hashes:
                    continue

                handled_hashes.add(h)
                print("\nMoved/renamed candidate found:")
                print(f"  PC : {pc_rel}")
                print(f"    size: {pc_size} bytes")
                print(f"    mtime: {datetime.fromtimestamp(pc_mtime)}")
                print(f"  Phone: {phone_rel}")
                print(f"    size: {phone_size} bytes")
                print(f"    mtime: {datetime.fromtimestamp(phone_mtime)}")

                print('Choose which side to keep for this moved/renamed duplicate:')
                print('  1) PC version')
                print('  2) Phone version')
                print('  3) Keep both (default)')

                while True:
                    decision = input('Enter 1, 2, or 3 [3]: ').strip() or '3'
                    if decision not in ('1', '2', '3'):
                        print('Please enter 1, 2, or 3.')
                        continue
                    break

                if decision == '1':
                    print('Keeping PC version and dropping Phone path from merge set.')
                    # Delete the phone version file
                    try:
                        os.remove(phone_abs)
                        print(f'Deleted: {phone_abs}')
                    except OSError as e:
                        print(f'Error deleting {phone_abs}: {e}')
                    # Delete the discarded path on PC if it exists
                    discarded_on_pc = os.path.join(str(pc_dir), phone_rel)
                    if os.path.exists(discarded_on_pc):
                        try:
                            os.remove(discarded_on_pc)
                            print(f'Deleted discarded path on PC: {discarded_on_pc}')
                        except OSError as e:
                            print(f'Error deleting {discarded_on_pc}: {e}')
                    # Add comment to kept file
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    comment = f"  {pc_rel}  kept after de-duplication at {timestamp}\n"
                    try:
                        with open(pc_abs, 'a') as f:
                            f.write(comment)
                        print(f'Added de-duplication comment to: {pc_abs}')
                    except OSError as e:
                        print(f'Error adding comment to {pc_abs}: {e}')
                    phone_files.pop(phone_rel, None)
                    # Keep pc_rel in pc_files so it gets copied to phone if needed
                elif decision == '2':
                    print('Keeping Phone version and dropping PC path from merge set.')
                    # Delete the PC version file
                    try:
                        os.remove(pc_abs)
                        print(f'Deleted: {pc_abs}')
                    except OSError as e:
                        print(f'Error deleting {pc_abs}: {e}')
                    # Delete the discarded path on phone if it exists
                    discarded_on_phone = os.path.join(str(phone_dir), pc_rel)
                    if os.path.exists(discarded_on_phone):
                        try:
                            os.remove(discarded_on_phone)
                            print(f'Deleted discarded path on phone: {discarded_on_phone}')
                        except OSError as e:
                            print(f'Error deleting {discarded_on_phone}: {e}')
                    # Add comment to kept file
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    comment = f"  {phone_rel}  kept after de-duplication at {timestamp}\n"
                    try:
                        with open(phone_abs, 'a') as f:
                            f.write(comment)
                        print(f'Added de-duplication comment to: {phone_abs}')
                    except OSError as e:
                        print(f'Error adding comment to {phone_abs}: {e}')
                    pc_files.pop(pc_rel, None)
                    # Keep phone_rel in phone_files so it gets copied to PC if needed
                else:
                    print('Keeping both files. Merge will treat them as independent files.')
                    # Add comments to both files to differentiate them
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    pc_comment = f"  {pc_rel}  kept after de-duplication at {timestamp}\n"
                    phone_comment = f"  {phone_rel}  kept after de-duplication at {timestamp}\n"
                    try:
                        with open(pc_abs, 'a') as f:
                            f.write(pc_comment)
                        print(f'Added de-duplication comment to PC file: {pc_abs}')
                    except OSError as e:
                        print(f'Error adding comment to {pc_abs}: {e}')
                    try:
                        with open(phone_abs, 'a') as f:
                            f.write(phone_comment)
                        print(f'Added de-duplication comment to Phone file: {phone_abs}')
                    except OSError as e:
                        print(f'Error adding comment to {phone_abs}: {e}')

    return pc_files, phone_files


def ensure_dir(path):
    """Ensure the directory for the given path exists."""
    # accept either Path or string
    print(f"Ensuring directory for {path}")
    parent = Path(path).parent
    parent.mkdir(parents=True, exist_ok=True)


def copy_file(source_path, dest_path):
    """Copy a file to the destination, creating directories as needed."""
    # Use pathlib.Path so spaces are handled naturally (no shell quoting needed)
    source_path = Path(source_path)
    dest_path = Path(dest_path)

    # Skip any path that contains a .obsidian directory (handles both ".obsidian" and "/.obsidian")
    src_str = str(source_path)
    if ".obsidian" in src_str or ".trash" in src_str:
        print(f"Skipping .obsidian file: {source_path}")
        return False
    ensure_dir(dest_path)
    print(f"Copying {source_path} to {dest_path}")
    shutil.copy2(source_path, dest_path)
    return True


def merge_directories(pc_dir, phone_dir):
    """Merge files bi-directionally between PC and phone directories."""
    phone_files = gather_files(phone_dir)
    pc_files = gather_files(pc_dir)

    # Detect moved/renamed files before path-based merge
    pc_files, phone_files = detect_moved_files(pc_files, phone_files, pc_dir, phone_dir)

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
        phone_path, phone_mtime, _ = phone_files[rel_path]
        pc_path, pc_mtime, _ = pc_files[rel_path]
        
        if phone_mtime > pc_mtime and os.path.exists(phone_path):
            # Phone has newer version -> update PC
            copy_file(phone_path, pc_path)
            copied_from_phone += 1
            print(f"Copied newer Phone file to PC: {rel_path}")
        elif pc_mtime > phone_mtime and os.path.exists(pc_path):
            # PC has newer version -> update Phone
            copy_file(pc_path, phone_path)
            copied_to_phone += 1
            print(f"Copied newer PC file to Phone: {rel_path}")
        else:
            skipped += 1

    # Handle phone-only files
    for rel_path in sorted(phone_only_keys):
        phone_path, _, _ = phone_files[rel_path]
        target_pc_path = os.path.join(str(pc_dir), rel_path)
        if os.path.exists(phone_path) and copy_file(phone_path, target_pc_path):
            copied_from_phone += 1
            print(f"Copied new file from Phone to PC: {rel_path}")
        else:
            print(f"Skipped Phone-only file: {rel_path}")

    # Handle PC-only files
    for rel_path in sorted(pc_only_keys):
        pc_path, _, _ = pc_files[rel_path]
        target_phone_path = os.path.join(str(phone_dir), rel_path)
        if os.path.exists(pc_path) and copy_file(pc_path, target_phone_path):
            copied_to_phone += 1
            print(f"Copied new file from PC to Phone: {rel_path}")
        else:
            print(f"Skipped PC-only file: {rel_path}")

    print(f"Files copied from Phone to PC: {copied_from_phone}")
    print(f"Files copied from PC to Phone: {copied_to_phone}")
    print(f"Files skipped (same in both): {skipped}")


def main():
    PHONE_DIR = Path("/mnt/android/Internal storage/Documents/Martin PKM")
    PC_DIR = Path("/mnt/saphira/home/PKM")

    print("Merging new/updated files from Phone directly into PC directory...")
    print("Phone Directory:", PHONE_DIR)
    print("PC Directory:", PC_DIR)

    merge_directories(PC_DIR, PHONE_DIR)


if __name__ == "__main__":
    main()
