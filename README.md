# ACCURATE MaaS Matchmaking Assistant

An AI-powered matchmaking assistant for Manufacturing-as-a-Service (MaaS) ecosystems, developed as part of the EU ACCURATE Gaia-X Lighthouse project.

The system uses a hybrid GraphRAG architecture combining a local LLM (Llama 3.1 via Ollama), an OWL ontology knowledge base (Apache Jena Fuseki), and a Streamlit chat interface.

---

## System Requirements

- **Docker Desktop** (required)
- **8 GB RAM** minimum (16 GB recommended)
- **10 GB free disk space** (for Llama 3.1 model)
- Internet connection (first-time setup only)

---

## Setup Guide (Windows)

### Step 1 — Install WSL2 (Windows only, one-time)

Ollama requires WSL2 to run on Windows.

1. Open **PowerShell as Administrator** and run:
   ```powershell
   wsl --install
   ```
2. Restart your computer when prompted.
3. After restart, open **Docker Desktop → Settings → Resources → WSL Integration** and enable WSL2.

### Step 2 — Install Docker Desktop

Download from: https://www.docker.com/products/docker-desktop/

After installation, make sure Docker Desktop is running (whale icon in system tray).

### Step 3 — Download this repository

Download and extract the ZIP, or clone via Git:
```bash
git clone https://github.com/yeechuan1108/maas-matchmaking.git
cd maas-matchmaking
```

### Step 4 — Start all services

Open a terminal in the `maas-matchmaking` folder and run:
```bash
docker compose up -d
```

This will automatically start and configure four services:
- **Ollama** at `http://localhost:11434`
- **Fuseki** at `http://localhost:3030`
- **Fuseki-init** — loads the ontology automatically on first startup
- **Streamlit** at `http://localhost:8501`

First startup takes 5–10 minutes as Docker builds the images.

### Step 5 — Download the Llama 3.1 model (first-time only)

After the containers are running, download the LLM:
```bash
docker exec ollama_service ollama pull llama3.1
```

This downloads ~4 GB and takes several minutes depending on internet speed.

### Step 6 — Open the Matchmaking Assistant

Go to: **`http://localhost:8501`**

The assistant is ready to use. The ontology is loaded automatically — no manual upload required.

---

## Daily Usage (after first-time setup)

Each time you want to use the system:

```bash
# Start all services (ontology loads automatically)
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
- Wait 30–60 seconds after `docker compose up` for all services to initialize.
- Check all containers are running: `docker ps`

**No results returned from queries**
- Check if the ontology loaded correctly:
  ```bash
  docker logs fuseki_init
  ```
  You should see `Ontology loaded successfully!` at the end.

**Ollama model not found**
- Run `docker exec ollama_service ollama pull llama3.1` again.

**Docker Desktop not starting on Windows**
- Ensure WSL2 is installed: run `wsl --status` in PowerShell.
- Restart Docker Desktop.

---

## Project Structure

```
maas-matchmaking/
├── docker-compose.yml                      # Orchestrates all 4 services
├── Dockerfile                              # Builds the Streamlit container
├── requirements.txt                        # Python dependencies
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
Streamlit UI  (port 8501)
    │
    ├──► Ollama / Llama 3.1  (port 11434)  — Natural language understanding
    │
    └──► Apache Jena Fuseki  (port 3030)   — OWL ontology / SPARQL queries
```

---

## Contact

Developed by Yi-Chuan Tsai  
Fraunhofer IAT — EU ACCURATE Project  
Supervisor: Dr. Joachim Lentes
