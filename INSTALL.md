# MixerBee – Installation Guide

## 🚀 Getting Started

MixerBee can be run in **two** ways:

1. **Docker** – the quickest, all‑in‑one route.
2. **Manual Python environment** – for those who prefer not to use Docker.

---

## 1 · Docker Setup

Running MixerBee with Docker is the simplest approach.

1. **Install Docker and Docker Compose** if they are not already on your system.

2. **Clone the repository**

   ```bash
   git clone https://github.com/tophers/mixerbee.git
   cd mixerbee
   ```

3. **Create and edit the configuration**

   ```bash
   cp examples/mixerbee.env.example .mixerbee.env
   vi .mixerbee.env   # set EMBY_URL, EMBY_USER, EMBY_PASS, …
   ```

4. **Launch MixerBee**

   ```bash
   docker compose up -d
   ```

   The web UI will be available at [http://localhost:9000](http://localhost:9000) (replace `localhost` with your server’s IP if remote).

---

## 2 · Manual Installation (Python)

Choose this path only if you do **not** want to use Docker.

1. **Clone the repository**

   ```bash
   git clone https://github.com/tophers/mixerbee.git
   cd mixerbee
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
   cp examples/mixerbee.env.example .mixerbee.env
   vi .mixerbee.env
   ```

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

# Docker users
docker compose build --pull && docker compose up -d

# Manual install
pip install -r requirements.txt
# then restart uvicorn or:  systemctl restart mixerbee
```

---

## Uninstalling / Cleaning Up

* **Docker:** `docker compose down -v` removes containers *and* volumes.
* **Manual:** deactivate and delete the virtual‑env folder, then remove the project directory.

---

Enjoy! 🍯🐝

