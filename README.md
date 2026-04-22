# MixerBee 🐝

**MixerBee** is a self-hosted automation hub for [Emby](https://emby.media/) and [Jellyfin](https://jellyfin.org). It turns your media library into a dynamic, "programmed" experience by allowing you to build smart playlists and collections by using metadata filters, either 100% local or "Cloud" AI and schedule whatever you create. All AI features are completely optional and are disabled when not configured.

Whether you want to build a "90s Saturday Morning Cartoon" block with interleaved episodes or a "Neon-Drenched Cyberpunk" movie marathon curated by a Cloud(Gemini) or local LLM, MixerBee bridges the gap between your server and a broadcast experience.

---

## Key Features

### The Builder
Stack different media types into a single cohesive list using **Blocks**:
* **TV Blocks**: Interleave episodes across multiple shows. Mix *The Office* and *Parks & Rec* for a custom comedy block, starting from specific episodes or automatically resuming from your **Next Unwatched**.
* **Movie Blocks**: Fine-tune your selection by genre, production year, studio, cast, and watched status.
* **Music Blocks**: Blend tracks by artist, specific albums, top tracks, or random genre samplers.
* **Collections & Playlists**: Output your build as a native server **Playlist** or a permanent **Collection (BoxSet)**.

### AI Orchestration (Gemini or Ollama)
MixerBee features an AI Builder that supports both cloud-based **Google Gemini** and 100% local **Ollama** instances (Qwen, Mistral, etc.).
* **Flexible**: Switch between cloud AI or private local AI in the UI settings.
* **Vibe Search**: Powered by a local `ChromaDB` vector store, MixerBee understands abstract concepts. Prompt for "isolation in deep space" or "cozy rainy Sunday vibes," and the AI will map these feelings to your specific library summaries.
* **Two Generation Modes**:
    1.  **Rule-Based**: AI sets the sliders and dropdowns for you (e.g., "80s Action movies"), after which you can modify.
    2.  **Curated Vibe Blocks**: AI picks specific IDs from your library based on semantic meaning, creating a LLM curated list.

### Automation & Synchronization
* **Scheduler**: Build configurations as **Presets** and schedule them to run daily or weekly. MixerBee can ensure your "Mix" is always ready when you sit down to watch.
* **Live Webhooks**: MixerBee can listen for server events. Mark a show as watched on your TV, and the relevant scheduled playlists will rebuild automatically in the background within seconds.
* **Delta Vector Indexing**: The library indexer is efficient and will performing differential syncs to only embed new or removed items, keeping the local "Vibe" database current without high CPU overhead.

### Unified Management
* **Manager Dashboard**: Sort, search, and delete playlists or collections across your entire server.
* **One-Click Conversion**: Easily swap a Playlist into a permanent Collection (or vice versa) with a single click.
* **Notification History**: A built-in log tracks every build and background job, so you always know what MixerBee is doing
* **Verbose Logging**: Add "VERBOSE_LOGGING="true" to your .env to provide additional logs to see everything MixerBee is doing as well what it is sending and receiving from any AI.

---

## Web Interface 
(Screenshots are out of date, Mixerbee has had a lot of UI/UX tweaks for a better experience)

| Builder (Dark) | Builder (Light) |
| :--- | :--- |
| ![Builder Dark](screenshots/mixerbee-builder-dark.png) | ![Builder Light](screenshots/mixerbee-builder-light.png) |

| Scheduler | Manager |
| :--- | :--- |
| ![Scheduler](screenshots/mixerbee-scheduler-dark.png) | ![Manager](screenshots/mixerbee-manager-dark.png) |

---

## Installation & Setup

### Requirements
* **Docker**: (Recommended) For easy deployment and database management.
* **Python**: v3.12+ (if running on bare metal).
* **Media Server**: Emby or Jellyfin with administrative access.

### Quick Start
MixerBee is available via **Docker Hub** or GitHub:
1.  Deploy the container: `docker pull trulytilted/mixerbee`
2.  Access the UI at `http://your-ip:9000`.
3.  Open **Settings** to configure your server URL, credentials, and preferred AI provider.

See [INSTALL.md](INSTALL.md) for full configuration details.

---

## Understanding Vibe Search
MixerBee doesn't just look at genres; it reads by using a **100% Local Vector Database** (ChromaDB). Powered by ChromaDB the app performs "Semantic Mapping."

### The AI Pipeline:
1.  **The Researcher**: When you prompt the AI, it first analyzes your library. If it detects a "mood" or "vibe," it queries your local ChromaDB for media that matches that description.
2.  **The Architect**: It then builds a JSON schema of your request, ensuring that exact IDs and metadata are used to attempt to prevent "hallucinations."
3.  **Privacy First**: Your library metadata never leaves your network for vectorization. All embeddings are generated and stored locally on your server's hardware. If you use a local Ollama model, no data leaves your network.

---

## Pro-Tips for Best Results
* **Descriptive Prompts**: The Vector DB engine prefer adjectives. Instead of "scary," you can use "psychological dread, claustrophobic, and atmospheric."
* **Hybrid Requests**: You can combine instructions. *"Give me 3 episodes of Seinfeld followed by 2 movies that feel like a neon-drenched 80s fever dream."*
* **Settings Sync**: All settings can be changed by the UI and are database backed. You can still  manually edit your `.env` file, the app detects the change and syncs the new values to the database on restart.

---

**Enjoy your media, different.**
