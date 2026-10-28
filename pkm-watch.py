#!/usr/bin/env python3
"""Watch an Android MTP mount and offer one GUI-approved PKM run per mount."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


class MountGate:
    """Debounce mounting: require two identical consecutive samples."""
    def __init__(self):
        self.previous = None

    def ready(self, identity, handled):
        stable = identity is not None and identity == self.previous
        self.previous = identity
        return stable and identity != handled


def mount_identity():
    result = subprocess.run(
        ["findmnt", "-rn", "--mountpoint", "/mnt/android", "-o", "ID,FSTYPE,SOURCE"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode == 1:
        return None
    if result.returncode:
        raise RuntimeError(f"findmnt failed: {result.stderr.strip()}")
    fields = result.stdout.strip().split(maxsplit=2)
    if len(fields) != 3 or fields[1] not in {"fuse.jmtpfs", "fuse.mtpfs"}:
        return None
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    return hashlib.sha256((boot + "|" + result.stdout.strip()).encode()).hexdigest()


def read_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def remember(path, identity):
    temp = path.with_suffix(".tmp")
    try:
        with temp.open("w") as stream:
            json.dump({"handled_mount": identity}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def notify(title, message, urgent=False):
    print(f"{title}: {message}", flush=True)
    if shutil.which("notify-send"):
        try:
            subprocess.run(
                ["notify-send", "--app-name=PKM Sync", "--urgency=" +
                 ("critical" if urgent else "normal"), title, message],
                timeout=10, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


def sync_busy(path):
    with path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(lock, fcntl.LOCK_UN)
        return False


def run_offer(home, state_dir):
    """No initial deployment automation; the operator must establish the master."""
    active = state_dir / "active-run.json"
    state = read_json(state_dir / "state.json", {})
    if not active.exists() and not state.get("initialized"):
        notify("PKM Sync setup required",
               "Complete the initial deployment manually before using the mount watcher.")
        return "setup-required"
    mode = "--resume" if active.exists() else "--mirror"
    logfile = state_dir / (
        "desktop-" + dt.datetime.now().strftime("%Y%m%dT%H%M%S") + ".log"
    )
    notify("Phone detected", "Preparing the PKM plan. A review dialog will appear; no changes yet.")
    with logfile.open("x") as log:
        result = subprocess.run(
            [str(home / ".local/bin/pkm-sync"), mode, "--apply", "--gui"],
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        )
    if result.returncode == 3:
        message = "No sync was started by this offer."
        if active.exists():
            message += " An unfinished run remains; keep both vaults inactive."
        notify("PKM Sync cancelled", message)
        return "cancelled"
    if result.returncode:
        notify("PKM Sync stopped", f"Keep both vaults inactive. Inspect {logfile}", urgent=True)
        return "failed"
    if active.exists():
        notify("PKM Sync not finished", f"A saved cursor remains. Inspect {logfile}", urgent=True)
        return "unfinished"
    notify("PKM Sync complete", "Transfers and final verification finished successfully.")
    return "success"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=5, help="Mount check interval in seconds.")
    parser.add_argument("--check", action="store_true", help="Report mount status only, with no dialog.")
    args = parser.parse_args()
    if args.interval < 1:
        parser.error("--interval must be at least 1 second")
    if args.check:
        print("Expected MTP mount detected." if mount_identity() else "Expected MTP mount not present.")
        return
    if os.getuid() == 0:
        raise RuntimeError("Run as your normal desktop user, not with sudo.")
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise RuntimeError("Start through pkm-watch-session from a graphical desktop.")
    for command in ("zenity", "findmnt"):
        if not shutil.which(command):
            raise RuntimeError(f"Missing dependency: {command}")
    home = Path.home()
    if not (home / ".local/bin/pkm-sync").is_file():
        raise RuntimeError("Install pkm-sync before starting the watcher.")
    os.umask(0o077)
    state_dir = home / ".local/state/pkm-sync"
    state_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(state_dir, 0o700)
    handled_path = state_dir / "watch-state.json"
    handled = read_json(handled_path, {}).get("handled_mount")
    gate = MountGate()
    with (state_dir / "watch.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("A mount watcher is already running.")
        print("Watching /mnt/android; approval is required before every sync.", flush=True)
        while True:
            try:
                identity = mount_identity()
                if gate.ready(identity, handled) and not sync_busy(state_dir / "lock"):
                    # Wait for mount contents to become accessible, not merely mounted.
                    if (home / ".local/state/pkm-sync/active-run.json").exists():
                        ready = True  # Engine validates the frozen destination.
                    else:
                        explicit = os.environ.get("PKM_PHONE_VAULT")
                        target = (Path(explicit).expanduser() if explicit else
                                  Path("/mnt/android/Internal storage/Documents"))
                        ready = target.is_dir()
                    if ready:
                        run_offer(home, state_dir)
                        # Persist after the offer: cancelling must not nag each poll.
                        handled = identity
                        remember(handled_path, handled)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                print(f"Watcher check failed: {error}", file=sys.stderr, flush=True)
            time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Watcher stopped: {error}", file=sys.stderr)
        sys.exit(1)
