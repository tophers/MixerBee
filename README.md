# MixerBee

MixerBee is a self-hosted automation app for [Emby](https://emby.media/) and [Jellyfin](https://jellyfin.org). It creates and manages playlists and collections using library metadata, watch status, optional AI tools, and schedules.

## Features

### Users and Servers

- **Multi-user**: Separate local accounts with their own connections, presets, schedules, and AI settings. The installation owner can create and remove household accounts.
- **Multi-server**: Each account can save and switch between multiple Emby or Jellyfin connections. Each connection has its own library data, presets, and schedules.

### Block Types

The Builder combines blocks into a playlist. Blocks can play in sequence or interleave.

- **TV**: Select shows and start from specific episodes or continue from the next unwatched episodes.
- **Movies**: Filter by genre, year, studio, cast, director, watched status, favorites, runtime, ratings, and audio or subtitle language.
- **Music**: Select albums, an artist's top or random tracks, or tracks by genre.
- **Curated**: Combine hand-picked movies with TV episode rules.
- **Echo**: Find similar titles from seed movies or shows using the local library index. No AI provider is required.
- **AI Vibe**: Use the AI Builder to select library items from a descriptive prompt.

### Builder Tools

- **Mix Rules**: Exclude recently watched or previously selected items, suppress duplicates, limit movies per franchise, choose block order, and set a total runtime target.
- **Previews and Snapshots**: Check selected items and total runtime. Movie, Echo, and Curated blocks can keep a preview's selection as a snapshot.
- **Editing**: Reorder blocks, undo or redo edits, and keep browser-local drafts.
- **Presets and Recipes**: Save complete builds as presets or individual blocks as recipes. Recipes support descriptions, tags, and favorites; presets can be shared by code.
- **Output**: Create or replace playlists, append to existing playlists, or build a movie collection from one Movie block. Collection changes require a media-server administrator account.

### Automation

- **Scheduler**: Run presets and Auto Playlists daily, weekly, or at an interval. Pause, resume, snooze, or run a schedule manually.
- **Webhooks**: Rebuild scheduled lists after playback or library events. Choose clock, watched, and library triggers for each schedule.
- **Movie and TV Auto Playlists**: Recently Added, Next Up, Pilot Sampler, From the Vault, Top Community Picks, and Top Critic Picks. Movie Genre Roulette is also available as a manual build.
- **Music Auto Playlists**: Artist Spotlight, Music Genre Sampler, and Album Roulette, including scheduled album rotation.
- **Enrichment Schedules**: Process batches of library metadata for AI mood tags.

### Management

- **Manager**: Search and sort playlists and collections, view runtime and contents, reorder or remove items, and delete multiple lists.
- **Conversion**: Convert playlists to collections or copy collections into playlists.
- **Overlap**: Check for media items shared across lists.
- **Build History**: Review recorded builds, compare their items, and replay an earlier selection as a new playlist.
- **Server Links**: Open playlists and collections directly in Emby or Jellyfin.
- **Backup and Restore**: Download, inspect, and restore configuration archives through the owner API.
- **External API**: Build lists from other tools using a connection-specific API key.
- **Verbose Logging**: The installation owner can enable detailed logs from Account settings, and watch them live in a drawer without leaving the app.

### Optional AI Tools

AI features support local Ollama and Google Gemini. They stay off until a provider is configured and can be disabled for the whole account. Echo blocks and local semantic search work without a provider.

- **AI Builder**: Generate filter-based blocks or specific selections from a prompt, then refine them with follow-up requests.
- **Playlist Assist**: Build a movie playlist through conversation. Pin movies to keep them, remove items, undo changes, and save the result as a new playlist. Currently supports movies only.
- **Metadata Enrichment**: Add mood tags to the local search index, with start/stop controls and progress in the AI Hub.
- **Library IQ**: View the percentage of the library enriched with mood tags.
- **Index Maintenance**: Refresh changed metadata or rebuild the local search index independently of AI enrichment.

---

## Web Interface

(Screenshots may not match the current UI.)

| Builder (Dark) | Builder (Light) |
| :--- | :--- |
| ![Builder Dark](screenshots/mixerbee-builder-dark.png) | ![Builder Light](screenshots/mixerbee-builder-light.png) |

| Scheduler | Manager |
| :--- | :--- |
| ![Scheduler](screenshots/mixerbee-scheduler-dark.png) | ![Manager](screenshots/mixerbee-manager-dark.png) |

---

## Documentation

- [Installation](INSTALL.md): Requirements, Docker and Python setup, updates, and account recovery.
- [Usage and behavior](USAGE.md): Accounts, connections, build behavior, presets, schedules, AI settings, integrations, and backups.
- [Webhook configuration](WEBHOOKS_EMBY.md): Media-server event setup.
- [Architecture](ARCHITECTURE.md): Code layout and internal behavior.
- [License](LICENSE.md): MIT license.
