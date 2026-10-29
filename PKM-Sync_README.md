# PKM Sync

A preview-first, laptop-master synchronization tool for an Obsidian vault, an Android journal, and a Google Drive intake folder. Collect external updates into the laptop vault, then return the aggregated content to the phone.

This is a controlled **collect-then-push workflow**, not unrestricted bidirectional sync. Version 2.3.2 asks for approval once, then continues sequentially through all batches and final verification. An optional XFCE/Zenity desktop watcher offers a reviewed sync when the phone is mounted.

For everyday commands and recovery decisions, start with the [PKM Sync Command Cheat Sheet](PKM-sync-command-cheat-sheet.md). Normal use is `pkm-sync --mirror` to preview and `pkm-sync --mirror --apply` to review and apply; `--resume` and `--reconcile` are only for unfinished runs.

## Workflow

```text
Android: External/Journal ────────┐
                                 ▼
                          ~/PKM (master)
                                 ▲
Google Drive: Muse ───────────────┘
                                 │
                                 ▼
                        Android vault content
```

- **Initial deployment:** Skip phone imports because all wanted phone content must already be in the master. Collect Muse updates, then return the master to the phone.
- **Regular runs:** Collect phone journal updates, collect Muse updates, then return the aggregated master to the phone.
- **Incoming collection:** External sources own their intake folders. Source contents replace differing same-path copies without timestamp arbitration; destination-only master files are retained.
- **Outbound mirror:** Optionally remove obsolete included phone files with `--mirror`, after preview and explicit confirmation.

Keep the phone inactive and close laptop vault editors, agents, and background writers throughout an apply operation. Keep both sides inactive after an interruption until recovery is complete.

## Safety boundaries

- **Preview by default:** No vault or phone content is changed without `--apply`. Preview may recover the Drive mount and create the local state/lock directory.
- **Explicit approval:** Apply requires either an interactive terminal confirmation or a checked Zenity plan-review dialog with `--gui`. It does not prompt again at each batch.
- **Verified transfers:** Compare SHA-256 content hashes, including final read-back verification of included phone files.
- **Pre-change backups:** Save replaced or deleted file contents locally before mutation.
- **Persistent recovery:** Save an immutable plan and durable cursor; retry an interrupted operation without overwriting its original backup.
- **Sequential I/O:** No worker pool or parallel file transfers. Default progress batches contain 500 phone operations and continue automatically.
- **Protected settings:** Do not copy or delete the excluded top-level phone application/configuration directories.

Phone writes are deliberately non-atomic to avoid phone-side temporary-file renames. A failure can leave a partial file; recovery uses the saved cursor. The entire run is not an atomic transaction, and there is no automatic whole-vault rollback.

## Repository contents

```text
.
├── README.md
├── .gitignore
├── pkm-sync.py
├── pkm-gdrive-guard.sh
├── pkm-watch.py
├── install-desktop.sh
├── test-pkm-sync.py
├── PKM-sync-guide.md
└── PKM-gdrive-guard-integration.md
```

The two longer guides provide detailed behavior and recovery notes. No Python third-party packages are required.

## Requirements and default paths

This implementation targets Linux with Python 3.9 or later, Bash, systemd user services, rclone, and a jmtpfs-mounted Android filesystem. The guard also uses `findmnt` and standard utilities including `timeout`.

| Role | Default |
|---|---|
| Master vault | `~/PKM` |
| Required master directories | `.obsidian`, `External/Journal`, `External/Google_Drive` |
| Android mountpoint | `/mnt/android` |
| Accepted mount types | `fuse.jmtpfs`, `fuse.mtpfs` |
| Phone vault discovery | Exactly one direct child of `/mnt/android/Internal storage/Documents` containing `.obsidian` |
| Drive remote | `gdrive:` |
| Drive mount | `~/gdrive` |
| Drive intake source | `gdrive:Muse`, mounted at `~/gdrive/Muse` |
| Drive intake destination | `~/PKM/External/Google_Drive` |
| Phone journal destination | `External/Journal` on both devices |
| Runtime state and backups | `~/.local/state/pkm-sync` |

`~` refers to the current user's home directory. Run as your normal desktop user, not with sudo. The master vault, mountpoint, remote name, and Muse layout are currently implementation defaults, not a general configuration framework.

## Installation

Clone your repository into a source directory separate from the vault, then run these commands from its root:

```bash
python3 test-pkm-sync.py

mkdir -p "$HOME/.local/bin"
install -m 755 pkm-sync.py "$HOME/.local/bin/pkm-sync"
install -m 755 pkm-gdrive-guard.sh "$HOME/.local/bin/pkm-gdrive-guard.sh"

"$HOME/.local/bin/pkm-sync" --version
```

Use the full executable path shown here unless `~/.local/bin` is on your `PATH`.

`install` deploys independent copies. A Git commit or pull does not update them; rerun the two install commands after reviewing and testing a new source version. Do not redeploy during an active run.

### Prepare the master and phone

Open `~/PKM` as an Obsidian vault so it has its own `.obsidian` directory. Create the intake folders if needed:

```bash
mkdir -p "$HOME/PKM/External/Journal" "$HOME/PKM/External/Google_Drive"
```

Prepare `/mnt/android` as a mountpoint accessible to your normal user, then mount the phone if it is not already mounted:

```bash
jmtpfs /mnt/android
findmnt --mountpoint /mnt/android
```

The phone should already have an Obsidian vault. If automatic discovery finds zero or multiple vaults, specify the intended location privately:

```bash
export PKM_PHONE_VAULT="/mnt/android/Internal storage/Documents/Your Vault"
```

Alternatively, supply `--phone-vault "/mnt/android/Internal storage/Documents/Your Vault"` on both the preview and apply commands for a new run. The selected directory must be below the Android mountpoint. No phone-folder rename is required.

### Configure Google Drive

Configure an authorized rclone remote named `gdrive` and ensure its `Muse` folder exists. Test direct API access before attempting the mount:

```bash
rclone lsd gdrive:
rclone lsf gdrive:Muse --max-depth 1
mkdir -p "$HOME/gdrive"
```

The guard expects a systemd user service named `rclone-gdrive.service`. If you already have a working service, keep it. Otherwise, the following is a starting configuration for `~/.config/systemd/user/rclone-gdrive.service`:

```ini
[Unit]
Description=Mount Google Drive with rclone

[Service]
Type=notify
ExecStart=/usr/bin/rclone mount gdrive: %h/gdrive --vfs-cache-mode full --dir-cache-time 72h --poll-interval 15s
ExecStop=/usr/bin/fusermount3 -u %h/gdrive
Restart=on-failure
RestartSec=10
TimeoutStopSec=60

[Install]
WantedBy=default.target
```

Verify the executable paths with `command -v rclone` and `command -v fusermount3`; adjust the unit if they differ. Then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now rclone-gdrive.service
"$HOME/.local/bin/pkm-gdrive-guard.sh"
```

The guard leaves a healthy mount running. Otherwise it attempts bounded service recovery, rejects unexpected mounted filesystems, and validates live `gdrive:Muse` access rather than trusting cached filenames. It does not force-unmount or perform unattended OAuth authorization.

## Usage

### First deployment

Back up the phone vault independently first. Ensure everything you want to retain from it is already in the laptop master: **`--initial` deliberately skips phone imports**.

```bash
# Preview, including proposed phone deletions.
"$HOME/.local/bin/pkm-sync" --initial --mirror

# Recompute the plan, approve once, and run to completion.
"$HOME/.local/bin/pkm-sync" --initial --mirror --apply
```

Review the deletion list before typing `MIRROR PHONE`. After `SUCCESS`, configure Android Obsidian's journal/daily-note tools to create entries in `External/Journal`.

If you omit `--mirror`, destination-only included phone files are retained. Once initial deployment succeeds, do not use `--initial` again.

### Regular runs

```bash
# Preview collections and the outbound mirror.
"$HOME/.local/bin/pkm-sync" --mirror

# Apply after reviewing the plan.
"$HOME/.local/bin/pkm-sync" --mirror --apply
```

The apply invocation recomputes its plan rather than applying a previously printed preview. Keep both sides quiescent and review the plan shown by that invocation too.

### Resume after an interruption

```bash
# Inspect the saved run/cursor without applying.
"$HOME/.local/bin/pkm-sync" --resume

# Approve once and finish all remaining work.
"$HOME/.local/bin/pkm-sync" --resume --apply
```

Do not combine `--resume` with `--initial`, `--mirror`, or `--phone-vault`: the saved plan already contains those choices. An active cursor blocks starting a different new run.

`CHECKPOINT` is progress, not completion. `PAUSED` is only expected with optional manual mode. Wait for **`SUCCESS`** before resuming editing or unmounting the phone.

Resume displays are labeled `RESUME INITIAL` or `RESUME REGULAR`. File counts are the saved snapshot, not a fresh scan. The operation list and `Remaining` summary show only work at or after the cursor. A verification-only cursor therefore shows zero remaining imports/writes/deletions and the outstanding verification-read count.

### Recover external edits or renamed notes during an unfinished run

If frozen hashes or paths no longer match legitimate edits/renames, do not delete files or state to satisfy the old plan. Version 2.3.2 provides an explicit replacement plan when the old run is in `verify` with `inflight: false`, or in `pushes` without an interrupted Journal write:

```bash
# Preview current content without modifying either vault or the active cursor.
"$HOME/.local/bin/pkm-sync" --reconcile

# Recompute, review, and approve the replacement plan once.
"$HOME/.local/bin/pkm-sync" --reconcile --apply
```

The phone is authoritative for `External/Journal`; Drive is authoritative for `External/Google_Drive`. Reconciliation imports their current contents before planning the outbound return. It does not arbitrate by timestamp or stop because both copies of a journal entry changed. Existing master copies replaced by imports are backed up.

After approval, the tool snapshots phone journal files under the new backup's `reconciliation/phone/External/Journal/` tree and archives the old cursor as `superseded-active-run.json` before replacing it atomically. Original plans, operation logs, and backup folders are retained. It does not mark the old run successful; initialization/success is committed only after the replacement run finishes verification. If interrupted after the new cursor is saved, use `--resume --apply`, not another initial deployment.

`--reconcile` requires completed imports: either verification with no in-flight operation, or the phone-write phase. An in-flight non-journal write may be replaced by a fresh plan; a partial phone destination is treated as current phone content and backed up before any new overwrite/deletion, while the original run's backups remain untouched. An interrupted Journal write is rejected because the authoritative phone source could itself be partial and needs recovery first.

Reconciliation retains the saved vault paths and mirror setting; do not combine it with `--resume`, `--initial`, `--mirror`, or `--phone-vault`. The mount watcher still offers ordinary resume, not automatic reconciliation. Keep both vaults inactive and review the fresh plan before applying.

### Android-compatible names

Planning rejects case-only filename and directory collisions conservatively, including collisions introduced by imported external files. This prevents a Linux master from sending distinct paths such as `Trinity Journal 1.md` and `trinity journal 1.md` to a destination that may treat them as the same name. The check does not establish compatibility with every phone naming rule or validate the physical phone's case sensitivity.

Preserve both contents and rename one note distinctly in Obsidian so links can be updated. If a frozen old plan still contains those names, do not resume it unchanged. Use the explicit reconciliation path after resolving master names, provided its phase is eligible. Apply also rejects case collisions in old saved plans. No automatic merge, deduplication, or filename renaming is performed.

### Abandoned failed creates with a retained case alias

If you deliberately discard the unwanted master note after an interrupted outbound create, the phone may still enumerate an unreadable old name. Reconciliation can record a narrow exception instead of requiring that entry to be read or deleted. This requires a saved in-flight `create` (no original destination), removal of its exact master path, and a wanted master note in the same directory whose filename differs only by case. No `External` path qualifies.

The preview explicitly shows `PHONE ALIAS EXCEPTION`. Only the abandoned exact filename is excluded from phone scanning and deletion; the wanted differently-cased note must still be readable and pass normal content verification. If the phone lists only the old name, the tool explicitly reads the retained canonical path before proceeding. It never deletes through the unwanted alias, which could otherwise remove the retained note on a case-insensitive destination. Unknown unreadable files and unreadable retained notes still stop the run.

This is a disclosed strict-mirror exception, not a claim that a phone metadata problem has been repaired or that the unwanted exact entry is absent. Approved exceptions are stored in `state.json` under `abandoned_phone_aliases` with the originating run and retained path, and are also present in the saved plan. They carry forward to regular syncs while the exact unwanted source remains absent and the case-alias counterpart remains wanted. Successful desired-content verification is followed by a mirror-exception notice. Reintroducing both source names triggers the normal collision guard.

### Optional controls

```bash
# Change the automatic progress-batch interval, not concurrency.
"$HOME/.local/bin/pkm-sync" --mirror --apply --batch-size 100

# Troubleshooting only: deliberately stop after one batch.
"$HOME/.local/bin/pkm-sync" --mirror --apply --batch-size 100 --pause-after-batch

# Inspect Python/jmtpfs file-descriptor counts and limits.
"$HOME/.local/bin/pkm-sync" --diagnose
```

Batches include phone writes, deletions, obsolete-directory checks, and verification reads. They do not cap initial enumeration/hashing or local imports.

## Optional XFCE desktop watcher

The watcher detects an already mounted phone; it does not mount USB devices itself. It polls `/mnt/android` every five seconds and requires two stable samples before preparing a sync.

Prerequisites: a graphical XFCE session, Zenity, the configured Drive service, and an initial deployment already completed manually. `notify-send` is optional for desktop status notifications; detailed logs are saved either way.

With the repository files together, run from a desktop terminal:

```bash
bash install-desktop.sh
```

The installer runs the tests, updates the local executables, generates a systemd user service and desktop-login autostart entry, imports the current graphical environment, and starts the watcher. It refuses a normal reinstall while the watcher is active and checks for an active sync/review lock. Install only while idle. If the phone is already mounted, a plan-review dialog may appear after installation.

For installation without starting the watcher:

```bash
bash install-desktop.sh --no-start
# Later, from a desktop terminal:
systemctl --user daemon-reload
"$HOME/.local/bin/pkm-watch-session"
```

The flow is:

1. Detect the expected MTP mount and wait for accessible contents.
2. If another sync holds the lock, wait rather than starting a competing job.
3. Prepare a regular mirror plan, or load an existing unfinished run for resumption.
4. Display the actual plan in one scrollable Zenity window.
5. Check the approval box and select **Sync**, or select **Cancel**.
6. Run all batches and final verification after that single approval.
7. Report completion, cancellation, or failure; never report success with an active cursor remaining.

Keep both devices inactive during review and apply. The watcher deliberately does not automate the first deployment. Cancellation or a handled failure does not produce a new prompt every poll. The handled boot/mount identity is stored locally; remounting offers another opportunity.

To retry on the same mount without waiting for another watcher offer:

```bash
# Fresh regular plan:
"$HOME/.local/bin/pkm-sync" --mirror --apply --gui
# Or continue an unfinished run:
"$HOME/.local/bin/pkm-sync" --resume --apply --gui
```

Do not add both commands to an automatic chain. Use the resume command if an unfinished cursor exists.

Check status and logs:

```bash
systemctl --user status pkm-watch.service --no-pager
journalctl --user -u pkm-watch.service -n 40 --no-pager
"$HOME/.local/bin/pkm-watch" --check
```

Per-offer logs are private files under `~/.local/state/pkm-sync/desktop-*.log`. Graphical environment variables are imported at desktop login; the watcher is not enabled as a headless boot service. Generated files live at:

```text
~/.local/bin/pkm-watch
~/.local/bin/pkm-watch-session
~/.config/systemd/user/pkm-watch.service
~/.config/autostart/pkm-watch.desktop
~/.local/state/pkm-sync/watch-state.json
```

For multiple phone vaults, pass `PKM_PHONE_VAULT` into the session launcher from a private desktop environment. Keep any personal environment configuration outside the public repository.

To disable, only while no sync or review is active:

```bash
systemctl --user stop pkm-watch.service
mv "$HOME/.config/autostart/pkm-watch.desktop" \
   "$HOME/.config/autostart/pkm-watch.desktop.disabled"
```

Stopping the service during an active run can interrupt its child sync. Use the cursor to recover rather than editing a partially updated phone.

## Update and move semantics

- **Source ownership:** The phone owns `External/Journal`; Drive owns `External/Google_Drive`. A differing same-path source file wins even if the master was edited or has a newer timestamp.
- **Checksums:** Detect identical content and verify copies. They do not choose which side owns a version.
- **Destination-only files:** Never delete them during incoming collection.
- **Previously handled versions:** Source path/content-hash receipts suppress reimport only when the corresponding external master path is absent, preserving intentional moves/deletions. They never prevent the source overwriting an existing same-path master copy.

Move imported notes outside the intake folders when you want to maintain a local version independently. A new source content version can be imported again even after an earlier version was moved.

## Exclusions and backups

These top-level directories are neither copied to nor deleted from the phone:

```text
.obsidian  .agents  .claude  .copilot
.opencode  .smart-env  .git  .trash
```

The phone retains its own Obsidian configuration. Ordinary content folders, including non-hidden `copilot`, are included.

Runtime files live outside the source repository and vault:

```text
~/.local/state/pkm-sync/
├── state.json
├── active-run.json             # Exists while a run is unfinished.
├── lock
└── backups/<run-id>/
    ├── plan.json
    ├── operations.jsonl
    ├── master/<relative-path>
    └── phone/<relative-path>
```

These are pre-change file backups, not a complete device image or offsite backup. There is no automatic retention cleanup, so monitor free space. Keep the state and original backups after an error; deleting receipts can cause previously moved material to reappear.

## Troubleshooting and tests

- **Source changes during a run:** Stop and inspect them; the immutable plan is not silently regenerated.
- **Descriptor exhaustion:** Run `--diagnose`. If jmtpfs is exhausted, normally unmount/remount the phone before resuming. Do not assume raising the Python limit fixes a separate daemon.
- **Busy mount:** Close shells and applications using it. Avoid routine forced/lazy unmounts or daemon termination.
- **Symlinks or file/directory collisions:** Resolve manually; included symlinks and conflicting entry types are rejected.
- **Slow MTP:** Full hashing and read-back verification can take time. Batch size does not add threads.
- **Interrupted phone write:** It may be partial. Leave both sides inactive and resume using the saved cursor.

Run the mock-filesystem tests from the repository root:

```bash
python3 test-pkm-sync.py
```

Version 2.3.2 has 83 tests covering abandoned-create alias exceptions, case-collision preflight, interrupted non-journal write reconciliation, source-authoritative collection, verification reconciliation, exclusions, backup preservation, partial-operation recovery, automatic continuation, cursors, pending-only resume displays, phone-path discovery, mount-disconnect guards, GUI approval/cancellation, and watcher behavior. Mock tests do not establish compatibility with every physical device, MTP implementation, or graphical session.

## Public repository hygiene

Commit code, tests, and documentation only. The included `.gitignore` provides defense in depth for credentials, local overrides, logs, state, backups, and accidental vault copies.

Before each public commit, review:

```bash
git status --short --ignored
git diff --cached
git ls-files
```

Never commit rclone tokens/configuration, OAuth client secrets, private keys, actual vault content, runtime plans, backups, or unredacted terminal output. Runtime files can contain personal absolute paths and private filenames.

`.gitignore` does not untrack files already committed, erase Git history, or detect arbitrary secrets. If a credential was published, revoke/rotate it and address repository history separately. Git author names and email addresses are also separate from source-file anonymization; review your Git identity before publishing.

No license file is included in this preparation. Choose the intended license separately before advertising redistribution or reuse terms.
