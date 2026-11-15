Synology NAS setup
===================

This document explains how to run the Cyno Studio project on a Synology NAS (DSM). It covers prerequisites, recommended paths and permissions, how to start the compose project (so the required network/device capabilities are preserved), and how to make the stack start automatically on boot using the included `synology-boot.sh` helper.

Prerequisites
-------------
- A Synology NAS running DSM 7.x (instructions assume DSM 7, adapt where needed).
- Docker package installed (and the Docker "compose" CLI or plugin available). If your NAS does not provide `docker compose`, you can run the compose v2 plugin or use Portainer to manage stacks.
- SSH access enabled (Control Panel → Terminal & SNMP → Enable SSH) so you can run `docker compose` from the shell. Many advanced options used here (device mapping, capabilities, network_mode) are not fully supported via DSM's GUI.
- Sufficient privileges. You will create a scheduled task that runs as root (the `synology-boot.sh` requires root to modify system nginx and run docker compose).

High-level notes about this project
-----------------------------------
- The compose stack relies on a VPN/proxy container (`gluetun`) that requires NET_ADMIN capabilities and access to `/dev/net/tun`. To ensure the stack can create the virtual tun device and apply network capabilities, start the stack from the Synology shell or use an automated boot script that runs at system start as root.
- The `app` container runs as the UID/GID set by `PUID` and `PGID` in your `.env` file. Set these to match the owner of your host data directory. Run `id` on the NAS shell to find your values.

Recommended install path
------------------------
Choose a directory on your NAS to hold the compose project. This README uses `/path/to/cyno-studio` as a placeholder — replace it with whatever path you choose. Example layout:

- Project root: /path/to/cyno-studio
- Compose file: /path/to/cyno-studio/docker-compose.yml
- Data dir (container mapping target): /path/to/cyno-studio/data

Create project folder and copy files
-----------------------------------
1. SSH into your NAS as an admin user (or root if you prefer):

```bash
ssh admin@your-nas.local
sudo -i
```

2. Create directories and copy the repository contents into the chosen folder. Example (adjust to how you transfer the repository):

```bash
mkdir -p /path/to/cyno-studio
cd /path/to/cyno-studio
# copy the repo files here (scp, git clone, rsync, etc.)
```

3. Ensure the host data directory exists and set ownership to match the UID/GID you will put in `.env` as `PUID`/`PGID`:

```bash
mkdir -p /path/to/cyno-studio/data
# Run `id` to find your UID and GID, then:
chown -R <PUID>:<PGID> /path/to/cyno-studio/data
```

Environment variables
---------------------
Create a `.env` file in the compose folder (same directory as `docker-compose.yml`) and set at minimum the environment variables referenced by the compose file. Example `.env`:

```env
# Auth: admins log in with email + password; everyone else via OAuth.
# Fail-closed — with none of these set, only admins get in.
ADMIN_EMAILS=you@gmail.com
# ALLOWED_EMAILS=friend@x.com
# OPEN_SIGNUP=false
SESSION_SECRET=a_long_random_string
# Set these once, never change them.
PASSWORD_PEPPER=a_long_random_string
KEYS_SECRET=a_long_random_string

# OAuth (optional): public https host + provider credentials
PUBLIC_BASE_URL=https://your-host.synology.me
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=

# Provider keys (Pollo/OpenRouter/Venice) are entered per-user in the app, not here.
CYNO_DATA_DIR=/data

# Host port the app is exposed on
APP_PORT=8080

# Hostname of the DSM reverse proxy rule, also used for the HTTPS redirect (see "HTTPS reverse proxy" below and synology-boot.sh)
APP_HOSTNAME=your-hostname.local

# Container user (run `id` on your NAS shell)
PUID=1000
PGID=1000

# Host data path
CYNO_HOST_DATA_DIR=/path/to/cyno-studio/data

# VPN (Gluetun)
VPN_SERVICE_PROVIDER=your_vpn_provider
VPN_TYPE=wireguard
WIREGUARD_PRIVATE_KEY=your_wireguard_key_here
WIREGUARD_ADDRESSES=10.x.x.x/16
SERVER_COUNTRIES=your_country
GLUETUN_API_KEY=your_gluetun_api_key_here
TZ=UTC
```

Copy `.env.example` as a starting point — it documents every variable.

Note: `CYNO_HOST_DATA_DIR` is used in the compose mapping; in the compose file it is mounted as `${CYNO_HOST_DATA_DIR}:/data`. Set this to the absolute host path you want to use before starting the stack via the shell. If you want to keep the project portable, you can export the environment variable before calling `docker compose`:

```bash
export CYNO_HOST_DATA_DIR=/path/to/cyno-studio/data
docker compose up -d
```

Starting the stack manually (recommended for first run)
-----------------------------------------------------
Set `COMPOSE_PROFILES` in `.env` before starting:

- `COMPOSE_PROFILES=novpn` — direct, no VPN (default)
- `COMPOSE_PROFILES=vpn` — all traffic routed through gluetun

Then from the Synology shell in the project folder:

```bash
cd /path/to/cyno-studio
docker compose pull
docker compose up -d
```

Important: The VPN profile requires `/dev/net/tun` and NET_ADMIN capability. Start from the shell as root — the DSM GUI may block these settings causing gluetun to fail.

Database migrations run automatically on every container start (`entrypoint.sh` runs `alembic upgrade head`), so there is no manual migration step — just start the stack.

Important (upgrading an existing single-user install): set `ADMIN_EMAILS` in `.env` **before** the first start on this version. The migration that adds multi-user ownership assigns all your existing data to the admin named by `ADMIN_EMAILS` (falling back to a throwaway `admin@local` if it is unset) — so if you start without it, your chats/projects/media are backfilled to the wrong account.

First-run: create the admin account
------------------------------------
Admin accounts are created only from the CLI (never through the app), so run this inside the container once the stack is up — use `app-vpn` instead of `app` if you started the VPN profile:

```bash
docker compose exec app python -m web.provision_admin --email you@gmail.com --set-password
```

The email must be in `ADMIN_EMAILS`. Then sign in at the app with that email + password. Upgrading an older single-user install? Add `--claim-orphans` to adopt your existing (unowned) chats/projects/media and move the old shared library into the admin's folder.

OAuth sign-in
-------------
To let users sign in with Google/Microsoft/X rather than the LAN `API_KEY`:

1. Set `PUBLIC_BASE_URL` in `.env` to your public https host (e.g. `https://your-host.synology.me` — a `.local` name can't do OAuth).
2. Register the app with each provider and set its `*_OAUTH_CLIENT_ID` / `*_OAUTH_CLIENT_SECRET` in `.env`.
3. Set each provider's authorised redirect URI to `<PUBLIC_BASE_URL>/api/auth/callback/<provider>` (e.g. `.../api/auth/callback/google`).
4. Restart the stack so the new env is picked up.

Automating startup on boot (use `synology-boot.sh`)
-------------------------------------------------
The repository includes `synology-boot.sh` which is designed to be used with DSM's Task Scheduler. It performs three useful tasks:

- Installs an HTTP→HTTPS redirect into DSM's nginx for the project's hostname (so plain HTTP is redirected to HTTPS).
- Waits for the Docker daemon then stops any half-started containers belonging to project `cyno-studio` that Docker's restart policy might have left in a broken state.
- Runs `docker compose up -d`, respecting `COMPOSE_PROFILES` from `.env` (`novpn` or `vpn`), to bring the stack up respecting `depends_on` and `healthcheck` ordering.

Before using the script:

1. Edit `COMPOSE_DIR` at the top of `synology-boot.sh` to point to your actual project path.
2. Set `APP_HOSTNAME` in `.env` — used for the HTTPS redirect.
3. Set `COMPOSE_PROFILES=vpn` in `.env` to use the VPN stack on boot, or `COMPOSE_PROFILES=novpn` for the default no-VPN stack.

Install the script into Task Scheduler:

1. Make the script executable:

```bash
chmod +x /path/to/cyno-studio/synology-boot.sh
```

2. Open DSM → Control Panel → Task Scheduler → Create → Triggered Task → User-defined script

   - Event: Boot-up
   - User: root
   - Task Settings → Run command: bash /path/to/cyno-studio/synology-boot.sh

3. Save the task. On next boot the script will run and start the compose stack in the correct order.

Networking and ports
--------------------
- The host port is configured via `APP_PORT` in `.env` (default `8080` if unset). The compose file maps `${APP_PORT}:80` on the host to the container's internal HTTP port.
- If using the VPN stack, `gluetun` provides the network for the whole stack (via `network_mode: "service:gluetun"`). Adjust firewall and router rules to allow external traffic to the mapped port if you want public access.

HTTPS reverse proxy (DSM)
-------------------------
Put the app behind DSM's reverse proxy so it is served over HTTPS on a friendly hostname. Traffic flows:

```
browser --HTTPS:443--> DSM reverse proxy --HTTP--> nginx container (APP_PORT) --> app
```

`APP_HOSTNAME` in `.env` must be the hostname you use below (e.g. `cyno.your-nas.local`).

1. **DNS.** Make the hostname resolve to the NAS's IP address. A `.local` name with a subdomain (`cyno.your-nas.local`) is not resolved by mDNS, so it needs a record where your network's DNS lives. Check which DNS server your devices use (`nslookup <hostname>` prints it as `Server`/`Address`) and add the record there:

   - **DSM's DNS Server package** (Package Center → DNS Server): open it → **Zones** → select your zone (e.g. `your-nas.local`) → **Edit** → **Resource Record** → **Create → A**: Name = the host part (`cyno`), IP address = the NAS's IP. When you rename the app, edit the existing A record's name (or add a new one) instead of leaving the old one. The zone's serial number updates automatically.
   - **A router, Pi-hole or AdGuard Home:** add a Local / Static DNS record for the hostname pointing at the NAS's IP.
   - **No DNS server:** add a line to each device's hosts file (`<NAS IP>  <hostname>`).

   Check from another machine with `nslookup <hostname>` (on Windows run `ipconfig /flushdns` first if you changed a record). It must return the NAS's IP before the reverse proxy rule can answer on that name.

2. **Certificate.** In DSM → Control Panel → Security → Certificate, make sure there is a certificate that covers the hostname (Let's Encrypt for a public name; a self-signed one or a wildcard for a local name). You assign it to the rule in step 3, via Configure.

3. **Create the reverse proxy rule.** DSM → Control Panel → Login Portal → Advanced → Reverse Proxy → Create:

   | Setting | Value |
   |---|---|
   | Source: Protocol | HTTPS |
   | Source: Hostname | the same as `APP_HOSTNAME` |
   | Source: Port | 443 |
   | Destination: Protocol | HTTP |
   | Destination: Hostname | `localhost` |
   | Destination: Port | your `APP_PORT` (default `8080`) |

   Then edit the rule:
   - **Advanced Settings:** raise the proxy connect / send / read timeouts to `300` seconds (DSM's default is 60). Streamed chat replies and large uploads can take longer, and the app's own nginx already allows 300s.
   - **Custom Header (only if needed):** the app marks the sign-in cookie `Secure` when it sees `X-Forwarded-Proto: https`. DSM normally sends it. If you can sign in but are signed straight out again, add a custom header `X-Forwarded-Proto` = `https` to the rule.
   - **Certificate:** Control Panel → Security → Certificate → Configure, and select your certificate for this rule's hostname.

4. **HTTP → HTTPS redirect.** Do not create a port-80 rule for the hostname: keep only the HTTPS (443) rule. `synology-boot.sh` installs a redirect for `APP_HOSTNAME` into DSM's nginx at boot (run `sudo bash synology-boot.sh`, or reboot, to apply it after a change).

5. **Check it.**

   ```bash
   nslookup <hostname>              # returns the NAS IP
   curl -I http://<hostname>        # 301 to https://
   curl -kI https://<hostname>      # 200 from the app (drop -k once the certificate is trusted)
   ```

**Changing the hostname later:** change or add the DNS record (the A record in the DNS Server zone), edit the rule's source hostname, assign a certificate that covers the new name, set `APP_HOSTNAME` in `.env`, and run `synology-boot.sh`. Browsers treat each hostname separately, so everyone has to sign in again and locally stored preferences (favourite models, picker filters) start fresh. Nothing on the server changes.

A public sign-in (Google, Microsoft or X) needs a real public HTTPS host: see "OAuth sign-in" above. A `.local` name cannot be used for it.

Updating the stack
------------------
To update images and restart with latest:

```bash
cd /path/to/cyno-studio
docker compose pull
docker compose up -d
```

Troubleshooting
---------------
- gluetun fails to start / cannot access /dev/net/tun
  - Confirm `/dev/net/tun` exists on the NAS. Many Synology kernels include tun; if not present you'll need to enable it or run on a model/kernel that supports tun devices.
  - Start the stack from the shell as root so Docker can map /dev/net/tun.

- App cannot read/write to host data directory
  - Confirm `PUID`/`PGID` in `.env` match the owner of the host data folder. Run `id` to get your values, `chown -R PUID:PGID /path/to/data` to fix ownership.

- Use `docker compose logs -f <service>` to tail logs for suspect services (e.g. `docker compose logs -f gluetun`).

- Container Manager "Project" won't stop / random-prefixed container it doesn't recognize
  - Container Manager's Project wizard names the compose project after the folder you point it at, not the `name: cyno-studio` set in `docker-compose.yml`. If that folder ever got auto-suffixed by DSM (e.g. re-uploading/re-extracting the project into a new folder instead of updating files in place), re-importing creates a *new* project with a new random-prefixed set of containers, and the old ones become orphaned — Container Manager's GUI can fail to stop/remove containers it no longer associates with a tracked project.
  - Fix the immediate problem via SSH, bypassing the GUI entirely:
    ```bash
    docker ps -a | grep -i pollo   # find the orphaned container(s) by image name
    docker stop <container_id>
    docker rm <container_id>
    ```
  - Prevent recurrence: keep the project in one stable folder (edit files in place rather than re-uploading/re-extracting), and when creating/re-creating the Project in Container Manager, explicitly set its "Project Name" field to `cyno-studio` rather than accepting whatever it auto-fills from the folder path.

Advanced options
----------------
- If you prefer a GUI approach, Portainer (installed on the NAS) can manage stacks and respects compose files. However, verify Portainer allows passing device mappings and capability flags needed by `gluetun`.
- If your NAS does not provide `docker compose`, you can install the compose plugin via the Docker project's instructions or run Compose V1 (less recommended). The `synology-boot.sh` uses `docker compose` (v2 style).

Security and best practices
---------------------------
- Keep your `.env` out of version control and protect API keys.
- Do not expose ports unnecessarily — use a reverse proxy + HTTPS where possible.
- Test restores and upgrades in a safe environment before using in production.

Useful commands
---------------

Start / stop / upgrade:

```bash
# Start
cd /path/to/cyno-studio
docker compose up -d

# Stop
docker compose down

# Pull new images and restart
docker compose pull
docker compose up -d
```

See also
--------
- `synology-boot.sh` (included) — script to run at boot via Task Scheduler
- `docker-compose.yml` — single compose file; profile selected via `COMPOSE_PROFILES` in `.env`
