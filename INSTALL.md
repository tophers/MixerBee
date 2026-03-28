# 🐝 MixerBee – Installation Guide

[![GitHub Actions](https://github.com/tophers/mixerbee/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/tophers/mixerbee/actions)

## Getting Started

MixerBee is designed to run as a background service. It can be deployed via **Docker** or a **Custom Python Environment**.

---

### Docker

#### Option A – Use the prebuilt image (Docker Hub)

1. **Run the container**
   ```sh
   docker run -d \
     --name mixerbee \
     -p 9000:9000 \
     -v $(pwd)/mixerbee_config:/config \
     --restart unless-stopped \
     trulytilted/mixerbee:latest
   ```
   *Note: Ensure you map the volume to `/config` to persist your database and settings.*

2. **Configure**
   * Open [http://localhost:9000](http://localhost:9000).
   * Click the **Settings (cog)** icon.
   * Enter your Emby/Jellyfin URL and credentials.
   * Save your settings. The application will automatically restart and re-authenticate.

#### Option B – Build locally (Docker Compose)

1. **Clone the Repository**
   ```sh
   git clone https://github.com/tophers/mixerbee.git && cd mixerbee
   ```

2. **Start the Service**
   ```sh
   docker compose up -d
   ```

---

### Custom Python Environment

**Requirement:** Python 3.14.3+

1. **Clone and Enter Directory**
   ```bash
   git clone https://github.com/tophers/mixerbee.git && cd mixerbee
   ```

2. **Setup Virtual Environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Initialize Config**
   ```bash
   cp examples/mixerbee.env.example config/.env
   ```
   *You can edit `config/.env` manually or use the built-in Settings UI.*

5. **Start Uvicorn**
   ```bash
   uvicorn web:app --host 0.0.0.0 --port 9000
   ```

---

### Webhook Integration (Recommended)

To enable real-time playlist updates when you finish an episode or add new media, add MixerBee as a webhook destination in your media server:

1. Go to **Server Settings** > **Webhooks**.
2. Add a new Generic/JSON webhook.
3. Set the URL to: `http://<YOUR-IP>:9000/api/webhook`
4. MixerBee will now automatically trigger debounced rebuilds for relevant events.

---

## Updating MixerBee

### Docker Hub
```bash
docker pull trulytilted/mixerbee:latest
docker stop mixerbee && docker rm mixerbee
# Rerun the docker run command from Step 1
```

### Docker Compose
```bash
git pull
docker compose build --pull && docker compose up -d
```

### Custom Install
```bash
git pull
source venv/bin/activate
pip install -r requirements.txt
# Restart your uvicorn process or systemd service
```

---

## Uninstalling / Cleaning Up

* **Docker:** `docker compose down -v` or `docker rm -f mixerbee`.
* **Manual:** Delete the `venv` folder and the project directory.

Enjoy! 
