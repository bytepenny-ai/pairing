#!/usr/bin/env bash
# The root part of a new pAIring server, run once by an admin on a fresh Debian/Ubuntu server: package sources, every
# package pAIring needs (also for joining other servers: NFS, MySQL clients), the "pairing" user, a clone of pAIring as
# that user, its systemd service (enabled, not started), a sudo rule letting pairing start/stop/restart only that
# service and, for a server joining others, the shared folders (NFS). Everything after this runs as pairing, without
# root: scripts/setup_server.sh.
# Checklist: docs/new_server_checklist.md
#
# As root:
#   wget https://raw.githubusercontent.com/bytepenny-ai/pairing/main/scripts/bootstrap_server.sh
#   bash bootstrap_server.sh
#
# Options (environment): SSH_KEY="ssh-ed25519 AAAA..." or SSH_KEY_URL=... lets that key log in as pairing;
# REPO_URL, INSTALL_DIR (/opt/pairing), APP_PORT (8000). Safe to re-run.

set -euo pipefail

step()    { printf '\n\033[1;34m==>\033[0m %s\n' "$1"; }
info()    { printf '    %s\n' "$1"; }
success() { printf '\033[1;32m  ✓\033[0m %s\n' "$1"; }
warn()    { printf '\033[1;33m  ! \033[0m%s\n' "$1"; }
die()     { printf '\033[1;31mError:\033[0m %s\n' "$1" >&2; exit 1; }
# ask VAR "question": a non-empty answer from the terminal.
ask() {
    local answer=""
    while [ -z "$answer" ]; do read -r -p "    $2: " answer < /dev/tty; done
    printf -v "$1" '%s' "$answer"
}
confirm() { local a; read -r -p "    $1 [y/N] " a < /dev/tty; [[ "$a" == [Yy]* ]]; }

REPO_URL="${REPO_URL:-https://github.com/bytepenny-ai/pairing.git}"
INSTALL_DIR="${INSTALL_DIR:-/opt/pairing}"
APP_PORT="${APP_PORT:-8000}"
APP_USER="pairing"

[ "$(id -u)" -eq 0 ] || die "Run as root ('su -' first)."
# `su` without "-" keeps the user's PATH, without the sbin folders dpkg and useradd need.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"
grep -qiE 'debian|ubuntu' /etc/os-release 2>/dev/null || die "This script is for Debian/Ubuntu."
# Current Python wheels (numpy and others) need x86-64-v2; a VM's generic CPU model lacks it and pAIring then dies
# with "illegal instruction" (status=4/ILL) only after the whole install.
if [ "$(uname -m)" = x86_64 ] && ! { grep -qw sse4_2 /proc/cpuinfo && grep -qw popcnt /proc/cpuinfo; }; then
    die "This CPU lacks SSE4.2/POPCNT (x86-64-v2), which pAIring's packages need. On a VM, give it a newer CPU model and restart it: with KVM virt-xml <vm> --edit --cpu host-passthrough; without KVM (emulated) --cpu Nehalem,clearxml=yes."
fi

step "1. Package sources and basic packages"
# A DVD install leaves only the DVD as a package source: switch it off and add Debian's online sources.
if grep -qs '^deb cdrom:' /etc/apt/sources.list; then
    sed -i 's/^deb cdrom:/# deb cdrom:/' /etc/apt/sources.list
    info "Switched off the install DVD as a package source."
fi
if grep -qi '^ID=debian' /etc/os-release && ! grep -rqsE '^[^#]*(deb\.debian\.org|ftp\.[a-z.]*debian\.org|security\.debian\.org)' \
        /etc/apt/sources.list /etc/apt/sources.list.d/; then
    CODENAME="$(. /etc/os-release && echo "$VERSION_CODENAME")"
    cat > /etc/apt/sources.list.d/debian.sources << EOF
Types: deb
URIs: http://deb.debian.org/debian
Suites: $CODENAME $CODENAME-updates
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: http://security.debian.org/debian-security
Suites: $CODENAME-security
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
EOF
    success "Added Debian's online package sources ($CODENAME)."
fi
if pgrep -x 'apt|apt-get|dpkg|unattended-upgr' > /dev/null; then
    die "apt is already running (another install, or automatic updates). Wait for it, then re-run."
fi
# An earlier run stopped mid-install leaves dpkg half done: finish it first.
DEBIAN_FRONTEND=noninteractive dpkg --configure -a
apt-get update -qq
# Everything a later join needs too (NFS, MySQL driver and client), so no root step is left after this script.
apt-get install -y -qq sudo git curl ca-certificates rsync python3 python3-venv python3-pip cmake build-essential \
    nfs-common default-mysql-client python3-pymysql python3-cryptography > /dev/null
success "Installed sudo, git, curl, python3 (+venv, pip), build tools, NFS and MySQL clients."

step "2. The $APP_USER user"
if id "$APP_USER" > /dev/null 2>&1; then
    info "$APP_USER already exists."
else
    useradd --create-home --shell /bin/bash "$APP_USER"
    success "Created $APP_USER (no password, no sudo)."
fi
[ -z "${SSH_KEY:-}" ] && [ -n "${SSH_KEY_URL:-}" ] && SSH_KEY="$(curl -fsS -m 8 "$SSH_KEY_URL")"
if [ -n "${SSH_KEY:-}" ]; then
    HOME_DIR="$(getent passwd "$APP_USER" | cut -d: -f6)"
    install -d -m 700 -o "$APP_USER" -g "$APP_USER" "$HOME_DIR/.ssh"
    touch "$HOME_DIR/.ssh/authorized_keys"
    grep -qxF "$SSH_KEY" "$HOME_DIR/.ssh/authorized_keys" || echo "$SSH_KEY" >> "$HOME_DIR/.ssh/authorized_keys"
    chown "$APP_USER":"$APP_USER" "$HOME_DIR/.ssh/authorized_keys"
    chmod 600 "$HOME_DIR/.ssh/authorized_keys"
    success "SSH key allowed for $APP_USER."
fi

step "3. Getting pAIring into $INSTALL_DIR (as $APP_USER)"
install -d -o "$APP_USER" -g "$APP_USER" "$INSTALL_DIR"
if [ -d "$INSTALL_DIR/.git" ]; then
    sudo -u "$APP_USER" git -C "$INSTALL_DIR" pull --ff-only --quiet
    success "Updated the existing checkout ($(sudo -u "$APP_USER" git -C "$INSTALL_DIR" rev-parse --short HEAD))."
elif [ -n "$(ls -A "$INSTALL_DIR")" ]; then
    die "$INSTALL_DIR holds files that are not a git checkout. Move them away or set INSTALL_DIR."
else
    sudo -u "$APP_USER" git clone --quiet "$REPO_URL" "$INSTALL_DIR"
    success "Cloned $REPO_URL ($(sudo -u "$APP_USER" git -C "$INSTALL_DIR" rev-parse --short HEAD))."
fi

step "4. The systemd service (enabled, started later by $APP_USER)"
SERVICE_FILE="/etc/systemd/system/pairing.service"
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=pAIring — on-prem multi-user chat UI for local models
After=network-online.target remote-fs.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$INSTALL_DIR
Environment="APP_PORT=$APP_PORT"
ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/run.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable pairing > /dev/null 2>&1
success "Created and enabled pairing.service (After=remote-fs: shared folders are mounted first)."

step "5. Letting $APP_USER run its own service"
SUDOERS="/etc/sudoers.d/pairing"
SYSTEMCTL="$(command -v systemctl)"
printf '%s ALL=(root) NOPASSWD: %s start pairing, %s stop pairing, %s restart pairing\n' \
    "$APP_USER" "$SYSTEMCTL" "$SYSTEMCTL" "$SYSTEMCTL" > "$SUDOERS.tmp"
chmod 440 "$SUDOERS.tmp"
visudo -cf "$SUDOERS.tmp" > /dev/null || die "The sudo rule did not validate; nothing was changed."
mv "$SUDOERS.tmp" "$SUDOERS"
usermod -aG systemd-journal "$APP_USER"
success "$APP_USER may start/stop/restart pairing.service (nothing else) and read the system log."

step "6. Shared folders (only for a server joining existing pAIring servers)"
# Joining servers share 4 folders over NFS, mounted at the same path as on the others; it needs root, so it is done
# here. setup_server.sh then checks they are the other servers' folders. No terminal: skipped.
if [ -r /dev/tty ] && confirm "Will this server join existing pAIring servers (shared database and folders)?"; then
    info "The NFS export holding them, e.g. 10.0.0.2:/srv/pairing, and where the other servers mount it."
    ask NFS_EXPORT "NFS export (server:/path)"
    ask NFS_MOUNT "Mount it at (the same path as on the other servers)"
    sed -i "\# $NFS_MOUNT nfs#d" /etc/fstab
    echo "$NFS_EXPORT $NFS_MOUNT nfs4 defaults,_netdev,nofail,x-systemd.automount 0 0" >> /etc/fstab
    systemctl daemon-reload
    mkdir -p "$NFS_MOUNT"
    systemctl restart remote-fs.target
    if ls "$NFS_MOUNT"/ > /dev/null 2>&1 && findmnt -t nfs4 "$NFS_MOUNT" > /dev/null; then
        success "Mounted $NFS_EXPORT at $NFS_MOUNT (in /etc/fstab, mounted on first use after a reboot): $(ls "$NFS_MOUNT" | tr '\n' ' ')"
    else
        warn "Could not mount $NFS_EXPORT: check that its server exports it to this one (/etc/exports there)."
        info "The line is in /etc/fstab; once fixed: systemctl restart remote-fs.target && ls $NFS_MOUNT"
    fi
else
    info "Skipped: a first pAIring needs no shared folders."
fi

step "Done: the rest runs as $APP_USER, without root"
cat << EOF

    su - $APP_USER                     # or log in as $APP_USER (SSH key)
    cd $INSTALL_DIR && bash scripts/setup_server.sh

It asks whether this is the first pAIring or one joining existing pAIring servers, and installs pAIring.
EOF
