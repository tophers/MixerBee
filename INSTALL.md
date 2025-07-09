# MixerBee – Installation Guide

## 🚀 Getting Started

MixerBee can be run in multiple ways, depending on your environment and preferences:

1. **Prebuilt Docker Image (Docker Hub)**
2. **Manual Docker Build from Source**
3. **Custom Python Environment**

---

### Option 1: Prebuilt Docker Image (Docker Hub)

You can now run MixerBee directly using the public image from Docker Hub.

```bash
docker run -d \
  --name mixerbee \
  -p 9000:9000 \
  -v "$PWD/mixerbee_config:/config" \
  trulytilted/mixerbee:latest
```

> *Adjust `$PWD` to an absolute path if needed on your OS.*
>
> Example for Linux/macOS:
>
> ```bash
> -v "$PWD/mixerbee_config:/config"
> ```
>
> Example for Windows Git Bash:
>
> ```bash
> -v "/c/Users/youruser/mixerbee_config:/config"
> ```

Then open [http://localhost:9000](http://localhost:9000) in your browser to configure settings.

To enable the AI Block Builder, add your `GEMINI_API_KEY` to your `.env` file in the `mixerbee_config` volume.

---

### Option 2: Manual Docker Build (From Source)

1. **Clone the Repository:**

   ```bash
   git clone https://github.com/tophers/mixerbee.git && cd mixerbee
   ```

2. **Start the Container:**

   ```bash
   docker-compose up -d
   ```

   This will build the Docker image locally and start the MixerBee container.

3. **Initial Configuration:**

   * Visit [http://localhost:9000](http://localhost:9000)
   * Click the **Settings** (gear icon)
   * Enter your Emby or JellyFin details and save
   * Config will be stored in `./mixerbee_config/.env`
   * Restart container after first setup (*#todo: improve live reload of environment config*)

---

### Option 3: Custom Python Environment

1. **Clone the repository**

   ```bash
   git clone https://github.com/tophers/mixerbee.git && cd mixerbee
   ```

2. **Create and activate a virtual environment**

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install Python dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Create and edit the configuration**

   ```bash
   cp examples/mixerbee.env.example config/.env
   vi config/.env
   ```

   Or configure via the Web UI cog icon, followed by a restart.

5. **Run the app**

   ```bash
   uvicorn web:app --host 0.0.0.0 --port 9000
   ```

   Access it at [http://localhost:9000](http://localhost:9000)

   *(You can also use the included systemd service: `examples/mixerbee.service.example`)*

---

## Updating MixerBee

```bash
# Pull latest code
git pull

# Docker (prebuilt image)
docker pull trulytilted/mixerbee:latest
docker container rm -f mixerbee
# Re-run the same docker run command used in Option 1 above

# Docker (manual build)
docker compose build --pull && docker compose up -d

# Custom install
pip install -r requirements.txt
# Restart uvicorn or:  systemctl restart mixerbee
```

---

## Uninstalling / Cleaning Up

* **Docker:** `docker compose down -v` removes containers *and* volumes.
* **Manual Python install:** deactivate and delete the `venv` folder, then remove the project directory.

---

Enjoy! 🍯🐝

