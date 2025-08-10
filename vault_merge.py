import obsidiantools.api as otools
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta 
import os
import shutil
import argparse



def cool_vault():
    VAULT_DIR = Path("C:\\Users\\Martin\\OneDrive\\Martin PKM")

    # VAULT_DIR = Path("This PC\\Martin's S24 FE\\Internal storage\\Documents\\Martin PKM")

    vault = otools.Vault(VAULT_DIR).connect().gather()

    print(f"Connected?: {vault.is_connected}")
    print(f"Gathered?:  {vault.is_gathered}")

    vault.dirpath

    # vault.md_file_index

    # vault.isolated_notes

    # vault.nonexistent_notes

    df = vault.get_note_metadata()
    #df.info()

    #  #   Column            Non-Null Count  Dtype
    # ---  ------            --------------  -----
    #  0   rel_filepath      1072 non-null   object
    #  1   abs_filepath      1072 non-null   object
    #  2   note_exists       1443 non-null   bool
    #  3   n_backlinks       1443 non-null   int64
    #  4   n_wikilinks       1072 non-null   float64
    #  5   n_tags            1072 non-null   float64
    #  6   n_embedded_files  1072 non-null   float64
    #  7   modified_time     1072 non-null   datetime64[ns]


    df.sort_values('modified_time', ascending=False)
    # print(df.to_markdown()) 

    # Get the current time
    current_time = datetime.now()

    # Subtract 24 hours
    time_24_hours_ago = pd.to_datetime(current_time - timedelta(hours=24))

    # Filter the DataFrame to get only the files modified in the last 24 hours
    filtered_df = df.query('modified_time > @time_24_hours_ago')
    for row in filtered_df.itertuples(index=False):
        if row.note_exists:
            print(
                # row.rel_filepath,
                row.abs_filepath,
                # row.note_exists,
                # row.n_backlinks,
                # row.n_wikilinks,
                # row.n_tags,
                # row.n_embedded_files,
                row.modified_time
            )


    # df = vault.md_file_index.items()

    # The only additional data this function gets is graph_category
    # df = vault.get_all_file_metadata()
    # df.info()

    # for rel_path, meta in vault.md_file_index.items():
    #     # note_text = vault.get_text(rel_path)
    #     text_2 = vault.get_readable_text(rel_path)
    #     # if 'Trump' in text_2:   
    #     #     print(rel_path, meta, text_2)
    #     if '2025-07-1' in rel_path:
    #         print(rel_path, meta)



    # df.sort_values('n_backlinks', ascending=False)

    # vault.backlinks_index

    # df_all = vault.get_all_file_metadata()
    # df_all.info
    return 0


def gather_files(base_dir):
    """Returns a dict mapping relative file paths to (absolute path, mod time)."""
    files = {}
    for root, _, filenames in os.walk(base_dir):
        for fname in filenames:
            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, base_dir)
            mod_time = os.path.getmtime(full_path)
            files[rel_path] = (full_path, mod_time)
    return files

def ensure_dir(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)

def copy_file(source_path, dest_path):
    ensure_dir(dest_path)
    shutil.copy2(source_path, dest_path)
    # print(f"Copied: {source_path} → {dest_path}")



def merge_directories(time_float, PC_DIR, PHONE_DIR, merged_dir):
    phone_files = gather_files(PHONE_DIR)
    pc_files = gather_files(PC_DIR)
    a_count = 0
    b_count = 0
    c_count = 0
    Time_Check = str(datetime.fromtimestamp(time_float))
    print(f"Time Check: {Time_Check} ({time_float})")

    all_keys = set(phone_files.keys()).union(pc_files.keys())

    for rel_path in all_keys:
        src_file = None

        phone_info = phone_files.get(rel_path)
        pc_info = pc_files.get(rel_path)

        if "Tai Chi" in rel_path:
            c_count += 1
            print(f"Found Tai Chi file: {rel_path}")
            print(f"PC modified at ({pc_info[1]}) {datetime.fromtimestamp(pc_info[1])}") 
            print(f"Phone modified at ({phone_info[1]}  {datetime.fromtimestamp(phone_info[1])}") 
            if pc_info[1] > time_float :
                print("PC file is newer than Time Check")
            if pc_info[1] > phone_info[1]:
                print("Phone file is older than PC file")

        if phone_info and pc_info:
            # File exists in both — compare mod time
            # print(f"Comparing files: {phone_info[0]} and {pc_info[0] } for {rel_path} ")


            if pc_info[1] > time_float and pc_info[1] > phone_info[1]:
                src_file = pc_info[0]
                b_count += 1
                print(f"PC file updated since last phone copy {Time_Check}): {rel_path} "
                      f"(modified at {datetime.fromtimestamp(pc_info[1])})")
            else:
                src_file = phone_info[0]
                a_count += 1
                # print(f"Using file from Phone: {rel_path} (modified at {datetime.fromtimestamp(phone_info[1])})")
        elif phone_info:
            src_file = phone_info[0]
            a_count += 1
            print(f"New file from Phone: {rel_path} (modified at {datetime.fromtimestamp(phone_info[1])})")
        elif pc_info:
            src_file = pc_info[0]
            b_count += 1
            print(f"New file from PC: {rel_path} (modified at {datetime.fromtimestamp(pc_info[1])})")

        # Copy chosen file to merged output
        target_path = os.path.join(merged_dir, rel_path)
        copy_file(src_file, target_path)

    print(f"Files from PC: {b_count}, Files from Phone: {a_count}")

def main():

    # Ideally we'd like to work with this android path
    # Phone_Vault = Path("This PC\\Martin's S24 FE\\Internal storage\\Documents\\Martin PKM")

    PHONE_DIR = Path("C:\\Users\\Martin\\Local_Stage\\Martin PKM")
    PC_DIR = Path("C:\\Users\\Martin\\OneDrive\\Martin PKM")
    MERGE_DIR = Path("C:\\Users\\Martin\\Local_Stage\\Merged\\Martin PKM")

    Time_Check = oldest_file_time = min(os.path.getmtime(os.path.join(root, fname))
        for root, _, filenames in os.walk(PHONE_DIR)
        for fname in filenames
    )   
    print("Oldest file in Phone Vault is from:", datetime.fromtimestamp(Time_Check))
    print("Checking for PC files modified after this time...")


    merge_directories(Time_Check, PC_DIR, PHONE_DIR, MERGE_DIR)

if __name__ == "__main__":
    main()
