# MixerBee

MixerBee is a self-hosted automation app for [Emby](https://emby.media/) and [Jellyfin](https://jellyfin.org). It lets you create playlists and collections from your media library using metadata filters, optional AI tools, and schedules.

AI features are optional and stay disabled unless you configure them.

MixerBee can be used to:
- build mixed TV, movie, and music lists
- create playlists or collections
- save builds as presets
- schedule builds to run automatically
- rebuild lists when library activity changes

---

## Features

### Builder
MixerBee uses blocks to build media lists.

- **TV Blocks**: Combine episodes from multiple shows. You can start from specific episodes or continue from next unwatched episodes.
- **Movie Blocks**: Filter movies by genre, year, studio, cast, and watched status.
- **Music Blocks**: Build lists from artists, albums, top tracks, or genre-based selections.
- **Collections and Playlists**: Save output as a server playlist or as a collection/box set.

### AI Builder
MixerBee supports both local Ollama and Google Gemini models.

- Use either local AI (preferred) or cloud AI in Settings
- Use prompt-based search to build lists from themes, moods, or styles
- Use AI in two ways:
  1. **Rule-Based**: AI fills in filters and settings for you
  2. **Curated Blocks**: AI selects specific media items from your library based on semantic matches

### Automation
- **Scheduler**: Save builds as presets and run them on a schedule
- **Webhooks**: Rebuild lists automatically when watched status or other server events change
- **Delta Indexing**: Only new or removed items are reprocessed for the local vector database

### Management
- **Manager Dashboard**: View, sort, search, and delete playlists or collections
- **Conversion Tools**: Convert playlists to collections, or collections to playlists
- **Notification History**: View build and background job history
- **Verbose Logging**: Optional detailed logging through the `.env` file

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

## Installation and Setup

### Requirements
- **Docker** recommended for deployment and database management
- **Python** 3.12+ for bare-metal installs
- **Emby or Jellyfin** with admin access

### Quick Start
MixerBee is available on Docker Hub and GitHub.

1. Pull the container: `docker pull trulytilted/mixerbee`
2. Open the UI at `http://your-ip:9000`
3. Go to **Settings** and enter your server URL, credentials, and AI provider if you want to use AI features

See `INSTALL.md` for full setup details.

---

## Mood-Based Search

MixerBee can use a local ChromaDB database to match descriptive prompts against your library metadata.

### How it works
1. The app checks your prompt for themes, moods, or descriptive terms
2. It searches your local vector database for matching media
3. It builds results using your library metadata and media IDs

Library metadata used for embeddings is stored locally. If you use a local Ollama model, requests also stay local.

---

## Notes
- More detailed prompts usually produce better results
- You can combine filters and prompt-based requests
- Settings changed in the UI are stored in the database
- `.env` changes are synced back into the app on restart
