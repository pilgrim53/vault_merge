#!/usr/bin/env bash
# Run from the repository. Installs locally; never performs a vault sync itself.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ "$(id -u)" == 0 ]]; then
    printf 'Run as your normal desktop user, not with sudo.\n' >&2
    exit 1
fi
start=1
if [[ "${1:-}" == --no-start && "$#" == 1 ]]; then
    start=0
elif [[ "$#" != 0 ]]; then
    printf 'Usage: %s [--no-start]\n' "$0" >&2
    exit 2
fi
command -v python3 >/dev/null
for file in pkm-sync.py pkm-gdrive-guard.sh pkm-watch.py; do
    [[ -f "$file" ]] || { printf 'Missing repository file: %s\n' "$file" >&2; exit 1; }
done
if ((start)); then
    for tool in zenity systemctl findmnt; do command -v "$tool" >/dev/null; done
    if [[ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
        printf 'Run in an XFCE desktop terminal, or use --no-start.\n' >&2
        exit 1
    fi
    if systemctl --user is-active --quiet pkm-watch.service; then
        printf 'Watcher already running. Stop it while idle before reinstalling.\n' >&2
        exit 1
    fi
fi
python3 - <<'PY'
import fcntl
from pathlib import Path
import sys
path = Path.home() / ".local/state/pkm-sync/lock"
if path.exists():
    with path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit("A PKM sync/review is active. Wait before installing.")
PY
python3 test-pkm-sync.py
mkdir -p "$HOME/.local/bin" "$HOME/.config/systemd/user" "$HOME/.config/autostart"
install -m 755 pkm-sync.py "$HOME/.local/bin/pkm-sync"
install -m 755 pkm-gdrive-guard.sh "$HOME/.local/bin/pkm-gdrive-guard.sh"
install -m 755 pkm-watch.py "$HOME/.local/bin/pkm-watch"

# Templates contain no personal usernames. Absolute desktop paths are generated
# privately on the destination laptop, not stored in repository source.
python3 - <<'PY'
from pathlib import Path
import os
import tempfile

home = Path.home()
files = {
    home / ".local/bin/pkm-watch-session": (0o755, """#!/usr/bin/env bash
set -euo pipefail
if [[ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    printf 'No graphical session available.\\n' >&2
    exit 1
fi
names=(DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS XDG_CURRENT_DESKTOP XDG_SESSION_TYPE WAYLAND_DISPLAY XDG_SESSION_ID XDG_RUNTIME_DIR PKM_PHONE_VAULT)
present=()
for name in "${names[@]}"; do
    [[ -z "${!name:-}" ]] || present+=("$name")
done
if ((${#present[@]})); then
    systemctl --user import-environment "${present[@]}"
fi
if systemctl --user is-active --quiet pkm-watch.service; then
    # Refresh an idle watcher's desktop environment after a new login.
    # Never restart it while the engine holds its sync/review lock.
    if ! python3 -c 'import fcntl,pathlib; p=pathlib.Path.home()/".local/state/pkm-sync/lock"; f=p.open("a") if p.exists() else None; fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB) if f else None' 2>/dev/null; then
        printf 'Existing watcher is syncing/reviewing; leaving it running.\\n'
        exit 0
    fi
    systemctl --user restart pkm-watch.service
else
    systemctl --user start pkm-watch.service
fi
"""),
    home / ".config/systemd/user/pkm-watch.service": (0o644, """[Unit]
Description=Offer PKM sync when the Android vault is mounted
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=%h/.local/bin/pkm-watch --interval 5
Restart=on-failure
RestartSec=10
UMask=0077
TimeoutStopSec=30
"""),
}
launcher = str(home / ".local/bin/pkm-watch-session")
# Desktop Exec quoting is not shell expansion; escape reserved characters.
launcher = (launcher.replace("\\", "\\\\\\\\").replace('"', '\\\\"')
            .replace("$", "\\\\$").replace("`", "\\\\`").replace("%", "%%"))
files[home / ".config/autostart/pkm-watch.desktop"] = (0o644, f"""[Desktop Entry]
Type=Application
Name=PKM Phone Mount Watcher
Comment=Offer a reviewed vault sync when the phone is mounted
Exec="{launcher}"
Terminal=false
""")
for destination, (mode, text) in files.items():
    with tempfile.NamedTemporaryFile(mode="w", dir=destination.parent, delete=False) as out:
        temp = Path(out.name)
        out.write(text)
    os.chmod(temp, mode)
    os.replace(temp, destination)
print("Installed the watcher, systemd user service, and desktop-login autostart.")
PY

if ((start)); then
    systemctl --user daemon-reload
    "$HOME/.local/bin/pkm-watch-session"
    printf 'Watcher started. It may offer a sync if the phone is already mounted.\n'
else
    printf 'Not started. From your desktop terminal, run:\n'
    printf '  systemctl --user daemon-reload\n  ~/.local/bin/pkm-watch-session\n'
fi
