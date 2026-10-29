#!/usr/bin/env python3
"""PKM collect-then-push job. Preview by default; standard library only."""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import uuid
from dataclasses import dataclass

VERSION = "2.3.2"

EXCLUDED = {
    ".obsidian", ".agents", ".claude", ".copilot", ".opencode",
    ".smart-env", ".git", ".trash",
}


class SyncError(Exception):
    pass


class SyncCancelled(Exception):
    pass


def confirm_gui(job):
    """Review the actual in-memory plan; no --yes flag or piped confirmation."""
    if not shutil.which("zenity"):
        raise SyncError("Zenity is required for --gui.")
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise SyncError("--gui requires an active graphical desktop environment.")
    text = io.StringIO()
    text.write("PKM Sync: review before applying\n\n")
    if hasattr(job, "progress"):
        text.write(
            f"Resume saved run at {job.progress['phase']}[{job.progress['index']}].\n"
            "Only pending operations are listed below. Completed work will not be repeated.\n"
            "This is a saved plan, not a fresh scan for new changes.\n\n"
        )
    text.write(
        "Keep the phone inactive and stop laptop vault editors/agents until SUCCESS.\n"
        "Included phone files may be overwritten"
        + (" or deleted." if job.mirror else ".")
        + "\nOriginal file contents are backed up locally before replacement/deletion.\n"
        "An interrupted phone write can be partial; use the saved cursor to recover.\n\n"
    )
    with contextlib.redirect_stdout(text):
        job.display()
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="pkm-review-",
                                     suffix=".txt") as review:
        review.write(text.getvalue())
        review.flush()
        result = subprocess.run([
            "zenity", "--text-info", "--title=PKM Sync: review plan",
            f"--filename={review.name}", "--width=950", "--height=650",
            "--checkbox=I have stopped editing on both devices and approve this plan.",
            "--ok-label=Sync", "--cancel-label=Cancel",
        ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise SyncError(f"Zenity failed with exit status {result.returncode}; no approval granted.")


@dataclass
class Item:
    path: Path
    digest: str
    size: int
    mtime: float


def inspect(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise SyncError(f"Not a regular file (or is a symlink): {path}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise SyncError(f"File changed while reading: {path}")
    return Item(path, h.hexdigest(), after.st_size, after.st_mtime)


def scan(root, exclusions=False, skip_files=(), skipped=None):
    if not root.is_dir() or root.is_symlink():
        raise SyncError(f"Directory missing, inaccessible, or symlinked: {root}")
    files, directories = {}, set()

    def walk_error(error):
        raise SyncError(f"Cannot enumerate source: {error}")

    for base, dirs, names in os.walk(root, onerror=walk_error, followlinks=False):
        base = Path(base)
        if exclusions and base == root:
            dirs[:] = [d for d in dirs if d not in EXCLUDED]
            names = [n for n in names if n not in EXCLUDED]
        for name in dirs:
            path = base / name
            if path.is_symlink():
                raise SyncError(f"Symlinked directory not supported: {path}")
            directories.add(path.relative_to(root).as_posix())
        for name in names:
            path = base / name
            rel = path.relative_to(root).as_posix()
            if rel in skip_files:
                if skipped is not None:
                    skipped.add(rel)
                continue
            files[rel] = inspect(path)
    return files, directories


def check_case_collisions(files, directories, label):
    """Conservative Android portability check, including ancestor directories."""
    seen = {}
    collisions = []
    for rel in sorted(set(files) | set(directories)):
        key = rel.casefold()
        if key in seen and seen[key] != rel:
            collisions.append(f"  {seen[key]}\n  {rel}")
        else:
            seen[key] = rel
    if collisions:
        details = "\n".join(collisions[:10])
        if len(collisions) > 10:
            details += f"\n  ...and {len(collisions) - 10} more collisions"
        raise SyncError(
            f"Case-colliding paths in {label}; these cannot safely share a "
            f"case-insensitive destination:\n{details}\n"
            "Preserve both contents and rename notes/folders distinctly in Obsidian. "
            "No transfer attempted; a saved plan may require --reconcile after renaming."
        )


def assert_unchanged(path, expected):
    if expected is None:
        if path.exists() or path.is_symlink():
            raise SyncError(f"Unexpected new destination: {path}")
    elif inspect(path).digest != expected.digest:
        raise SyncError(f"File changed since preview: {path}")


def copy_checked(source, destination, expected_hash, timestamp_required=False):
    """Write a sibling temporary file, verify it, then rename into place."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(".pkm-transfer-" + uuid.uuid4().hex)
    try:
        # Exclusive create: never overwrite an unrelated temporary file.
        with source.open("rb") as src, temp.open("xb") as dst:
            h = hashlib.sha256()
            for block in iter(lambda: src.read(1024 * 1024), b""):
                dst.write(block)
                h.update(block)
        if h.hexdigest() != expected_hash or inspect(temp).digest != expected_hash:
            raise SyncError(f"Transfer verification failed: {source} -> {destination}")
        try:
            stamp = source.stat().st_mtime
            os.utime(temp, (stamp, stamp))
        except OSError:
            if timestamp_required:
                raise
            # MTP may not support setting timestamps. Content verification is mandatory.
            print(f"NOTICE: timestamp not preserved: {destination}", flush=True)
        os.replace(temp, destination)
    finally:
        if temp.exists():
            temp.unlink()


def copy_phone_checked(source, destination, expected_hash):
    """No MTP rename: verified local source -> final phone path -> read-back."""
    if inspect(source).digest != expected_hash:
        raise SyncError(f"Outbound source changed: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Caller must have saved the old content AND an in-flight checkpoint first.
    # This deliberately is not atomic. A failed copy stays resumable.
    with source.open("rb") as src, destination.open("wb") as dst:
        h = hashlib.sha256()
        for block in iter(lambda: src.read(1024 * 1024), b""):
            dst.write(block)
            h.update(block)
    if h.hexdigest() != expected_hash or inspect(destination).digest != expected_hash:
        raise SyncError(f"Phone transfer verification failed: {destination}")
    try:
        stamp = source.stat().st_mtime
        os.utime(destination, (stamp, stamp))
    except OSError:
        print(f"NOTICE: timestamp not preserved: {destination}", flush=True)


def write_json_atomic(path, value):
    temp = path.with_name(path.name + "-" + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("x") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        # Persist the rename as well as file content on the local state disk.
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temp.exists():
            temp.unlink()


def pack_item(item):
    return None if item is None else {
        "path": str(item.path), "digest": item.digest, "size": item.size, "mtime": item.mtime,
    }


def unpack_item(value):
    return None if value is None else Item(
        Path(value["path"]), value["digest"], value["size"], value["mtime"],
    )


def diagnostics():
    print("Resource diagnostics (no limits changed):")
    pids = {os.getpid()}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if (entry / "comm").read_text().strip() in {"jmtpfs", "mtpfs"}:
                pids.add(int(entry.name))
        except OSError:
            pass
    for pid in sorted(pids):
        try:
            root = Path("/proc") / str(pid)
            # Explicitly close the directory iterator before continuing.
            with os.scandir(root / "fd") as entries:
                count = sum(1 for _ in entries)
            limits = next(
                line for line in (root / "limits").read_text().splitlines()
                if line.startswith("Max open files")
            )
            print(f"  PID {pid} {(root / 'comm').read_text().strip()}: "
                  f"FDs={count}; {limits}")
        except (OSError, StopIteration):
            print(f"  PID {pid}: cannot inspect descriptors/limits")


def resolve_phone_vault(explicit=None, documents=Path("/mnt/android/Internal storage/Documents")):
    """Use a private override, or discover exactly one Obsidian vault."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_absolute():
            raise SyncError("--phone-vault must be an absolute mounted path.")
        return path
    if not documents.is_dir():
        raise SyncError("Phone Documents folder not found. Supply --phone-vault.")
    candidates = sorted(
        path for path in documents.iterdir()
        if path.is_dir() and not path.is_symlink() and (path / ".obsidian").is_dir()
    )
    if len(candidates) != 1:
        raise SyncError(
            f"Found {len(candidates)} Obsidian vaults in phone Documents; "
            "choose one with --phone-vault or PKM_PHONE_VAULT."
        )
    return candidates[0]


def phone_mount_token():
    """Guard against writing into the local directory after MTP unmount/remount."""
    found = None
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        left, right = line.split(" - ", 1)
        fields, filesystem = left.split(), right.split()
        if fields[4] == "/mnt/android":
            found = (fields[0], filesystem[0], filesystem[1])
    if found is None or found[1] not in {"fuse.jmtpfs", "fuse.mtpfs"}:
        raise SyncError("Expected Android MTP mount is absent; refusing phone writes.")
    return found


class Job:
    def __init__(self, master, phone, muse, state, initial=False, mirror=False):
        self.master, self.phone, self.muse = map(Path, (master, phone, muse))
        self.state_path = Path(state)
        self.initial, self.mirror = initial, mirror
        self.state = (
            json.loads(self.state_path.read_text())
            if self.state_path.exists()
            else {"initialized": False, "receipts": {}}
        )
        if not initial and not self.state.get("initialized"):
            raise SyncError("First run must use --initial; no phone pull is permitted yet.")
        if initial and self.state.get("initialized"):
            raise SyncError("Initial deployment already succeeded. Omit --initial to collect phone updates.")
        self.imports, self.pushes, self.deletes = [], [], []
        self.messages = []

    def receipt(self, source, rel, digest):
        key = source + ":" + rel
        values = self.state["receipts"].setdefault(key, [])
        if digest not in values:
            values.append(digest)

    def collect(self, source, root, prefix, desired):
        files, directories = scan(root)
        for rel, item in sorted(files.items()):
            key = source + ":" + rel
            target = prefix + "/" + rel
            current = desired.get(target)
            if current and current.digest == item.digest:
                self.receipt(source, rel, item.digest)
                continue
            # External sources own same-path contents, regardless of timestamps.
            # Receipts only suppress resurrection when the target is absent;
            # they must not prevent a source overwriting an existing target.
            if current is None and item.digest in self.state["receipts"].get(key, []):
                continue
            self.imports.append((target, item, current))
            desired[target] = item
            self.receipt(source, rel, item.digest)
        # Do not recreate directories of receipted files moved by the user.
        for target, _, _ in self.imports:
            parent = Path(target).parent
            while parent != Path("."):
                self.desired_dirs.add(parent.as_posix())
                parent = parent.parent
        return files

    def plan(self):
        self.master_files, self.desired_dirs = scan(self.master, exclusions=True)
        check_case_collisions(self.master_files, self.desired_dirs, "master vault")
        desired = dict(self.master_files)
        # An exact stale alias left by our failed CREATE must not force us to
        # read/delete a case-insensitive alias of a wanted, differently-cased
        # note. Never generalize this to unknown unreadable files or External.
        aliases = dict(self.state.get("abandoned_phone_aliases", {}))
        candidate = getattr(self, "abandoned_create", None)
        if candidate:
            rel = candidate["path"]
            for kept in self.master_files:
                if (rel != kept and rel.casefold() == kept.casefold()
                        and Path(rel).parent == Path(kept).parent):
                    aliases[rel] = {"kept": kept, "origin_run": candidate["run"]}
        aliases = {
            rel: record for rel, record in aliases.items()
            if rel not in self.master_files
            and Path(rel).parts[0].casefold() != "external"
            and record["kept"] in self.master_files
            and rel != record["kept"]
            and rel.casefold() == record["kept"].casefold()
            and Path(rel).parent == Path(record["kept"]).parent
        }
        self.state["abandoned_phone_aliases"] = aliases
        skipped = set()
        self.phone_files, self.phone_dirs = scan(
            self.phone, exclusions=True, skip_files=aliases, skipped=skipped)
        for rel, record in sorted(aliases.items()):
            kept = record["kept"]
            if rel in skipped and kept not in self.phone_files:
                # The retained path must be readable. This also guarantees a
                # real before-image if a later write through that alias occurs.
                self.phone_files[kept] = inspect(self.phone / kept)
            self.messages.append(
                f"PHONE ALIAS EXCEPTION: {rel}; abandoned failed create; "
                f"retained path {kept} will be verified. "
                "Old exact-name entry is not read or deleted; strict mirror excludes it."
            )
        if getattr(self, "reconcile_cursor", None) or not self.initial:
            journal = self.collect(
                "phone", self.phone / "External/Journal",
                "External/Journal", desired,
            )
            if getattr(self, "reconcile_cursor", None):
                self.recovery_journal = {
                    "External/Journal/" + rel: item for rel, item in journal.items()
                }
        self.collect("drive", self.muse, "External/Google_Drive", desired)
        check_case_collisions(desired, self.desired_dirs, "aggregated vault")
        for path in self.desired_dirs:
            if path in self.phone_files:
                raise SyncError(f"Phone file blocks required directory: {path}")
        for rel, item in sorted(desired.items()):
            if rel in self.phone_dirs:
                raise SyncError(f"Phone directory blocks required file: {rel}")
            old = self.phone_files.get(rel)
            if old is None or old.digest != item.digest:
                self.pushes.append((rel, item, old))
        if self.mirror:
            self.deletes = sorted(set(self.phone_files) - set(desired))
        self.desired = desired
        self.remove_dirs = (
            sorted(self.phone_dirs - self.desired_dirs, key=lambda s: (-s.count("/"), s))
            if self.mirror else []
        )

    def reconciliation(self):
        """Preview a replacement plan; never bless an unverified old run."""
        phase = self.progress["phase"]
        if phase == "verify" and not self.progress["inflight"]:
            pass
        elif phase == "pushes":
            index = self.progress["index"]
            if not 0 <= index <= len(self.pushes):
                raise SyncError("Invalid saved phone-write cursor.")
            if self.progress["inflight"]:
                if index == len(self.pushes):
                    raise SyncError("Invalid in-flight phone-write cursor.")
                rel = self.pushes[index][0]
                if rel.startswith("External/Journal/"):
                    raise SyncError(
                        "Cannot reconcile an interrupted Journal write: the phone source "
                        "may be partial. Recover it from the saved plan/backups first."
                    )
        else:
            raise SyncError(
                "Reconciliation requires verification with no in-flight operation, "
                "or the phone-write phase with no interrupted Journal write."
            )
        job = Job(self.master, self.phone, self.muse, self.state_path,
                  initial=self.initial, mirror=self.mirror)
        # Imports completed before either permitted phase. Retain their
        # receipts, but do not set initialized or last_success.
        job.state = json.loads(json.dumps(self.state))
        job.reconcile_cursor = dict(self.progress)
        if phase == "pushes" and self.progress["inflight"]:
            rel, _, old = self.pushes[self.progress["index"]]
            if old is None and Path(rel).parts[0].casefold() != "external":
                job.abandoned_create = {"path": rel, "run": self.progress["run"]}
        # Remember journal versions that were already present/copied on the
        # phone, only for moved-file suppression, never to arbitrate contents.
        completed_writes = {
            rel for rel, _, _ in self.pushes[:self.progress["index"]]
        } if phase == "pushes" else set(self.desired)
        for rel, item in self.desired.items():
            if rel.startswith("External/Journal/"):
                prior = self.phone_files.get(rel)
                if rel in completed_writes or (prior and prior.digest == item.digest):
                    job.receipt("phone", rel[len("External/Journal/"):], item.digest)
        job.plan()
        return job

    def display(self):
        resumable = hasattr(self, "progress")
        mode = "INITIAL (no phone import)" if self.initial else "REGULAR"
        if getattr(self, "reconcile_cursor", None):
            mode = "RECONCILIATION (phone-authoritative journal recovery)"
        print("MODE:", ("RESUME " if resumable else "") + mode)
        print("MASTER:", self.master)
        print("PHONE:", self.phone)
        print("EXTERNAL POLICY: phone owns Journal; Drive owns Google_Drive. "
              "Source wins same-path differences; replaced master copies are backed up.")
        label = "Saved snapshot (not a live scan)" if resumable else "Included files"
        print(f"{label}: master={len(self.master_files)}, phone={len(self.phone_files)}")
        imports, pushes, deletes = self.imports, self.pushes, self.deletes
        directories = self.remove_dirs
        verification = len(self.desired)
        if resumable:
            phases = ["imports", "pushes", "deletes", "directories", "verify", "complete"]
            phase, index = self.progress["phase"], self.progress["index"]
            if phase not in phases or index < 0:
                raise SyncError("Invalid saved cursor.")
            current = phases.index(phase)
            def pending(items, name):
                position = phases.index(name)
                return [] if current > position else items[index:] if current == position else items
            imports = pending(imports, "imports")
            pushes = pending(pushes, "pushes")
            deletes = pending(deletes, "deletes")
            directories = pending(directories, "directories")
            verification = len(pending(list(self.desired), "verify"))
            print(f"CURSOR: {phase}[{index}]; in-flight={self.progress['inflight']}")
            print("This is unfinished saved work, not a new initial deployment.")
        for message in self.messages:
            print(message)
        for rel, _, old in imports:
            print("IMPORT " + ("UPDATE " if old else "ADD ") + rel)
        for rel, _, old in pushes:
            print("PHONE " + ("REPLACE " if old else "ADD ") + rel)
        for rel in deletes:
            print("PHONE DELETE " + rel)
        for rel in directories:
            print("PHONE REMOVE DIRECTORY IF EMPTY " + rel)
        prefix = "Remaining" if resumable else "Summary"
        print(
            f"{prefix}: {len(imports)} imports, {len(pushes)} phone writes, "
            f"{len(deletes)} phone file deletions."
        )
        if resumable:
            print(f"Also pending: {len(directories)} directory checks, {verification} verification reads.")
        print("Preserved/excluded top-level folders:", ", ".join(sorted(EXCLUDED)))

    def save_plan(self):
        value = {
            "schema": 1, "master": str(self.master), "phone": str(self.phone),
            "muse": str(self.muse), "state_path": str(self.state_path),
            "initial": self.initial, "mirror": self.mirror, "state": self.state,
            "master_files": {k: pack_item(v) for k, v in self.master_files.items()},
            "phone_files": {k: pack_item(v) for k, v in self.phone_files.items()},
            "desired": {k: pack_item(v) for k, v in self.desired.items()},
            "desired_dirs": sorted(self.desired_dirs), "phone_dirs": sorted(self.phone_dirs),
            "imports": [[r, pack_item(i), pack_item(o)] for r, i, o in self.imports],
            "pushes": [[r, pack_item(i), pack_item(o)] for r, i, o in self.pushes],
            "deletes": self.deletes, "remove_dirs": self.remove_dirs,
            "messages": self.messages,
            "supersedes": getattr(self, "reconcile_cursor", None),
        }
        write_json_atomic(self.backup / "plan.json", value)

    @classmethod
    def resume(cls, state_path):
        progress_path = Path(state_path).parent / "active-run.json"
        progress = json.loads(progress_path.read_text())
        backup = Path(progress["backup"])
        value = json.loads((backup / "plan.json").read_text())
        if value.get("schema") != 1:
            raise SyncError("Unsupported checkpoint schema.")
        self = cls.__new__(cls)
        for name in ("master", "phone", "muse", "state_path"):
            setattr(self, name, Path(value[name]))
        if self.state_path != Path(state_path):
            raise SyncError("Checkpoint state path mismatch.")
        for name in ("initial", "mirror", "state", "deletes", "remove_dirs", "messages"):
            setattr(self, name, value[name])
        for name in ("master_files", "phone_files", "desired"):
            setattr(self, name, {k: unpack_item(v) for k, v in value[name].items()})
        for name in ("desired_dirs", "phone_dirs"):
            setattr(self, name, set(value[name]))
        for name in ("imports", "pushes"):
            setattr(self, name, [(r, unpack_item(i), unpack_item(o))
                                for r, i, o in value[name]])
        self.backup, self.progress = backup, progress
        self.reconcile_cursor = value.get("supersedes")
        self.journal = backup / "operations.jsonl"
        return self

    def checkpoint(self):
        write_json_atomic(self.state_path.parent / "active-run.json", self.progress)

    def start_run(self):
        active = self.state_path.parent / "active-run.json"
        previous = getattr(self, "reconcile_cursor", None)
        if previous:
            if not active.exists() or json.loads(active.read_text()) != previous:
                raise SyncError("Saved cursor changed since reconciliation preview. Replan recovery.")
        elif active.exists():
            raise SyncError("An unfinished run exists. Use --resume, not a new run.")
        run = dt.datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z") + "-" + uuid.uuid4().hex[:8]
        self.backup = self.state_path.parent / "backups" / run
        self.backup.mkdir(parents=True, exist_ok=False)
        self.journal = self.backup / "operations.jsonl"
        self.save_plan()
        if previous:
            # Archive, do not erase, the original recovery record. Old backup
            # directories and their plans/logs are never modified.
            write_json_atomic(self.backup / "superseded-active-run.json", previous)
            for rel, item in self.recovery_journal.items():
                copy_checked(item.path, self.backup / "reconciliation/phone" / rel, item.digest)
        self.progress = {
            "backup": str(self.backup), "run": run, "phase": "imports", "index": 0,
            "inflight": False,
        }
        self.checkpoint()

    def begin_operation(self, device, rel, action, old, destination):
        if self.progress["inflight"]:
            # Only a previously checkpointed operation may bypass the original
            # destination checksum. It may contain a partial direct MTP write.
            # Old content must still exist in the original verified backup.
            if old:
                saved = self.backup / device / rel
                if not saved.is_file() or inspect(saved).digest != old.digest:
                    raise SyncError(f"Missing/invalid original backup: {saved}")
            self.record("retry", device, rel, action)
            return
        assert_unchanged(destination, old)
        if old:
            self.save_backup(device, rel, old)
        self.record("intent", device, rel, action)
        self.progress["inflight"] = True
        self.checkpoint()

    def end_operation(self, device, rel, action):
        self.record("done", device, rel, action)
        self.progress["index"] += 1
        self.progress["inflight"] = False
        self.checkpoint()

    def next_phase(self, name):
        self.progress.update(phase=name, index=0, inflight=False)
        self.checkpoint()

    def apply(self, batch_size=None, pause_after_batch=False):
        if batch_size is not None and batch_size < 1:
            raise SyncError("Batch size must be positive.")
        self.check_phone_mount()
        check_case_collisions(self.desired, self.desired_dirs, "planned vault")
        if not hasattr(self, "progress"):
            # Check before opening an active run, so a preflight mismatch can be
            # corrected and freshly previewed without a resumable mutation.
            self.validate_new_plan()
            self.start_run()
        budget = batch_size
        used = 0

        def pause_if_needed():
            nonlocal used
            if budget is not None and used >= budget:
                label = "PAUSED" if pause_after_batch else "CHECKPOINT"
                print(f"{label} after {used} phone operations; cursor saved: "
                      f"{self.progress['phase']}[{self.progress['index']}]", flush=True)
                if pause_after_batch:
                    print("Keep phone and master inactive. Continue: pkm-sync --resume --apply")
                    diagnostics()
                    return True
                # No new prompt or worker process: continue sequentially with
                # the already approved immutable plan and durable cursor.
                used = 0
            return False

        if self.progress["phase"] == "imports":
            while self.progress["index"] < len(self.imports):
                rel, item, old = self.imports[self.progress["index"]]
                destination = self.master / rel
                assert_unchanged(item.path, item)
                self.begin_operation("master", rel, "replace" if old else "create", old, destination)
                copy_checked(item.path, destination, item.digest, timestamp_required=True)
                self.end_operation("master", rel, "replace" if old else "create")
            self.next_phase("pushes")

        if self.progress["phase"] in {"pushes", "deletes", "directories", "verify"}:
            # All imports must have succeeded. Verify local sources every batch,
            # but don't re-read every phone file or open a new transport session.
            for rel, item in self.desired.items():
                assert_unchanged(self.master / rel, item)

        if self.progress["phase"] == "pushes":
            for rel in sorted(self.desired_dirs, key=lambda s: (s.count("/"), s)):
                self.check_phone_mount()
                (self.phone / rel).mkdir(parents=True, exist_ok=True)
            while self.progress["index"] < len(self.pushes):
                if pause_if_needed():
                    return False
                rel, item, old = self.pushes[self.progress["index"]]
                destination = self.phone / rel
                self.check_phone_mount()
                self.begin_operation("phone", rel, "replace" if old else "create", old, destination)
                self.check_phone_mount()
                copy_phone_checked(self.master / rel, destination, item.digest)
                self.end_operation("phone", rel, "replace" if old else "create")
                used += 1
                print(f"PHONE WRITE {self.progress['index']}/{len(self.pushes)}: {rel}", flush=True)
            self.next_phase("deletes")

        if self.progress["phase"] == "deletes":
            while self.progress["index"] < len(self.deletes):
                if pause_if_needed():
                    return False
                rel = self.deletes[self.progress["index"]]
                old = self.phone_files[rel]
                destination = self.phone / rel
                self.check_phone_mount()
                self.begin_operation("phone", rel, "delete", old, destination)
                self.check_phone_mount()
                if destination.exists():
                    destination.unlink()
                self.end_operation("phone", rel, "delete")
                used += 1
                print(f"PHONE DELETE {self.progress['index']}/{len(self.deletes)}: {rel}", flush=True)
            self.next_phase("directories")

        if self.progress["phase"] == "directories":
            while self.progress["index"] < len(self.remove_dirs):
                if pause_if_needed():
                    return False
                rel = self.remove_dirs[self.progress["index"]]
                directory = self.phone / rel
                self.check_phone_mount()
                if directory.is_dir():
                    # Explicitly close even when the directory is nonempty.
                    with os.scandir(directory) as entries:
                        empty = next(entries, None) is None
                    if empty:
                        directory.rmdir()
                self.progress["index"] += 1
                self.checkpoint()
                used += 1
            self.next_phase("verify")

        if self.progress["phase"] == "verify":
            desired_list = sorted(self.desired.items())
            while self.progress["index"] < len(desired_list):
                if pause_if_needed():
                    return False
                rel, item = desired_list[self.progress["index"]]
                if inspect(self.phone / rel).digest != item.digest:
                    raise SyncError(f"Final phone verification failed: {rel}")
                self.progress["index"] += 1
                self.checkpoint()
                used += 1
            # Build receipts even for entries verified in an earlier batch.
            for rel, item in desired_list:
                if rel.startswith("External/Journal/"):
                    self.receipt("phone", rel[len("External/Journal/"):], item.digest)
            self.state["initialized"] = True
            self.state["last_success"] = self.progress["run"]
            write_json_atomic(self.state_path, self.state)
            self.next_phase("complete")

        if self.progress["phase"] == "complete":
            (self.state_path.parent / "active-run.json").unlink()
            print("SUCCESS. Changed/deleted originals and operation log:", self.backup)
            if self.state.get("abandoned_phone_aliases"):
                print("NOTE: Desired content verified; strict mirror has recorded "
                      "abandoned-name exceptions. Those old alias entries were not read or deleted.")
            return True
        raise SyncError(f"Unknown cursor phase: {self.progress['phase']}")

    def check_phone_mount(self):
        # CLI installs the live check; mock filesystem tests use no real mount.
        callback = getattr(self, "phone_mount_check", None)
        if callback:
            callback()

    def validate_new_plan(self):
        # Validate the whole plan before any content mutation.
        for rel, item in self.master_files.items():
            assert_unchanged(self.master / rel, item)
        for rel, item in self.phone_files.items():
            assert_unchanged(self.phone / rel, item)
        for _, item, _ in self.imports:
            assert_unchanged(item.path, item)

    def record(self, phase, device, rel, action):
        with self.journal.open("a") as stream:
            stream.write(json.dumps({
                "phase": phase, "device": device, "path": rel, "action": action,
            }) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def save_backup(self, device, rel, item):
        copy_checked(item.path, self.backup / device / rel, item.digest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    parser.add_argument("--initial", action="store_true", help="Skip phone imports.")
    parser.add_argument("--mirror", action="store_true", help="Remove obsolete INCLUDED phone files.")
    parser.add_argument("--apply", action="store_true", help="Apply after interactive confirmation.")
    parser.add_argument("--gui", action="store_true",
                        help="With --apply, review and approve the plan in Zenity instead of a terminal.")
    parser.add_argument("--resume", action="store_true", help="Use the saved unfinished plan/cursor.")
    parser.add_argument("--reconcile", action="store_true",
                        help="Replan verification or a safe interrupted phone-write phase; phone owns Journal.")
    parser.add_argument("--batch-size", type=int, default=500,
                        help="Phone operations per progress batch; continues automatically (default 500).")
    parser.add_argument("--pause-after-batch", action="store_true",
                        help="Optional manual mode: stop after one batch with a saved cursor.")
    parser.add_argument("--diagnose", action="store_true", help="Show Python/jmtpfs FD counts and limits only.")
    parser.add_argument("--phone-vault", default=None,
                        help="Mounted phone vault path; otherwise use PKM_PHONE_VAULT or unique-vault discovery.")
    args = parser.parse_args()
    if args.gui and not args.apply:
        parser.error("--gui requires --apply")
    if args.diagnose:
        diagnostics()
        return
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    if args.resume and (args.initial or args.mirror or args.phone_vault):
        parser.error("--resume uses the saved flags/path; omit --initial, --mirror and --phone-vault")
    if args.reconcile and (args.resume or args.initial or args.mirror or args.phone_vault):
        parser.error("--reconcile uses the saved vault/flags; omit --resume, --initial, --mirror and --phone-vault")
    if os.getuid() == 0:
        raise SyncError("Run as your normal laptop user, not with sudo.")
    home = Path.home()
    state_dir = home / ".local/state/pkm-sync"
    state_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(state_dir, 0o700)
    with (state_dir / "lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SyncError("Another PKM sync is running.")
        subprocess.run([str(home / ".local/bin/pkm-gdrive-guard.sh")], check=True)
        mount = subprocess.run(
            ["findmnt", "-rn", "--mountpoint", "/mnt/android", "-o", "FSTYPE"],
            text=True, capture_output=True, check=True,
        ).stdout.strip()
        if mount not in {"fuse.jmtpfs", "fuse.mtpfs"}:
            raise SyncError(f"Expected jmtpfs/mtpfs at /mnt/android; found: {mount!r}")
        expected_mount = phone_mount_token()
        for required in ("External/Journal", "External/Google_Drive", ".obsidian"):
            if not (home / "PKM" / required).is_dir():
                raise SyncError(f"Expected master-vault directory missing: {home / 'PKM' / required}")
        state_path = state_dir / "state.json"
        if args.reconcile:
            saved = Job.resume(state_path)
            print("Reading current files for reconciliation; no vault/phone content writes yet.", flush=True)
            job = saved.reconciliation()
            print("The old plan/cursor will be archived only after approval.")
            print("Phone journals will be preserved locally before replacing the cursor.")
            job.display()
        elif args.resume:
            job = Job.resume(state_path)
            print(f"RESUME: {job.progress['phase']}[{job.progress['index']}]; "
                  f"in-flight operation={job.progress['inflight']}")
            print(f"Saved plan: {job.backup / 'plan.json'}")
            job.display()
        else:
            if (state_dir / "active-run.json").exists():
                raise SyncError("Unfinished run exists. Use --resume; do not start a new plan.")
            job = Job(
                home / "PKM",
                resolve_phone_vault(args.phone_vault or os.environ.get("PKM_PHONE_VAULT")),
                home / "gdrive/Muse",
                state_path,
                initial=args.initial, mirror=args.mirror,
            )
            phone_root = Path("/mnt/android").resolve()
            phone_target = job.phone.resolve()
            if phone_target == phone_root or not phone_target.is_relative_to(phone_root):
                raise SyncError("Phone vault must be a directory below /mnt/android.")
            print("Reading and hashing files. MTP can be slow; no content writes yet.", flush=True)
            job.plan()
            job.display()
        if not args.apply:
            print("PREVIEW ONLY. No vault or phone content changed.")
            print("The Drive guard may have mounted/recovered Drive; local lock directory was created.")
            return
        if args.gui:
            if not confirm_gui(job):
                raise SyncCancelled("Cancelled; no content changes applied by this invocation.")
        else:
            if not sys.stdin.isatty():
                raise SyncError("--apply requires a terminal, or --gui with desktop approval.")
            phrase = "MIRROR PHONE" if job.mirror else "APPLY"
            print("Keep the phone inactive and close Obsidian/editors/agents on the laptop.")
            print("Replaced/deleted file contents will be backed up locally before mutation.")
            if input(f"Type {phrase!r} to proceed: ") != phrase:
                raise SyncCancelled("Cancelled; no content changes applied by this invocation.")
        def check_same_mount():
            if phone_mount_token() != expected_mount:
                raise SyncError("Phone mount changed since plan review. Stop and resume after checking it.")
        job.phone_mount_check = check_same_mount
        job.apply(batch_size=args.batch_size, pause_after_batch=args.pause_after_batch)


if __name__ == "__main__":
    try:
        main()
    except SyncCancelled as error:
        print(str(error), file=sys.stderr)
        sys.exit(3)
    except (SyncError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"STOPPED: {error}", file=sys.stderr)
        print("Do not resume phone editing if an apply was interrupted; inspect backups/log first.",
              file=sys.stderr)
        if isinstance(error, OSError) and error.errno in {23, 24}:
            print("Descriptor exhaustion may be inside jmtpfs. Remount it before resuming.",
                  file=sys.stderr)
            try:
                diagnostics()
            except OSError:
                pass
        sys.exit(1)
