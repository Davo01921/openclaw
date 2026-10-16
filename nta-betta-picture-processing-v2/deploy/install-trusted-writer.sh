#!/bin/bash
# ============================================================================
# install-trusted-writer.sh — root-gated installer for the NTA Betta trusted
# Shopify write boundary (closes incident H1).
#
# WHAT IT INSTALLS (idempotent; refuses drift without --upgrade):
#   /usr/local/libexec/nta-betta-write/           root:wheel 0755
#     betta_write_boundary.py  betta_write_daemon.py
#     betta_write_client.py    betta_write_admin.py       (root:wheel 0755)
#     version.json                                       (root:wheel 0644)
#   /var/db/nta-betta-write/                      root:wheel 0700
#     boundary-policy.json  corrections/  authorisations/  ledger/  receipts/
#   /var/run/nta-betta-write/                     root:wheel 0711 (runtime socket dir)
#   /Library/LaunchDaemons/com.nanotanksaustralia.betta-write.plist  root:wheel 0644
#   /usr/local/bin/nta-betta-write  ->  libexec .../betta_write_admin.py (symlink)
#   /etc/sudoers.d/nta-betta-write   ONLY with --consent-timestamp-timeout (0440)
#
# HARD RULES HONOURED HERE:
#   * A real installation requires EUID 0; --dry-run prints every action and
#     changes nothing (safe to run unprivileged for review).
#   * The write credential file /var/db/nta-betta-write/shopify.env is NEVER
#     created, read, printed or logged by this installer. The owner provisions
#     it separately with the rotated write secret. Only presence/ownership/mode
#     are inspected, and a file readable by a non-root uid is refused.
#   * Every installed path is absolute and root-owned; the installer refuses a
#     privilege path that is group/other-writable or not owned by root.
#   * Installed code is SHA-256 pinned in version.json; a changed repository
#     file never changes daemon behaviour until a new (sudo) install.
#
# USAGE:
#   sudo deploy/install-trusted-writer.sh [--upgrade] [--consent-timestamp-timeout]
#        deploy/install-trusted-writer.sh --dry-run [--consent-timestamp-timeout]
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
LOG_FILE="/var/log/nta-betta-write.install.log"
PYTHON="/usr/bin/python3"

SCRIPT_DIR="$(cd "$(dirname "$BASH_SOURCE")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCE_DIR="$PROJECT_DIR/scripts"
POLICY_SOURCE="$SCRIPT_DIR/boundary-policy.production.json"
PLIST_TEMPLATE="$SCRIPT_DIR/${SERVICE_LABEL}.plist.template"
SUDOERS_TEMPLATE="$SCRIPT_DIR/nta-betta-write.sudoers.template"

SOURCE_SCRIPTS="betta_write_boundary.py betta_write_daemon.py betta_write_client.py betta_write_admin.py betta_corrections.py"

DRY_RUN=0
UPGRADE=0
CONSENT_SUDOERS=0
PROBLEMS=0
INSTALLED_STATE="fresh"

usage() {
    cat <<'EOF'
usage: sudo install-trusted-writer.sh [--upgrade] [--consent-timestamp-timeout]
       install-trusted-writer.sh --dry-run [--consent-timestamp-timeout]

  --dry-run                    Print every action without changing anything.
                               May run unprivileged; a real install needs root.
  --upgrade                    Replace a previously installed boundary whose
                               files differ from the repository sources.
                               Without this flag, drift is refused.
  --consent-timestamp-timeout  Install the owner-consented sudoers hardening
                               (Defaults:davidlo timestamp_timeout=0) after
                               `visudo -c -f` validation. Without this flag the
                               step is skipped and the residual 5-minute sudo
                               window is recorded.

Never run this automatically from an agent. It is an owner-gated deployment
step; see docs/incident/TRUSTED_WRITE_BOUNDARY_MIGRATION_2026-10-16.md.
EOF
}

# ---------------------------------------------------------------- logging ---#
log() {
    local line
    line="$(date -u +%Y-%m-%dT%H:%M:%SZ) [install] $*"
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

# Fail the real run; record the problem and continue the dry-run plan.
fatal_or_problem() {
    if [ "$DRY_RUN" -eq 1 ]; then
        problem "$@"
        return 0
    fi
    fatal "$@"
}

# Execute (or print) one command. Real failures are fatal.
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

# ----------------------------------------------------------- read helpers ---#
sha256_of() {
    # Empty output when unreadable/absent; never fails the script.
    if [ -f "$1" ]; then
        shasum -a 256 "$1" 2>/dev/null | awk '{print $1}' || true
    fi
    return 0
}

mode_of() {
    stat -f '%Lp' "$1" 2>/dev/null || printf '?'
}

owner_of() {
    stat -f '%Su' "$1" 2>/dev/null || printf '?'
}

is_group_or_other_writable() {
    local sym
    sym="$(stat -f '%Sp' "$1" 2>/dev/null || true)"
    [ -n "$sym" ] || return 1
    if [ "${sym:5:1}" = "w" ]; then return 0; fi
    if [ "${sym:8:1}" = "w" ]; then return 0; fi
    return 1
}

source_path() {
    printf '%s/%s' "$SOURCE_DIR" "$1"
}

differ_gate() {
    # Refuse to replace an installed file with different content unless the
    # owner explicitly asked for an upgrade.
    if [ "$UPGRADE" -eq 1 ]; then
        return 0
    fi
    if [ "$DRY_RUN" -eq 1 ]; then
        problem "$1 (a real run would refuse without --upgrade)"
        return 0
    fi
    fatal "$1 (re-run with --upgrade to replace)"
}

# -------------------------------------------------------------- preflight ---#
require_root() {
    if [ "$(id -u)" -ne 0 ]; then
        if [ "$DRY_RUN" -eq 1 ]; then
            log "NOTE: dry-run as uid $(id -u); no changes will be made. A real installation requires root."
            return 0
        fi
        log "REFUSED: this installer must run as root: sudo $0"
        exit 2
    fi
}

check_file() {
    local kind="$1" path="$2" digest
    if [ ! -e "$path" ]; then
        fatal_or_problem "$kind missing: $path"
        return 0
    fi
    if [ -L "$path" ]; then
        fatal_or_problem "$kind must not be a symlink: $path"
        return 0
    fi
    if [ ! -f "$path" ] || [ ! -s "$path" ]; then
        fatal_or_problem "$kind is not a non-empty regular file: $path"
        return 0
    fi
    digest="$(sha256_of "$path")"
    log "  $kind sha256=$digest"
    log "    path: $path"
}

step1_check_sources() {
    log "step 1/10: verify repository sources and hashes"
    local name
    for name in $SOURCE_SCRIPTS; do
        check_file "source script $name" "$(source_path "$name")"
    done
    check_file "policy source" "$POLICY_SOURCE"
    check_file "plist template" "$PLIST_TEMPLATE"
    check_file "sudoers template" "$SUDOERS_TEMPLATE"

    # The daemon runs on Apple Python 3.9; syntax-check the sources with that
    # exact interpreter before anything is snapshotted root-owned.
    for name in $SOURCE_SCRIPTS; do
        local path
        path="$(source_path "$name")"
        if [ ! -f "$path" ]; then continue; fi
        if ! "$PYTHON" -c 'import ast,sys; ast.parse(open(sys.argv[1], encoding="utf-8").read(), filename=sys.argv[1])' "$path" 2>/dev/null; then
            fatal_or_problem "python syntax check failed under $PYTHON: $path"
        else
            log "  syntax ok ($PYTHON): $name"
        fi
    done

    if [ -f "$PLIST_TEMPLATE" ] && [ -x /usr/bin/plutil ]; then
        if ! /usr/bin/plutil -lint "$PLIST_TEMPLATE" >/dev/null 2>&1; then
            fatal_or_problem "plist template failed plutil -lint: $PLIST_TEMPLATE"
        else
            log "  plist lint ok"
        fi
    fi

    if [ -f "$SUDOERS_TEMPLATE" ] && [ -x /usr/sbin/visudo ]; then
        if ! /usr/sbin/visudo -c -f "$SUDOERS_TEMPLATE" >/dev/null 2>&1; then
            fatal_or_problem "sudoers template failed visudo -c -f: $SUDOERS_TEMPLATE"
        else
            log "  sudoers lint ok (visudo -c -f)"
        fi
    fi
}

step2_preflight() {
    log "step 2/10: preflight (privilege path, existing install, credentials)"
    local dir owner count=0

    for dir in /usr /usr/local /usr/local/libexec /usr/local/bin; do
        if [ -e "$dir" ]; then
            owner="$(owner_of "$dir")"
            if [ "$owner" != "root" ]; then
                problem "privilege path $dir is owned by '$owner' (must be root)"
                count=$((count + 1))
            fi
            if is_group_or_other_writable "$dir"; then
                problem "privilege path $dir is group/other-writable (mode $(mode_of "$dir"))"
                count=$((count + 1))
            fi
        else
            log "  $dir does not exist yet; it will be created root-owned"
        fi
    done
    if [ "$count" -gt 0 ] && [ "$DRY_RUN" -eq 0 ]; then
        fatal "privilege path is not root-secure; fix ownership/modes above and re-run"
    fi

    # Existing install classification: fresh / unchanged / drift.
    if [ ! -e "$INSTALL_ROOT" ]; then
        INSTALLED_STATE="fresh"
        log "  existing install: none (fresh install)"
    else
        local drift=0 name dest installed_policy installed_plist
        for name in $SOURCE_SCRIPTS; do
            dest="$INSTALL_ROOT/$name"
            if [ ! -f "$dest" ]; then
                drift=1
            elif [ "$(sha256_of "$dest")" != "$(sha256_of "$(source_path "$name")")" ]; then
                drift=1
            fi
        done
        if [ ! -f "$INSTALL_ROOT/version.json" ]; then
            drift=1
        fi
        # Policy: only compared when readable (root-only state dir; in a
        # dry-run as a normal user it is expected to be unreadable).
        installed_policy="$(sha256_of "$STATE_ROOT/boundary-policy.json")"
        if [ -n "$installed_policy" ]; then
            if [ "$installed_policy" != "$(sha256_of "$POLICY_SOURCE")" ]; then
                drift=1
            fi
        fi
        if [ "$drift" -eq 0 ]; then
            INSTALLED_STATE="unchanged"
            log "  existing install: identical, version.json present (idempotent re-run)"
        else
            INSTALLED_STATE="upgrade"
            differ_gate "installed boundary differs from the repository sources"
            log "  existing install: drift detected; will replace (upgrade)"
        fi
    fi

    # These two targets are compared regardless of the code-dir state so a
    # foreign file at either path is never silently overwritten.
    local installed_plist
    installed_plist="$(sha256_of "$PLIST_DEST")"
    if [ -n "$installed_plist" ] && [ "$installed_plist" != "$(sha256_of "$PLIST_TEMPLATE")" ]; then
        differ_gate "existing LaunchDaemon plist $PLIST_DEST differs from the template"
    fi

    # Credential file: presence/ownership/mode ONLY. Never read the contents.
    if [ ! -e "$STATE_ROOT/shopify.env" ]; then
        log "  credential: $STATE_ROOT/shopify.env is NOT present"
        log "    Writes will be refused until the owner creates it separately, e.g.:"
        log "      sudo /usr/bin/install -o root -g wheel -m 600 /dev/null $STATE_ROOT/shopify.env"
        log "      then edit it in an editor as root and add the ROTATED write-store settings."
        log "    This installer never creates, reads, prints or logs that file."
    else
        local owner_mode
        owner_mode="$(owner_of "$STATE_ROOT/shopify.env"):$(stat -f '%Sg' "$STATE_ROOT/shopify.env" 2>/dev/null || printf '?')"
        local cred_mode
        cred_mode="$(mode_of "$STATE_ROOT/shopify.env")"
        log "  credential: $STATE_ROOT/shopify.env present (owner=$owner_mode mode=$cred_mode); contents never read"
        if [ "$owner_mode" != "root:wheel" ]; then
            fatal_or_problem "$STATE_ROOT/shopify.env must be root:wheel (fix: sudo chown root:wheel ...; do not print contents)"
        fi
        case "$cred_mode" in
            600|400) ;;
            *)
                fatal_or_problem "$STATE_ROOT/shopify.env mode must be 0600 or stricter (fix: sudo chmod 600 ...; do not print contents)"
                ;;
        esac
    fi
}

# ------------------------------------------------------------------ steps ---#
step3_install_code() {
    log "step 3/10: install boundary code to $INSTALL_ROOT (root:wheel 0755)"
    run "mkdir -p $INSTALL_ROOT" /bin/mkdir -p "$INSTALL_ROOT"
    run "chown root:wheel $INSTALL_ROOT" /usr/sbin/chown root:wheel "$INSTALL_ROOT"
    run "chmod 0755 $INSTALL_ROOT" /bin/chmod 0755 "$INSTALL_ROOT"
    local name
    for name in $SOURCE_SCRIPTS; do
        run "install -m 0755 -o root -g wheel $(source_path "$name") -> $INSTALL_ROOT/$name" \
            /usr/bin/install -m 0755 -o root -g wheel "$(source_path "$name")" "$INSTALL_ROOT/$name"
    done
    if [ "$DRY_RUN" -eq 0 ]; then
        for name in $SOURCE_SCRIPTS; do
            if [ "$(sha256_of "$INSTALL_ROOT/$name")" != "$(sha256_of "$(source_path "$name")")" ]; then
                fatal "installed file hash mismatch after copy: $INSTALL_ROOT/$name"
            fi
        done
        [ "$(owner_of "$INSTALL_ROOT")" = "root" ] || fatal "$INSTALL_ROOT must be root-owned"
        if is_group_or_other_writable "$INSTALL_ROOT"; then
            fatal "$INSTALL_ROOT must not be group/other-writable"
        fi
        log "  verified: installed hashes equal source hashes; directory root-owned, not group/other-writable"
    else
        log "DRY-RUN: would verify installed hashes equal source hashes"
    fi
}

step4_state() {
    log "step 4/10: create/verify state dir $STATE_ROOT (root:wheel 0700) + policy"
    run "mkdir -p $STATE_ROOT" /bin/mkdir -p "$STATE_ROOT"
    run "chown root:wheel $STATE_ROOT" /usr/sbin/chown root:wheel "$STATE_ROOT"
    run "chmod 0700 $STATE_ROOT" /bin/chmod 0700 "$STATE_ROOT"
    local sub
    for sub in corrections authorisations ledger receipts; do
        run "mkdir -p $STATE_ROOT/$sub (0700 root:wheel)" /bin/mkdir -p "$STATE_ROOT/$sub"
        run "chown root:wheel $STATE_ROOT/$sub" /usr/sbin/chown root:wheel "$STATE_ROOT/$sub"
        run "chmod 0700 $STATE_ROOT/$sub" /bin/chmod 0700 "$STATE_ROOT/$sub"
    done
    run "install -m 0644 -o root -g wheel boundary-policy.production.json -> $STATE_ROOT/boundary-policy.json" \
        /usr/bin/install -m 0644 -o root -g wheel "$POLICY_SOURCE" "$STATE_ROOT/boundary-policy.json"
    log "  note: signing.key is generated by the daemon on first start (0600 root), not by this installer"
}

step5_runtime() {
    log "step 5/10: create runtime socket dir $RUN_ROOT (root:wheel 0711)"
    run "mkdir -p $RUN_ROOT" /bin/mkdir -p "$RUN_ROOT"
    run "chown root:wheel $RUN_ROOT" /usr/sbin/chown root:wheel "$RUN_ROOT"
    run "chmod 0711 $RUN_ROOT" /bin/chmod 0711 "$RUN_ROOT"
    log "  note: the daemon re-asserts this directory and its socket ownership/mode at start"
}

step6_plist() {
    log "step 6/10: install LaunchDaemon plist $PLIST_DEST (root:wheel 0644)"
    run "install -m 0644 -o root -g wheel $PLIST_TEMPLATE -> $PLIST_DEST" \
        /usr/bin/install -m 0644 -o root -g wheel "$PLIST_TEMPLATE" "$PLIST_DEST"
    if [ "$DRY_RUN" -eq 0 ]; then
        /usr/bin/plutil -lint "$PLIST_DEST" >/dev/null 2>&1 || fatal "installed plist failed plutil -lint: $PLIST_DEST"
        log "  installed plist lint ok"
    else
        log "DRY-RUN: would lint the installed plist with plutil"
    fi
}

step7_cli() {
    log "step 7/10: install admin CLI symlink $CLI_LINK"
    local target="$INSTALL_ROOT/betta_write_admin.py"
    if [ -L "$CLI_LINK" ]; then
        local existing
        existing="$(readlink "$CLI_LINK" 2>/dev/null || true)"
        if [ "$existing" = "$target" ]; then
            log "  admin CLI symlink already correct: $CLI_LINK -> $target"
            return 0
        fi
        differ_gate "existing $CLI_LINK -> $existing does not match expected $target"
    elif [ -e "$CLI_LINK" ]; then
        fatal_or_problem "$CLI_LINK exists and is not a symlink; refusing to replace"
        return 0
    fi
    run "mkdir -p /usr/local/bin" /bin/mkdir -p /usr/local/bin
    run "ln -sfn $target $CLI_LINK" /bin/ln -sfn "$target" "$CLI_LINK"
    run "chown -h root:wheel $CLI_LINK" /usr/sbin/chown -h root:wheel "$CLI_LINK"
}

step8_sudoers() {
    if [ "$CONSENT_SUDOERS" -ne 1 ]; then
        log "step 8/10: sudoers timestamp hardening SKIPPED (owner consent not given)"
        log "  residual: after any manual sudo, a ~5-minute passwordless sudo window exists (H1 residual)."
        log "  to install later: sudo $0 --upgrade --consent-timestamp-timeout"
        return 0
    fi
    log "step 8/10: install sudoers hardening $SUDOERS_DEST (root:wheel 0440)"
    local includedir_ok=0
    if grep -Eq '^[[:space:]]*#includedir[[:space:]]+/?(private/)?etc/sudoers\.d' /etc/sudoers 2>/dev/null; then
        includedir_ok=1
    elif [ ! -r /etc/sudoers ]; then
        if [ "$DRY_RUN" -eq 1 ]; then
            log "  /etc/sudoers is not readable as uid $(id -u); a real (root) run will verify the includedir"
            includedir_ok=1
        else
            fatal "/etc/sudoers is not readable; cannot verify its includedir"
        fi
    fi
    if [ "$includedir_ok" -ne 1 ]; then
        fatal_or_problem "/etc/sudoers does not include /etc/sudoers.d; refusing to install an unused fragment"
        return 0
    fi
    if [ -f "$SUDOERS_DEST" ] && cmp -s "$SUDOERS_DEST" "$SUDOERS_TEMPLATE"; then
        log "  sudoers hardening already installed and identical: $SUDOERS_DEST"
        return 0
    fi
    if [ -e "$SUDOERS_DEST" ]; then
        differ_gate "sudoers fragment $SUDOERS_DEST exists with different content"
    fi
    if [ "$DRY_RUN" -eq 0 ]; then
        local check_file_path
        check_file_path="$(/bin/mktemp "$STATE_ROOT/.sudoers-check.XXXXXX")"
        /bin/cat "$SUDOERS_TEMPLATE" >"$check_file_path"
        if ! /usr/sbin/visudo -c -f "$check_file_path" >/dev/null 2>&1; then
            /bin/rm -f "$check_file_path"
            fatal "sudoers template failed visudo -c -f"
        fi
        run "install -m 0440 -o root -g wheel sudoers fragment -> $SUDOERS_DEST" \
            /usr/bin/install -m 0440 -o root -g wheel "$check_file_path" "$SUDOERS_DEST"
        /bin/rm -f "$check_file_path"
        /usr/sbin/visudo -c -f "$SUDOERS_DEST" >/dev/null 2>&1 || fatal "installed sudoers fragment failed visudo -c -f"
        log "  sudoers hardening installed and validated"
    else
        log "DRY-RUN: install -m 0440 -o root -g wheel nta-betta-write.sudoers.template -> $SUDOERS_DEST (after visudo -c -f)"
    fi
}

step9_version_json() {
    log "step 9/10: write $INSTALL_ROOT/version.json (sha256 of installed files)"
    if [ "$DRY_RUN" -eq 1 ]; then
        local name
        for name in $SOURCE_SCRIPTS; do
            log "DRY-RUN: version.json entry $name sha256=$(sha256_of "$(source_path "$name")")"
        done
        log "DRY-RUN: version.json entry boundary-policy.json sha256=$(sha256_of "$POLICY_SOURCE")"
        log "DRY-RUN: version.json entry plist sha256=$(sha256_of "$PLIST_TEMPLATE")"
        return 0
    fi
    local git_branch git_commit target tmp installed_at tracked_files
    git_branch="$(git -C "$PROJECT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || printf 'unknown')"
    git_commit="$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null || printf 'unknown')"
    installed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    target="$INSTALL_ROOT/version.json"
    tmp="$target.tmp.$$"
    tracked_files="$INSTALL_ROOT/betta_write_boundary.py $INSTALL_ROOT/betta_write_daemon.py $INSTALL_ROOT/betta_write_client.py $INSTALL_ROOT/betta_write_admin.py $STATE_ROOT/boundary-policy.json $PLIST_DEST"
    if [ "$CONSENT_SUDOERS" -eq 1 ] && [ -f "$SUDOERS_DEST" ]; then
        tracked_files="$tracked_files $SUDOERS_DEST"
    fi
    "$PYTHON" - "$tmp" "$installed_at" "$SERVICE_LABEL" "$PROJECT_DIR" "$git_branch" "$git_commit" \
        $tracked_files "$CONSENT_SUDOERS" <<'PY'
import hashlib
import json
import os
import sys

(target, installed_at, label, project, branch, commit) = sys.argv[1:7]
paths = sys.argv[7:-1]
sudoers_installed = sys.argv[-1] == "1"

files = {}
for path in paths:
    with open(path, "rb") as handle:
        data = handle.read()
    files[os.path.basename(path)] = {
        "path": path,
        "sha256": hashlib.sha256(data).hexdigest(),
    }

record = {
    "schema": "nta-betta-write-install-v1",
    "service_label": label,
    "installed_at": installed_at,
    "installer": "deploy/install-trusted-writer.sh",
    "installer_version": "1",
    "source_project": project,
    "git_branch": branch,
    "git_commit": commit,
    "files": files,
    "sudoers_hardening_installed": sudoers_installed,
}
with open(target, "w", encoding="utf-8") as handle:
    json.dump(record, handle, indent=2, sort_keys=True, ensure_ascii=False)
    handle.write("\n")
os.chmod(target, 0o644)
PY
    run "install -m 0644 -o root -g wheel $tmp -> $target" \
        /usr/bin/install -m 0644 -o root -g wheel "$tmp" "$target"
    /bin/rm -f "$tmp"
    log "  version.json written: $target"
}

step10_load() {
    log "step 10/10: (re)load LaunchDaemon $SERVICE_LABEL"
    if [ "$DRY_RUN" -eq 1 ]; then
        log "DRY-RUN: /bin/launchctl bootout system $PLIST_DEST (ignore failure)"
        log "DRY-RUN: /bin/launchctl bootstrap system $PLIST_DEST"
        log "DRY-RUN: /bin/launchctl print system/$SERVICE_LABEL (expect success)"
        return 0
    fi
    if [ "$INSTALLED_STATE" = "unchanged" ] && /bin/launchctl print "system/$SERVICE_LABEL" >/dev/null 2>&1; then
        log "  daemon already loaded and installed code unchanged; leaving the running instance untouched"
        return 0
    fi
    /bin/launchctl bootout system "$PLIST_DEST" >/dev/null 2>&1 || true
    if ! /bin/launchctl bootstrap system "$PLIST_DEST"; then
        fatal "launchctl bootstrap failed for $PLIST_DEST"
    fi
    if ! /bin/launchctl print "system/$SERVICE_LABEL" >/dev/null 2>&1; then
        fatal "daemon is not registered after bootstrap"
    fi
    log "  daemon loaded; verify with: sudo $CLI_LINK --state-dir $STATE_ROOT status"
}

# ------------------------------------------------------------------- main ---#
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        --upgrade) UPGRADE=1 ;;
        --consent-timestamp-timeout) CONSENT_SUDOERS=1 ;;
        --help|-h) usage; exit 0 ;;
        *) usage >&2; printf 'unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
done

require_root
log "start (dry-run=$DRY_RUN upgrade=$UPGRADE consent_timestamp_timeout=$CONSENT_SUDOERS uid=$(id -u))"

step1_check_sources
step2_preflight
step3_install_code
step4_state
step5_runtime
step6_plist
step7_cli
step8_sudoers
step9_version_json
step10_load

if [ "$DRY_RUN" -eq 1 ]; then
    if [ "$PROBLEMS" -gt 0 ]; then
        log "DRY RUN finished with $PROBLEMS problem(s); NO changes were made."
        exit 1
    fi
    log "DRY RUN complete — every action printed above; NO changes were made. A real installation requires root."
    exit 0
fi

if [ -e "$STATE_ROOT/disabled" ]; then
    log "WARNING: $STATE_ROOT/disabled exists — the boundary refuses all writes until: sudo $CLI_LINK --state-dir $STATE_ROOT enable"
fi
log "install complete (state=$INSTALLED_STATE). Next: sudo $CLI_LINK --state-dir $STATE_ROOT status; then follow docs/incident/TRUSTED_WRITE_BOUNDARY_MIGRATION_2026-10-16.md"
exit 0
