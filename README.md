# vault_merge
Merge Sync 2 directories such as PC and Mobile Obsidian Vaults


1) On your mobile device, zip/compress your vault directory  (I use CX File Explorer)
2) NOTE:  You need to do this in order to preserve your file modified times
3) Connect your mobile device to your PC
4) Drag and drop the vault.zip to "stage_dir"
5) Run python vault_merge.py
6) Copy merge_dir/vault_dir to PC vault area
7) Copy merge_dir/vault_dir to mobile vault area

NOTE:  If you have confidence, you can change the program to update the stage and pc vaults directly
        However you can not updte the mobile device directly from the PC
