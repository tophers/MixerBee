# MixerBee Installation Guide

[![GitHub Actions](https://github.com/tophers/mixerbee/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/tophers/mixerbee/actions)

## Before installing

MixerBee is designed to run continuously as a background service. The prebuilt Docker Hub image is the recommended installation; Docker Compose and custom Python installations are also supported.

You need:

- An Emby or Jellyfin server reachable from the MixerBee runtime.
- Credentials for each media user who will have a MixerBee connection.
- A persistent directory for MixerBee's SQLite database, ChromaDB index, and optional `.env` file.
- Python 3.12 or newer only when using a custom Python installation. The container uses the Python 3.14 image family.

A media-server administrator is not required for normal playlist use. Administrator rights are required for collection mutations and for configuring server-side notifications/webhooks. Ollama and Gemini are optional.

> On an uninitialized installation, the first account created becomes the MixerBee installation owner. Start MixerBee on a trusted network and create that account before exposing the UI more broadly.

## Docker Hub installation (recommended)

1. From the directory where you want to keep MixerBee data, start the container:

   ```sh
   docker run -d \
     --name mixerbee \
     -p 9000:9000 \
     -v "$(pwd)/mixerbee_config:/config" \
     --restart unless-stopped \
     trulytilted/mixerbee:latest
   ```

   The host directory `mixerbee_config/` is mounted at `/config`. Reuse this exact directory whenever the container is updated or recreated.

2. Open `http://your-server-ip:9000` and create the initial local MixerBee owner account.

3. Choose **Add connection** and enter the Emby or Jellyfin URL and credentials for the first media user.

4. Optionally configure Ollama or Gemini in the connection settings. AI settings and indexes are separate for every saved connection.

5. From **Account settings**, optionally create household accounts. Each member signs in separately and adds their own media connections.

The media-server URL must be reachable from inside the container. `localhost` in a connection URL refers to the MixerBee container itself, not the Docker host. Use a host LAN address, resolvable hostname, or an appropriate Docker network address.

Useful commands:

```sh
docker logs --tail 100 mixerbee
docker restart mixerbee
docker exec mixerbee date
curl http://localhost:9000/api/status
```

The date command shows the timezone used by schedules.

## Docker Compose installation

The supplied Compose file builds the current checkout and mounts `./mixerbee_config` at `/config`.

1. Clone the repository:

   ```sh
   git clone https://github.com/tophers/mixerbee.git
   cd mixerbee
   ```

2. Build and start MixerBee:

   ```sh
   docker compose up -d --build
   ```

3. Open `http://your-server-ip:9000`, create the owner account, and add a media connection.

Use `docker compose logs -f mixerbee` to follow startup and job output.

## Custom Python installation

1. Clone the repository and create a virtual environment:

   ```sh
   git clone https://github.com/tophers/mixerbee.git
   cd mixerbee
   python3 -m venv venv
   source venv/bin/activate
   ```

2. Install the pinned dependencies:

   ```sh
   pip install -r requirements.txt
   ```

3. Create the persistent configuration directory:

   ```sh
   mkdir -p config
   ```

   A fresh account-based installation does not require an `.env` file. Connections and AI settings are created in the UI.

4. Start Uvicorn. For direct access without a path-prefix reverse proxy, explicitly use an empty root path:

   ```sh
   MIXERBEE_ROOT_PATH="" uvicorn web:app --host 0.0.0.0 --port 9000
   ```

5. Open `http://your-server-ip:9000`, create the owner account, and add a media connection.

For a persistent service, adapt [the systemd example](examples/mixerbee.service.example). Add `Environment=MIXERBEE_ROOT_PATH=` for direct root hosting, or set it to the proxy path described below.

### Custom configuration directory

Set `MIXERBEE_CONFIG_DIR` in the process environment before startup to place all persistent state elsewhere:

```sh
MIXERBEE_CONFIG_DIR=/srv/mixerbee/config MIXERBEE_ROOT_PATH="" \
  uvicorn web:app --host 0.0.0.0 --port 9000
```

Do not put `MIXERBEE_CONFIG_DIR` inside MixerBee's `.env`; the path must be known before that file can be located.

## First-run and household setup

The local MixerBee password is separate from the Emby/Jellyfin password and must contain at least 10 characters.

1. The first local account becomes the installation owner.
2. The owner adds one or more media connections for their own workspace.
3. The owner creates household accounts under **Account settings**.
4. Each household member signs in and adds their own connections.
5. Each browser session remembers its selected connection independently.

The owner can manage local accounts and webhook requests but cannot browse another member's library, presets, schedules, or saved credentials.

## Configuration and the legacy .env file

New installations do not need a MixerBee `.env` file. Configure media connections and AI providers in the UI. The installation owner controls **Verbose logging** under **Account settings → Administration**. That setting is saved in SQLite and applies immediately; see [Verbose logging](USAGE.md#verbose-logging) for usage and log commands.

Legacy `.env` import is kept for upgrades from older installations. Before the first local account is created, it can import saved media credentials and settings, including `VERBOSE_LOGGING`. After account setup, editing `VERBOSE_LOGGING` in `.env` does not override the saved UI setting.

The legacy file is still loaded for compatibility with existing environment overrides such as `GEMINI_MODEL`. Keep it if your installation uses those overrides. Deployment settings such as `MIXERBEE_CONFIG_DIR` and `MIXERBEE_ROOT_PATH` should be set in the process or container environment; they do not require a MixerBee `.env` file.

## AI providers

AI features are optional and configured per connection.

- **Ollama** is the default provider for new settings. Enter an Ollama URL reachable from the MixerBee runtime and select a tool-capable model.
- **Gemini** requires a Google Gemini API key in that connection's settings.
- Each connection receives its own ChromaDB semantic index, so initial indexing or migration can take time for large libraries.

When MixerBee runs in Docker and Ollama runs elsewhere, do not use `http://localhost:11434` unless Ollama is in the same container. Use a reachable host or container-network address.

## Webhook integration (recommended)

Webhooks keep scheduled playlists and collections synchronized after playback or library events. They do not rebuild one-off Builder output.

1. Open the applicable connection's settings and generate a webhook secret.
2. Copy the complete connection-specific URL.
3. Configure that URL in Emby or the Jellyfin Webhook plugin for the media user shown by MixerBee.
4. MixerBee reports **Connected** after receiving the first authenticated event with a valid event name.

For a household member, generating a secret creates a persistent request for the installation owner. The owner can copy the URL and mark it installed under **Account settings → Webhook administration**.

If the media server reaches MixerBee through a different hostname, HTTPS origin, port, or proxy path, the owner should first set **MixerBee URL reachable by media servers** in Webhook administration.

Every connection has a different URL and secret. The old shared `/api/webhook` endpoint is retired. Follow [Webhook configuration](WEBHOOKS_EMBY.md) for the complete Emby/Jellyfin event setup and debounce behavior.

## Reverse proxy and path-prefix deployments

Use TLS at the reverse proxy when MixerBee is exposed beyond a trusted private network. Preserve the original `Host`, scheme, and client-address forwarding headers according to your proxy setup.

Set `MIXERBEE_ROOT_PATH` to the externally visible path when the proxy publishes MixerBee below a prefix and strips that prefix before forwarding. For example:

```sh
MIXERBEE_ROOT_PATH=/mixerbee uvicorn web:app --host 127.0.0.1 --port 9000
```

Users would then open `https://example.com/mixerbee/`. For direct root hosting, set `MIXERBEE_ROOT_PATH=""`. The container defaults to an empty root path; non-container execution defaults to `/mixerbee` when the variable is absent.

After configuring a proxy, set the canonical media-server-reachable URL in the owner's Webhook administration panel so copied callbacks use the correct external origin and prefix.

## Migrating from an older single-connection installation

Before upgrading, stop MixerBee and back up the complete configuration directory, including hidden files, SQLite sidecar files, and `chroma_db/`.

On first startup of the account-based release:

1. MixerBee may import legacy server configuration from `.env` before any local account exists.
2. Create the local owner account in the browser. Existing unowned saved connections are assigned to it without changing their IDs.
3. Legacy presets are copied once into the first eligible connection.
4. Legacy schedules matching that connection's media user are assigned to it. Unmatched schedules remain inactive rather than being assigned to an unknown server.
5. Review the migrated presets and schedules, allow connection-specific AI indexes to build, and replace old webhook URLs.

If legacy credentials are unavailable at startup, create the owner first and save the intended connection through the UI; the first eligible owner connection performs the one-time preset/schedule migration.

The legacy preset table and shared Chroma collection are retained for recovery but are not kept synchronized with new connection-scoped data. Legacy browser drafts cannot be safely attributed to a connection; save important drafts as presets before upgrading.

See [2026.10.0 release notes](docs/RELEASE_NOTES_2026.10.0.md) and [Usage and behavior](USAGE.md#backup-and-restore) for full migration and backup details.

## Local account recovery

Changing a password from the UI signs out all sessions for that account without stopping schedules.

For Docker:

```sh
docker exec -it mixerbee python manage_accounts.py list
docker exec -it mixerbee python manage_accounts.py reset-password USERNAME
```

For Docker Compose:

```sh
docker compose exec mixerbee python manage_accounts.py list
docker compose exec mixerbee python manage_accounts.py reset-password USERNAME
```

For a custom installation, activate its environment and run the same utility from the repository root:

```sh
source venv/bin/activate
python manage_accounts.py list
python manage_accounts.py reset-password USERNAME
```

Set `MIXERBEE_CONFIG_DIR` for the command when the installation uses a nondefault configuration path.

## Updating MixerBee

[Back up the complete configuration](USAGE.md#backup-and-restore) before updating. A container update preserves data only when the same host directory remains mounted at `/config`.

### Docker Hub

```sh
docker pull trulytilted/mixerbee:latest
docker stop mixerbee
docker rm mixerbee
# Run the original docker run command again with the same /config mount.
```

### Docker Compose

```sh
git pull
docker compose build --pull
docker compose up -d
```

### Custom Python

```sh
git pull
source venv/bin/activate
pip install -r requirements.txt
# Restart the uvicorn or systemd service.
```

After updating, sign in and verify connections, presets, schedules, webhook status, and AI index state. Database migrations run automatically during startup.

## Uninstalling and cleanup

- **Docker Hub:** `docker stop mixerbee && docker rm mixerbee` removes the container. The bind-mounted `mixerbee_config/` directory remains.
- **Docker Compose:** `docker compose down` removes the service container and network. The bind-mounted `mixerbee_config/` directory remains.
- **Custom Python:** Stop the service before removing its environment or project directory. Preserve the configured data directory if you may reinstall.

Deleting MixerBee's configuration directory permanently removes local accounts, saved credentials, presets, schedules, integration secrets, and AI indexes. Removing MixerBee does not delete playlists or collections already stored on Emby or Jellyfin.
