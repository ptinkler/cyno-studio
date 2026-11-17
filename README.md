# Cyno Studio

A self-hosted studio for chat, image, video and audio generation across several providers ([Pollo](https://pollo.ai), [OpenRouter](https://openrouter.ai) and [Venice](https://venice.ai)), with a web UI and an API backend.

Originally built for rapid on-the-fly D&D resource creation — generating atmospheric video loops, character portraits, and scene backgrounds for tabletop use. Grew into a general-purpose personal generation studio with chats, galleries, characters, credit tracking, and VPN rotation.

## Features

- Generate videos from image + prompt via multiple Pollo models
- Project-based organisation with per-project galleries
- Credit usage tracking and balance display
- Source and reference image uploads (stored locally)
- Characters: a name, description and reference images, attachable to chats and generations so a character looks the same everywhere (made ad hoc in a chat, or saved and managed on the Characters page)
- VPN country rotation via Gluetun control API
- Background job polling with automatic recovery on restart
- Multi-user: email+password admin login plus OAuth (Google/Microsoft/X), per-user encrypted provider keys, per-user data isolation
- Cookie-based authentication (HttpOnly session cookie)

## Quick Start

Local or LAN try-out (for a real server with HTTPS, see [Deploy on an Ubuntu server](#deploy-on-an-ubuntu-server)):

```bash
cp .env.example .env
# Edit .env — set ADMIN_EMAILS, the three secrets, CYNO_HOST_DATA_DIR, PUID/PGID
docker compose up -d
```

Create the admin account from the CLI (it can't be done through the app):

```bash
docker compose exec app python -m web.provision_admin --email you@gmail.com --set-password
```

Then open `http://localhost:<APP_PORT>` (default `8080`) and sign in with that email + password (or an OAuth provider, if configured). From another machine over plain HTTP, also set `COOKIE_SECURE=false`. Provider keys (Pollo, OpenRouter, Venice) are entered per-user in **Settings → Keys** and stored encrypted — never in `.env`.

Upgrading an existing single-user install? See [Users & access](#users--access) for the one ordering gotcha and `provision_admin`.

## Deploy on an Ubuntu server

Production setup on a dedicated Ubuntu Server (22.04 or 24.04) with Docker. Traffic flows:

```
browser --HTTPS:443--> Caddy (on the host) --HTTP--> nginx container (127.0.0.1:APP_PORT) --> app
```

Images are built by CI and pulled from `ghcr.io/ptinkler/cyno-studio` (and `-nginx`); nothing is built on the server. Database migrations run automatically on every container start.

### 1. Prerequisites

- A DNS name (e.g. `cyno.example.com`) pointing at the server's public IP, and ports **80** and **443** forwarded to it (router) and allowed by the firewall. Caddy needs both to get and renew its certificate. OAuth sign-in needs a real public HTTPS name.
- Docker Engine with the compose plugin:

  ```bash
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker $USER   # log out and back in
  ```

- Caddy (automatic HTTPS): follow the [official apt instructions](https://caddyserver.com/docs/install#debian-ubuntu-raspbian).
- If the GHCR packages are private: `docker login ghcr.io` with a personal access token that has `read:packages`.

### 2. Install

The server only needs `docker-compose.yml` and `.env`, not the whole repo:

```bash
sudo mkdir -p /opt/cyno-studio/data && sudo chown $USER: /opt/cyno-studio && cd /opt/cyno-studio
curl -fsSLO https://raw.githubusercontent.com/ptinkler/cyno-studio/main/docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/ptinkler/cyno-studio/main/.env.example -o .env
chmod 600 .env
```

(Or `git clone` the repo there if you prefer.) Edit `.env`:

- `ADMIN_EMAILS`, `PUBLIC_BASE_URL=https://cyno.example.com`, plus any OAuth ids/secrets.
- Three long random secrets: `SESSION_SECRET`, `PASSWORD_PEPPER`, `KEYS_SECRET` (`openssl rand -hex 32` for each). `PASSWORD_PEPPER` and `KEYS_SECRET` are set once and never changed: changing them locks out passwords and makes stored provider keys unreadable.
- `CYNO_HOST_DATA_DIR=/opt/cyno-studio/data`, and `PUID` / `PGID` from `id -u` / `id -g` (the data dir must be owned by that user).
- `COMPOSE_PROFILES=novpn`, or `vpn` plus the Gluetun settings (see [VPN Stack](#vpn-stack)). The VPN profile needs `/dev/net/tun`, which a normal Ubuntu host has.

### 3. Start

```bash
docker compose up -d
docker compose exec app python -m web.provision_admin --email you@gmail.com --set-password
```

(Use `app-vpn` instead of `app` on the VPN profile.) The containers have `restart: unless-stopped` and Docker starts on boot, so the stack comes back after a reboot with no extra script. If a migration fails the container restart-loops: see `docker compose logs app`.

### 4. HTTPS with Caddy

`/etc/caddy/Caddyfile`:

```
cyno.example.com {
    reverse_proxy 127.0.0.1:8080 {
        flush_interval -1
    }
}
```

```bash
sudo systemctl reload caddy
```

Caddy sends `X-Forwarded-Proto`, which the app uses to mark the sign-in cookie `Secure`, and has no short proxy timeout (streamed chat replies and 200 MB uploads work). Set `APP_PORT` to match the port above.

Docker publishes `APP_PORT` on all interfaces and bypasses `ufw`, so the plain-HTTP port is reachable from the LAN. To bind it to the host only, add `docker-compose.override.yml` (Compose 2.24+):

```yaml
services:
  nginx:
    ports: !override
      - "127.0.0.1:${APP_PORT:-8080}:80"
  gluetun:
    ports: !override
      - "127.0.0.1:${APP_PORT:-8080}:80"
```

### 5. Check it

```bash
docker compose ps
curl -I http://127.0.0.1:8080        # 200 from the app
curl -I https://cyno.example.com     # 200 over HTTPS (Caddy redirects http to https itself)
```

### Updating

```bash
cd /opt/cyno-studio
docker compose pull && docker compose up -d
docker image prune -f
```

`pull_policy: always` also refreshes the images on every `up`.

### Backup

The app also copies its database by itself: every `BACKUP_INTERVAL_HOURS` (default 24, `0` = off) a consistent snapshot goes to `backups/` in the data directory, and all but the newest `BACKUP_KEEP` (default 7) are deleted. That guards against a bad migration or a deleted row, not a dead disk, so still copy the data directory elsewhere. To restore: stop the app, copy a snapshot over `data/metadata.db`, start it.

Everything lives in `CYNO_HOST_DATA_DIR` (SQLite DB, videos, images). Also keep a copy of `.env`: without the original `KEYS_SECRET` and `PASSWORD_PEPPER`, a restored database is unusable. Stop the stack for a consistent copy:

```bash
docker compose stop
sudo rsync -a /opt/cyno-studio/data/ /mnt/backup/cyno-studio/data/
docker compose start
```

### Moving from the Synology NAS

1. On the NAS: `docker compose down` (stops writes to the SQLite DB).
2. Copy the data dir and `.env` across, keeping permissions:

   ```bash
   rsync -aH --info=progress2 nas:/path/to/cyno-studio/data/ /opt/cyno-studio/data/
   scp nas:/path/to/cyno-studio/.env /opt/cyno-studio/.env
   ```

3. Edit `.env` for the new host: `CYNO_HOST_DATA_DIR`, `PUID` / `PGID` (then `sudo chown -R PUID:PGID /opt/cyno-studio/data`), `PUBLIC_BASE_URL`. **Keep the three secrets exactly as they were.** `APP_HOSTNAME` and `synology-boot.sh` are Synology-only and can be ignored.
4. `docker compose up -d`, then sign in with your existing admin account (no need to run `provision_admin`).
5. Point DNS (or the router's port forward) at the new server. If the hostname is unchanged the OAuth redirect URIs keep working; if not, update them at each provider and `PUBLIC_BASE_URL`.
6. Keep the NAS data until you have used the new server for a few days.

## Configuration

See `.env.example` for the full list.

| Variable                                      | Description                                                                   |
| --------------------------------------------- | ----------------------------------------------------------------------------- |
| `ADMIN_EMAILS`                                | Comma-separated admin emails; they log in with a password and control the VPN |
| `ALLOWED_EMAILS`                              | Non-admins allowed to sign in via OAuth (admins always may)                   |
| `ALLOWED_OAUTH_IDS`                           | Sign-ins with no email (X) let in by id, e.g. `x:12345` — shown on the "not allowed" screen |
| `OPEN_SIGNUP`                                 | `true` = anyone who authenticates gets an account                             |
| `SESSION_SECRET`                              | Signs the login cookie — 32+ random characters, or the app won't start       |
| `PASSWORD_PEPPER`                             | Server-side secret mixed into password hashes — set once, never change        |
| `KEYS_SECRET`                                 | Encrypts stored per-user provider keys — set once, never change               |
| `PUBLIC_BASE_URL`                             | Public https base URL for OAuth callbacks (behind a proxy/DDNS)               |
| `*_OAUTH_CLIENT_ID` / `*_OAUTH_CLIENT_SECRET` | Google/Microsoft/X credentials; a provider turns on when both are set         |
| `MICROSOFT_OAUTH_TENANT`                      | Your Microsoft tenant id or domain — required, or Microsoft sign-in is refused |
| `BACKUP_INTERVAL_HOURS` / `BACKUP_KEEP`       | Database snapshot every N hours (default 24, `0` = off) and how many to keep (default 7) |
| `CYNO_HOST_DATA_DIR`                          | Host path for persistent data (videos, DB)                                    |
| `APP_PORT`                                    | Host port to expose the app on (default `8080`)                               |
| `COMPOSE_PROFILES`                            | `novpn` (default) or `vpn` — selects the stack                                |
| `PUID` / `PGID`                               | User/group the app container runs as (run `id` to find values)                |
| `APP_HOSTNAME`                                | Synology only: hostname for the HTTPS redirect in the boot script             |
| `GLUETUN_API_KEY`                             | Gluetun control server API key (VPN stack only)                               |

Provider keys (`POLLO_API_KEY`, `OPENROUTER_API_KEY`, `VENICE_API_KEY`) are entered per-user in the UI and are never read from the environment.

## Users & access

Multi-user: each user signs in, gets their own data (chats, projects, media, characters, settings) and their own provider keys — no user sees another's. There is no API key; protection is by login session.

- **Sign-in** — admins (emails in `ADMIN_EMAILS`) use email + password; everyone else uses OAuth (Google/Microsoft/X). An OAuth login with an admin's email resolves to the same account, so only emails the provider verifies count: Google's verified emails, and Microsoft addresses from the tenant named in `MICROSOFT_OAUTH_TENANT`. X gives no email, so an X account is just its X user id (the handle is only a label, since handles can be taken over once released) and has no email.
- **Who gets in** — fail-closed. With none of `ADMIN_EMAILS`/`ALLOWED_EMAILS`/`OPEN_SIGNUP` set, only admins. `ALLOWED_EMAILS` admits a fixed list (and `ALLOWED_OAUTH_IDS` the same for sign-ins with no email, like X; someone refused is shown the id to send you); `OPEN_SIGNUP=true` admits anyone who authenticates.
- **Admin accounts** — created only via the CLI, never through the app (so a visitor can't claim one):

  ```bash
  docker compose exec app python -m web.provision_admin --email you@gmail.com --set-password
  ```

- **Upgrading a single-user install** — set `ADMIN_EMAILS` **before the first start**: migration `0020` backfills all existing data to that admin (or to a throwaway `admin@local` if unset). Then run `provision_admin --email you@… --claim-orphans` to adopt any remaining unowned data and move the old shared library into the admin's folder.
- **OAuth setup** — set `PUBLIC_BASE_URL` and register each provider's redirect URI as `<PUBLIC_BASE_URL>/api/auth/callback/<provider>`.

## VPN Stack

Set `COMPOSE_PROFILES=vpn` in `.env` to route all outbound traffic through [Gluetun](https://github.com/qdm12/gluetun). Requires a WireGuard-compatible VPN provider.

```bash
# .env
COMPOSE_PROFILES=vpn
VPN_SERVICE_PROVIDER=your_vpn_provider
VPN_TYPE=wireguard
WIREGUARD_PRIVATE_KEY=...
WIREGUARD_ADDRESSES=...
```

## Models

| Model     | Type    | Notes          |
| --------- | ------- | -------------- |
| Pollo 2.0 | img2vid | 5s or 10s only |

## Development

```bash
uv sync          # creates .venv from uv.lock
cd src/js && npm install && cd -
make dev        # API on :5000, Vite dev server on :5173
make test       # pytest + vitest
make lint       # what CI checks
make format     # fix what can be fixed automatically
make hooks      # check (and fix) staged files on every commit
```

Code standards, enforced in CI:

- **Python** — [ruff](https://docs.astral.sh/ruff/) for linting (PEP 8, pyflakes, import order, bugbear,
  pyupgrade, simplifications, and a cyclomatic complexity limit of 7) and formatting. 120-column lines.
  Settings in `pyproject.toml`.
- **Frontend** — everything under `src/js/src` is strict TypeScript (`vue-tsc`: `strict`,
  `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`), with no `any` and no suppressions. ESLint
  runs `typescript-eslint` `strictTypeChecked` (complexity limit 7, 600 lines per file) and Prettier
  (no semicolons, single quotes, 120 columns). API types are generated from the backend (`make gen-api`).
  Settings in `src/js/eslint.config.ts`, `src/js/tsconfig.json` and `.prettierrc.json`. See
  [src/js/README.md](src/js/README.md).
- **Line endings** — LF everywhere (`.gitattributes`, `.editorconfig`).

## Data

All data (videos, source images, chat media, character images, SQLite DB) is stored in `CYNO_HOST_DATA_DIR` on the host. Back this up.

## NAS / Synology

The previous production host. See [SYNOLOGY-README.md](SYNOLOGY-README.md) for DSM setup, boot automation and the DSM reverse proxy.

## Security

Every endpoint requires a login session (an HttpOnly cookie holding a signed, expiring user id). Admin passwords are hashed with argon2id over an HMAC pepper (`PASSWORD_PEPPER`); access is fail-closed (see [Users & access](#users--access)); each user's data is isolated at the database layer; per-user provider keys are encrypted at rest (`KEYS_SECRET`). If you expose the app publicly, serve it over HTTPS and set `PUBLIC_BASE_URL`.

## License

MIT — see [LICENSE](LICENSE).
