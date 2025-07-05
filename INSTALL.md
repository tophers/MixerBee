# MixerBee – Installation Guide

## 🚀 Getting Started

MixerBee can be run in **two** ways:

1. **Docker** – the quickest, all‑in‑one route.
2. **Manual Python environment** – for those who prefer not to use Docker.

---
### Docker

Follow these steps for a clean, containerized setup.

1.  **Clone the Repository:** If you haven't already, clone this repository to your local machine.
2.  **Create a Docker Config Directory:** Before starting, create a directory to permanently store your configuration. In the project's root folder (next to `docker-compose.yml`), run:
    ```sh
    mkdir mixerbee_config
    ```
3.  **Start the Container:** From the project's root directory, run:
    ```sh
    docker-compose up -d
    ```
    This will build the Docker image and start the MixerBee container.
4.  **Configure the Application:**
    * Open your web browser and navigate to `http://localhost:9000`.
    * Click the **Open Settings** button.
    * Enter your Emby credentials and save. The page will reload.
    * Your settings are now permanently saved in the `./mixerbee_config/.env` file on your host machine.

---
To upgrade to the latest version of MixerBee:
```sh
# Pull the latest changes from the repository
git pull

# Rebuild the image and restart the container
docker-compose up -d --build
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

