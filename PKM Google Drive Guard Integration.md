# PKM Google Drive mount guard

This is the Google Drive preflight component called by `pkm-sync.py`, not a standalone phone synchronization job. It uses the current user's home directory and existing rclone user service.

## Install on the laptop

Save the accompanying `pkm-gdrive-guard.sh` download, then install it as your normal laptop user. Adjust the download path if necessary:

```bash
mkdir -p ~/.local/bin
install -m 755 ~/Downloads/pkm-gdrive-guard.sh ~/.local/bin/pkm-gdrive-guard.sh
```

Do not use sudo. The guard uses your existing rclone configuration and systemd user service.

## Test independently

```bash
~/.local/bin/pkm-gdrive-guard.sh
echo "Exit status: $?"
```

Exit status zero means the expected mount is readable and a direct Google Drive listing succeeded. Any nonzero status means stop the sync and inspect the reported error. An empty Muse folder is valid; lack of files is not itself a failure.

## Integration into the final sync script

Put this mandatory gate before any phone import, Muse import, or outbound phone operation:

```bash
source "$HOME/.local/bin/pkm-gdrive-guard.sh" || exit 1
pkm_ensure_gdrive || exit 1

# Existing sync phases go below this point.
# Initial deployment: no phone pull; collect Muse, then preview/apply phone push.
# Later runs: collect phone journal, collect Muse, then preview/apply phone push.
# Each phase must explicitly abort on failure before the following phase runs.
```

Do not simply source the guard without calling `pkm_ensure_gdrive`, and do not ignore its return status.

## Recovery behavior

- A readable `gdrive:` mount of type `fuse.rclone` is left running.
- A missing or unreadable expected mount triggers one bounded attempt to reset the service's failure state and restart `rclone-gdrive.service`.
- An unexpected filesystem at the mountpoint stops the job without restarting the service.
- After recovery, the guard checks mount identity, reads `~/gdrive/Muse`, and lists `gdrive:Muse` directly to validate current API access rather than relying on cached filenames.
- Authentication errors require interactive repair; the guard does not run an unattended browser authorization flow.
- It does not change ownership, use `--allow-non-empty`, force unmount, or copy/delete any Drive or vault content.

Recovery uses the existing service definition, including its unmount behavior. A busy/stale mount or a service without working teardown may require manual diagnosis; the guard fails closed rather than forcibly dismantling it. The checks validate readiness at that moment, not continued availability, so later transfer errors must still abort the phone push.
