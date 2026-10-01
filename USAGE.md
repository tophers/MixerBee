# Usage and behavior

This guide describes current account, connection, build, automation, integration, and backup behavior. See [Installation](INSTALL.md) for deployment and [README](README.md#block-types) for the available Builder blocks.

## Accounts and workspaces

MixerBee accounts are local to the installation and are separate from Emby or Jellyfin accounts.

- The first local account is the installation owner. It can create and remove household accounts from **Account settings** and review household webhook setup requests.
- To remove a member, open **Account settings → Household accounts**, click **Remove** beside their name, and confirm. This permanently deletes their local MixerBee account, browser sessions, connections and credentials, presets, recipes, schedules, build history, and AI indexes. Their Emby/Jellyfin account, playlists, and collections are unchanged. The installation owner cannot be removed.
- Removal prevents future scheduled runs; requests already sent to a media server may still finish.
- Every account has an independent workspace. One member cannot see another member's connections, presets, schedules, library data, AI index, keys, or Builder drafts.
- Changing a local password signs out every browser session for that account. Its saved schedules continue running.
- The installation owner does not automatically gain administrator permission on Emby or Jellyfin and cannot browse another member's workspace.

If a password is lost, the host administrator can use the recovery commands in [Installation](INSTALL.md#local-account-recovery).

## Media connections

Each account can save multiple Emby or Jellyfin connections. A connection belongs to one local MixerBee account and one media-server user on one server.

- Use the header selector to change connections. Presets, schedules, Builder drafts, library data, integration credentials, and AI settings follow the selected connection.
- Connection selection is stored per browser session, so two browsers can use different connections without redirecting each other's work.
- Saved connections continue supporting their schedules while the owner is signed out.
- If authentication or the server becomes unavailable, MixerBee shows a recovery state with **Try again** and **Check connection** actions.
- Removing a connection deletes its MixerBee credentials, presets, schedules, cached state, webhook/API credentials, and AI index. It does not delete playlists, collections, media, or watch history from Emby or Jellyfin.

MixerBee verifies a saved connection's media-server and user identity when credentials are updated. To connect a different server or media user, add a new connection instead of editing an existing one into a different identity.

## Media-server permissions

Available actions follow the selected Emby or Jellyfin user's current policy.

- Normal media users can browse permitted libraries and create or manage their own playlists where the server allows it.
- Collection creation, replacement, reordering, item removal, and deletion require a media-server administrator account.
- MixerBee hides collection mutation controls when the selected user is not an administrator and enforces the same rule in the backend.
- A visible collection can be copied into a playlist without modifying the original collection.

Library visibility also scopes caches and AI/vector results. Changing a media user's server permissions may require a reconnect or cache refresh before the UI reflects the new policy.

## Creating, replacing, and appending

When building a playlist, MixerBee looks for an existing playlist with the same name for the selected media user. Matching ignores capitalization and leading or trailing spaces. A match replaces that playlist's contents in place and preserves its server ID. Use a distinct name to keep the existing playlist and create another one.

Use the Builder's add-to-playlist mode to append items to a selected playlist instead of replacing its contents.

Movie collection builds resolve candidate movies before touching server state. If no items match, the build is refused and the existing collection remains untouched. For matching selections, MixerBee updates existing collections in place where supported by the server, preserving the server ID. If recreate is required, prior members are captured to attempt rollback upon failure. Collection builds return one of three explicit outcomes: `replaced`, `refused` (collection unchanged), or `failed`. Standard and scheduled collection builds require exactly one Movie block and media-server administrator permission.

Manager edits change the item stored on the media server, not the preset that generated it. A later scheduled rebuild can replace those manual edits. Update and save the source preset when an edit should affect future scheduled builds.

## Dynamic blocks and snapshots

Dynamic blocks store selection rules. Their output may change as the library and watch state change or when random selection is used. Scheduled builds evaluate the saved rules when the job runs.

Movie, Echo (Mirror), and Curated blocks support snapshots from their block preview. A snapshot records selected media IDs and their order. Unlocking the block clears the snapshot and returns it to rule-based selection. Snapshots do not copy media files or keep deleted/inaccessible items available.

For a one-off playlist matching the items and order currently displayed, use the preview's build action. Normal Builder builds may reuse cached block previews, so a manual build does not necessarily perform a new random selection.

## Drafts, presets, and share codes

Builder blocks are autosaved in the browser's local storage under the selected connection. The draft is specific to that browser, site address, and connection. Clearing browser data removes it, and it is not included in a MixerBee server backup.

Save a preset to keep block configuration in SQLite. Preset names need to be unique only within their connection. Loading another preset replaces the current Builder blocks; editing Builder blocks changes the saved preset only after choosing save/update.

Presets have stable internal IDs. Schedules bind to those IDs rather than relying only on editable names. A preset referenced by a schedule cannot be deleted until the schedule is reassigned or removed.

Preset export copies a share code for the currently saved preset. Save edits before exporting. Share codes can contain snapshots and media IDs from the originating server, so review all selections after importing into another connection or library.

## Schedules and timezones

Fixed-time schedules use the timezone of the machine or container running MixerBee, not the browser timezone. There is no timezone selector in the UI. Check it before choosing a daily or weekly time; for Docker, run:

```sh
docker exec mixerbee date
```

Interval schedules run every configured number of minutes. Restarting MixerBee recreates interval triggers, so the countdown begins again instead of resuming the previous interval.

Builder schedules assigned to a preset load the latest contents of that stable preset when they run. Updating the preset changes future runs; unsaved Builder changes do not. A missing assigned preset stops the job with an error. An intentionally empty builder configuration may fall back to a randomly generated Movie or TV block.

Scheduled collection builds require exactly one Movie block and an administrator-capable media connection. Enrichment schedules update the selected connection's semantic index and are not triggered by media-server webhooks. They are suspended, not deleted, while the owning account has AI disabled or the connection has no provider configured.

**Run Now** queues a background run. Its initial response confirms queuing, not completion. Check the schedule's last-run result or application logs for the final status. If the same schedule is triggered while already running, MixerBee queues a follow-up pass instead of overlapping the two writes; repeated reruns are capped.

The notification-history window contains only toasts from the current browser session. It is not a durable job history.

## Webhooks and live synchronization

Webhooks run configured non-enrichment schedules in addition to their normal timing. They do not refresh standalone one-off Builder outputs.

Every connection has a distinct webhook URL and secret. Generating a secret prepares MixerBee to receive events but does not configure Emby or Jellyfin:

- A household member generating or rotating a secret creates a persistent request for the installation owner.
- The owner reviews requests in **Account settings → Webhook administration**, copies the connection-specific URL, and configures it for the indicated media user.
- **Mark installed** changes the state to **Waiting for event**.
- MixerBee reports **Connected** only after receiving an authenticated event with a valid event name for the current secret.
- Rotating the secret invalidates the old URL and creates a new request. Disabling it rejects further calls and clears the setup state.

The owner should set **MixerBee URL reachable by media servers** when Emby or Jellyfin must use a different hostname, port, HTTPS origin, or reverse-proxy path than the browser uses.

Relevant event bursts are debounced for 30 seconds by default. A webhook affects only schedules on its connection and, when the payload identifies a user, only schedules for that media user. See [Webhook configuration](WEBHOOKS_EMBY.md) for Emby and Jellyfin event settings.

## External API access

Each connection can have its own external API key under **Connection settings → Integrations**. External clients send the key in the `X-MixerBee-Key` header to `/api/external/*` endpoints.

- A key resolves only its assigned connection; a caller cannot redirect it with a connection header.
- External keys do not grant access to account, connection, or ordinary browser settings routes.
- Replacing or disabling a key immediately invalidates the previous credential.
- Treat keys as secrets. They are displayed to the connection owner and stored in the local configuration database.

## AI providers and semantic indexes

Two separate things live here, and only the first is optional:

**Generative AI** — the AI Block Builder, Playlist Assist, and metadata enrichment (mood tags) — needs a provider. It is off until you deliberately configure one, per connection, in the AI Hub. A new connection selects *no* provider: the localhost URL and model name in the form are placeholders, not saved values, so saving media credentials never turns AI on. Gemini needs an API key; Ollama needs both a server URL and a model name.

**Semantic search** — the local ChromaDB index, Echo blocks, and “Find Similar” — is a core library feature. It needs no provider and no account preference. MixerBee builds the index from your Emby/Jellyfin metadata on every usable connection. Enrichment tags improve those embeddings but are not required for them.

### Turning AI off for an account

Account settings has one checkbox, **Disable AI features**. It applies to your whole MixerBee account: every device, session, and media connection, including ones you add later. It does not affect other accounts, and MixerBee ownership grants nothing over another member's preference.

While it is on:

- Assist, the AI Block Builder, Library IQ, the AI Hub, and enrichment controls are hidden — not shown greyed out.
- No Gemini or Ollama request is made, including provider discovery. Direct HTTP calls, external API keys, manual job runs, and clock/webhook jobs are refused too: the check reads the account that owns the connection, so a saved key cannot outrank it. Generation and enrichment return `403` with reason `disabled_by_user`; missing setup returns `409` with `ai_not_configured`.
- A run already under way stops at its next provider call. A request already sent cannot be recalled, so it finishes on its own and its result is discarded rather than written.
- Echo blocks, semantic search, index refresh, index reset, ordinary schedules, presets, recipes, the Manager, and Auto Playlists all keep working.
- Provider credentials and previously generated tags are kept. Enrichment schedules are kept too, with their enabled flags intact; they are hidden, skipped without producing failure notifications, and resume at their next normal occurrence when you turn AI back on. No missed runs are replayed.
- Previously AI-generated blocks and Vibe selections still preview and build. They resolve through ordinary TV/movie processing, so they are presented as saved selections rather than AI blocks.

Index maintenance lives in **Connection settings → Library Search & Indexing**, outside the AI Hub, so hiding the hub can never strand it.

### Upgrading from an earlier version

Older versions pre-filled `http://localhost:11434` and a default model into every connection, so a saved Ollama provider did not prove you had chosen one. On first start after this upgrade, MixerBee keeps any provider it can tell was deliberate — a Gemini key, a non-default Ollama URL, model or timeout, a starred model, or an existing enrichment schedule — and clears the *selection* on connections that only ever held defaults. Nothing is deleted: the URL, model and key are preserved, so re-enabling is one save in the AI Hub. MixerBee never probes localhost to guess consent.

Each connection has a separate ChromaDB collection and enrichment state. Reset/re-index operations apply only to the selected connection. Removing a connection deletes its local AI index. A large library may take time to warm or re-index after startup or migration.

- **On-Demand Enrichment**: Initiate or halt background metadata enrichment from the AI Hub or via `POST /api/library/enrichment/start` and `stop`. An internal concurrency lock ensures manual enrichment runs and scheduled enrichment passes never conflict. Starting is policy-gated; stopping stays available so a worker can always be halted.
- **Selective Semantic Refresh**: Instead of a full ChromaDB reset, `POST /api/library/semantic_refresh` analyzes current server metadata against stored fingerprints, re-embedding only added or changed items while strictly preserving existing vibe tags and enrichment status. Never policy-gated, and it does not start enrichment.
- **Account AI preference**: `POST /api/account/preferences` with `{"ai_disabled": true|false}` updates only the signed-in account. It works with no connection saved, an unreachable server, or no provider configured. `GET /api/config_status` and `GET /api/settings` return the resulting capability: `ai_disabled`, `ai_provider_configured`, `generative_ai_available`, `ai_unavailable_reason`, and `semantic_search_allowed`.

## Manager tools and bulk actions

The Manager pane enables library curation across all playlists and collections:
- **Multi-Selection & Bulk Delete**: Check multiple playlists or collections to delete them simultaneously with permission verification.
- **Direct Server Links**: Open playlists and collections directly on the Emby/Jellyfin web interface.
- **Runtime Presentation**: Formatted total duration is computed and displayed alongside item counts.
- **Overlap Analysis**: Identify duplicate media items that appear across multiple playlists or collections with bounded queries to prevent server overload.

## Verbose logging

The installation owner can enable **Account settings → Administration → Verbose logging**. It applies to all accounts and media connections, including background jobs. It works even when no media connection is configured or a media server is unavailable.

The setting is off by default, saved in SQLite, and loaded on every startup. Changes apply immediately without restarting MixerBee. Enabling it changes MixerBee's subsystem loggers and APScheduler from `WARNING` to `INFO`; warnings and errors remain visible when it is off. It does not change Uvicorn's access logging.

Verbose output includes media queries, scheduler and webhook activity, indexing, enrichment, and AI processing. It can include prompts, media titles, and AI tool arguments. Turn it off after troubleshooting and check logs before sharing them.

To follow logs:

```sh
# Docker Hub installation
docker logs --tail 100 -f mixerbee

# Docker Compose
docker compose logs --tail 100 -f mixerbee
```

For a custom installation, read the terminal output or the service's logs. MixerBee writes its subsystem logs to standard output; this option does not create a separate log file.

### Live log viewer

While verbose logging is on, the installation owner gets a **Live logs** button in the header and an
**Open live logs** action beside the Administration checkbox. Both open a resizable drawer along the bottom
of the window. The rest of the app stays usable behind it, the drawer survives tab changes, and it is
available when no media connection exists or a media server is unreachable.

The drawer shows each entry's local time, severity, subsystem, and message, and offers severity filters, a
subsystem selector, text search, **Follow latest** (which pauses when you scroll up and counts what arrived
meanwhile), **Clear view**, **Copy visible**, and **Download**. Multiline messages and tracebacks expand in
place. Severity totals sit in the footer.

What it is and is not:

- **Scope is installation-wide** — all accounts and all media connections. Changing the selected media
  connection does not filter it. Household members cannot open it, and an external API key cannot reach it.
- **Memory only.** The server keeps the most recent 2,000 records or 2 MiB, whichever comes first, with each
  record capped at 16 KiB; your browser keeps 1,000 records or 1 MiB. Older entries are discarded and the
  drawer says so. Nothing is written to disk, to SQLite, or into backups, and nothing survives a reload.
  Search and the filters apply to what the drawer currently holds — this is not a server-side log archive.
- **Console logs are unaffected.** The output described above keeps working identically whether or not the
  viewer is open, and remains the place to look for a full history.
- **Turning verbose logging off** stops the feed and clears the server's buffer. An open drawer keeps its
  entries readable and copyable until you close it.
- **Recognized credentials are redacted** from viewer text — password, secret and token fields, API keys,
  `Authorization` headers, webhook token parameters, and URL user information, including inside tool
  arguments and exception messages. This is a safety net over values that reach a log line incidentally,
  not a guarantee about arbitrary free text, so still review logs before sharing them.
- **Single process only.** Running MixerBee under multiple Uvicorn workers would give each worker its own
  buffer, and the drawer would show only the worker that served the request.

Behind a reverse proxy, the feed is a `text/event-stream` response and must not be buffered. MixerBee sends
`Cache-Control: no-store, no-transform` and `X-Accel-Buffering: no`, which is enough for nginx's defaults.
For other proxies, disable response buffering and allow a long-lived connection on
`/api/admin/logs/stream`; MixerBee sends a keepalive comment at least every 15 seconds, so a read timeout
above 30 seconds is sufficient. If the drawer keeps reconnecting while the container logs look healthy,
proxy buffering is the first thing to check.

## Backup and restore

MixerBee provides both online, owner-authenticated API backup/restore and file-system archive options.

### Online archive (Owner API)

The installation owner can create, inspect, and restore configuration archives while MixerBee is running:
- **Download**: `GET /api/backup/download` creates a verified `.zip` archive containing a consistent SQLite online snapshot (`mixerbee.db`), ChromaDB collections, and `manifest.json`.
- **Inspect**: `POST /api/backup/inspect` checks archive validity, validates schema versions, and runs an SQLite integrity check without applying changes.
- **Restore**: `POST /api/backup/restore` stages the restoration, creates an automatic rollback backup of the active database, restores SQLite and ChromaDB data in place, and reloads active connections and schedules.

### File-system backup

Alternatively, back up the complete configuration directory:

| Installation | Directory to back up |
| --- | --- |
| Docker Hub command or supplied Compose file | `mixerbee_config/` on the host, mounted at `/config` |
| Standard custom Python install | `config/` inside the project |
| Custom path | The directory supplied through `MIXERBEE_CONFIG_DIR` |

The directory includes `.env` when present, `mixerbee.db`, SQLite sidecar files, and `chroma_db/`. It contains account hashes, media-server credentials, AI credentials, webhook secrets, and external API keys. Credentials are not encrypted at rest; store backups privately.

#### File-system back up

1. Stop MixerBee so SQLite and ChromaDB are not changing during the copy. For Docker Hub, run `docker stop mixerbee`; for Compose, run `docker compose stop`.
2. Copy or archive the entire configuration directory to a separate location. Include hidden files and database sidecar files.
3. Start MixerBee again with `docker start mixerbee` or `docker compose start`. For a custom install, restart its service.

#### File-system restore

1. Stop MixerBee and keep a separate copy of the current configuration directory.
2. Restore the complete backup into an empty configuration directory rather than merging database files. Preserve ownership and permissions so MixerBee can read and write it.
3. Start MixerBee using the restored directory. Prefer the same application version that created the backup, verify the restore, and then upgrade.
4. Check local accounts, connections, presets, schedules, integrations, and AI index state. Restored schedules become active when MixerBee starts.

MixerBee backups do not contain media files, playlists, collections, or watch history stored on Emby/Jellyfin. Back up the media server separately. Browser-local Builder drafts are also excluded; save important drafts as presets first.
