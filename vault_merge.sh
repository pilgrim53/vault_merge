echo "Are Saphira and phone properly mounted?"
read A
. ~/gitlab/obsidian_venv/bin/activate
~/gitlab/obsidian_venv/bin/python ~/gitlab/vault_merge/vault_merge_rsync.py
