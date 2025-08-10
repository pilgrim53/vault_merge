# vault_merge
Merge Sync 2 directories such as PC and Mobile Obsidian Vaults

git clone https://github.com/pilgrim53/vault_merge.git

create your venv using requirements.txt

Go to MAIN and update:
    # PHONE_DIR = Path("Where is your phone vault")
    # PC_DIR = Path("Where is your PC vault")
    # MERGE_DIR = Path("Where to put the merged vault")


1) On your mobile device, zip/compress your vault directory  (I use CX File Explorer)
   NOTE:  You NEED to do this in order to preserve your file modified times
2) Connect your mobile device to your PC
3) Drag and drop the vault.zip to "stage_dir"
4) Run python vault_merge.py
5) Copy merge_dir/vault_dir to PC vault area
6) Copy merge_dir/vault_dir to mobile vault area

NOTE:  If you have confidence, you can change the program to update the stage and pc vaults directly
        However you can not update the mobile device directly from the PC (hence the need for this program in the first place)
