#!/bin/bash
# ============================================================================
# uninstall-trusted-writer.sh — remove the NTA Betta trusted Shopify write
# boundary (daemon, code, plist, CLI symlink).
#
# SAFE DEFAULTS:
#   * --keep-state is TRUE by default: /var/db/nta-betta-write (receipts,
#     ledger, corrections, authorisations, credentials) is preserved.
#   * The sudoers hardening fragment is preserved unless
#     --remove-sudoers-hardening is given explicitly.
#   * The legacy user-side Shopify write path is NOT restored by this script.
#     Never re-enable it silently; see
#     docs/incident/TRUSTED_WRITE_BOUNDARY_ROLLBACK_2026-10-16.md.
#
# HARD RULES: a real uninstall requires EUID 0; --dry-run prints every action
# and changes nothing. The write credential file is never read or printed.
#
# USAGE:
#   sudo deploy/uninstall-trusted-writer.sh [--remove-sudoers-hardening]
#        deploy/uninstall-trusted-writer.sh --dry-run
#   sudo deploy/uninstall-trusted-writer.sh --purge-state --force
# ============================================================================

set -eu
umask 022

SERVICE_LABEL="com.nanotanksaustralia.betta-write"
INSTALL_ROOT="/usr/local/libexec/nta-betta-write"
CLI_LINK="/usr/local/bin/nta-betta-write"
PLIST_DEST="/Library/LaunchDaemons/${SERVICE_LABEL}.plist"
STATE_ROOT="/var/db/nta-betta-write"
RUN_ROOT="/var/run/nta-betta-write"
SUDOERS_DEST="/etc/sudoers.d/nta-betta-write"
LOG_FILE="/var/log/nta-betta-write.uninstall.log"

SOURCE_SCRIPTS="betta_write_boundary.py betta_write_daemon.py betta_write_client.py betta_write_admin.py"

DRY_RUN=0
KEEP_STATE=1
FORCE=0
REMOVE_SUDOERS=0
PROBLEMS=0

usage() {
    cat <<'EOF'
usage: sudo uninstall-trusted-writer.sh [--remove-sudoers-hardening]
       uninstall-trusted-writer.sh --dry-run
       sudo uninstall-trusted-writer.sh --purge-state --force

  --dry-run                    Print every action without changing anything.
                               May run unprivileged.
  --keep-state                 Preserve /var/db/nta-betta-write (default).
  --purge-state                Delete /var/db/nta-betta-write entirely,
                               including the write credential and evidence
                               receipts. Requires --force; archive receipts
                               first (rollback doc §evidence preservation).
  --force                      Required confirmation for --purge-state.
  --remove-sudoers-hardening   Also remove /etc/sudoers.d/nta-betta-write
                               (kept by default because it is a security
                               control, not part of the daemon).
EOF
}

log() {
    local line
    line="$(date -u +%Y-%m-%dT%H:%M:%SZ) [uninstall] $*"
    printf '%s\n' "$line"
    if [ "$DRY_RUN" -eq 0 ] && [ "$(id -u)" -eq 0 ]; then
        printf '%s\n' "$line" >>"$LOG_FILE" 2>/dev/null || true
    fi
}

problem() {
    PROBLEMS=$((PROBLEMS + 1))
    log "PROBLEM: $*"
}

fatal() {
    log "REFUSED: $*"
    exit 2
}

fatal_or_problem() {
    if [ "$DRY_RUN" -eq 1 ]; then
        problem "$@"
        return 0
    fi
    fatal "$@"
}

run() {
    local description="$1"
    shift
    if [ "$DRY_RUN" -eq 1 ]; then
        log "DRY-RUN: $description"
        return 0
    fi
    log "$description"
    if ! "$@"; then
        fatal "command failed: $description"
    fi
}

is_group_or_other_writable() {
    local sym
    sym="$(stat -f '%Sp' "$1" 2>/dev/null || true)"
    [ -n "$sym" ] || return 1
    if [ "${sym:5:1}" = "w" ]; then return 0; fi
    if [ "${sym:8:1}" = "w" ]; then return 0; fi
    return 1
}

# ------------------------------------------------------------------ flags ---#
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        --keep-state) KEEP_STATE=1 ;;
        --purge-state) KEEP_STATE=0 ;;
        --force) FORCE=1 ;;
        --remove-sudoers-hardening) REMOVE_SUDOERS=1 ;;
        --help|-h) usage; exit 0 ;;
        *) usage >&2; printf 'unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
done

if [ "$KEEP_STATE" -eq 0 ] && [ "$FORCE" -ne 1 ]; then
    fatal "--purge-state deletes receipts, ledger and the write credential; re-run with --force after archiving (see rollback doc)"
fi

if [ "$(id -u)" -ne 0 ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
        log "NOTE: dry-run as uid $(id -u); no changes will be made. A real uninstall requires root."
    else
        log "REFUSED: this uninstaller must run as root: sudo $0"
        exit 2
    fi
fi

log "start (dry-run=$DRY_RUN keep-state=$KEEP_STATE remove-sudoers=$REMOVE_SUDOERS uid=$(id -u))"

# -------------------------------------------------------------- daemon down -#
log "step 1/6: stop and remove the LaunchDaemon"
if [ "$DRY_RUN" -eq 1 ]; then
    log "DRY-RUN: launchctl bootout system/$SERVICE_LABEL (ignore failure)"
elif ! /bin/launchctl print "system/$SERVICE_LABEL" >/dev/null 2>&1; then
    log "  daemon is not loaded"
else
    run "launchctl bootout system/$SERVICE_LABEL" \
        /bin/launchctl bootout "system/$SERVICE_LABEL" || true
fi
if [ "$DRY_RUN" -eq 1 ]; then
    log "DRY-RUN: rm -f $PLIST_DEST"
elif [ -e "$PLIST_DEST" ]; then
    run "rm -f $PLIST_DEST" /bin/rm -f "$PLIST_DEST"
else
    log "  plist not present: $PLIST_DEST"
fi

# ----------------------------------------------------------- installed code -#
log "step 2/6: remove installed boundary code and version record"
if [ -L "$INSTALL_ROOT" ]; then
    fatal_or_problem "$INSTALL_ROOT is a symlink; refusing to remove"
elif [ -e "$INSTALL_ROOT" ]; then
    if [ "$DRY_RUN" -eq 0 ] && [ "$(stat -f '%Su' "$INSTALL_ROOT" 2>/dev/null || printf '?')" != "root" ]; then
        fatal "$INSTALL_ROOT is not root-owned; refusing to remove"
    fi
    local_name=""
    for local_name in $SOURCE_SCRIPTS; do
        if [ -e "$INSTALL_ROOT/$local_name" ]; then
            run "rm -f $INSTALL_ROOT/$local_name" /bin/rm -f "$INSTALL_ROOT/$local_name"
        fi
    done
    run "rm -f $INSTALL_ROOT/version.json" /bin/rm -f "$INSTALL_ROOT/version.json"
    for local_name in "$INSTALL_ROOT"/version.json.bak.*; do
        if [ -e "$local_name" ]; then
            run "rm -f $local_name" /bin/rm -f "$local_name"
        fi
    done
    if [ -d "$INSTALL_ROOT/__pycache__" ]; then
        run "rm -rf $INSTALL_ROOT/__pycache__" /bin/rm -rf "$INSTALL_ROOT/__pycache__"
    fi
    if [ "$DRY_RUN" -eq 1 ]; then
        log "DRY-RUN: rmdir $INSTALL_ROOT (only if empty)"
    elif /bin/rmdir "$INSTALL_ROOT" 2>/dev/null; then
        log "  removed $INSTALL_ROOT"
    else
        log "  $INSTALL_ROOT not empty; unmanaged files were left in place"
    fi
else
    log "  install root not present: $INSTALL_ROOT"
fi

# ---------------------------------------------------------------- CLI link -#
log "step 3/6: remove admin CLI symlink (only when it points into $INSTALL_ROOT)"
if [ -L "$CLI_LINK" ]; then
    if [ "$(readlink "$CLI_LINK" 2>/dev/null || true)" = "$INSTALL_ROOT/betta_write_admin.py" ]; then
        run "rm -f $CLI_LINK" /bin/rm -f "$CLI_LINK"
    else
        log "  $CLI_LINK points elsewhere ($(readlink "$CLI_LINK" 2>/dev/null || true)); leaving it"
    fi
elif [ -e "$CLI_LINK" ]; then
    log "  $CLI_LINK exists and is not a symlink; leaving it"
else
    log "  admin CLI symlink not present"
fi

# ------------------------------------------------------------ runtime dir -#
log "step 4/6: remove runtime socket dir $RUN_ROOT (recreated at install)"
if [ -e "$RUN_ROOT" ]; then
    run "rm -rf $RUN_ROOT" /bin/rm -rf "$RUN_ROOT"
else
    log "  runtime dir not present"
fi

# ------------------------------------------------------- sudoers hardening -#
log "step 5/6: sudoers hardening"
if [ "$REMOVE_SUDOERS" -ne 1 ]; then
    if [ -e "$SUDOERS_DEST" ]; then
        log "  preserved (default): $SUDOERS_DEST — remove with --remove-sudoers-hardening"
    else
        log "  not installed"
    fi
elif [ -e "$SUDOERS_DEST" ]; then
    if [ "$DRY_RUN" -eq 0 ] && ! grep -q 'nta-betta-write sudoers hardening' "$SUDOERS_DEST" 2>/dev/null; then
        fatal "$SUDOERS_DEST does not carry the nta-betta-write marker; refusing to remove a foreign file"
    fi
    run "rm -f $SUDOERS_DEST" /bin/rm -f "$SUDOERS_DEST"
else
    log "  not installed"
fi

# ------------------------------------------------------------------- state -#
log "step 6/6: state directory"
if [ "$KEEP_STATE" -eq 1 ]; then
    if [ -e "$STATE_ROOT" ]; then
        log "  preserved (default): $STATE_ROOT (ledger, receipts, corrections, credentials)"
        log "  the write credential inside is NOT touched or printed by this script"
    else
        log "  state dir not present"
    fi
else
    if [ -L "$STATE_ROOT" ]; then
        fatal_or_problem "$STATE_ROOT is a symlink; refusing to purge"
    elif [ -e "$STATE_ROOT" ]; then
        if [ "$DRY_RUN" -eq 0 ] && [ "$(stat -f '%Su' "$STATE_ROOT" 2>/dev/null || printf '?')" != "root" ]; then
            fatal "$STATE_ROOT is not root-owned; refusing to purge"
        fi
        log "  WARNING: purging $STATE_ROOT deletes evidence receipts and the write credential"
        log "  archive receipts first: see docs/incident/TRUSTED_WRITE_BOUNDARY_ROLLBACK_2026-10-16.md"
        run "rm -rf $STATE_ROOT" /bin/rm -rf "$STATE_ROOT"
    else
        log "  state dir not present"
    fi
fi

if [ "$DRY_RUN" -eq 1 ]; then
    if [ "$PROBLEMS" -gt 0 ]; then
        log "DRY RUN finished with $PROBLEMS problem(s); NO changes were made."
        exit 1
    fi
    log "DRY RUN complete — every action printed above; NO changes were made. A real uninstall requires root."
    exit 0
fi

log "uninstall complete"
log "NOTE: the legacy user-side Shopify write path was NOT restored; do not re-enable it without the owner break-glass procedure"
exit 0
