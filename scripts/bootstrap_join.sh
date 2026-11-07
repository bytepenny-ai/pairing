# Sourced by setup_server.sh (as pairing, no root) when this server joins existing pAIring servers: asks for and checks
# the shared MySQL, the SECRET_KEY, the shared folders and the Matricxon engine, then writes pAIring's .env.
# The shared folders are not mounted here: an admin mounts them first (e.g. NFS in /etc/fstab), at the same paths as on
# the other servers. Packages come from bootstrap_server.sh. Uses step/info/success/warn/die/ask from setup_server.sh;
# the checks are in bootstrap_checks.py.

CHECKS=(python3 -I "$APP_DIR/scripts/bootstrap_checks.py")
ENV_FILE="$APP_DIR/.env"

# Sets KEY=value in pAIring's .env, replacing an earlier line.
set_env() {
    if [ ! -f "$ENV_FILE" ]; then
        (umask 077 && cp "$APP_DIR/.env.example" "$ENV_FILE")
    fi
    sed -i "/^$1=/d" "$ENV_FILE"
    printf '%s=%s\n' "$1" "$2" >> "$ENV_FILE"
}

step "J1. The shared MySQL database"
info "The database the other pAIring servers use (their .env: DATABASE_URL)."
while true; do
    ask DB_HOST "MySQL host" "${DB_HOST:-}"
    ask DB_PORT "MySQL port" "${DB_PORT:-3306}"
    ask DB_NAME "Database name" "${DB_NAME:-pairing_db}"
    ask DB_USER "MySQL user (one allowed from this server)" "${DB_USER:-pairing}"
    ask_secret DB_PASS "MySQL password"
    export DB_HOST DB_PORT DB_NAME DB_USER DB_PASS
    status=0
    "${CHECKS[@]}" db "$(git -C "$APP_DIR" rev-parse --short HEAD)" || status=$?
    if [ "$status" = 0 ]; then
        success "Connected: a running pAIring database, same version."
        break
    fi
    if [ "$status" = 3 ]; then
        info "Best: update the servers (or this clone) to the same version first."
        confirm "Go on anyway (only if you know the two versions share the database schema)?" \
            || die "Stopped at the version check; nothing was changed in pAIring."
        warn "Going on with different versions."
        break
    fi
    warn "Fix it, or on the database server: allow this user from $(hostname -I | awk '{print $1}') and open port $DB_PORT."
    confirm "Try again?" || die "Stopped at the database check; nothing was changed in pAIring."
done

step "J2. pAIring SECRET_KEY (the same on every pAIring server)"
info "Copy it from another pAIring server's .env (SECRET_KEY=...). It decrypts the stored Matricxon API key and admin secret."
while true; do
    ask_secret SECRET_KEY "pAIring SECRET_KEY"
    export SECRET_KEY
    if "${CHECKS[@]}" secret; then success "Same key as the other servers."; break; fi
    confirm "Try again?" || die "Stopped at the pAIring SECRET_KEY check."
done

step "J3. Shared folders"
if ! FOLDER_LINES="$("${CHECKS[@]}" folders)"; then
    printf '%s\n' "$FOLDER_LINES" | sed 's/^/    /'
    die "Put those folders on shared storage on the other servers first (Cluster > Servers > This server)."
fi
printf '%s\n' "$FOLDER_LINES" | sed 's/^/    /'
info "This server needs the same folders at the same paths (the shared storage mounted here, e.g. NFS in /etc/fstab)."
until "${CHECKS[@]}" markers; do
    findmnt -t nfs,nfs4 -o TARGET,SOURCE | sed 's/^/    mounted: /'
    confirm "Mount the shared storage there, then try again?" || die "Stopped at the shared folders check."
done
success "The same folders as the other servers (their share markers match)."
while IFS='=' read -r name path; do
    if ! { touch "$path/.bootstrap_test" && rm "$path/.bootstrap_test"; } 2> /dev/null; then
        die "$(id -un) cannot write to $path. Export it with all_squash,anonuid=<owner uid>,anongid=<owner gid>."
    fi
    set_env "$name" "$path"
done <<< "$FOLDER_LINES"
success "$(id -un) can write to all of them."

step "J4. Matricxon engine (from the shared settings)"
info "The API key and admin secret come from the shared database: nothing to enter."
if ! "${CHECKS[@]}" matricxon; then
    warn "Chats sent to a node marked above would fail from this server."
    confirm "Continue anyway (fix it on the Cluster page later)?" || die "Stopped at the Matricxon check."
fi

step "J5. Local instances of this server"
"${CHECKS[@]}" instances "$(hostname)" || die "Stopped: could not save this server's instance count."

step "J6. Writing $ENV_FILE"
set_env DATABASE_URL "$("${CHECKS[@]}" url)"
set_env SECRET_KEY "$SECRET_KEY"
set_env MATRICXON_AUTOSTART false
chmod 600 "$ENV_FILE"
unset DB_PASS SECRET_KEY
success "Database, pAIring SECRET_KEY and the 4 folders set; no local Matricxon is started."
