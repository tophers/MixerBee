# MixerBee 🐝

**MixerBee** is a self-hosted web app for building and managing smart playlists and collections on your [Emby](https://emby.media/) or [Jellyfin](https://jellyfin.org) server. 

MixerBee allows you to interleave episodes across multiple shows, create themed movie blocks with complex filters, and automate your media management with a robust scheduling engine. Whether you want to mimic the feel of a custom TV channel or keep a "Next Up" playlist perfectly synced across devices, MixerBee is built to handle it.

---

## Features

* **Advanced Playlist & Collection Builder**:
  * **TV Blocks**: Interleave episodes from multiple shows. Start from a specific point or automatically pick up from the next unwatched episode.
  * **Movie Blocks**: Filter by genre, year range, studio, cast, and watched status.
  * **Music Blocks**: Blend tracks by artist, album, popularity, or genre.
  * **Static Collections**: Optionally generate native server **Collections** (BoxSets) instead of playlists.

* **Live Synchronization (Webhooks)**:
  MixerBee can listen for server events. Mark a show as watched or add new media, and MixerBee will automatically trigger a debounced rebuild of your relevant playlists within seconds. See [WEBHOOKS_EMBY.md](WEBHOOKS_EMBY.md)

* **Hardened Stability**:
  Engineered for long-term uptime with a "self-healing" auth system, database connection pooling, and transaction-safe playlist rollbacks to prevent data loss during network blips.

* **AI Block Builder** (Optional):
  Use natural language prompts to build complex mixes (e.g. *"A block of 90s thriller movies followed by two random episodes of The X-Files"*). Requires a Google Gemini API key.
  
* **Scheduler**:
  Automate your builds on a daily or weekly cadence with a full "Last Run" log for every job.

* **Manager**:
  A unified dashboard to view, sort, search, and delete all playlists and collections on your server.

---

## Web Interface

| Builder (Dark)                                         | Builder (Light)                                          |
| ------------------------------------------------------ | -------------------------------------------------------- |
| ![Builder Dark](screenshots/mixerbee-builder-dark.png) | ![Builder Light](screenshots/mixerbee-builder-light.png) |

| Scheduler (Dark)                                           | Scheduler (Light)                                            |
| ---------------------------------------------------------- | ------------------------------------------------------------ |
| ![Scheduler Dark](screenshots/mixerbee-scheduler-dark.png) | ![Scheduler Light](screenshots/mixerbee-scheduler-light.png) |

| Manager (Dark)                                         | Manager (Light)                                          |
| ------------------------------------------------------ | -------------------------------------------------------- |
| ![Manager Dark](screenshots/mixerbee-manager-dark.png) | ![Manager Light](screenshots/mixerbee-manager-light.png) |

---

## Installation

See [INSTALL.md](INSTALL.md) for full setup instructions.

### Requirements
* **Docker**: Recommended for most users.
* **Python**: v3.14.3+ (if running on bare metal).
* **Media Server**: Emby or Jellyfin with administrative access.

### Quick Start
MixerBee is available via:
* [Docker Hub](https://hub.docker.com/r/trulytilted/mixerbee)
* Manual Docker Build (`docker-compose up --build`)
* Local Python Venv

---

## Usage

### 1. Configure Webhooks (Optional but Recommended)
To enable real-time playlist updates, add MixerBee's webhook URL to your Emby/Jellyfin Webhook plugin:
`http://your-ip:9000/api/webhook`

### 2. Build Your Mix
Use the **Builder Tab** to stack TV, Movie, or Music blocks. You can save these configurations as **Presets** for easy reuse.

### 3. Automate
In the **Scheduler Tab**, link your Presets to a time and frequency. MixerBee will ensure your playlists stay fresh without you ever having to open the app again.

### 4. Manage
Use the **Manager Tab** to clean up old playlists or view the contents of your collections without leaving the MixerBee interface.

---

# Introducing Vibe Search: Semantic AI for MixerBee

Recently completely overhauled the AI engine to understand not just *what* your media is, but how it *feels*. 

By moving to a 100% local Vector Database, MixerBee can now mathematically map abstract concepts, moods, and atmospheres directly to the plot summaries of the movies, shows, and music on your server. 

Here is everything you need to know to get the most out of the new AI Builder.

---

## The Two Modes of the AI Builder

The MixerBee AI acts as a smart orchestrator. It reads your prompt and dynamically decides which type of UI block will serve you best: **Dynamic Rule Blocks** or **Curated AI Blocks**.

### 1. Dynamic Rule Blocks (The Traditional Way)
If you ask for concrete, metadata-driven rules, the AI will build a standard block. This leaves the UI fully open, allowing you to manually tweak the dropdowns, sliders, and checkboxes after the AI generates it.

**Examples of Rule-Based Prompts:**
* *"Give me 5 Action movies from the 1980s."*
* *"Build a block of Sci-Fi movies starring Harrison Ford."*
* *"Give me a mix of 10 Rock songs and 3 random episodes of The Office."*

**What to expect:** The block will appear with your genres selected, years set, and actor tokens populated. You can change these at any time before hitting "Build."

### 2. Curated AI Blocks (Vibe Search)
If you ask for an abstract concept, feeling, or mood, the AI realizes that standard dropdowns aren't enough. It will silently search your local vector database, hand-pick the exact media that matches that feeling, and build a locked-down, curated list. 

**Examples of Vibe-Based Prompts:**
* *"I want a movie night that feels isolating, unsettling, and set in deep space."*
* *"Give me a block of cozy, feel-good movies perfect for a rainy Sunday."*
* *"Build me a playlist of movies with a gritty, neon-soaked cyberpunk aesthetic."*
* *"I'm looking for a mind-bending psychological thriller that will leave me guessing."*

**What to expect:** The manual filters (genres, years) will disappear. Instead, you will see an AI badge, a custom title generated by the AI (e.g., *Vibe: Cozy Rainy Day*), and a **"View Selected Items"** button where you can preview the exact media the AI hand-picked for you.

---

## Tips for the Best Results

* **Be Descriptive:** The vector database loves adjectives. Instead of just saying "scary," say "dread-inducing, atmospheric, and suspenseful."
* **Mix and Match:** You can combine rules and vibes in the same prompt! 
  * *Example:* *"Give me 3 episodes of Seinfeld, followed by a block of movies with a high-octane, adrenaline-pumping vibe."*
* **The "Thinking..." State:** Because the AI actively researches your library, reads summaries, and formats complex data, generations take a few seconds. Watch for the "Thinking..." button state to know the AI is crunching the numbers.
* **Privacy First:** The actual semantic search (the "Vibe" matching) happens entirely locally on your server's CPU. Your library metadata is never sent to the cloud for vectorization.

## Under the Hood
MixerBee now utilizes a two-agent RAG (Retrieval-Augmented Generation) pipeline:
1. **The Researcher:** Analyzes your prompt. If it detects a "vibe," it queries a local `ChromaDB` instance running an optimized `all-MiniLM-L6-v2` embedding model to fetch matching media IDs.
2. **The Builder:** Takes the IDs and context gathered by the Researcher and strictly formats it into the MixerBee JSON schema for the frontend to render.

Enjoy!
