# ACCURATE MaaS Matchmaking Assistant

An AI-powered matchmaking assistant for Manufacturing-as-a-Service (MaaS) ecosystems, developed as part of the EU ACCURATE Gaia-X Lighthouse project.

The system uses a hybrid GraphRAG architecture combining a local LLM (Llama 3.1 via Ollama), an OWL ontology knowledge base (Apache Jena Fuseki), and a Streamlit chat interface.

---

## System Requirements

- **Docker Desktop** (required)
- **Ollama** (installed locally, NOT via Docker)
- **8 GB RAM** minimum (16 GB recommended)
- **10 GB free disk space** (for Llama 3.1 model)
- Internet connection (first-time setup only)

---

## Setup Guide

### Step 1 — Install Ollama locally

Download and install Ollama directly on your system (do NOT use Docker for this):
https://ollama.com/download

After installation, **configure Ollama to listen on all network interfaces**:

**Windows / macOS:**
Ollama listens on all interfaces by default. No extra configuration needed.

**Linux:**
```bash
sudo systemctl edit ollama
```
Add the following between the comment lines:
```
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
```
Save and restart Ollama:
```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

Then download the Llama 3.1 model:
```bash
ollama pull llama3.1
```

### Step 2 — Install Docker Desktop

Download from: https://www.docker.com/products/docker-desktop/

**Windows users only:** Docker requires WSL2.
1. Open PowerShell as Administrator and run:
   ```powershell
   wsl --install
   ```
2. Restart your computer.
3. Open Docker Desktop → Settings → Resources → WSL Integration and enable WSL2.

### Step 3 — Download this repository

```bash
git clone https://github.com/yeechuan1108/maas-matchmaking.git
cd maas-matchmaking
```

### Step 4 — Linux users only: configure environment

If you are on Linux, copy the environment template:
```bash
cp .env.linux .env
```

Then verify the correct Docker Gateway IP on your system:
```bash
docker network inspect bridge | grep Gateway
```

If the IP shown is different from `172.18.0.1`, edit `.env` and update it:
```
OLLAMA_HOST=http://<your-gateway-ip>:11434
```

Windows and macOS users can skip this step entirely.

### Step 5 — Start all services

```bash
docker compose up -d
```

This will automatically start and configure:
- **Fuseki** at `http://localhost:3030`
- **Fuseki-init** — creates the dataset and loads the ontology automatically
- **Streamlit** at `http://localhost:8501`

First startup takes 3–5 minutes as Docker builds the images.

### Step 6 — Open the Matchmaking Assistant

Go to: **`http://localhost:8501`**

The assistant is ready to use. The ontology loads automatically — no manual upload required.

---

## Daily Usage (after first-time setup)

```bash
# Make sure Ollama is running (check system tray on Windows/macOS)
# Then start Docker services:
docker compose up -d

# Wait ~30 seconds, then open:
# http://localhost:8501
```

To stop all services:
```bash
docker compose down
```

---

## Troubleshooting

**"Connection refused" on localhost:8501**
- Wait 30–60 seconds after `docker compose up`.
- Check containers are running: `docker ps`

**No results / Fuseki errors**
- Check ontology loaded correctly:
  ```bash
  docker logs fuseki_init
  ```
  You should see `Ontology loaded successfully!` at the end.
- If dataset is missing, check Fuseki at `http://localhost:3030` (admin / admin123).

**LLM not responding (Connection timed out)**
- Make sure Ollama is running on your local machine.
- Verify: `ollama list` should show `llama3.1`.
- **Linux only**: Verify Ollama is listening on all interfaces:
  ```bash
  curl http://172.18.0.1:11434
  ```
  Should return `Ollama is running`. If not, repeat Step 1 (Linux configuration).
- **Linux only**: Verify your `.env` file has the correct Gateway IP:
  ```bash
  docker network inspect maas_network | grep Gateway
  ```

**Docker Desktop not starting on Windows**
- Ensure WSL2 is installed: `wsl --status` in PowerShell.
- Restart Docker Desktop.

---

## Project Structure

```
maas-matchmaking/
├── docker-compose.yml                      # Orchestrates Fuseki + Streamlit
├── Dockerfile                              # Builds the Streamlit container
├── fuseki-init.sh                          # Auto-loads ontology on startup
├── requirements.txt                        # Python dependencies
├── .gitattributes                          # Ensures correct line endings on Windows
├── .env.linux                              # Linux environment template
├── matchmaking-assistant-final-withUI.py   # Main application (with UI)
├── matchmaking-assistant-final-RDversion.py # Research version (no UI)
├── ontology/
│   └── OBMM_RESCUE.ttl                     # OWL ontology (auto-loaded)
├── fuseki-docker-master/                   # Fuseki Docker build files
└── ollama-models/                          # Llama 3.1 model files (local only)
```

---

## Architecture

```
User (Browser)
    │
    ▼
Streamlit UI  (port 8501, Docker)
    │
    ├──► Ollama / Llama 3.1  (port 11434, local install)
    │
    └──► Apache Jena Fuseki  (port 3030, Docker)
```

---

## Contact

Developed by Yi-Chuan Tsai
Fraunhofer IAT — EU ACCURATE Project
Supervisor: Dr. Joachim Lentes
