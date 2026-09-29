# MixerBee Architecture Map

## Overview

MixerBee is a FastAPI and Alpine.js application for building, managing, and scheduling smart playlists and collections on Emby and Jellyfin. SQLite stores local accounts, saved media connections, presets, schedules, integration credentials, and global settings. ChromaDB provides a connection-isolated semantic index for AI search and enrichment through Ollama or Gemini.

The frontend has no Node.js build step. It uses Jinja2 partials, vendored Alpine.js, native JavaScript modules, and a single CSS stylesheet.

MixerBee has two distinct identity and permission layers:

1. A **local MixerBee account** controls sign-in, workspace ownership, connection selection, and installation-owner actions.
2. A **saved media connection** identifies one Emby or Jellyfin server and one authenticated media-server user. That user's server policy controls operations such as collection management.

These identities are intentionally not interchangeable. The MixerBee installation owner cannot browse another member's workspace, and being a MixerBee owner does not grant administrator rights on a media server.

## Request and execution model

```text
Browser session ──► account middleware ──► owned connection ──► MediaClient
                         │                       │                    │
                         │                       ├─ presets           ├─ Emby/Jellyfin API
                         │                       ├─ schedules         └─ current user policy
                         │                       ├─ cache
                         │                       └─ AI/vector index
                         │
External API key ────────┴────────────────► key-bound connection

Webhook URL + secret ─────────────────────► connection schedules
Scheduler job ────────────────────────────► persisted connection ID
```

- Browser API requests are authenticated by a local session. The selected connection is stored on that session and pinned into requests by the frontend.
- `routers.dependencies.owned_connection()` verifies that a requested connection belongs to the signed-in account before any browser operation resolves a media client.
- External API keys bypass browser sessions only for `/api/external/*`; each key resolves exactly one connection.
- Webhooks authenticate with a connection-specific URL and secret, then fan out only to schedules assigned to that connection.
- Background jobs do not use the active browser selection. They resolve the `connection_id` persisted on the schedule.

## 1. Application entry point and lifecycle

- `web.py`: Creates the FastAPI application, applies API security middleware, mounts static files and routers, serves the Jinja2 shell, and owns process startup/shutdown.
- `runtime_paths.py`: Resolves the configuration directory. `MIXERBEE_CONFIG_DIR` can select an isolated directory for development or tests; Docker defaults to `/config`, while non-container installs default to `config/`.
- `app_state.py`: Retains legacy/bootstrap configuration and process-level operational settings such as cache refresh and webhook debounce intervals. Connection credentials and AI settings are no longer read from it during normal request execution.
- `database.py`: Opens SQLite in WAL mode with foreign keys enabled, creates the legacy base tables, and delegates account/connection schema creation and additive migrations.
- `models.py`: Pydantic request models used by the API routers.

During FastAPI lifespan startup, MixerBee:

1. Initializes and migrates SQLite.
2. Imports legacy environment configuration only when no local account exists.
3. Starts a background warm-up pass for every saved connection, refreshing its library cache and AI index when configured.
4. Loads persisted schedules into APScheduler and starts the scheduler.

Shutdown stops APScheduler cleanly.

## 2. Local accounts, sessions, and API security

### Account model

- `accounts.py`: Implements local account creation, `scrypt` password hashing, authentication, rate limiting, session creation/revocation, password changes, and per-origin cookie names.
- `routers/accounts.py`: Exposes initial setup, login/logout, password changes, installation-owner account management, connection selection/removal, and webhook administration.
- `static/js/accessGate.js`: Blocks application initialization until `/api/auth/status` reports an authenticated session. It switches between first-owner setup and normal login without a separate setup token.
- `manage_accounts.py`: Provides command-line account listing and password recovery for administrators with host access.

The first successfully created local account is the installation owner (`is_admin=1`). Only that account can create household accounts or use the webhook-administration endpoints. There is currently one owner role; account deletion and ownership transfer are not exposed.

### Sessions and middleware

`web.py` enforces the following before protected API routes execute:

- Local sessions use random tokens stored as SHA-256 hashes in SQLite and expire after seven days.
- Session cookies are HTTP-only, `SameSite=Strict`, and `Secure` when served over HTTPS.
- Login, setup, and password checks are rate-limited by client address.
- The browser sends `X-MixerBee-Account` and `X-MixerBee-CSRF`. A mismatched account or CSRF token returns `409` so stale tabs reload instead of operating as a different signed-in user.
- State-changing browser calls are checked against the request origin. Webhook and external-integration routes are exempt because they use their own credentials.
- API responses receive `Cache-Control: no-store`.

Public routes are limited to authentication status/setup/login and the health endpoint. Webhooks are public at the HTTP layer but require their connection secret. External routes require `X-MixerBee-Key`.

## 3. Saved media connections and ownership

- `connections.py`: Creates and migrates connection storage, saves authenticated connections, performs the one-time legacy assignment, derives webhook state, and maintains the in-process `MediaClient` registry.
- `app/media_client.py`: Defines immutable `Connection` data and the connection-bound `MediaClient` used for all normal media-server requests.
- `routers/dependencies.py`: Centralizes browser ownership checks, media-user validation, current connection resolution, and background-job connection lookup.

A saved connection contains the server type and URL, authenticated server/user identity, credentials, a user label, AI configuration, external API credentials, and webhook state. Its stable UUID is derived from the local owner plus the media server and media user identity. Updating a saved connection cannot silently change it into a different server or user.

`MediaClient` provides:

- Connection-specific authorization headers and device identity.
- Token refresh and server/user identity validation.
- Thread-local `requests.Session` objects so concurrent jobs do not mutate shared HTTP state.
- A five-minute authentication check window.
- Validation that user-scoped paths and `UserId` parameters match the connection's media user.
- Current media-server administrator capability through `User.Policy.IsAdministrator`.
- A context-variable scope used by synchronous AI/vector helpers without falling back to a global active connection.

Browser requests may resolve only connections owned by the current local account. The installation owner has narrow administrative visibility into pending webhook requests but does not receive general access to household members' connections, presets, schedules, or libraries.

Removing a connection deletes its local schedules, presets, cached data, AI index, integration credentials, and saved media credentials. It cancels registered and queued schedule jobs and selects another owned connection when possible. It does not delete playlists or collections from Emby or Jellyfin.

## 4. SQLite data model

SQLite is the authoritative local store. Important tables are:

| Table | Purpose and scope |
| --- | --- |
| `accounts` | Local usernames, password hashes, owner flag, creation time, and the account-wide `ai_disabled` preference. |
| `account_sessions` | Hashed session token, CSRF token, selected connection, and expiry. Selection is per browser session. |
| `media_connections` | Owner-bound Emby/Jellyfin identity, credentials, AI settings, API key material, webhook secret, and webhook lifecycle timestamps. |
| `connection_presets` | Stable preset ID, connection ID, name, and block JSON. Names are unique only within a connection. |
| `schedules` | APScheduler-facing job definition, target media user, connection ID, optional stable preset ID, serialized configuration, and last-run result. |
| `settings` | Installation-wide values and migration markers, including the canonical webhook base URL and `ai_provider_optin_migrated`. |
| `presets` | Retained legacy preset table used only for one-time migration and rollback compatibility. |

Schema changes use additive `CREATE TABLE IF NOT EXISTS` and `ALTER TABLE` migrations during startup. The application stores media-server and AI credentials in local SQLite using the existing plaintext-at-rest model; configuration directories and backups must be protected accordingly.

### Legacy migration

The first installation owner claims previously unowned saved connections without changing their IDs. On the first eligible connection migration:

- Legacy presets are copied into that connection's namespace while the original table is retained.
- Legacy schedules with a matching media user are assigned to the connection; unmatched jobs remain inactive rather than being guessed onto a server.
- Name-based builder/preset schedules are linked to matching stable preset IDs when possible.
- The legacy shared Chroma collection and browser draft are not automatically attributed to a user because their original permission context is unknown.

See [Connection refactor](docs/CONNECTION_REFACTOR.md), [multi-user testing](docs/MULTI_USER_TESTING.md), and [2026.10.0 release notes](docs/RELEASE_NOTES_2026.10.0.md) for migration and acceptance details.

## 5. API routers (`routers/`)

- `accounts.py`: Authentication, household-account administration, owned connection listing/selection/removal, canonical webhook URL administration, and the owner webhook-request inbox.
- `assist.py`: Playlist Assist availability, one conversational curation turn, and the create-only save that writes the finished playlist to the media server.
- `builder.py`: Random block generation, AI prompt-to-block generation, preview/build operations, and connection-keyed external build endpoints.
- `config.py`: Connection testing and persistence, per-connection AI settings, external API key and webhook-secret lifecycle, Ollama status, model selection, and vector-index maintenance.
- `dependencies.py`: Ownership enforcement and explicit connection/media-client resolution for browser, external, and background execution.
- `library.py`: Connection-scoped library data, semantic discovery, media-user identity/capability data, episode lookup, and playlist/collection management operations.
- `presets.py`: Connection-scoped preset catalog, save/delete operations, stable preset identity, scheduled-use protection, and external prompt-to-preset creation.
- `quick_playlists.py`: Immediate quick-build endpoints such as Recently Added, Continue Watching, and other predefined playlist types.
- `scheduler.py`: Connection-scoped schedule CRUD and manual-run endpoints, stable preset binding, and server-side collection permission enforcement.
- `webhooks.py`: Connection-specific secret validation, event parsing, setup verification, debounce scheduling, and schedule fan-out.

Collection permission is enforced in router dependencies and at mutation boundaries, not only in the frontend. A normal media user may manage playlists and copy a visible collection into a playlist but cannot create, replace, reorder, or delete collections through MixerBee.

## 6. Presets, schedules, and automation

### Presets

- `preset_manager.py` stores presets in `connection_presets` and resolves them by stable ID or connection-local name.
- Saving over the same name preserves its existing ID.
- First-party clients use `/api/presets/catalog`, which returns ID, name, and decoded block data.
- A preset referenced by one or more schedules cannot be deleted until those schedules are reassigned or removed.

### Scheduler

- `scheduler.py` wraps APScheduler's background scheduler and mirrors persisted jobs in an in-memory dictionary keyed by schedule ID.
- Fixed-time jobs use cron expressions; interval jobs use `IntervalTrigger`.
- Builder/preset schedules store a stable `preset_id` and load the latest preset contents when they run. Jobs with embedded blocks do not bind to a preset.
- Quick-playlist and AI enrichment schedules carry their own typed configuration.
- Every job requires a saved `connection_id`; unassigned legacy jobs load but remain inactive.
- Cron, webhook, and manual runs all enter `scheduled_job_wrapper()`.

Concurrency is controlled per schedule:

- A nonblocking lock prevents two executions of the same schedule from modifying the same server item concurrently.
- A trigger received during a running job sets a pending-rerun flag instead of starting an overlap.
- Reruns reload the latest in-memory schedule definition and are capped at three consecutive passes.
- Manual/webhook runs use deterministic queued-job IDs.
- Every job carries a five-minute misfire grace period via APScheduler `job_defaults` (the default is one second), so a fire that came due during downtime or executor congestion is not silently discarded. `coalesce` collapses a backlog into a single catch-up run; it is APScheduler's default and is set explicitly alongside it.
- A run re-verifies that its schedule still exists in SQLite before building, so a schedule deleted while its run was already on a pool thread cannot produce a ghost playlist.
- `reload_schedules()` re-reads the table and resyncs APScheduler jobs; a backup restore calls it so restored schedules become active and deleted ones stop firing without a process restart. `_load_schedules()` raises rather than returning `{}` when the read fails, so a transient database error cannot be mistaken for an empty table and tear down every live job.
- Last-run timestamp, status, and log messages are persisted to SQLite and mirrored in memory.

The scheduler also runs two recurring system jobs: `cache_refresh_job` refreshes every saved connection's library cache, and `vibe_index_catchup_job` retries any connection whose vibe index has not yet been built successfully in this process (a server that was unreachable at startup). They are separate jobs because APScheduler's `max_instances` is 1 per job, so a long index run would otherwise suppress cache refreshes for its whole duration. Schedules continue to run while their local owner is signed out.

## 7. Webhooks and external integrations

### Webhooks

Each connection uses `/api/webhook/{connection_id}?token={secret}`. The old shared `/api/webhook` route returns `410 Gone` because it cannot identify a safe account/server execution scope.

After secret validation, `routers/webhooks.py`:

1. Requires valid JSON with an event name.
2. Records the first valid event as proof that the current secret and callback URL are installed.
3. Ignores incomplete playback-stop events to avoid rebuild thrashing.
4. Extracts the media user and item type for logging and routing.
5. Coalesces relevant event bursts through a connection/user-specific debounce job.
6. Queues every non-enrichment schedule for that connection that matches the event user, or all such schedules when no user is supplied.

Webhook status is derived from secret and lifecycle timestamps as `disabled`, `needs_setup`, `setup_requested`, `waiting_for_event`, or `connected`. Household members generating or rotating a secret create a persistent owner request. The installation owner can copy the exact callback URL, acknowledge installation, and configure a global media-server-reachable base URL. Verification occurs only after MixerBee receives a valid authenticated event for the current secret.

### External API keys

Each connection may have one external API key. MixerBee stores the key for later display and a SHA-256 hash for lookup. An `X-MixerBee-Key` presented to `/api/external/*` resolves only that connection, and browser-supplied connection headers cannot redirect the request to another workspace. External credentials do not grant access to ordinary settings or account routes.

## 8. Core media domain (`app/`)

- `__init__.py`: Compatibility/public import surface used as `app as core`. It re-exports the media-building and item-management functions used by routers and schedules.
- `client.py`: Legacy/bootstrap facade and compatibility exports. Normal connection-bound HTTP execution lives in `media_client.py`.
- `media_client.py`: Saved connection model, authentication, HTTP transport, media-user enforcement, policy lookup, and scoped execution context.
- `cache.py`: Per-connection library metadata cache with a separate refresh lock for each connection. Failed refreshes remove the old visibility snapshot instead of serving potentially unauthorized data.
- `builder.py`: Converts ordered block definitions into media IDs, formats previews, and creates or appends to mixed playlists.
- `items.py`: Playlist and collection CRUD plus quick-build generators such as Recently Added, Continue Watching, Forgotten Favorites, Movie Marathon, and music playlists. `create_playlist()` adopts and replaces a same-named playlist; `create_playlist_exclusive()` never does, and rolls back through `delete_playlist_by_id()` rather than the name-matching `delete_playlist()`.
- `movies.py`: Movie library, genre, people, studio, year, runtime, watch-state, and item-selection queries.
- `tv.py`: Series and episode queries, manual episode resolution, next/first/random unwatched logic, and watched-state changes.
- `music.py`: Music genres, artists, albums, tracks, and music-filter selection.
- `people.py`, `studios.py`, `users.py`: Focused metadata and user API wrappers.
- `ai_policy.py`: The single source of truth for whether generative AI is available. Reads only persisted account and connection records -- it imports neither chromadb nor a provider SDK, so the policy is answerable for a connection whose vector store has never been opened. Also owns the one-time provider opt-in migration.
- `logger.py`: Central logger factory with runtime verbosity refresh.

Domain functions receive a `MediaClient` explicitly or run inside its scoped context. They must not infer a browser's active connection from global process state.

### AI availability policy

Two questions that used to be conflated are now decided separately, and `app/ai_policy.py`
is the only place either is answered:

```text
generative_ai_available = not account.ai_disabled and selected_provider_is_configured
semantic_search_allowed = connection_exists
```

- **Generative AI** covers prompt-to-blocks, Playlist Assist, enrichment tagging, Library IQ,
  enrichment-tag prompt suggestions, and Ollama discovery. It needs the owning account to allow it
  *and* a deliberately configured provider on the connection.
- **Semantic search** covers ChromaDB indexing, local embeddings, Echo/`mirror` blocks, and
  similarity search. Nothing in the policy gates it. Startup warming, `warm_connection()`, and
  `vibe_index_catchup_job()` index every usable connection with or without a provider; enrichment
  writes into the same store, so the *enrichment workflow* is gated rather than vector writes.
- **Deliberate setup is the consent signal.** An empty `AI_PROVIDER` means no generative AI. New
  connections store one, `POST /api/settings` never writes `ai_settings` at all, and
  `save_authenticated_connection()` leaves an existing row's AI settings untouched -- that is what
  used to let a stale connection form erase a configured provider. `POST /api/settings/ai` is the
  only writer, and it validates only the selected provider's own requirements.
- **Enforcement is at the service layer, not only HTTP.** `require_generative()` is called inside
  `generate_smart_blocks()`, `run_assist_turn()`, `start_enrichment()`, and
  `process_enrichment_queue()`, because a cached `MediaClient` held by a worker cannot be
  invalidated by clearing the registry. Workers recheck before every batch, every item, and before
  writing an enrichment result, so a request already in flight finishes on its own and its result
  is discarded rather than stored.
- **Reasons are machine-readable.** `403` + `disabled_by_user` for an opt-out, `409` +
  `ai_not_configured` for missing setup, checked outside the routers' broad exception handlers so
  neither collapses into a generic `500`. `apiClient.js` flattens the structured `detail`, and
  deliberately does *not* treat a reason-bearing `409` as a stale session, which would otherwise
  reload the page and discard the user's draft.
- **Upgrades opt in once.** `migrate_provider_optin()` keeps any provider it can prove was chosen
  (a Gemini key, a non-default Ollama URL/model/timeout, a starred model, an existing enrichment
  schedule) and clears only the *selection* on connections that held nothing but the old
  auto-filled defaults. Stored values are preserved and localhost is never probed.

## 9. AI and semantic search (`app/ai/`)

- `__init__.py`: Public exports for smart-block generation, enrichment, and library-IQ calculations.
- `orchestrator.py`: Ollama/Gemini routing, prompt construction, tool calling, multi-phase playlist design, and enrichment batching for the Builder's block generation.
- `assist_orchestrator.py`: Playlist Assist turn runner. Routes one chat turn to Gemini or Ollama, enforces the tool/size/history/deadline budgets, and applies deterministic pin restoration before returning a resolved canvas.
- `tools.py`: Media-aware functions exposed to LLM tool calling. `AVAILABLE_TOOLS` serves the Builder from the library cache; `ASSIST_TOOLS` serves Playlist Assist through live authenticated server searches, because the cache holds no full movie catalogue.
- `vector_store.py`: ChromaDB collection lifecycle, indexing, enrichment metadata, mood discovery, and Echo/composite similarity searches. Its `ai_enabled()` now delegates to `ai_policy` and answers only the *generative* question; it is never a gate on indexing or similarity search.
- `enrichment_manager.py`: Per-connection enrichment worker state, the concurrency guard, cooperative cancellation, and `stop_all_for_account()`, which the account preference endpoint calls after persisting a disable.

### Playlist Assist

Playlist Assist curates one flat list of **movies** through conversation; Series-to-episode and
Album-to-track resolution is deliberately out of scope for this phase. Two invariants carry the
feature:

- **Pins are enforced by the backend, not the prompt.** `enforce_pins()` cross-references the
  canvas the browser sent and re-injects any `locked` item the model dropped at its original index.
  Pins beat the size cap: the cap only ever trims unpinned items. A pin that no longer resolves on
  the media server voids the whole turn with a `400` rather than silently producing a different
  playlist.
- **A response is never discarded.** The canvas stays editable while a turn is in flight, so
  `assistStore.js` tracks each mid-flight edit and replays it onto the arriving `new_items`. The
  three actions are distinct operations: a removal drops the item, a pin may have to re-insert an
  item the model never knew was pinned, and an unpin clears a lock without removing anything. The
  echoed `revision_id` is only a fast path for skipping that merge, never a reason to drop a
  response. The chat input is locked during a turn because two concurrent turns can return out of
  order and `revision_id` cannot disambiguate them.

Two further rules keep a small local model from putting the wrong films in the playlist:

- **The candidate pool is filtered before the model sees it.** Emby's `SearchTerm` is a bare
  substring match, so asking for "Tank Girl" also returns "Stolen Girl" and "Working Girl", and the
  vector index has no usable notion of a release period, so "90s sci-fi" returns 2025 titles.
  `_match_rank()` admits only exact, prefix, or whole-token-containment title matches (a similarity
  ratio cannot do this: "Tank Girl"/"Stolen Girl" scores higher than "The Matrix"/"The Matrix
  Reloaded"), and `semantic_movie_vibe_search` takes a `year_from`/`year_to` window applied as a
  hard filter over an over-fetched pool.
- **Release-year constraints are declared by the model and enforced by the backend.** The model
  names the window in its response; `run_assist_turn` applies it to authoritative `ProductionYear`
  values. Asking a 7B model to apply a year predicate across a dozen items by hand is unreliable;
  asking it to name the window is not. Pins are exempt, per the collision rule.
- **Only sourced IDs survive.** `TurnLedger` records every ID the tools actually returned, and the
  final list is intersected with (canvas ∪ ledger). Resolving on the server is not sufficient proof
  on its own: incidental search noise and invented IDs both resolve perfectly well.

The canvas is re-resolved from the media server at the top of every turn. The browser sends only
`{Id, locked, Name}`, so building the manifest from the request would show the model `(Unknown)`
for every release year and then ask it to filter by year.

Vibe search is omitted from the toolset entirely when the connection's vector collection is empty,
detected by counting the collection inside the connection's scope. `connection_needs_index()` is
not used for this: it reports process-local state and would disable vibe search on every restart.

`resolve_movies()` is MixerBee's own uncapped lookup; `get_movie_metadata()` is the model-facing
tool and caps at `MAX_ASSIST_METADATA_IDS`. Internal callers (a vibe pool awaiting a year filter, a
canvas being validated, a save of more than 60 items) must use the former or they silently truncate.

Saving goes through `create_playlist_exclusive()`, so Assist can never adopt or overwrite a
same-named playlist the user already has. The description needs a second call (Emby's
`POST /Playlists` takes no `Overview`) and a failure there returns a partial-success warning rather
than deleting the playlist. Every save records a `build_runs` row with `trigger_source='assist'`.

Every vector collection is named from the connection ID (`mixerbee_{connection_id}`). Vector helpers use the initiating media context, so overlapping media IDs on different servers or users cannot select the wrong index. Enrichment backups and media-type caches are also keyed by connection. New installations default to Ollama; Gemini remains available when configured.

## 10. Frontend state (`static/js/`)

Alpine stores are registered with lightweight placeholders in `_head.html`, then hydrated with the module implementations in `app.js` after authentication.

Every AI capability flag starts `false` in both the placeholder and the real store, and the
authoritative values arrive from `/api/config_status` before any AI store begins work, so no AI
control can render and no AI request can fire before the server has been asked. The backend stays
authoritative for a tab left open: capability is refreshed when the tab regains focus and after any
policy rejection.

- `accessGate.js`: Initial owner setup, login, session handoff, and forced reload on unauthorized/stale-session events.
- `apiClient.js`: Native `fetch` wrapper. Pins account, CSRF token, and selected connection headers and normalizes responses to `{data, error, status}`.
- `app.js`: Hydrates Alpine stores, initializes modals, loads account/configuration state, handles connection recovery, loads the selected library, and then initializes presets and Builder state.
- `settingsStore.js`: Account menu, connection list/selection/removal, connection settings, AI configuration, external keys, webhook URL/state, owner webhook inbox, public callback base URL, and theme. It also holds the authoritative AI capability (`applyCapability`/`refreshCapability`/`setAiDisabled`); every template and store reads `generative_ai_available` from here rather than deriving it from form inputs.
- `mixerStore.js`: Builder blocks, draft persistence, search suggestions, previews, and build actions. Draft keys include the connection ID.
- `presetStore.js`: Stable preset catalog, current preset, load/save/delete/import/export behavior, and ID/name mapping for schedules.
- `schedulerStore.js`: Schedule loading, editing, validation, stable preset selection, permission-aware collection options, and manual runs.
- `managerStore.js`: Playlist/collection browsing and mutations, including permission-aware collection controls and copy-to-playlist behavior.
- `aiStore.js`: AI prompt state, model switching, mood discovery, and AI-generated blocks. Its generative lifecycle (Library IQ, enrichment polling, mood discovery) starts only when `generative_ai_available` is true and is torn down by `stopGenerativeActivity()` on a disable. A `_capabilityToken` is captured by every mutating request so a late response cannot repopulate the panels or restart the poll chain. `runSemanticRefresh()` is deliberately outside that lifecycle: index maintenance must never start enrichment polling.
- `assistStore.js`: Playlist Assist chat history, movie canvas, pins, undo snapshots, and the client-side merge that replays mid-flight edits onto an arriving response.
- `blockFactory.js`: Default state factory for each Builder block type.
- `definitions.js`: Block and quick-build definitions.
- `modals.js`: Promise-based modal actions and toast-history integration.
- `uiStore.js`: Top-level tab state.
- `utils.js`: Toasts, browser-session notification history, loading/button wrappers, debouncing, and UUID generation.
- `header.js`: One-time typewriter animation controlled by `localStorage`.

The browser notification history is deliberately ephemeral. Persistent administrative webhook requests live in SQLite and are fetched through the owner API.

## 11. Templates and styling

- `templates/index.html`: Main shell, authentication overlay, connection-recovery states, pane container, and partial includes.
- `_head.html`: Styles, vendored script imports, inline SVG icon store, and placeholder Alpine stores used before module hydration. The placeholders start with generative AI unavailable.

Generation and enrichment entry points share one gate, `$store.settings.generative_ai_available`:
the Assist tab and pane, the header and Builder Library IQ buttons, the AI Builder launcher and its
generator/mood/model/tweaks controls, the AI Hub's enrichment panel, and enrichment schedule
creation. The AI Hub itself and its provider fields are gated on `!ai_disabled`, so setup stays
reachable while AI is allowed but unconfigured. Echo creation, "Find Similar", semantic search, and
index maintenance are never gated -- index maintenance lives in Connection settings under
**Library Search & Indexing** precisely so hiding the hub cannot strand it.
- `_access_gate.html`: Initial setup and login UI.
- `_nav.html`: Connection selector, Add Connection action, owner-request badge, account menu, and Builder/Assist/Scheduler/Manager tabs.
- `_accounts.html`: Password changes, owner household-account management, canonical webhook URL setting, and persistent webhook setup inbox.
- `_builder_pane.html`, `_assist_pane.html`, `_scheduler_pane.html`, `_manager_pane.html`: Main application views.
- `_block_header.html`: Shared block title, drag handle, and removal controls.
- `_tv_block.html`, `_movie_block.html`, `_music_block.html`, `_vibe_block.html`, `_curated_block.html`, `_mirror_block.html`: Builder block editors. Echo/Mirror uses positive and negative semantic seeds and may store a preview snapshot.
- `_modals.html`: Settings, integration controls, previews, confirmations, imports, AI tweaks, reset-watch actions, and ephemeral notification history.
- `static/css/main.css`: Theme variables, responsive layout, components, account/integration states, and all modal/pane styling.
- `static/vendor/`: Vendored Alpine.js core and sort plugin; no package manager or bundler is required.

## 12. Testing and operational boundaries

- `regression_tests/test_connections.py`: Offline connection, migration, cache/vector isolation, concurrency, AI context, schedule, and HTTP execution coverage.
- `regression_tests/test_accounts.py`: Local account/session security, workspace ownership, integration credential, connection removal, webhook workflow, and migration coverage.
- Tests set an isolated `MIXERBEE_CONFIG_DIR`, use temporary SQLite databases, mock media-server network calls, and do not modify a development installation.

Run the suite from the project root:

```sh
.venv/bin/python -m unittest discover -s regression_tests -p 'test_*.py'
```

Current architectural boundaries:

- Local account and connection ownership cannot be transferred.
- Account deletion is not exposed in the UI.
- Credentials are not encrypted at rest.
- The media server remains authoritative for library visibility and playlist/collection permissions.
- Webhooks trigger configured non-enrichment schedules, not standalone Builder outputs.

## 13. Deployment layout

- `config/`: Default non-container configuration directory containing `.env`, `mixerbee.db`, and `chroma_db/`.
- `mixerbee_config/`: Host directory mounted as `/config` by the supplied Compose setup.
- `examples/`: Environment and systemd templates.
- `Dockerfile`: Python 3.14 container build.
- `docker-compose.yml`: Single-service development/build deployment with persistent configuration mounting.
- `requirements.in` / `requirements.txt`: Direct and pinned Python dependencies.

`MIXERBEE_ROOT_PATH` controls reverse-proxy path mounting. Its default is empty in a container and `/mixerbee` outside a container.
