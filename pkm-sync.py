#!/usr/bin/env bash
# Run directly, or source this file and call pkm_ensure_gdrive.
# Does not copy, overwrite, or delete any PKM or Google Drive files.

pkm_gdrive_log() {
    printf '[%s] gdrive: %s\n' "$(date '+%F %T %Z')" "$*" >&2
}

pkm_gdrive_identity() {
    findmnt -rn --mountpoint /home/martin/gdrive -o SOURCE,FSTYPE
}

pkm_gdrive_mount_readable() {
    local identity
    identity="$(pkm_gdrive_identity)" || return 1
    [[ "$identity" =~ ^gdrive:[[:space:]]+fuse\.rclone$ ]] || return 1
    timeout 20s ls -A -- /home/martin/gdrive/Muse >/dev/null 2>&1
}

pkm_ensure_gdrive() {
    local tool identity
    for tool in findmnt timeout ls systemctl rclone date id; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            pkm_gdrive_log "Required command not found: $tool"
            return 1
        fi
    done
    if [[ "$(id -un)" != martin ]]; then
        pkm_gdrive_log "Run as martin, not with sudo or as another user."
        return 1
    fi

    if ! pkm_gdrive_mount_readable; then
        identity="$(pkm_gdrive_identity 2>/dev/null)" || identity=""
        if [[ -n "$identity" ]] &&
           [[ ! "$identity" =~ ^gdrive:[[:space:]]+fuse\.rclone$ ]]; then
            pkm_gdrive_log "Unexpected filesystem at /home/martin/gdrive: $identity"
            pkm_gdrive_log "Refusing to replace or unmount it. Sync must stop."
            return 1
        fi
        if [[ ! -d /home/martin/gdrive ]]; then
            pkm_gdrive_log "Mountpoint missing or inaccessible. Sync must stop."
            return 1
        fi

        pkm_gdrive_log "Mount missing or unreadable; recovering via rclone-gdrive.service."
        if ! timeout 15s systemctl --user reset-failed rclone-gdrive.service; then
            pkm_gdrive_log "Could not clear service failure state. Sync must stop."
            return 1
        fi
        # One bounded recovery attempt. No manual mount, forced unmount,
        # --allow-non-empty, permission changes, or OAuth reconfiguration.
        if ! timeout 90s systemctl --user restart rclone-gdrive.service; then
            pkm_gdrive_log "Service restart failed or timed out. Sync must stop."
            pkm_gdrive_log "Inspect: journalctl --user -u rclone-gdrive.service -n 40 --no-pager"
            return 1
        fi
        if ! pkm_gdrive_mount_readable; then
            pkm_gdrive_log "Expected gdrive: mount or readable Muse folder still absent. Sync must stop."
            return 1
        fi
    fi

    # A cached FUSE listing alone does not prove current Google API access.
    # This read-only check validates the remote without depending on FUSE.
    pkm_gdrive_log "Mount readable; checking live Google Drive access."
    if ! timeout 45s rclone lsf gdrive:Muse --max-depth 1 \
        --contimeout 10s --timeout 20s --retries 1 --low-level-retries 1 \
        >/dev/null; then
        pkm_gdrive_log "Live Drive check failed. No imports or phone push should run."
        pkm_gdrive_log "If the error reports invalid_grant, run: rclone config reconnect gdrive:"
        return 1
    fi
    pkm_gdrive_log "Ready: gdrive:Muse at /home/martin/gdrive/Muse."
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    pkm_ensure_gdrive
    exit "$?"
fi
