#!/usr/bin/env bash
# The pairing-user part of a new pAIring server, after an admin ran scripts/bootstrap_server.sh as root. No root needed:
# asks whether this is the first pAIring or one joining existing pAIring servers (then checks the shared MySQL, the
# SECRET_KEY, the shared folders and the Matricxon engine: scripts/bootstrap_join.sh), installs pAIring
# (scripts/install.sh) and starts its service. Checklist: docs/new_server_checklist.md
#
# As pairing:
#   cd /opt/pairing && bash scripts/setup_server.sh
#
# Safe to re-run.

set -euo pipefail

step()    { printf '\n\033[1;34m==>\033[0m %s\n' "$1"; }
info()    { printf '    %s\n' "$1"; }
success() { printf '\033[1;32m  ✓\033[0m %s\n' "$1"; }
warn()    { printf '\033[1;33m  ! \033[0m%s\n' "$1"; }
die()     { printf '\033[1;31mError:\033[0m %s\n' "$1" >&2; exit 1; }
# ask VAR "question" [default]: a non-empty answer from the terminal.
ask() {
    local answer=""
    while [ -z "$answer" ]; do
        read -r -p "    $2${3:+ [$3]}: " answer < /dev/tty
        answer="${answer:-${3:-}}"
    done
    printf -v "$1" '%s' "$answer"
}
# ask_secret VAR "question": like ask, not shown on screen.
ask_secret() {
    local answer=""
    while [ -z "$answer" ]; do
        read -r -s -p "    $2: " answer < /dev/tty
        echo
    done
    printf -v "$1" '%s' "$answer"
}
confirm() { local a; read -r -p "    $1 [y/N] " a < /dev/tty; [[ "$a" == [Yy]* ]]; }

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_PORT="$(sed -n 's/^Environment="APP_PORT=\([0-9]*\)"/\1/p' /etc/systemd/system/pairing.service 2>/dev/null)"
APP_PORT="${APP_PORT:-8000}"

[ "$(id -u)" -ne 0 ] || die "Run this as the pairing user, not root: su - pairing"
[ -r /dev/tty ] || die "Run it from a terminal: it asks a few questions."
[ -O "$APP_DIR/run.py" ] || die "$APP_DIR belongs to another user: run this as its owner."
[ -f /etc/systemd/system/pairing.service ] || die "No pairing.service yet: an admin runs scripts/bootstrap_server.sh first."
sudo -n -l "$(command -v systemctl)" restart pairing > /dev/null 2>&1 \
    || die "$(id -un) may not restart pairing.service: an admin runs scripts/bootstrap_server.sh first."

step "1. First pAIring, or joining existing ones?"
info "1) The first pAIring here: a single install, nothing shared."
info "2) Joins existing pAIring servers: the same MySQL database, shared folders and Matricxon engine."
info "   Have at hand: the MySQL details, the SECRET_KEY of the other servers, and the shared folders mounted here."
ask SETUP "Choose 1 or 2" "1"
[[ "$SETUP" == [12] ]] || die "Choose 1 or 2."

if [ "$SETUP" = 2 ]; then
    step "2. Joining the existing pAIring servers"
    # shellcheck source=bootstrap_join.sh
    source "$APP_DIR/scripts/bootstrap_join.sh"
else
    step "2. A single pAIring: nothing to join"
fi

step "3. Installing pAIring (venv, packages, .env, database)"
info "This takes a while on a small server (about 20 minutes on 1 CPU)."
# No terminal on stdin: install.sh asks nothing and does not start pAIring itself (the service does).
bash "$APP_DIR/scripts/install.sh" < /dev/null

step "4. Starting pairing.service"
sudo -n systemctl restart pairing
info "The first start can take a few minutes on a small server."
for _ in $(seq 1 60); do  # up to 5 minutes
    curl -s -o /dev/null -m 3 "http://127.0.0.1:$APP_PORT/" && break
    systemctl is-failed --quiet pairing && break
    sleep 5
done
curl -s -o /dev/null -m 3 "http://127.0.0.1:$APP_PORT/" \
    || die "pAIring does not answer on port $APP_PORT: journalctl -u pairing -n 50"
success "pAIring answers on port $APP_PORT."

IP="$(hostname -I | awk '{print $1}')"
echo
echo "Next, in the browser at http://$IP:$APP_PORT (see docs/new_server_checklist.md):"
if [ "$SETUP" = 2 ]; then
    echo "  1. Log in with your existing account (the users are shared)."
    echo "  2. Cluster > Servers: this server is listed, with green checks for the key and the 4 folders."
    echo "  3. Send a test chat from this server."
else
    echo "  1. Log in as admin / admin, then Settings > Account > Update password."
    echo "  2. Settings > Inference engines: install and choose an engine, then Settings > Models."
    echo "     (To use an existing Matricxon cluster instead: Cluster > Join an existing cluster.)"
fi
echo "Logs: journalctl -u pairing -f    Restart: sudo systemctl restart pairing"
