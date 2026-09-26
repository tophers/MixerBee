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
| `accounts` | Local usernames, password hashes, owner flag, and creation time. |
| `account_sessions` | Hashed session token, CSRF token, selected connection, and expiry. Selection is per browser session. |
| `media_connections` | Owner-bound Emby/Jellyfin identity, credentials, AI settings, API key material, webhook secret, and webhook lifecycle timestamps. |
| `connection_presets` | Stable preset ID, connection ID, name, and block JSON. Names are unique only within a connection. |
| `schedules` | APScheduler-facing job definition, target media user, connection ID, optional stable preset ID, serialized configuration, and last-run result. |
| `settings` | Installation-wide values and migration markers, including the canonical webhook base URL. |
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
- Manual/webhook runs use deterministic queued-job IDs and a five-minute misfire grace period so executor congestion does not silently discard rebuilds.
- Last-run timestamp, status, and log messages are persisted to SQLite and mirrored in memory.

The scheduler also runs a periodic cache refresh across all saved connections. Schedules continue to run while their local owner is signed out.

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
- `items.py`: Playlist and collection CRUD plus quick-build generators such as Recently Added, Continue Watching, Forgotten Favorites, Movie Marathon, and music playlists.
- `movies.py`: Movie library, genre, people, studio, year, runtime, watch-state, and item-selection queries.
- `tv.py`: Series and episode queries, manual episode resolution, next/first/random unwatched logic, and watched-state changes.
- `music.py`: Music genres, artists, albums, tracks, and music-filter selection.
- `people.py`, `studios.py`, `users.py`: Focused metadata and user API wrappers.
- `logger.py`: Central logger factory with runtime verbosity refresh.

Domain functions receive a `MediaClient` explicitly or run inside its scoped context. They must not infer a browser's active connection from global process state.

## 9. AI and semantic search (`app/ai/`)

- `__init__.py`: Public exports for smart-block generation, enrichment, and library-IQ calculations.
- `orchestrator.py`: Ollama/Gemini routing, prompt construction, tool calling, multi-phase playlist design, and enrichment batching.
- `tools.py`: Media-aware functions exposed to LLM tool calling.
- `vector_store.py`: ChromaDB collection lifecycle, indexing, enrichment metadata, mood discovery, and Echo/composite similarity searches.

Every vector collection is named from the connection ID (`mixerbee_{connection_id}`). Vector helpers use the initiating media context, so overlapping media IDs on different servers or users cannot select the wrong index. Enrichment backups and media-type caches are also keyed by connection. New installations default to Ollama; Gemini remains available when configured.

## 10. Frontend state (`static/js/`)

Alpine stores are registered with lightweight placeholders in `_head.html`, then hydrated with the module implementations in `app.js` after authentication.

- `accessGate.js`: Initial owner setup, login, session handoff, and forced reload on unauthorized/stale-session events.
- `apiClient.js`: Native `fetch` wrapper. Pins account, CSRF token, and selected connection headers and normalizes responses to `{data, error, status}`.
- `app.js`: Hydrates Alpine stores, initializes modals, loads account/configuration state, handles connection recovery, loads the selected library, and then initializes presets and Builder state.
- `settingsStore.js`: Account menu, connection list/selection/removal, connection settings, AI configuration, external keys, webhook URL/state, owner webhook inbox, public callback base URL, and theme.
- `mixerStore.js`: Builder blocks, draft persistence, search suggestions, previews, and build actions. Draft keys include the connection ID.
- `presetStore.js`: Stable preset catalog, current preset, load/save/delete/import/export behavior, and ID/name mapping for schedules.
- `schedulerStore.js`: Schedule loading, editing, validation, stable preset selection, permission-aware collection options, and manual runs.
- `managerStore.js`: Playlist/collection browsing and mutations, including permission-aware collection controls and copy-to-playlist behavior.
- `aiStore.js`: AI prompt state, model switching, mood discovery, and AI-generated blocks.
- `blockFactory.js`: Default state factory for each Builder block type.
- `definitions.js`: Block and quick-build definitions.
- `modals.js`: Promise-based modal actions and toast-history integration.
- `uiStore.js`: Top-level tab state.
- `utils.js`: Toasts, browser-session notification history, loading/button wrappers, debouncing, and UUID generation.
- `header.js`: One-time typewriter animation controlled by `localStorage`.

The browser notification history is deliberately ephemeral. Persistent administrative webhook requests live in SQLite and are fetched through the owner API.

## 11. Templates and styling

- `templates/index.html`: Main shell, authentication overlay, connection-recovery states, pane container, and partial includes.
- `_head.html`: Styles, vendored script imports, inline SVG icon store, and placeholder Alpine stores used before module hydration.
- `_access_gate.html`: Initial setup and login UI.
- `_nav.html`: Connection selector, Add Connection action, owner-request badge, account menu, and Builder/Scheduler/Manager tabs.
- `_accounts.html`: Password changes, owner household-account management, canonical webhook URL setting, and persistent webhook setup inbox.
- `_builder_pane.html`, `_scheduler_pane.html`, `_manager_pane.html`: Main application views.
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
