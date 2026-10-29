# PKM Sync Command Cheat Sheet

For version 2.3.2. Normal use needs only `--mirror` and `--apply`; recovery options are not part of the everyday workflow. Run commands as your normal user, without `sudo`.

## Everyday sync

Keep the phone mounted and inactive. Close Obsidian, editors, agents, and other vault writers on the laptop before applying.

```bash
# Preview a fresh regular sync. No vault/phone content changes.
"$HOME/.local/bin/pkm-sync" --mirror

# Build a fresh regular plan, review it, and approve once.
"$HOME/.local/bin/pkm-sync" --mirror --apply
```

The separate preview is optional: apply displays its own plan and requires approval. It recomputes the plan rather than applying a stored copy of the previous preview. Keep both sides inactive through `SUCCESS`.

Regular sync collects phone journals, collects Drive entries, then returns the aggregated master to the phone. It may replace external master files and, with mirror enabled, delete obsolete included phone files. Replaced/deleted file contents are backed up locally before mutation.

## Choose the right mode

| Situation | Preview command | Apply command |
| --- | --- | --- |
| No unfinished run; ordinary sync | `pkm-sync --mirror` | `pkm-sync --mirror --apply` |
| An apply was interrupted; continue the unchanged saved plan | `pkm-sync --resume` | `pkm-sync --resume --apply` |
| An unfinished plan is stale after legitimate edits/renames; an eligible replacement plan is needed | `pkm-sync --reconcile` | `pkm-sync --reconcile --apply` |
| Initial deployment already completed | Never use `--initial` again for ordinary operation | Do not reset state to force it |

The table assumes `~/.local/bin` is on your shell's PATH. Otherwise use `"$HOME/.local/bin/pkm-sync"` as in the everyday examples.

## Recovery is exceptional

- **Resume:** Continues the original frozen paths, hashes, operation list, and cursor. It does not scan for and collect new work as a fresh regular sync would. It can retry the current partially completed phone write. If the underlying error persists, investigate rather than repeatedly retrying.
- **Reconcile:** Scans current content to propose a replacement for an unfinished plan. After approval, it preserves phone journals and archives the old cursor; original plans/backups remain. It is not a normal sync mode and requires an active cursor.
- **Eligibility:** Reconciliation permits verification with no in-flight operation, or the phone-write phase provided the interrupted operation is not a Journal write. Other phases require inspection/recovery first.
- **Saved settings:** Resume and reconcile inherit saved paths and mirror policy. Do not combine either with `--initial`, `--mirror`, or `--phone-vault`; do not combine resume with reconcile.
- **Missing cursor:** After `SUCCESS`, absence of `active-run.json` is expected. Use normal `--mirror`, not either recovery command.

If apply stopped, keep both vaults inactive until the unfinished run has been recovered or deliberately superseded. Do not delete state/cursors, alter backup files, skip failed verification, or add `--initial` to get around an error.

## What the flags mean

| Flag | Meaning and consequence |
| --- | --- |
| No `--apply` | Preview only. The Drive guard may mount/recover Drive, and local state/lock directories may be created. No vault/phone content is changed. |
| `--apply` | Perform operations after terminal or GUI approval. This is the content-changing switch. |
| `--mirror` | In a new plan, remove obsolete included phone files and eligible empty directories. It does not delete master-only files during incoming collection. |
| `--resume` | Recover using an existing saved plan. Add `--apply` to execute. |
| `--reconcile` | Recover by proposing a fresh replacement plan from an eligible saved run. Add `--apply` to execute. |
| `--initial` | First deployment only; skips phone journal imports. Not a repair, reset, or full-resync switch. |
| `--gui` | With `--apply`, use the desktop review dialog instead of terminal approval. It changes the approval interface, not the sync policy. |
| `--version` | Show the installed engine version. No sync is performed. |
| `--diagnose` | Show Python/MTP file-descriptor diagnostics only. Does not establish that a vault is synchronized. |
| `--batch-size N` | Set operations per progress batch. Batches normally continue automatically; this is not a thread count or concurrency setting. |
| `--pause-after-batch` | Deliberately stop after a batch for manual recovery/testing. Not needed in normal operation. |
| `--phone-vault PATH` | Override the mounted phone vault on a new run. Normally leave it alone; recovery uses saved paths. |

Running with no mode flags is a new regular, non-mirroring preview: it still plans collection and outbound additions/replacements, but omits mirror deletions. Use it only when you intentionally want to retain obsolete phone files.

## Ownership and protection

- **Phone Journal:** The phone owns same-path contents under `External/Journal`. Regular collection imports its version even if the laptop copy has a newer timestamp.
- **Drive intake:** Google Drive owns same-path contents under `External/Google_Drive`. Incoming collection retains destination-only master files.
- **Other included content:** The laptop is authoritative on the outbound leg. Phone edits outside Journal are not imported automatically; back them up or merge them before a mirror.
- **Excluded state:** `.agents`, `.claude`, `.copilot`, `.git`, `.obsidian`, `.opencode`, `.smart-env`, and `.trash` are excluded as top-level folders. The phone is not a byte-identical clone of desktop application state.
- **Names and errors:** Case-only name collisions stop planning. Unknown unreadable files stop the run; source ownership does not override transfer failures or skip verification.
- **Alias exceptions:** A `PHONE ALIAS EXCEPTION` is a narrowly recorded abandoned-create exception, not proof of a completely clean exact-name mirror. The retained note must still be verified. See the README for eligibility and limitations.

## Read the result correctly

| Output | Meaning |
| --- | --- |
| `PREVIEW ONLY` | Nothing was applied to vault/phone content. |
| `CHECKPOINT` | Progress saved; the run is not finished. Normal automatic batches continue. |
| `PAUSED` | A deliberate batch pause; use resume after checking the situation. |
| `STOPPED` | An error occurred. Whether unfinished work exists depends on whether an apply had started and whether a cursor remains. |
| `SUCCESS` | The run completed, including final desired-content verification; its active cursor was removed. Read any mirror-exception notice too. |
| Regular preview with zero imports/writes/deletions | No file-content changes or file deletions are currently planned. This is not itself an apply or success receipt. Directory checks can still be listed separately. |

The generic warning following `STOPPED` is conservative. A failed request to resume/reconcile after a completed run does not itself create an interrupted transfer.

## Check whether recovery is pending

This is read-only:

```bash
if test -f "$HOME/.local/state/pkm-sync/active-run.json"; then
    printf '%s\n' "Unfinished run exists. Inspect its phase before choosing recovery."
    python3 -m json.tool "$HOME/.local/state/pkm-sync/active-run.json"
else
    printf '%s\n' "No recovery cursor. Use the normal --mirror workflow."
fi
```

Backups and logs live under `~/.local/state/pkm-sync/backups/`. Keep them outside the public repository.

## Desktop approval and code updates

The mount watcher offers regular mirror sync when no run is pending, or resume when a cursor exists. It never automatically chooses initial deployment or reconciliation. Do not launch a second terminal sync while its review/apply is active.

Downloading code or pulling the repository does not update the installed copy. When only the engine changes, install it while no sync/review is running:

```bash
cd /path/to/your/repository
python3 test-pkm-sync.py &&
install -m 755 pkm-sync.py "$HOME/.local/bin/pkm-sync"
"$HOME/.local/bin/pkm-sync" --version
```

Installing the engine does not reset initialization, remove recovery state, or change vault files. Updating README/test files alone needs no runtime installation. Changes to the watcher or desktop integration may require the desktop installer; use its README instructions rather than rerunning a recovery command after every update.
