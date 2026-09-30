---
applyTo: "**"
---

# Ollama Setup & LLM Model Guide

## Project Overview

This project runs **Ollama** — a local LLM inference server — via Docker Compose, alongside:
- **Open WebUI** — browser-based chat UI (port 3000)
- **AnythingLLM** — RAG/document chat UI (port 3001)
- **Python tooling** — `ollama`, `llm`, `llm-ollama` packages managed by `uv`

Models are stored in `~/ollama_doc/models/` (bind-mounted into the container).

---

## Quick Start (Docker — recommended)

### 1. Prerequisites

- Docker Engine with the NVIDIA Container Toolkit (for GPU passthrough)
- `uv` (Python package manager)

### 2. Start the Stack

```bash
docker compose up -d
```

This starts `ollama`, `open-webui`, and `anything-llm` containers. Ollama listens on:
- `http://localhost:11434` (loopback)
- `http://192.0.2.28:11434` (LAN)

### 3. Check Status

```bash
python3 scripts/status.py                    # server version, GPU info, loaded models
docker exec ollama ollama list               # list all downloaded models
docker exec ollama nvidia-smi --query-gpu=name,memory.total,memory.free,utilization.gpu \
    --format=csv,noheader,nounits            # GPU memory usage inside the container
docker compose logs -f ollama               # tail live ollama logs
```

### 4. Stop the Stack

```bash
docker compose down                          # containers stop; models on host are safe
```

---

## Running LLM Models

### Pull a Model

```bash
docker exec ollama ollama pull qwen2.5:3b   # default model
docker exec ollama ollama pull mistral
docker exec ollama ollama pull llama3.2
docker exec ollama ollama pull codellama
```

### Run a One-Shot Prompt

```bash
docker exec -it ollama ollama run qwen2.5:3b "Explain transformers in 2 sentences"
docker exec -it ollama ollama run mistral "Tell me a joke"
```

### Start an Interactive Chat Session

```bash
docker exec -it ollama ollama run qwen2.5:3b   # interactive chat with default model
docker exec -it ollama ollama run llama3.2      # interactive chat with a specific model
```

### Remove a Model

```bash
docker exec ollama ollama rm llama3.2           # delete model from disk
docker exec ollama ollama stop llama3.2         # unload from GPU memory only
```

---

## Recommended Models

| Use Case        | Model              | Size    |
|-----------------|--------------------|---------|
| General chat    | `llama3.2`         | ~2 GB   |
| General chat    | `mistral`          | ~4 GB   |
| Code generation | `codellama`        | ~4 GB   |
| Small / fast    | `phi3`             | ~2 GB   |
| Analysis        | `qwen2.5:3b`       | ~2 GB   |
| Long context    | `llama3.1:70b`     | ~40 GB  |

---

## Custom Models (Modelfile)

The project ships with `Modelfile` — a pre-configured analysis assistant built on `qwen2.5:3b`.

**Build and register it:**

```bash
docker cp Modelfile ollama:/tmp/Modelfile
docker exec ollama ollama create analysis-assistant -f /tmp/Modelfile
```

**Manually create your own Modelfile:**

```
FROM llama3.2

SYSTEM "You are a helpful coding assistant. Answer concisely."

PARAMETER temperature 0.7
PARAMETER num_ctx 4096
```

Then build it:

```bash
docker cp Modelfile ollama:/tmp/Modelfile
docker exec ollama ollama create my-model -f /tmp/Modelfile
```

---

## Python Integration

### Setup

```bash
uv sync                           # installs all dependencies into .venv
```

### Using the `ollama` Python Package

```python
import ollama

response = ollama.chat(
    model="qwen2.5:3b",
    messages=[{"role": "user", "content": "Why is the sky blue?"}]
)
print(response["message"]["content"])
```

### Using the `llm` CLI

```bash
source .venv/bin/activate

llm models list                              # list available models
llm -m llama3.2 "What is the capital of France?"
llm models default llama3.2                  # set default model
llm "Summarize the Rust ownership model"     # uses default model
llm chat -m mistral                          # multi-turn conversation
```

### REST API (OpenAI-compatible)

```bash
# Generate
curl http://localhost:11434/api/generate \
  -d '{"model": "qwen2.5:3b", "prompt": "Tell me a joke", "stream": false}'

# Chat
curl http://localhost:11434/api/chat \
  -d '{"model": "qwen2.5:3b", "messages": [{"role": "user", "content": "Hello!"}], "stream": false}'
```

### Run the Demo Script

```bash
uv run python main.py             # shows server status, GPU info, and a live generation demo
```

---

## Bare-Metal Setup (without Docker)

### Install Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### Configure Model Storage

```bash
mkdir -p ~/ollama_doc/models
echo 'export OLLAMA_MODELS=~/ollama_doc/models' >> ~/.bashrc
source ~/.bashrc
```

### Run as a systemd Service

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf <<'EOF'
[Service]
Environment="OLLAMA_MODELS=/home/<user>/ollama/models"
EOF
sudo systemctl daemon-reload && sudo systemctl enable --now ollama
```

### Start Manually

```bash
ollama serve                        # listens on http://localhost:11434
```

---

## Key Environment Variables

| Variable                   | Purpose                                   | Value in this project            |
|----------------------------|-------------------------------------------|----------------------------------|
| `OLLAMA_MODELS`            | Model storage path                        | `~/ollama_doc/models`            |
| `OLLAMA_HOST`              | Bind address                              | `0.0.0.0:11434`                  |
| `OLLAMA_NUM_PARALLEL`      | Max parallel requests                     | `1`                              |
| `OLLAMA_MAX_LOADED_MODELS` | Models held in GPU memory simultaneously  | `2`                              |
| `OLLAMA_FLASH_ATTENTION`   | Enable flash attention (speed boost)      | `1`                              |
| `OLLAMA_KEEP_ALIVE`        | How long to keep a model loaded           | `10m`                            |

---

## Disk Usage

```bash
du -sh ~/ollama_doc/models        # show size of models directory
```
