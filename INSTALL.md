# MixerBee – Installation Guide

[![GitHub Actions](https://github.com/tophers/mixerbee/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/tophers/mixerbee/actions)

## 🚀 Getting Started

MixerBee can be run in **two** ways:

1. **Docker**
2. **Custom Python environment**

---

### Docker

You can either **pull the prebuilt image from Docker Hub** or **build locally** with Docker Compose.

#### Option A – Use the official Docker Hub image

1. **Pull and run the image**

   ```sh
   docker run -d \
     --name mixerbee \
     -p 9000:9000 \
     -v $(pwd)/mixerbee_config:/app/config \
     trulytilted/mixerbee:latest
   ```

   This will start MixerBee on port **9000** and persist your config in the `./mixerbee_config` directory.

2. **Configure the application**

   * Open your browser at [http://localhost:9000](http://localhost:9000).
   * Click the cog **Open Settings** button.
   * Enter your Emby credentials and save.
   * The settings are saved in `./mixerbee_config/.env`.
   * You may see an init error; restart the container to load new settings.

#### Option B – Build locally with Docker Compose

1. **Clone the Repository**

   ```sh
   git clone https://github.com/tophers/mixerbee.git && cd mixerbee
   ```

2. **Start the Container**

   ```sh
   docker compose up -d
   ```

   This builds the image locally and starts MixerBee.

3. **Configure the Application:** Same as Option A above.

---

### Custom Python Environment

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

   Edit the required variables. (You can also set up the `.env` in the UI settings cog, *requires restart*)

5. **Run the web server** (or use the provided *systemd* service file)

   ```bash
   uvicorn web:app --host 0.0.0.0 --port 9000
   ```

   Access the UI at [http://localhost:9000](http://localhost:9000).

---

## Updating MixerBee

```bash
# pull the latest code
git pull

# Docker Hub users
docker pull trulytilted/mixerbee:latest
docker stop mixerbee && docker rm mixerbee
docker run -d -p 9000:9000 -v $(pwd)/mixerbee_config:/app/config trulytilted/mixerbee:latest

# Docker Compose users
docker compose build --pull && docker compose up -d

# Custom install
pip install -r requirements.txt
# then restart uvicorn or:  systemctl restart mixerbee
```

---

## Uninstalling / Cleaning Up

* **Docker:**
  `docker compose down -v` removes containers *and* volumes.
  If you used `docker run`, just `docker rm -f mixerbee`.

* **Manual:**
  deactivate and delete the virtual-env folder, then remove the project directory.

---

Enjoy! 🍯🐝
