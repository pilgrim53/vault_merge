# PKM collect-then-push sync

Version 2.3.2 uses the laptop as the complete master Obsidian vault, while external sources own same-path content within their intake folders. It is not general-purpose bidirectional sync. Apply requires one approval in a terminal or the optional Zenity review dialog, then all batches continue automatically through final verification. The implementation was tested with mock local filesystems, not with the actual Android MTP mount. Preview the real device before applying.

Validation: 83 automated tests passed, including narrow abandoned-create alias exceptions, case-collision preflight, safe interrupted-write reconciliation, source-wins imports, verification recovery with preserved cursors/backups, pending-only resume displays, mount-disconnect guards, GUI approval/cancellation, watcher behavior, phone-vault discovery/overrides, automatic continuation without batch prompts, compatibility with version 2.0 paused cursors, in-flight overwrite/create/deletion retries, backup preservation, and cursor resumption without phone rescanning. The version 2.0 transfer path also passed a local stress test of 1,300 writes and final read-back verification in nine 300-operation batches under a 32-file-descriptor limit; descriptor counts were five before and five afterward. This establishes bounded descriptor use in the tested Python path, not absence of resource issues in an external MTP daemon.

## Descriptor-exhaustion fix and recovery from version 1

The original Python job was already single-threaded. However, it wrote phone-side temporary files and renamed them into place. An upstream jmtpfs report documents accumulating file descriptors during MTP renames, matching the observed failure pattern; it does not prove the exact installed binary has that bug ([jmtpfs issue 39](https://github.com/JasonFerrara/jmtpfs/issues/39)).

Version 2 eliminates all phone-side temporary-file renames. It writes one phone file at a time, directly to its final path, after saving its original content locally and checkpointing the in-flight operation. It verifies every completed transfer by reading back its content. Local master/state/backup writes still use temporary files and atomic local renames.

Batching is not a substitute for fixing a leak in a separate filesystem daemon. Reset an exhausted jmtpfs process once, using a normal unmount/remount, before retrying:

```bash
cd ~
# Close file-manager windows and shells accessing the phone mount first.
fusermount -u /mnt/android
# Only if unmount succeeded:
jmtpfs /mnt/android
```

If unmount fails because the mount is busy, stop and identify the holders. Do not use a forced/lazy unmount or kill jmtpfs as a routine recovery step.

Do not remove previous backup folders, state, or logs. Version 1 created no resumable cursor. After installing version 2, preview again with `--initial --mirror`, then apply with those flags. Its fresh plan will skip phone files already matching the master. Use `--resume` only after version 2 has created an active run.

This change trades atomic phone-file replacement for recoverability: an interrupted direct write can leave a partial phone file. Do not edit the phone or master between batches or after a failure.

## Batches and persistent cursor

The CLI defaults to progress batches of 500 phone operations. Batches continue automatically in the same process until success or error, without repeated confirmation. There are no worker threads or concurrent file transfers. `--batch-size 100` changes the progress-batch interval, not concurrency.

The budget covers phone file writes, file deletions, obsolete-directory checks, and final verification reads. It does not cap initial enumeration/hashing, local imports, source-tree revalidation, or the number of files represented in the plan.

After each completed operation, the local cursor is saved. At an automatic batch boundary the job reports `CHECKPOINT` and continues. Use `--resume` only after an error, interruption, or deliberate manual pause:

```bash
# Inspect the saved cursor/plan, without applying:
~/.local/bin/pkm-sync --resume

# Continue all remaining batches after one approval:
~/.local/bin/pkm-sync --resume --apply --batch-size 500
```

Do not repeat `--initial` or `--mirror` with `--resume`: their original values are frozen in the saved plan. Resume does not rescan/replan the whole phone. Version 2.0 cursors work with version 2.1, including a cursor already in the verification phase. If the old run has not reported `SUCCESS`, resume rather than starting a new plan.

### Verification or phone writes stopped after legitimate edits/renames

Do not delete journal entries to satisfy a stale verification hash. For a `verify` cursor with `inflight: false`, or a `pushes` cursor without an interrupted Journal write, version 2.3.2 can explicitly replace the frozen plan while preserving its history:

```bash
# Preview only.
"$HOME/.local/bin/pkm-sync" --reconcile
# Review a freshly computed replacement plan and approve once.
"$HOME/.local/bin/pkm-sync" --reconcile --apply
```

Reconciliation collects phone journals with the phone authoritative, and Drive entries with Drive authoritative, without timestamp or three-way version arbitration. It retains master-only files. After approval, it snapshots current phone journal files in the new backup's `reconciliation/phone/External/Journal/` directory and saves the prior cursor as `superseded-active-run.json`. Old plans/backups/logs remain intact. It then replaces the active cursor atomically, performs the freshly planned imports/return/mirror work, and verifies the new desired contents. It does not mark the old run successful or initialized.

Existing master files overwritten by imports are backed up under `master/` as usual. If journal preservation fails before cursor replacement, the old active cursor remains. Once a new active cursor exists, an interrupted recovery uses ordinary `--resume --apply`. Do not combine `--reconcile` with `--resume`, `--initial`, `--mirror`, or `--phone-vault`; it retains the saved paths and mirror policy. Both vaults must remain inactive.

For an interrupted non-journal phone write, imports already completed, so the fresh plan can account for a renamed master file and a partial phone destination. Any overwrite/deletion of that partial destination receives a new backup; original backups from the superseded run remain unchanged. An interrupted Journal write cannot be reconciled this way, because pulling its partial phone copy would risk replacing a valid master journal.

### Case-only name collisions

Preflight conservatively rejects filenames or directories that differ only by case in the master or aggregated desired vault, before content transfer. The same check protects application of older frozen plans. It does not test every Android filename restriction or determine the actual device's case sensitivity.

Preserve distinct contents and rename one note clearly in Obsidian, for example `Note.md` and `note.md` becoming `Note.md` and `Note - alternate.md`. Do not merge or delete notes based only on similar names. An eligible active plan can then be explicitly reconciled; an unchanged old plan still refers to old paths and should not be resumed after a rename.

If you deliberately remove an unwanted source after a failed outbound create, reconciliation can handle its unreadable phone alias without touching the retained case-variant note. The saved operation must be an in-flight create with no original destination; its exact master path must be absent; a differently-cased note in the same master directory must remain wanted. External paths are never eligible.

The preview labels this `PHONE ALIAS EXCEPTION`. The abandoned exact-name entry is not read or deleted, but the retained canonical note must be read and verified. Unknown unreadable files, prior replacement operations, and unreadable retained notes still stop recovery. Approved exceptions persist as `abandoned_phone_aliases` in state and saved plans, and future regular syncs honor them only while eligibility remains valid. This is explicitly not a strict mirror of exact filenames or proof that phone metadata has been repaired; successful desired-content verification prints an exception notice.

For optional troubleshooting only, add `--pause-after-batch` to stop deliberately after one batch. This is no longer the default.

Cursor and immutable plan:

```text
~/.local/state/pkm-sync/active-run.json
~/.local/state/pkm-sync/backups/<run-id>/plan.json
```

A local file lock prevents overlapping invocations. An active cursor prevents starting a different new run. An in-flight retry preserves the original backup rather than backing up partial replacement bytes over it.

If a source changes while a batch is paused, resume stops rather than silently applying a new plan. Keep both sides inactive and resolve the change before continuing. No timer is installed; automatic batch continuation stays inside the single approved invocation.

To inspect descriptor counts/limits without performing any sync or changing limits:

```bash
~/.local/bin/pkm-sync --diagnose
```

## Default paths

| Role | Path |
|---|---|
| Laptop master | `~/PKM` |
| Phone vault | Auto-discovered under `/mnt/android/Internal storage/Documents`, or explicitly configured |
| Phone mountpoint | `/mnt/android`, mounted with `jmtpfs` |
| Google Drive mount | `~/gdrive` |
| Muse source | `~/gdrive/Muse` |
| Muse destination in master | `External/Google_Drive` |
| Journal location after initial deployment | `External/Journal` on both devices |

`~` means the current user's home directory. Python uses `Path.home()` and the shell guard uses quoted `$HOME`; neither embeds a username. For new runs, phone discovery requires exactly one direct child of phone Documents containing `.obsidian`. Multiple or zero candidates stop the job rather than guessing. An existing phone folder need not be renamed.

For a different phone location, use a private shell variable:

```bash
export PKM_PHONE_VAULT="/mnt/android/Internal storage/Documents/Your Vault"
```

Or pass `--phone-vault "/mnt/android/Internal storage/Documents/Your Vault"` on new preview/apply commands. Keep personal overrides outside the public repository. Resume uses the frozen checkpoint paths and does not rediscover or change its phone destination.

Runtime logs, plans, checkpoints, import receipts, and backups can contain actual absolute paths and private filenames. Do not commit `~/.local/state/pkm-sync`, your rclone configuration, terminal transcripts, or vault content to the public repository. Publishing anonymized source files does not sanitize earlier Git history or previously uploaded logs.

## Install

Save `pkm-sync.py` from the attachment. The download interface may use its display title rather than the original filename; adjust the source filename below if necessary.

```bash
mkdir -p ~/.local/bin
install -m 755 ~/Downloads/pkm-sync.py ~/.local/bin/pkm-sync
```

Run as your normal laptop user, without sudo. Python 3, `findmnt`, and the installed `~/.local/bin/pkm-gdrive-guard.sh` are required.

Do not enable the old `pkm-sync.timer` from the earlier design. If you enabled it previously, stop it before using this replacement:

```bash
systemctl --user disable --now pkm-sync.timer
```

If that unit does not exist, there is nothing to disable. Use this job manually while the phone is connected and inactive, or install the optional desktop watcher described in `README.md`. The watcher offers a GUI review rather than applying silently.

## First deployment

All wanted phone content is already in the laptop master. The first deployment deliberately imports nothing from the phone.

1. Mount the phone with `jmtpfs /mnt/android` if it is not already mounted.
2. Keep the phone inactive. Close Obsidian and anything else editing the laptop vault, including AI agents or background writers.
3. Preview:

   ```bash
   ~/.local/bin/pkm-sync --initial --mirror
   ```

4. Inspect `IMPORT`, `PHONE ADD`, `PHONE REPLACE`, and especially `PHONE DELETE` entries.
5. Apply only if the preview is correct:

   ```bash
   ~/.local/bin/pkm-sync --initial --mirror --apply
   ```

   The script recomputes and displays its plan, then requires you to type `MIRROR PHONE`.

6. Batches continue automatically. Wait for `SUCCESS` before unmounting:

   ```bash
   fusermount -u /mnt/android
   ```

7. On Android, continue using the same existing vault folder. Change the daily-note/journal creation destination to `External/Journal`, including any mobile template or plugin setting that chooses the folder.

Preview creates a local state/lock directory and may recover the Drive mount. It does not modify vault or phone content.

## Later runs

With the phone mounted and inactive, and laptop editors/background writers stopped:

```bash
# Preview
~/.local/bin/pkm-sync --mirror

# Apply after reviewing the plan
~/.local/bin/pkm-sync --mirror --apply

# Only if interrupted or deliberately paused:
~/.local/bin/pkm-sync --resume --apply
```

The phases are strictly ordered:

- **Drive gate:** Run the installed mount guard. Mount/recovery or live API failure stops the job.
- **Phone collection:** Read phone `External/Journal` and plan imports into laptop `External/Journal`.
- **Muse collection:** Read Drive `Muse` and plan imports into laptop `External/Google_Drive`.
- **Master imports:** Add new content; an external source replaces a differing same-path external master copy regardless of timestamp. Back up replaced master files first.
- **Phone return:** Copy the aggregated laptop content, verifying checksums. Back up replaced phone files first.
- **Mirror cleanup:** Only after all outbound copies succeed, back up and remove obsolete included phone files. Remove obsolete directories only if empty.
- **Verification:** Read back every included phone file and compare its SHA-256 with the planned master version. Save receipts only after success.

Any failure stops the operation. This is not an atomic whole-vault transaction: imports or earlier phone writes may already have completed before a later failure. Backups and an operation journal support manual recovery.

## Incoming updates and moves

Both incoming feeds preserve destination-only master files. They never perform inbound deletion.

- Unseen source files are imported.
- A differing same-path external source copy wins, regardless of timestamp or edits to the master copy. The phone owns Journal; Drive owns Google_Drive.
- Checksums detect unchanged content and verify transfers; they do not arbitrate source ownership.
- Previously handled source path/content-hash pairs are skipped only when the corresponding master intake path is absent. This prevents a persistent source original from resurrecting an already imported note you moved or deleted.
- An existing same-path master copy can still be overwritten by its authoritative source even if that source version was receipted previously.

Move notes outside the intake folders to edit them independently. A changed source version can be imported again even if an earlier version was moved.

Keep `~/.local/state/pkm-sync/state.json`: losing it loses import receipts and can cause moved imports to reappear. Do not edit it casually.

## What is excluded from the phone mirror

These top-level directories are neither copied from the laptop nor deleted on the phone:

```text
.obsidian
.agents
.claude
.copilot
.opencode
.smart-env
.git
.trash
```

The phone retains its Obsidian settings and plugins. Existing excluded phone folders are not cleaned up. Ordinary content directories, including non-hidden `copilot`, are included.

This is therefore a mirror of included vault content, not a byte-identical clone of all desktop application state.

## Safety and limitations

- One job runs at a time through a local file lock.
- The CLI verifies an actual `fuse.jmtpfs` or `fuse.mtpfs` mount at `/mnt/android`; it will not write into an ordinary unmounted local directory.
- Symlinks in included content stop the job rather than following links outside the intended trees.
- File-versus-directory collisions stop for manual resolution rather than attempting destructive type conversion.
- Phone writes avoid MTP renames and use verified direct writes with a durable in-flight cursor and local pre-change backups. This is not atomic; resume can retry a partially written file. Local mock tests do not establish device compatibility.
- MTP may not preserve timestamps; the script warns if timestamp-setting fails. Phone return comparisons use hashes, not timestamps.
- No unattended `--apply` is allowed. Mirror deletion requires both `--mirror` and terminal confirmation or explicit approval of the graphical plan-review dialog.
- Changes in a source file's bytes are detected with SHA-256; timestamps never decide which incoming version wins.
- Keep the phone inactive through completion. Keep the master quiescent too; a checksum check cannot prevent an external writer changing a file immediately afterward.
- Full-file hashing and read-back verification can be slow over MTP. The terminal may appear quiet during enumeration.
- A successful empty Muse listing is valid and does not delete existing master imports.

## Backups and errors

Changed/deleted originals are stored outside the vault:

```text
~/.local/state/pkm-sync/backups/<run-id>/master/<relative-path>
~/.local/state/pkm-sync/backups/<run-id>/phone/<relative-path>
~/.local/state/pkm-sync/backups/<run-id>/operations.jsonl
```

The JSON-lines log records intent and completion for file mutations. Newly created files have no prior version; their paths are recorded instead. These are pre-change file backups, not a complete device image, automatic rollback, or offsite vault backup. Keep sufficient laptop disk space.

If interrupted, do not start editing on the phone immediately. Inspect the error and the latest backup/log before retrying or restoring. A failure partway through imports leaves already imported files in the master; reruns recognize identical content. A failure during phone updates may leave a partially updated phone.

For a permission or MTP rename failure, share the exact error. Do not add `--allow-non-empty`, use sudo, or delete local state to force progress.
