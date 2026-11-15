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

Status as of 2026-11-15. Measured numbers are from running the tools, not estimates.

## 1. Land the type-debt burn-down

- [x] The `chore/ruff` PR (#9) and the complexity / lint sweep (#10) are merged to `main`. `chore/ruff` and `chore/code-quality` are dead and can be deleted.
- [x] basedpyright step added to `.github/workflows/ci.yml` (installs `requirements-dev.txt`, runs `basedpyright`).

## 2. Complexity ratchet: DONE (backend)

- [x] All 40 functions over 7 were split (helpers extracted, behaviour unchanged) and `max-complexity` is now 7 in `pyproject.toml`.
- [ ] Frontend: ESLint `complexity` is still 12; tighten it once the big frontend files (section 5) are split.
- Found and fixed on the way: `scripts/audit_pollo_models.py --write` pointed at `v1_video.py`, which no longer exists (now `video/models.py`).

## 3. Stricter lint rules

Adopted (now in `select`, code already clean): `A` (builtin shadowing: `credits` renamed `credit_cost`), `PLW` (the four `global` caches became small holder objects with public test seams `reset_blank_checks()` / `reset_sweep()`), `PLR0911`, `PLR0912`, `PLR0915`.

Not adopted yet. Each needs a decision, because the violations are mostly in tests and `tests/*` per-file-ignores are limited to S101/ANN/ARG without the maintainer's approval:
- [ ] `PLR0913` too many arguments (max 5): 50 violations. 11 are test methods whose count is pytest fixtures; 4 are 10-14 argument provider facade functions (`src/py/web/providers/__init__.py` x2, `pollo.py` x2, `venice.py` `submit_video`, `request_log.py`) that mirror the HTTP request model. Fixing them means parameter objects and touching every call site.
- [ ] `PLR2004` magic numbers: 246 violations, 214 of them in tests (asserts on counts). In `src/py/web/` there are 32, mostly HTTP statuses (`>= 400`, 429, 404 ...): replace with `http.HTTPStatus`.
- [ ] `FBT` boolean positional arguments: 74 violations, 58 in `src/py/web/`. Make them keyword-only.
- Decision needed: approve test-only ignores for `PLR2004` / `PLR0913` / `FBT` (as was done for S101/ANN/ARG), or fix the tests too.
- Not recommended: `EM` (128) and `CPY` (133) are noise for this repo.

## 4. Split the oversized modules

Backend line counts (functions at module level):
- [x] `src/py/web/providers/pollo_engine/video.py` is now a `video/` package: `types.py`, `models.py` (the `VIDEO_MODELS` rows, `cfg`, endpoints), `payloads.py` (the body builders); `__init__.py` re-exports the public names.
- [x] `src/py/web/providers/venice.py` (1106 -> 754 lines): catalogue shaping moved to `venice_catalogue.py`, video input / duration / size rules to `venice_video.py` (alongside the existing `venice_errors.py` / `venice_types.py`). The HTTP client, caches and public API stay in `venice.py`: tests patch them there, so a deeper split needs the shared state moved first.
- [ ] `src/py/web/chat/turn.py` (~1000): essentially one huge `Turn` class. Extract streaming, tool dispatch, persistence and poller start-up into collaborators.
- [x] `src/py/web/chat/routes.py` (870 -> 592 lines): settings / instructions / spaces moved to `routes_settings.py`, attachments / media files / library / request log to `routes_media.py` (all registered from `src/py/web/chat/__init__.py`).
- [x] `src/py/web/chat/routes_turns.py` (877 -> 392 lines): pin / favourite / regenerate / version / active-generation routes moved to `routes_media_items.py`; the shared start lock now lives in `chat/deps.py` as `start_lock`.
- [ ] `src/py/web/media.py` (~810, 47 defs): library index, thumbnails, durations and the blank-image cache are four concerns. Split into a `media/` package.
- [ ] `src/py/web/chatgpt_import.py` (~760), `src/py/web/providers/pollo.py` (~750), `src/py/web/providers/openrouter.py` (~590): same treatment, lower priority.
- [x] `tests/test_chat.py` (5245 lines) is now `test_chat_conversations.py`, `test_chat_turns.py`, `test_chat_media.py`, `test_chat_images.py` and `test_chat_pollo.py`, with the shared fakes in `tests/chat_support.py`. Largest is `test_chat_media.py` (1461 lines): split further by class if it grows.

## 5. Frontend

- [ ] Split `composables/useStudio.js` (1054 lines) into focused composables (queue, models, uploads, presets, usage); it has no component-level seams today.
- [ ] Split the 700+ line components: `ModelPicker.vue` (910), `StudioComposer.vue` (762), `StudioView.vue` (750), `ChatMessage.vue` (738), `StudioSidebar.vue` (657).
- [ ] Add type safety. The Python side is strict-typed end to end but the frontend is plain JS with no type check. Cheapest step: JSDoc plus `checkJs` in a `tsconfig`; fuller step: migrate to TypeScript starting with `composables/` and `utils/`.
- [ ] Stop hand-mirroring the model tags: `composables/modelTags.js` `TAG_LABELS` copies `src/py/web/providers/model_tags.py` `TAGS` "in the same order". Serve the labels from the backend catalogue instead, or add a test that fails when they drift.
- [ ] ESLint is `js.configs.recommended` + Vue recommended only. Consider `vue/flat/strongly-recommended` rules and `eslint-plugin-vue` `no-undef-components`, plus a `max-lines` limit to stop the files above regrowing.

## 6. Maintenance

- [ ] Keep the refs-to-video docs and the audit/probe scripts (`scripts/`) in sync with what Pollo actually accepts (frontend/backend `[@name]` naming contract).
- [ ] Periodically re-diff `docs.pollo.ai/openapi.json` against `MODEL_INFO` for newly added models. The Pollo build-out itself is finished: tags and filters, video extend/edit, motion, lip-sync, upscale, image tools and TTS/music are all wired.
- [ ] Deferred Pollo gaps: Sora-2 extend (uses `generationId`, not a video URL), Runway extend (takes `images`), video-edit extras (images, seed, audio).

## 7. Rename clean-up (after every deployment has moved to the new names)

- [ ] Drop the legacy `POLLO_DATA_DIR` fallback (`src/py/web/core/config.py`, its tests, `tests/conftest.py`) and the `${POLLO_HOST_DATA_DIR}` fallback in `docker-compose.yml`.
- [ ] Drop the "Renamed from pollo-api" note in `README.md` (the old-project cleanup line in `synology-boot.sh` is already gone).
- [ ] Delete the old GHCR packages `ghcr.io/ptinkler/pollo-api` and `pollo-nginx` (GitHub profile -> Packages) and the old images on the NAS.
