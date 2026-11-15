# TODO

What is left to do for clean, consistent code. Kept in-repo so people and Claude can read it.
Update it when an item is started, finished or dropped; delete finished items.

Rules that apply to everything below:
- Run `ruff check`, `ruff format --check`, `basedpyright` (strict, no baseline), `pytest`, and in `web/frontend` `npm run lint`, `npm run format:check`, `npm test` before calling anything done.
- Lint and type rules are mandatory. Do not add ignores, `noqa`, `type: ignore` or a pyright baseline; fix the code. A suppression that is truly unavoidable needs the maintainer's approval first. Adding *stricter* rules is fine.
- Never submit real Pollo jobs (billable, no cancel or refund) without explicit per-run consent.
- Do not `git commit` or `git push` from an agent session; the maintainer commits.

Status as of 2026-11-15. Measured numbers are from running the tools, not estimates.

## 1. Land the type-debt burn-down

- [x] The `chore/ruff` PR was merged to `main` on GitHub as a squash commit (`4b49875 Chore/ruff (#9)`). Its content is identical to the branch's committed content, so merging `origin/main` into `chore/ruff` is a no-op that only joins the histories.
- [x] basedpyright step added to `.github/workflows/ci.yml` (installs `requirements-dev.txt`, runs `basedpyright`). Uncommitted until the maintainer commits.

## 2. Complexity ratchet: DONE (backend)

- [x] All 40 functions over 7 were split (helpers extracted, behaviour unchanged) and `max-complexity` is now 7 in `pyproject.toml`.
- [ ] Frontend: ESLint `complexity` is still 12; tighten it once the big frontend files (section 5) are split.
- Found and fixed on the way: `scripts/audit_pollo_models.py --write` pointed at `v1_video.py`, which no longer exists (now `video.py`).

## 3. Stricter lint rules

Adopted (now in `select`, code already clean): `A` (builtin shadowing: `credits` renamed `credit_cost`), `PLW` (the four `global` caches became small holder objects with public test seams `reset_blank_checks()` / `reset_sweep()`), `PLR0911`, `PLR0912`, `PLR0915`.

Not adopted yet. Each needs a decision, because the violations are mostly in tests and `tests/*` per-file-ignores are limited to S101/ANN/ARG without the maintainer's approval:
- [ ] `PLR0913` too many arguments (max 5): 50 violations. 11 are test methods whose count is pytest fixtures; 4 are 10-14 argument provider facade functions (`web/providers/__init__.py` x2, `pollo.py` x2, `venice.py` `submit_video`, `request_log.py`) that mirror the HTTP request model. Fixing them means parameter objects and touching every call site.
- [ ] `PLR2004` magic numbers: 246 violations, 214 of them in tests (asserts on counts). In `web/` there are 32, mostly HTTP statuses (`>= 400`, 429, 404 ...): replace with `http.HTTPStatus`.
- [ ] `FBT` boolean positional arguments: 74 violations, 58 in `web/`. Make them keyword-only.
- Decision needed: approve test-only ignores for `PLR2004` / `PLR0913` / `FBT` (as was done for S101/ANN/ARG), or fix the tests too.
- Not recommended: `EM` (128) and `CPY` (133) are noise for this repo.

## 4. Split the oversized modules

Backend line counts (functions at module level):
- [ ] `web/providers/pollo_engine/video.py` (~1020): one file holds the generic family plus Kling, extend, edit, upscale, lipsync and motion builders. Make `video/` a package with one module per family, keeping `registry.py` as the single entry point.
- [ ] `web/providers/venice.py` (~1000, 56 defs): text, image and video clients and the billing logic in one file. Make it a package like `pollo_engine`.
- [ ] `web/chat/turn.py` (~1000): essentially one huge `Turn` class. Extract streaming, tool dispatch, persistence and poller start-up into collaborators.
- [ ] `web/chat/routes.py` (~870, 55 defs) and `routes_turns.py` (~800): split by resource (settings, conversations, media, turns/SSE) with one `APIRouter` each.
- [ ] `web/media.py` (~810, 47 defs): library index, thumbnails, durations and the blank-image cache are four concerns. Split into a `media/` package.
- [ ] `web/chatgpt_import.py` (~760), `web/providers/pollo.py` (~750), `web/providers/openrouter.py` (~590): same treatment, lower priority.
- [ ] `tests/test_chat.py` (4522 lines) is the biggest file in the repo. Split by feature (settings, conversations, turns, media, SSE, migrations) and share fixtures through `tests/chat_fixtures.py`.

## 5. Frontend

- [ ] Split `composables/useStudio.js` (1054 lines) into focused composables (queue, models, uploads, presets, usage); it has no component-level seams today.
- [ ] Split the 700+ line components: `ModelPicker.vue` (910), `StudioComposer.vue` (762), `StudioView.vue` (750), `ChatMessage.vue` (738), `StudioSidebar.vue` (657).
- [ ] Add type safety. The Python side is strict-typed end to end but the frontend is plain JS with no type check. Cheapest step: JSDoc plus `checkJs` in a `tsconfig`; fuller step: migrate to TypeScript starting with `composables/` and `utils/`.
- [ ] Stop hand-mirroring the model tags: `composables/modelTags.js` `TAG_LABELS` copies `web/providers/model_tags.py` `TAGS` "in the same order". Serve the labels from the backend catalogue instead, or add a test that fails when they drift.
- [ ] ESLint is `js.configs.recommended` + Vue recommended only. Consider `vue/flat/strongly-recommended` rules and `eslint-plugin-vue` `no-undef-components`, plus a `max-lines` limit to stop the files above regrowing.

## 6. Maintenance

- [ ] Keep the refs-to-video docs and the audit/probe scripts (`scripts/`) in sync with what Pollo actually accepts (frontend/backend `[@name]` naming contract).
- [ ] Periodically re-diff `docs.pollo.ai/openapi.json` against `MODEL_INFO` for newly added models. The Pollo build-out itself is finished: tags and filters, video extend/edit, motion, lip-sync, upscale, image tools and TTS/music are all wired.
- [ ] Deferred Pollo gaps: Sora-2 extend (uses `generationId`, not a video URL), Runway extend (takes `images`), video-edit extras (images, seed, audio).
