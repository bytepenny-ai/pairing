# New pAIring server: checklist

From a freshly installed Debian/Ubuntu server to a working pAIring: the first one, or one joining existing pAIring
servers. Two parts, each run by its own user:

- **root**, once, by an admin: [scripts/bootstrap_server.sh](../scripts/bootstrap_server.sh) (packages, user, service).
- **pairing**, no root: [scripts/setup_server.sh](../scripts/setup_server.sh) (asks first or joining, installs, starts).

## Before you start

- [ ] Debian 12/13 or Ubuntu, nothing else on it, a root login (`su -`). It reaches the internet.
- [ ] A CPU with x86-64-v2 (SSE4.2, POPCNT); the script checks it first. A VM's generic CPU model lacks it and pAIring dies with "illegal instruction": with KVM give it the host's CPU (`virt-xml <vm> --edit --cpu host-passthrough`); without KVM (no `/dev/kvm`: VT-x off in the BIOS, emulated and slow) use `--cpu Nehalem,clearxml=yes`.
- [ ] Time: about 30 minutes on a 1-CPU server (mostly installing the Python packages).
- [ ] Joining existing pAIring servers: prepare them first (section 3), then have at hand
  - [ ] the MySQL host, port, database, and a MySQL user allowed from the new server, with its password
  - [ ] the `SECRET_KEY` from another server's `.env`
  - The Matricxon API key and admin secret are not needed: they come from the shared database.

## 1. As root: `bootstrap_server.sh`

```bash
wget https://raw.githubusercontent.com/bytepenny-ai/pairing/main/scripts/bootstrap_server.sh
bash bootstrap_server.sh
```

- [ ] Package sources: a DVD install's `cdrom:` source is switched off and Debian's online sources are added.
- [ ] An install stopped half way is finished (`dpkg --configure -a`), then every package pAIring needs, including the
      NFS and MySQL clients for joining, so nothing needs root later.
- [ ] The `pairing` user (no password). `SSH_KEY="ssh-ed25519 ..."` also lets that key log in as it.
- [ ] pAIring cloned into `/opt/pairing` as `pairing`, from GitHub or `REPO_URL=...` (your own repository). That
      stays its update source: Cluster → Servers → Update all pulls from there, so it must stay reachable.
- [ ] `pairing.service`, enabled (starts after the network and the shared folders), not started yet.
- [ ] A sudo rule: `pairing` may start, stop and restart `pairing.service`, nothing else; it can read the system log.
- [ ] Asks whether this server joins existing pAIring servers. Yes: asks for the NFS export (`server:/path`) and the
      mount point (the same path as on the other servers), writes the `/etc/fstab` line (with
      `x-systemd.automount`: mounted on first use, so a slow network at boot cannot leave it unmounted) and mounts
      it, showing the folders it found. No: nothing to mount.

## 2. As pairing: `setup_server.sh`

```bash
su - pairing                # or log in as pairing
cd /opt/pairing && bash scripts/setup_server.sh
```

- [ ] Asks: 1) the first pAIring, or 2) joining existing pAIring servers.
- Joining only (each is checked; on a problem it says what to fix and offers to try again):
  - [ ] **MySQL**: connects, finds running pAIring servers, and the same version as this clone (pAIring migrates the
        database when it starts, so a newer server would change it under the older ones).
  - [ ] **pAIring SECRET_KEY**: the same as the other pAIring servers' (compared by fingerprint; it is never shown).
  - [ ] **Shared folders**: the other servers keep the 4 folders on shared storage, and this server sees the same
        folders at the same paths (their share markers match) and `pairing` can write to them. Not mounted yet: an
        admin mounts it, then answer "try again".
  - [ ] **Matricxon**: every node in the shared settings is reachable from here (not `localhost`).
  - [ ] **Local instances**: this server gets its own count, 1 (unless it already had one); raise it on its own
        Settings → System page.
  - [ ] `.env` written: `DATABASE_URL`, `SECRET_KEY`, the 4 folders, `MATRICXON_AUTOSTART=false`.
- [ ] `scripts/install.sh`: venv, packages, `.env` (a new `SECRET_KEY` only for a first pAIring), the database.
- [ ] `sudo systemctl restart pairing`, then pAIring answers on port 8000 (the first start can take minutes).

## 3. Preparing the existing servers (joining only, once)

- [ ] MySQL accepts the new server: listens on the network, port open, a user for it, e.g.
      `CREATE USER 'pairing'@'10.0.0.%' IDENTIFIED BY '...'; GRANT ALL ON pairing_db.* TO 'pairing'@'10.0.0.%';`
- [ ] The 4 folders (knowledge, attachments, avatars, images) on an NFS export, at the same path on every server
      (Cluster → Servers → This server). The export allows the new server; with different user ids, map them:
      `all_squash,anonuid=<owner uid>,anongid=<owner gid>`, e.g. in `/etc/exports`:
      `/srv/shared 10.0.0.0/24(rw,sync,no_subtree_check,all_squash,anonuid=1000,anongid=1000)`, then `exportfs -ra`.
- [ ] On the new server it is mounted by `bootstrap_server.sh` (section 1). By hand, the `/etc/fstab` line is
      `10.0.0.2:/srv/shared  /mnt/shared  nfs4  defaults,_netdev,nofail,x-systemd.automount  0 0`, then
      `systemctl daemon-reload && mkdir -p /mnt/shared && systemctl restart remote-fs.target`.
- [ ] Matricxon nodes stored by an address every server reaches (Cluster page), not `localhost`, and each node
      advertises that address (`MATRICXON_ADVERTISE_URL` in its `.env`). A node that started without it records the
      address it found itself (e.g. a Wi-Fi address): set it, restart the node, then on the Cluster page open the node
      and press **Update its address**.
- [ ] Every server runs the version the new one will clone (update and restart them first).

## 4. In the browser (`http://<server>:8000`)

- First pAIring: log in as `admin` / `admin`, then Settings → Account → **Update password**.
  - [ ] Settings → Inference → Engine: install and choose llama.cpp or Matricxon; then Settings → Models.
  - To use an existing Matricxon cluster instead: Cluster → **Join an existing cluster** (node address, cluster id,
    admin secret), then Cluster → **API key**.
- Joining: log in with your existing account (the users are shared).
  - [ ] Cluster → Servers: the new server is listed with its IP addresses, its key and folder checks green.
  - Image generation, with more than one server on the database: its engine (stable-diffusion.cpp) runs only in
    **remote** mode there, one image server every pAIring reaches, not `localhost` (Inference → Engine; set once,
    shared by all).
    In local mode it is off on every server (the Images Gen link shows **Off**); a local engine is stopped on
    every server (not uninstalled).

## 5. Check

- [ ] `systemctl status pairing` is active; it also starts after a reboot (and the NFS mount comes back).
- [ ] A test chat gets a reply.

## If something fails

| What you see | What to do |
|---|---|
| `The repository 'cdrom://...' does not have a Release file` | Run the script again: it switches the DVD source off. |
| `dpkg was interrupted, you must manually run 'dpkg --configure -a'` | An earlier run stopped mid-install. Run the script again: it finishes that first. |
| `apt is already running` | Another install or the automatic updates: wait for it, then run the script again. |
| `Cannot read the database: ... Access denied` / `Can't connect` | The MySQL user is not allowed from this server, or the port is closed (section 3). |
| `(1044, "Access denied for user ... to database ...")` | Logged in, but that MySQL account (`user@host`, e.g. `root@'%'`, not the same as `root@localhost`) has no rights on the database: `GRANT ALL PRIVILEGES ON pairing_db.* TO 'user'@'10.0.0.%'; FLUSH PRIVILEGES;` |
| `status=4/ILL` (illegal instruction) in `journalctl -u pairing`, or `This CPU lacks SSE4.2/POPCNT` | The (virtual) CPU is too old a model: `virt-xml <vm> --edit --cpu host-passthrough` (KVM) or `--cpu Nehalem,clearxml=yes` (no KVM), then restart the VM. |
| `host-passthrough ... not supported` when starting the VM | No KVM on the host (no `/dev/kvm`; enable VT-x/AMD-V in the BIOS), so only emulated CPU models work: `--cpu Nehalem,clearxml=yes`. |
| `Permission denied: '/mnt/shared/...'` at start, or `mount.nfs4: Network is unreachable` in the boot log | The share was mounted before the network was up, so pAIring found an empty local folder: add `x-systemd.automount` to its `/etc/fstab` options, `systemctl daemon-reload`, then `systemctl restart remote-fs.target pairing`. |
| Update all: `fatal: unable to access '<url>'` | The server pulls from the repository it was cloned from (`REPO_URL`): make it reachable, or point it elsewhere: `git -C /opt/pairing remote set-url origin <url>` (as pairing). |
| `dpkg: warning: 'ldconfig' not found in PATH` | Root through `su` without `-` (the user's PATH): use `su -`. The script now sets root's PATH itself. |
| `Version mismatch` | Best: update the existing servers (or this clone) to the same commit. It asks whether to go on: only if both versions share the database schema. |
| `Not on shared storage on the other servers yet` | Move their 4 folders to the NFS export first (section 3). |
| `Not the other servers' folders` | The shared storage is not mounted here, or at another path: `findmnt -t nfs4`. |
| `mount.nfs4: access denied` | The export does not list this server (`/etc/exports`, then `exportfs -ra` there). |
| `/etc/fstab: parse error` or `unknown filesystem type ...(rw,sync,...)` | An `/etc/exports` line went into `/etc/fstab`: exports go on the server sharing the folder, fstab gets only `host:/path  /mnt/point  nfs4  defaults,_netdev,nofail  0 0`. |
| `pairing cannot write to ...` | Different user ids: export with `all_squash,anonuid=...,anongid=...`. |
| `'localhost' is the server itself here` | On the Cluster page, store the nodes by an address every server reaches. |
| Service fails to start | `journalctl -u pairing -n 50` (as pairing too, after logging in again) |
| `may not restart pairing.service` / `No pairing.service yet` | The root part has not run (or an older one): an admin runs `bootstrap_server.sh` again. |
| `Run this as the pairing user, not root` | `su - pairing`, then `cd /opt/pairing && bash scripts/setup_server.sh`. |
