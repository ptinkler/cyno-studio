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
- [x] Frontend: ESLint `complexity` is now 10 (tests exempt) and `max-lines` is 600 for source files. Nine functions were split to get there. Going lower (the backend uses 7) is optional.
- Found and fixed on the way: `scripts/audit_pollo_models.py --write` pointed at `v1_video.py`, which no longer exists (now `video/models.py`).

## 3. Stricter lint rules

Adopted and enforced: `A`, `PLW`, `PLR0911`, `PLR0912`, `PLR0915`, `PLR2004` (magic numbers: HTTP statuses are `http.HTTPStatus`, the rest are named constants) and `FBT` (flag arguments are keyword-only). `PLR0913` is enforced too. Test-only ignores for `PLR0913`, `PLR2004` and `FBT` are approved and documented in `pyproject.toml`.

- [x] `PLR0913` (at most 5 arguments) is enforced for non-test code. The 31 violations were fixed with request objects, not keyword-only tricks: `providers/specs.py` holds `ImageRequest`, `VideoRequest`, `StreamOptions` and `CostQuery` (every provider takes the same object and uses the fields it knows); `chat/generation.py` has `HistoryShape`, `RefLimits` and `ImageAsk`; `turn_generation.py` has `ImageSpec` and `VideoSpec`; `turn_base.py` has `TurnLink` and `Reword`; `request_log.CallResult`; `imports.ImportStamp`; `add_chat_message` takes typed `**fields` (`NewMessage`); Venice's `_Call`; uploads' `_UploadRule`; `MediaFilter` for the media list query.
- Not recommended: `EM` (128) and `CPY` (133) are noise for this repo.

## 4. Split the oversized modules

Done: `providers/pollo/engine/video/` package; the Python provider and importer splits (`providers/pollo/`, `providers/venice/`, `transfer/chatgpt/`); `venice_catalogue.py` / `venice_video.py`; `chat/routes_*` (settings, media, media items, turns); the test files; `media/` (paths, video, durations, thumbs, blank, index, routes); `chat/turn*.py` as a layered chain (`turn_base` -> `turn_history` -> `turn_generation` -> `turn_tools` -> `turn`); and the loose modules of `web/` moved into packages (`auth/`, `media/`, `uploads/`, `transfer/`, `core/`).

- [x] `providers/pollo.py` (799) is now a `providers/pollo/` package behind a facade `__init__`: `catalogue` (models, voices, key lookup), `uploads`, `tasks` (submit, poll, download), `submit` (image/video/audio jobs) and `cost`. Tests patch the module that looks the name up (`tasks.POLL_INTERVAL`, `tasks.submit_task`, `uploads.upload`, `submit.get_*_generator`). The flat `pollo_engine/`, `pollo_errors`, `pollo_estimate` and `pollo_models` now live inside it as `engine/`, `errors`, `estimate` and `models`.
- [x] `transfer/chatgpt.py` (769) is now a `transfer/chatgpt/` package: `parse` (the export zip and its turns), `media`, `importer` (merge and run), `routes` (folder listing, run job, chunked uploads) and `common` (names and stats). Tests patch `importer.get_db` and `routes.UPLOAD_CHUNK`.
- [x] `providers/venice.py` (754) is now a `providers/venice/` package: `client` (HTTP, auth, errors, balance), `models` (per-user catalogue and quotes), `text`, `images`, `jobs` (video queue to MP4) behind a facade `__init__` that also owns `clear_caches`. The flat `venice_catalogue`, `venice_errors`, `venice_types` and `venice_video` are now `catalogue`, `errors`, `types` and `video` in the package. Tests patch `client.http` and `jobs._VIDEO_DIR`.
- [ ] `src/py/web/chat/routes_media_items.py` (506), `media/routes.py` (394) are fine; keep an eye on them.

## 5. Frontend

- [x] `composables/useStudio.js` (was 1054) is a 340-line composition root over `useStudioAttachments`, `useStudioThreads`, `useStudioTurns`, `useStudioPrompt` (estimate + enhance), `useStudioReuse`, plus the existing media/sidebar/defaults ones and the pure `studioDelete.js`. `studio.test.js` pins its public surface and the send/open/delete/reuse flows.
- [x] The 700+ line components are split: `ModelPicker` (910 -> 450: `ModelRow`, `ModelBadge`, `useModelList`, `usePopPlacement`, `utils/modelBadges`), `StudioComposer` (762 -> 350: `ComposerAttachments`, `useMentionEditor`, `utils/refItems`), `StudioView` (750 -> 500: `useStudioRoutes`, `useGalleryModal`, `useThreadView`, `useStudioTheme`, `useAttachmentPicker`), `ChatMessage` (738 -> 360: `ChatMediaCard`, `ChatAttachments`, `PromptBox`, `PinButton`), `StudioSidebar` (657 -> 560: `SidebarSpaceFolder`). Scoped CSS moved with the markup; not yet looked at in a browser (see below).
- [ ] Eyeball the split components in a browser (model picker badges and folded dots, composer attachment strip, chat media cards, sidebar space folders): the unit tests cover behaviour, not the moved scoped CSS.
- [x] `npm run typecheck` (`tsc` with `checkJs`, non-strict) checks `composables/` and `utils/` and runs in CI; it needed five JSDoc annotations. Note `.vue` files are not covered yet: `vue-tsc` reports about 250 errors, nearly all from untyped array/object props (need `PropType` JSDoc per component).
- [ ] Type the components so `vue-tsc` can cover them, then turn on `noImplicitAny` for the JS (about 690 errors today: mostly untyped parameters, so JSDoc on the composables' public functions first).
- [x] `modelTags.test.js` reads `model_tags.py` and fails when `TAG_LABELS` drifts (it caught an existing ordering mismatch for `audio`, now fixed). Serving the labels from the backend instead remains an option.
- [x] ESLint also enforces `eqeqeq`, `no-var`, `prefer-const`, `no-shadow`, `no-console` (warn/error allowed), `vue/no-undef-components` and `vue/no-unused-refs`, plus the complexity and `max-lines` limits above.
- [x] `vue/define-macros-order` is enforced (props, emits, model). `flat/recommended` already includes the strongly-recommended rules.

## 6. Maintenance

- [ ] Keep the refs-to-video docs and the audit/probe scripts (`scripts/`) in sync with what Pollo actually accepts (frontend/backend `[@name]` naming contract).
- [ ] Periodically re-diff `docs.pollo.ai/openapi.json` against `MODEL_INFO` for newly added models. The Pollo build-out itself is finished: tags and filters, video extend/edit, motion, lip-sync, upscale, image tools and TTS/music are all wired.
- [ ] Deferred Pollo gaps: Sora-2 extend (uses `generationId`, not a video URL), Runway extend (takes `images`), video-edit extras (images, seed, audio).

## 7. Rename clean-up (after every deployment has moved to the new names)

- [ ] Drop the legacy `POLLO_DATA_DIR` fallback (`src/py/web/core/config.py`, its tests, `tests/conftest.py`) and the `${POLLO_HOST_DATA_DIR}` fallback in `docker-compose.yml`.
- [ ] Drop the "Renamed from pollo-api" note in `README.md` (the old-project cleanup line in `synology-boot.sh` is already gone).
- [ ] Delete the old GHCR packages `ghcr.io/ptinkler/pollo-api` and `pollo-nginx` (GitHub profile -> Packages) and the old images on the NAS.

## 8. Code inspection (hacks, workarounds, suppressions)

Done 2026-11-15:
- Suppressions: only three exist in the code (`# noqa: S106` in `oauth.py`, `# fmt: skip` in one test, one `eslint-disable` in `ChatMessage.vue`), each now with its reason beside it. The blanket `reportUnusedFunction = "none"` relaxation was removed: it was hiding dead code (`_aspect_from_image` and `_image_dimensions`, now deleted).
- About 75 docstrings were cut mid-sentence by an earlier automated "first line must end in a period" pass (`caches.py`, `polling.py`, `helpers.py`, many tests...); they now read properly.
- `request_log`: exception-to-log-entry link goes through `entry_of(error)` instead of `__dict__` writes and `getattr` + `cast` at the call sites.
- Metadata layer: one `set_fields()` replaces three different `setattr` loops (some silently dropped unknown names, some set stray attributes); an unknown field is now an error.
- `openrouter.py` uses the shared `jsonutil` helpers (`as_object`, `body_of`, new `loads`) instead of private copies and 14 casts; `cast(` count in `src/py` went 88 -> 64.
- `vpn.py` catches `requests.RequestException`, not bare `Exception`; the scripts no longer rely on a `sys.path` hack (run them with `make audit-models` / `make probe-models`).

Also done (second pass):
- Startup now fails fast: `ensure_schema` raises `MigrationFailedError` (the original error chained) instead of letting the server run on a half-migrated database. Note `restart: unless-stopped` will retry-loop a container whose migration fails; the cause is in `docker compose logs app`.
- JSON narrowing casts replaced with the shared `jsonutil` helpers (`as_object`, `as_objects`, `body_of`, `loads`): `cast(` count in `src/py` went 88 -> 50. The 50 left are deliberate: TypedDict construction, Protocol shims for untyped libraries (Authlib, ASGI scope), ORM internals.
- Legacy `chat_conversations.instruction_id` column removed (migration 0030, reversible; its values were carried into `instruction_ids_json` by 0011).
- The Pollo balance route moved from `/api/usage/balance` (in `api.py`) to `/api/chat/pollo-balance`, beside the OpenRouter and Venice balances.
- The two failed-image retries share `utils/imageRetry.js`.

Open:
- [ ] Remaining `cast(` calls in `request_log.py` / `chat/turn.py` / `chat/tools.py` could be tightened with TypedDicts for the tool schemas.
