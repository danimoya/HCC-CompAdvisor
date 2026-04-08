# AI Advisor Setup Guide

The AI Advisor uses a local Small Language Model (SLM) via [Ollama](https://ollama.com) to provide intelligent compression recommendations. All data stays on your network — no cloud services, no API keys, no data leaving your infrastructure.

## Prerequisites

- A server with at least **8 GB RAM** (16 GB recommended for larger models)
- Network access from the HCC Advisor application to the Ollama server (port 11434)
- **Optional**: GPU for faster inference (NVIDIA recommended)

## Step 1: Install Ollama

### Linux / macOS

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### Windows

Download the installer from [ollama.com/download](https://ollama.com/download).

### Docker (headless server, recommended for production)

```bash
# CPU only
docker run -d -v ollama:/root/.ollama -p 11434:11434 --name ollama ollama/ollama

# With NVIDIA GPU
docker run -d --gpus=all -v ollama:/root/.ollama -p 11434:11434 --name ollama ollama/ollama
```

### Verify Installation

```bash
curl http://localhost:11434/api/tags
# Should return: {"models":[]}
```

## Step 2: Download a Model

```bash
# Best overall (recommended)
ollama pull llama3

# Faster, less RAM required
ollama pull phi3:mini

# Good for deeper schema-level analysis
ollama pull mistral
```

### Model Comparison

| Model | Parameters | RAM Required | Speed | Best For |
|-------|-----------|-------------|-------|----------|
| `phi3:mini` | 3.8B | ~3 GB | Fast (~5s) | Quick per-object analysis |
| `mistral` | 7B | ~5 GB | Medium (~15s) | Schema-level reasoning |
| `llama3` | 8B | ~5 GB | Medium (~15s) | Best overall technical analysis |
| `llama3:70b` | 70B | ~40 GB | Slow (~60s) | Most capable (GPU required) |

**Recommendation**: Start with `llama3` for the best balance of quality and speed. Use `phi3:mini` if RAM is limited.

## Step 3: Configure HCC Advisor

1. Open HCC Advisor in your browser
2. Navigate to **Admin** (sidebar, bottom)
3. Click the **AI / Ollama** tab
4. Enter the **Ollama URL**:
   - Same server: `http://localhost:11434`
   - Different server: `http://<server-ip>:11434`
   - Docker on same host: `http://host.docker.internal:11434`
5. Enter the **Model** name (must match exactly, e.g., `llama3`)
6. Click **Save**
7. Click **Test Connection** — should show available models

## Step 4: Use AI Advisor

1. Navigate to **AI Advisor** in the sidebar
2. Select a **Scope**:
   - **Full Estate** — analyzes all databases and schemas
   - **Schema** — focuses on one schema
   - **Single Table** — deep dive on one table (format: `OWNER.TABLE_NAME`)
3. Click **Analyze** — the AI will process your compression data
4. Review the markdown-formatted analysis
5. Ask **follow-up questions** in the chat input

### What the AI Analyzes

The AI Advisor automatically gathers:

- **Compression recommendations** — all pending candidates with size, hotness, advised type
- **Compression progress** — how much has been compressed vs remaining
- **Execution history** — recent failures with error messages
- **Growth alerts** — tables that grew back after compression
- **Forecast data** — estimated time and savings for remaining candidates

## Network & Security

| Aspect | Detail |
|--------|--------|
| Data location | All data stays on your local network |
| Cloud dependency | None — Ollama is fully self-hosted |
| API keys | Not required |
| Air-gapped | Yes — download model once, runs offline |
| Data sent to model | Table names, schemas, sizes, hotness scores, error messages |
| Data NOT sent | Actual table data, passwords, connection strings |

## Troubleshooting

### "Cannot reach Ollama" error

- Verify Ollama is running: `curl http://localhost:11434/api/tags`
- Check firewall: port 11434 must be open
- If using Docker, ensure the HCC Advisor container can reach the Ollama container

### "No models found" warning

- Download a model: `ollama pull llama3`
- Verify: `ollama list`

### Slow responses

- Use a smaller model (`phi3:mini` instead of `llama3`)
- Add a GPU for faster inference
- Reduce the scope (Schema instead of Full Estate)

### Out of memory

- Use `phi3:mini` (3 GB RAM) instead of larger models
- Close other applications to free RAM
- Consider running Ollama on a dedicated server

## Using AI Advisor in the Compression Wizard

The Compression Wizard (Step 3: Review Candidates) includes a **"Get AI Analysis"** button that redirects to the AI Advisor page with the current database context pre-loaded.

## Prompt Customization

The AI Advisor uses structured prompts with your compression data. The prompt template includes:

1. Estate summary (total objects, compressed count, savings)
2. Top candidates table (owner, table, size, hotness, advised type)
3. Recent failures (error messages)
4. Growth alerts (tables that grew back)
5. A structured request for 5-point analysis

The model responds with markdown-formatted recommendations that are rendered directly in the UI.
