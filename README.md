# MixerBee 🐝

**MixerBee** is a self-hosted web app for building and updating smart playlists and collections on your [Emby](https://emby.media/) server. Mix episodes from multiple shows, create movie collections that fit your criteria, blend in music from your favorite artists, or schedule block-style programming to mimic a TV channel.

## ✨ Features

*   **Advanced Playlist & Collection Builder**:
    *   **TV Blocks**: Mix episodes from multiple shows. Start from a specific episode or let MixerBee automatically find the next unwatched one for you.
    *   **Movie Blocks**: Filter your movie library by genre, year range, watched status, and more to create highly specific lists.
    *   **Music Blocks**: Add songs by artist and album, create a mix of an artist's top tracks, or build a playlist based on music genre.
    *   **Create as Collection**: Generate a static **Collection** in your Emby library instead of a playlist for easier visual navigation.
*   **AI Block Builder** (Optional): Use natural language to build complex playlists. Simply ask for what you want (e.g., "80s action movies and some episodes of Star Trek"), and let the AI generate the playlist blocks for you. *Requires a Google Gemini API key.*
*   **Scheduler**: Automatically rebuild your favorite presets on a daily or weekly schedule. Set your "prime time" or "Saturday morning cartoon" blocks once and always have fresh content ready. Includes a "Last Run" status to monitor job success.
*   **Manager**: A unified dashboard to view, search, sort, and delete all of your Playlists and Collections in one place.
*   **Quick Playlists**: Instantly create special playlists with a single click.
    *   **Video**: Pilot Sampler, Next Up, From the Vault, and Movie Genre Roulette.
    *   **Music**: Artist Spotlight, Album Roulette, and Music Genre Sampler.
*   **Modern UI**: A clean, responsive interface with both **Light and Dark modes** and collapsible sections to keep the workspace tidy.
*   **Preset System**: Save your complex builder configurations as presets. Import and export presets via shareable text codes to share with friends.

## 🖥️ Web Interface

| Builder                                             | Scheduler                                             | Manager                                             |
| --------------------------------------------------- | ----------------------------------------------------- | --------------------------------------------------- |
| ![Builder Tab](screenshots/mixerbee_builder.png) | ![Scheduler Tab](screenshots/mixerbee_scheduler.png) | ![Manager Tab](screenshots/mixerbee_manager.png) |

## 🚀 Installation

See **[INSTALL.md](INSTALL.md)** for setup instructions. For container-based setups, see the included `Dockerfile` and `docker-compose.yml`.

To enable the AI Block Builder feature, you must add your `GEMINI_API_KEY` to your `.mixerbee.env` file.

## ⚙️ Usage

Browse to the server URL (default `http://localhost:9000`) and start building.

*   **Builder Tab:** The most powerful feature.
    *   **Add Blocks**: Add TV, Movie, or Music "blocks" to design a custom content lineup.
    *   **Build**: Use the Action Bar at the bottom to give your creation a name and build it as either a static Playlist or a Collection inside Emby.
    *   **Presets**: Save your block configuration as a preset for easy access later or for use with the scheduler.
*   **Scheduler Tab:** Automate your content.
    1.  First, build a playlist on the "Builder" tab and save it as a preset.
    2.  Go to the "Scheduler" tab.
    3.  Select your saved preset, choose a frequency (Daily or Weekly), pick the days, and set a time.
    4.  Click "Create Schedule". Your playlist or collection will now be automatically rebuilt on Emby at the specified time.
*   **Manager Tab:**
    *   View all of your existing playlists and collections.
    *   Search by name to quickly find an item.
    *   Sort by name, type, item count, or creation date.
    *   Delete items you no longer need.
