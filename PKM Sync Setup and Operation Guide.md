# PKM collect-then-push sync

Version 2.0.0 uses the laptop as the authoritative Obsidian vault. It is not general-purpose bidirectional sync. The implementation was tested with mock local filesystems, not with the actual Android MTP mount. Preview the real device before applying.

Validation: 24 automated tests passed, including in-flight overwrite/create/deletion retries, backup preservation, and cursor resumption without phone rescanning. A local stress test completed 1,300 writes and final read-back verification in nine 300-operation batches under a 32-file-descriptor limit; descriptor counts were five before and five afterward. This establishes bounded descriptor use in the tested Python path, not absence of resource issues in an external MTP daemon.

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

The CLI defaults to at most 500 phone operations per invocation. There are no worker threads or concurrent file transfers. Use `--batch-size 100` for a smaller trial or a larger positive number to do more work per invocation without increasing concurrency.

The budget covers phone file writes, file deletions, obsolete-directory checks, and final verification reads. It does not cap initial enumeration/hashing, local imports, source-tree revalidation, or the number of files represented in the plan.

After each completed operation, the local cursor is saved. At the batch boundary the job reports `PAUSED`, not `SUCCESS`. Continue with:

```bash
# Inspect the saved cursor/plan, without applying:
~/.local/bin/pkm-sync --resume

# Continue the next batch:
~/.local/bin/pkm-sync --resume --apply --batch-size 500
```

Repeat the apply command until `SUCCESS`. Each invocation requires confirmation. Do not repeat `--initial` or `--mirror` with `--resume`: their original values are frozen in the saved plan. Resume does not rescan/replan the whole phone.

Cursor and immutable plan:

```text
~/.local/state/pkm-sync/active-run.json
~/.local/state/pkm-sync/backups/<run-id>/plan.json
```

A local file lock prevents overlapping invocations. An active cursor prevents starting a different new run. An in-flight retry preserves the original backup rather than backing up partial replacement bytes over it.

If a source changes while a batch is paused, resume stops rather than silently applying a new plan. Keep both sides inactive and resolve the change before continuing. No unattended loop or timer is installed.

To inspect descriptor counts/limits without performing any sync or changing limits:

```bash
~/.local/bin/pkm-sync --diagnose
```

## Confirmed paths

| Role | Path |
|---|---|
| Laptop master | `~/PKM` |
| Phone vault | `/mnt/android/Internal storage/Documents/PKM` |
| Phone mountpoint | `/mnt/android`, mounted with `jmtpfs` |
| Google Drive mount | `~/gdrive` |
| Muse source | `~/gdrive/Muse` |
| Muse destination in master | `External/Google_Drive` |
| Journal location after initial deployment | `External/Journal` on both devices |

## Install

Save `pkm-sync.py` from the attachment. The download interface may use its display title rather than the original filename; adjust the source filename below if necessary.

```bash
mkdir -p ~/.local/bin
install -m 755 ~/Downloads/pkm-sync.py ~/.local/bin/pkm-sync
```

Run without sudo. Python 3, `findmnt`, and the already installed `~/.local/bin/pkm-gdrive-guard.sh` are required.

Do not enable the old `pkm-sync.timer` from the earlier design. If you enabled it previously, stop it before using this replacement:

```bash
systemctl --user disable --now pkm-sync.timer
```

If that unit does not exist, there is nothing to disable. Use this job manually while the phone is connected and inactive; no automatic timer is installed.

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

6. If `PAUSED` is printed, continue with `pkm-sync --resume --apply` until `SUCCESS`. Wait for `SUCCESS` before unmounting:

   ```bash
   fusermount -u /mnt/android
   ```

7. On Android, continue using the same vault folder, `Documents/PKM`. Change the daily-note/journal creation destination to `External/Journal`, including any mobile template or plugin setting that chooses the folder.

Preview creates a local state/lock directory and may recover the Drive mount. It does not modify vault or phone content.

## Later runs

With the phone mounted and inactive, and laptop editors/background writers stopped:

```bash
# Preview
~/.local/bin/pkm-sync --mirror

# Apply after reviewing the plan
~/.local/bin/pkm-sync --mirror --apply

# If PAUSED, repeat this until SUCCESS:
~/.local/bin/pkm-sync --resume --apply
```

The phases are strictly ordered:

- **Drive gate:** Run the installed mount guard. Mount/recovery or live API failure stops the job.
- **Phone collection:** Read phone `External/Journal` and plan imports into laptop `External/Journal`.
- **Muse collection:** Read Drive `Muse` and plan imports into laptop `External/Google_Drive`.
- **Master imports:** Add new content; replace older same-path external copies when the source timestamp is newer. Back up replaced master files first.
- **Phone return:** Copy the aggregated laptop content, verifying checksums. Back up replaced phone files first.
- **Mirror cleanup:** Only after all outbound copies succeed, back up and remove obsolete included phone files. Remove obsolete directories only if empty.
- **Verification:** Read back every included phone file and compare its SHA-256 with the planned master version. Save receipts only after success.

Any failure stops the operation. This is not an atomic whole-vault transaction: imports or earlier phone writes may already have completed before a later failure. Backups and an operation journal support manual recovery.

## Incoming updates and moves

Both incoming feeds preserve destination-only master files. They never perform inbound deletion.

- Unseen source files are imported.
- Different content replaces the external master copy only when its source modification time is more than two seconds newer.
- A newer master copy is retained.
- Different contents with timestamps within two seconds cause the job to stop for manual resolution. MTP timestamps are not assumed to be authoritative in ambiguous cases.
- Previously handled source path/content-hash pairs are skipped. This prevents a persistent source original from resurrecting a note you moved or deleted in the master.
- A deliberately rejected older source version is remembered too, so it cannot later resurrect after you move the newer master.

Receipts mean this is an ingestion workflow, not continuous reconciliation: a previously handled source version is not reapplied just because it still exists. If the source content changes again, that new version is reconsidered.

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
- No unattended `--apply` is allowed. Mirror deletion requires both `--mirror` and typed confirmation.
- Changes in a source file's bytes are detected with SHA-256; timestamps are used only to resolve competing incoming versions.
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
