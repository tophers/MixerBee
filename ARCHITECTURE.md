# MixerBee Architecture Map

## Overview
MixerBee is a Python (FastAPI) and Javascript (Alpine.js) application designed to build, manage, and schedule smart media playlists for Emby and Jellyfin servers. It utilizes a local vector database (ChromaDB) and LLMs (Ollama/Gemini) for semantic searches and metadata enrichment.

The frontend is built without node modules or a build step, using pure CSS, vanilla JS modules, and Jinja2 templates for HTML structure.

---

## 1. Root Directory (Core Configuration & State)
* `web.py`: The FastAPI application entry point. Handles route mounting and lifespan events (starting the scheduler, init DB).
* `app_state.py`: Manages global configuration, environment variables, and the authentication token caching.
* `database.py`: Manages the SQLite database connection, initialization, and table schemas (`presets`, `schedules`, `settings`).
* `models.py`: Contains all Pydantic schemas used for request/response validation across the API.
* `scheduler.py`: Wraps `APScheduler`. Manages the execution, saving, and triggering of background playlist jobs.
* `preset_manager.py`: Handles saving and loading block configurations (presets) to the SQLite database.

---

## 2. API Routers (`/routers`)
These files define the FastAPI endpoints connecting the frontend to the backend logic.
* `builder.py`: Endpoints for generating blocks via AI (`/api/create_from_text`), previewing blocks, and finalizing playlists.
* `config.py`: Endpoints for saving settings, testing connections, and querying Ollama status.
* `dependencies.py`: Contains `get_current_auth_headers`, the core dependency injected into routes to ensure valid Emby/Jellyfin tokens.
* `library.py`: Endpoints for fetching library data, episode lookups, and basic item CRUD (delete, remove from playlist).
* `presets.py`: Endpoints for saving, loading, and deleting UI presets.
* `quick_playlists.py`: Endpoint for triggering pre-configured "Smart Builds" (e.g., Recently Added, Next Up).
* `scheduler.py`: CRUD endpoints for automated background jobs.
* `webhooks.py`: Listens for playback events from the media server to trigger debounced playlist rebuilds.

---

## 3. Core Domain Logic (`/app`)
These files handle business logic and direct communication with the Emby/Jellyfin REST API.
* `client.py`: Manages the `requests.Session`, connection testing, and authentication headers.
* `cache.py`: Manages a background thread that caches massive library data (studios, genres, all series) in memory for fast UI access.
* `builder.py`: The engine that takes a JSON definition of UI "Blocks" and converts them into a flat list of media item IDs to build the final playlist.
* `items.py`: Generic CRUD operations for Playlists and Collections (creating, deleting, clearing items).
* `movies.py`: Logic for querying movies based on complex filters (genres, years, actors, studios, runtime).
* `tv.py`: Logic for querying series, finding specific episodes, and resolving "Next Unwatched" states.
* `music.py`: Logic for querying audio tracks, albums, and artists.
* `people.py` & `studios.py` & `users.py`: Specific API wrappers for querying metadata.

---

## 4. AI & Semantic Logic (`/app/ai`)
* `orchestrator.py`: The LLM routing engine. Manages prompts for Gemini and Ollama. Handles the "Divide and Conquer" logic (Researcher phase -> Architect phase) for prompt parsing. Also handles the metadata enrichment queue.
* `vector_store.py`: Wraps ChromaDB. Handles indexing library items, maintaining `cosine` similarity, and executing composite "Vibe Searches" (Echo blocks).
* `tools.py`: Python function definitions passed to the LLMs for tool-calling (e.g., validating genres, searching for specific shows).

---

## 5. Frontend State Management (`/static/js`)
State is managed using Alpine.js `Alpine.store()`.
* `app.js`: The initialization script. Hydrates stores and bootstraps the application loop.
* `apiClient.js`: A wrapper around the native `fetch` API. Handles global loading overlays, error catching, and toast notifications.
* `mixerStore.js`: The primary state container. Manages the array of "Blocks", updates preview counts, and triggers final playlist builds.
* `aiStore.js`: Manages AI Builder state, prompt input, and "Mood Discovery" slots.
* `blockFactory.js`: Utility for generating clean, default state objects for new UI blocks.
* `managerStore.js`: State for the "Manager" tab (viewing and reordering existing playlists/collections).
* `schedulerStore.js`: State for the "Scheduler" tab (cron jobs).
* `presetStore.js` & `settingsStore.js` & `uiStore.js`: State for presets, user settings, and tab navigation.
* `modals.js`: Logic for showing/hiding and awaiting promises from popup modals.
* `definitions.js`: Constants (Block types, Smart Build definitions).

---

## 6. Frontend UI (`/templates` & `/static/css`)
* `templates/index.html`: The main layout shell.
* `templates/partials/`: Contains Jinja2 HTML snippets.
    * `_builder_pane.html`, `_scheduler_pane.html`, `_manager_pane.html`: The main views.
    * `_*_block.html`: The UI representation for each specific media block type (e.g., `_tv_block.html`, `_vibe_block.html`).
    * `_modals.html`: All popup windows.
* `static/css/main.css`: The singular stylesheet using CSS variables for theming.