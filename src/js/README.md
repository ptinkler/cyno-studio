# Cyno Studio frontend

A Vue 3 + TypeScript single-page app. It is the whole UI: one routed view, `StudioView`, which shows a chat
or gallery thread, the library, settings and the other panes depending on the URL.

Everything here is strict TypeScript, including the tests. There is no `any` and no `ts-ignore`,
`ts-expect-error` or `eslint-disable` for types (the one `eslint-disable` is for a DOMPurify-sanitised `v-html`).

## Commands

Run from `src/js` (or use the `make` targets from the repo root).

| Command                | What it does                                                                           |
| ---------------------- | -------------------------------------------------------------------------------------- |
| `npm run dev`          | Vite dev server on :5173, proxying `/api` to FastAPI on :5000 (`make dev` starts both) |
| `npm run build`        | Production build into `dist/`, which the API (and nginx in the image) serves           |
| `npm test`             | Vitest (jsdom)                                                                         |
| `npm run lint`         | ESLint, `typescript-eslint` `strictTypeChecked`, for `.ts` and `.vue`                  |
| `npm run typecheck`    | `vue-tsc`: every `.ts` file and every `<script setup lang="ts">`                       |
| `npm run format:check` | Prettier                                                                               |
| `npm run gen:api`      | Regenerate `src/api/schema.d.ts` (normally `make gen-api` from the repo root)          |

CI runs lint, format, typecheck, tests, and fails if `schema.d.ts` is stale.

## Routes

Every route renders `StudioView`, which reads the route to pick the pane (`src/router/index.ts`).

| Path                                       | Pane                                  |
| ------------------------------------------ | ------------------------------------- |
| `/`                                        | New thread                            |
| `/:id` and `/:id/(chat\|gallery)`          | A thread, as a chat or as its gallery |
| `/space/:spaceId`                          | A space's threads                     |
| `/media`, `/favourites`                    | Media library, favourites             |
| `/characters`, `/instructions`, `/presets` | Library pages                         |
| `/usage`, `/requests`                      | Credit usage, provider request log    |
| `/settings`, `/tools`                      | Settings, tools and library menu      |

## Layout

```
src/
├── api/             # The typed client
│   ├── schema.d.ts  #   generated from the backend's OpenAPI (never edit)
│   ├── paths.ts     #   turns `paths` into a typed `api.get('/x/${id}')`
│   ├── http.ts      #   requests, errors, uploads, downloads
│   └── json.ts      #   the one place server JSON gets its type
├── composables/     # Logic. `*Api.ts` wrap endpoints; `use*.ts` are stateful composables
│   ├── useChat.ts   #   facade over the `chat*Api.ts` modules (tests mock this one seam)
│   ├── useStudio.ts #   the Studio's whole state, built from the `useStudio*` pieces
│   └── studioTypes.ts # shared UI types (UiMessage, GenerationItem, panes…)
├── components/      # <script setup lang="ts"> components
│   ├── form/  media/  characters/  chat/  studio/
│   └── *.vue        #   dialogs, toasts, login
├── views/StudioView.vue
├── utils/           # Pure helpers (formatting, storage, ref planning, card specs…)
├── injection.ts     # Typed InjectionKeys (toast, composer settings, model catalogues)
├── router/  main.ts  App.vue  style.css
└── __tests__/       # Vitest, plus typed fixtures and helpers (see below)
```

## How the types work

- The backend's Pydantic models are exported as OpenAPI (`scripts/export_openapi.py`) and turned into
  `src/api/schema.d.ts` by `openapi-typesafe`. The client in `api/` takes request and response types from it,
  so a path the backend doesn't serve, or a body of the wrong shape, is a compile error.
- Server JSON is trusted only through that generated schema. Anything else read from outside (localStorage,
  third-party catalogue rows, a media card's open-JSON `params`) is parsed where it enters:
  `utils/storage.ts` plus `readShape` for stored settings, `utils/cardSpecs.ts` for card params.
- Components declare props and emits with `defineProps<…>()` / `defineEmits<…>()`. Under
  `exactOptionalPropertyTypes`, an optional prop is written `x?: T | undefined`; templates read `props.x` where
  a default makes it non-optional.
- `useChat.ts` stays as the single facade over the API modules, so composables import from one path and tests
  mock one module.

## Scoped CSS

Styles are scoped per component, and scoped CSS does not reach into a child component. A parent that styles an
element a child owns must say so with `:deep(...)`, or the rule silently does nothing (this once left space
names in the sidebar underlined).

## Tests

Tests are `*.test.ts` in `src/__tests__/`, run by Vitest with `globals: true` and a jsdom environment.

- `models.ts`: typed builders for every row a test needs (`uiMessage`, `serverMessage`, `mediaCard`,
  `libraryEntry`, `character`, `space`, `imageModel`…). They are complete, as the backend serves them, so a test
  spells out only what it cares about and a fixture can't drift from the real shape.
- `fakeServer.ts`: answers every `fetch` from one function and records the calls.
- `dom.ts`: `one` / `all` / `defined` for reading the document (teleported dialogs live in `<body>`) and the
  `Wrapper` type for helpers that take a mounted component. `intersection.ts` drives `IntersectionObserver`.
- `src/vue-shim.d.ts` lets typed ESLint resolve `.vue` imports (it can't open them); `vue-tsc` still checks the
  real component types.
- A test that starts failing after a type change is usually a fixture or fake-server answer missing a field the
  backend always sends: complete the fixture rather than loosening the type.
