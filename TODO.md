# TODO

The project was renamed from pollo-api to **Cyno Studio** (`cyno-studio`). Pollo is now just one provider.

What is left to do for clean, consistent code. Kept in-repo so people and Claude can read it.
Update it when an item is started, finished or dropped; delete finished items.

Rules that apply to everything below:
- Run `ruff check`, `ruff format --check`, `basedpyright` (strict, no baseline), `pytest`, and in `src/js` `npm run lint`, `npm run format:check`, `npm test` before calling anything done.
- Lint and type rules are mandatory. Do not add ignores, `noqa`, `type: ignore` or a pyright baseline; fix the code. A suppression that is truly unavoidable needs the maintainer's approval first. Adding *stricter* rules is fine.
- Never submit real Pollo jobs (billable, no cancel or refund) without explicit per-run consent.
- Do not `git commit` or `git push` from an agent session; the maintainer commits.

Layout: Python lives in `src/py/web/` (an import root: `src/py` is on the path, the package is still `web`), the Vue app in `src/js/`; `tests/`, `alembic/`, `scripts/` stay at the repo root. Paths below are relative to the repo root.

Status as of 2026-11-16. Measured numbers are from running the tools, not estimates.

## Open

- [ ] Keep the refs-to-video docs and the audit/probe scripts (`scripts/`) in sync with what Pollo actually accepts (frontend/backend `[@name]` naming contract).
- [ ] Periodically re-diff `docs.pollo.ai/openapi.json` against `MODEL_INFO` for newly added models.
- [ ] **Reference modes found by the 2026-11-16 audit** (`make audit-models`, estimate probe only, nothing billed). Enabled models whose docs have a reference-to-video branch but which declare no `ref_mode`: `hailuo03` (up to 15, image/video), `veo31` (3 images), `wan26` (3 videos). `pollo26` / `pollo26fast` (15) answer UNKNOWN to the estimate probe; `klingv3omni` declares a `ref_mode` the docs don't show (known; kept). Also documented but not in the registry: `gemini-omni-1-2-flash`, `minimax-h3-fast`, `minimax-h3-max-turbo`, `hailuo-2-3-fast`, `happyhorse-1-1` / `1-5`, `pollo-dance-2-0` / `-fast`. To enable one: run `audit_pollo_models.py --write`, keep only that model's hunk (`ref_mode` + `HAS_REFS`), then try it once by hand: the refs payload can't be verified without a billed job (needs explicit consent).
- [ ] Deferred Pollo gaps: Sora-2 extend (uses `generationId`, not a video URL), Runway extend (takes `images`), video-edit extras (images, seed, audio).
- [ ] Frontend dev dependencies: `npm audit` still reports 21 issues (vitest/vite/esbuild/tinypool chain) that need `npm audit fix --force` (breaking upgrades). Dev tooling only; do as a deliberate upgrade.
- [ ] Watch file size: `chat/routes_media_items.py` (~520), `media/routes.py` (394), and `components/chat/ChatMediaCard.vue` (~630: its footer and its pending / error states split out cleanly).
- [ ] **Guard every provider-URL download.** Only OpenRouter uses `core/net_guard`. Pollo's `download_image` / `download_video` (`providers/pollo/tasks.py`) and the upload-host checks (`uploads/hosts.py`) call `requests.get` directly: redirects followed, no size cap. `net_guard.get_public` also has no size cap and resolves the host separately from connecting (DNS rebinding). Moving everything from `requests` to `httpx` would let one guarded client do every fetch.
- [ ] Sign-ins with no email (X) are let in by id (`ALLOWED_OAUTH_IDS`) or `OPEN_SIGNUP`. A "pending approval" list the admin clears in Settings (instead of editing `.env` with the id the refused user sends) would be friendlier.
- [ ] **Dependencies and CI.** `npm audit --omit=dev` reports `@vue/server-renderer` (high; SSR isn't used, but `npm audit fix` clears it without a breaking upgrade). Authlib is pinned at 1.3.2 (latest 1.9.8) and is the sign-in library: check its advisories. `python-multipart`, `starlette` and `fastapi` are well behind. CI has no pip-audit, `npm audit`, Dependabot / Renovate or image scan. Both Dockerfiles use `npm install` instead of `npm ci`.
- [ ] **Verify after deploying the 2026-11-16 security changes:** rebuild **both** images (the nginx one now ships `security-headers.inc`). Load the app once with the browser console open and look for Content-Security-Policy violations (the policy allows only this origin, `data:`/`blob:`, and the Google / X avatar hosts; anything else the UI loads is blocked). Failed logins from different devices should no longer share one rate limit (needs DSM's reverse proxy to send `X-Forwarded-For`). The app now refuses to start without a real `SESSION_SECRET` (32+ chars); for Microsoft sign-in set `MICROSOFT_OAUTH_TENANT`. Migrations 0031 and 0032 add `users.session_version` and make `users.email` nullable (an X account has none; run it on a copy of the database first); existing login cookies keep working (they count as version 0). Settings → Account has "Sign out other devices".
- [ ] Ideas: a per-user disk quota with periodic cleanup of old import zips and orphaned files; a scheduled backup of the SQLite database (a restored database is unusable without the original `KEYS_SECRET` and `PASSWORD_PEPPER`, so back those up with it).
- [ ] One vitest failure on the first run after a fresh `npm ci` (2026-11-16), not reproduced in 5 later runs; probably a cold-start timeout. Re-open if it recurs.

## Notes worth keeping

- **Complexity:** `max-complexity` is 7 for Python (ruff) and for the frontend (ESLint, tests exempt); `max-lines` is 600 for frontend source. Stricter ruff rules enforced: `A`, `PLW`, `PLR0911/0912/0913/0915`, `PLR2004`, `FBT`. Test-only ignores for `PLR0913`, `PLR2004`, `FBT` are approved (see `pyproject.toml`). `EM` and `CPY` are noise here: not recommended.
- **Typed API:** `make gen-api` writes `src/js/src/api/schema.d.ts` (committed; CI fails when stale). Every endpoint has a Pydantic response model; `api/paths.ts` maps endpoint strings to routes so `api.get/put/...` are typed. Turn streams publish `TurnEvent` models as `text/event-stream` (`core/openapi.event_stream_only`). Server JSON is trusted from the schema at runtime (`readJson<T>`); if that bites, generate validators from the schema. Persisted browser state is read through `utils/storage.ts` / `readShape`, never trusted.
- **Frontend is all strict TypeScript:** no `.js` left; `vue-tsc` over `.ts` and `.vue`; ESLint `strictTypeChecked`; no `any`, no suppressions. Conventions: optional props are `x?: T | undefined` (`exactOptionalPropertyTypes`), templates read `props.x` where a default makes it non-optional, typed `InjectionKey`s in `injection.ts`, input values via `typedValue`, test rows from the factories in `__tests__/models.ts`. `useChat.ts` is deliberately the one facade over the typed API modules. `gen:api` passes `--default-non-nullable false`; the SPA catch-all route is `include_in_schema=False`.
- **Scoped CSS trap:** when a component is split, rules in the parent's scoped CSS stop reaching elements the children now own; use `:deep()` or move the rule (this caused the sidebar underline bug).
- **Audit script:** `audit_pollo_models.py --write` unhides only img2vid models, merges limits, keeps only `image` / `video` / `audio` refs, and leaves edit / extend models to a human (tests in `tests/test_audit_editor.py`). Run scripts via `make audit-models` / `make probe-models`.
- **Startup** fails fast: `ensure_schema` raises `MigrationFailedError`; with `restart: unless-stopped` a failing migration retry-loops (see `docker compose logs app`).
- **Rename:** the legacy `POLLO_DATA_DIR` / `${POLLO_HOST_DATA_DIR}` fallbacks are gone; a deployment still using the old names gets the repo root or an unset mount, so check `.env` first.
- Remaining `cast(` calls in `src/py` (34) are deliberate: TypedDict construction, Protocol shims for untyped libraries (Authlib, ASGI scope), ORM internals.
