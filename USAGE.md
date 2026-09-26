# Usage and behavior

This guide describes current account, connection, build, automation, integration, and backup behavior. See [Installation](INSTALL.md) for deployment and [README](README.md#block-types) for the available Builder blocks.

## Accounts and workspaces

MixerBee accounts are local to the installation and are separate from Emby or Jellyfin accounts.

- The first local account is the installation owner. It can create household accounts from **Account settings** and review household webhook setup requests.
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

Movie collection builds delete an existing collection with the matching name before creating the replacement, so its server ID can change. Standard and scheduled collection builds require exactly one Movie block and media-server administrator permission.

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

Scheduled collection builds require exactly one Movie block and an administrator-capable media connection. Enrichment schedules update the selected connection's semantic index and are not triggered by media-server webhooks.

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

AI features are optional and configured independently for each connection. Ollama is the default provider for new settings; Gemini requires an API key.

Each connection has a separate ChromaDB collection and enrichment state. Reset/re-index operations apply only to the selected connection. Removing a connection deletes its local AI index. A large library may take time to warm or re-index after startup or migration.

## Backup and restore

Back up the complete configuration directory:

| Installation | Directory to back up |
| --- | --- |
| Docker Hub command or supplied Compose file | `mixerbee_config/` on the host, mounted at `/config` |
| Standard custom Python install | `config/` inside the project |
| Custom path | The directory supplied through `MIXERBEE_CONFIG_DIR` |

The directory includes `.env` when present, `mixerbee.db`, SQLite sidecar files, and `chroma_db/`. It contains account hashes, media-server credentials, AI credentials, webhook secrets, and external API keys. Credentials are not encrypted at rest; store backups privately.

### Back up

1. Stop MixerBee so SQLite and ChromaDB are not changing during the copy. For Docker Hub, run `docker stop mixerbee`; for Compose, run `docker compose stop`.
2. Copy or archive the entire configuration directory to a separate location. Include hidden files and database sidecar files.
3. Start MixerBee again with `docker start mixerbee` or `docker compose start`. For a custom install, restart its service.

### Restore

1. Stop MixerBee and keep a separate copy of the current configuration directory.
2. Restore the complete backup into an empty configuration directory rather than merging database files. Preserve ownership and permissions so MixerBee can read and write it.
3. Start MixerBee using the restored directory. Prefer the same application version that created the backup, verify the restore, and then upgrade.
4. Check local accounts, connections, presets, schedules, integrations, and AI index state. Restored schedules become active when MixerBee starts.

MixerBee backups do not contain media files, playlists, collections, or watch history stored on Emby/Jellyfin. Back up the media server separately. Browser-local Builder drafts are also excluded; save important drafts as presets first.
