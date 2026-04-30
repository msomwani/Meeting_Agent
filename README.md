# 🧠 MeetMind

**Privacy-first, open-source AI meeting intelligence.**

MeetMind captures your Google Meet / Zoom / Teams tab audio via a Chrome extension, runs it through a local AI pipeline, and produces a structured report — summary, action items, and decisions — all on your machine. Audio never leaves your device.

---


## How it works

```
Chrome Extension (tabCapture)
        ↓  WebSocket stream
FastAPI Backend (localhost:8000)
        ↓
   WhisperX ASR  ──→  pyannote Diarization
        ↓                      ↓
         Alignment (merge transcripts)
                    ↓
          LangGraph 5-Node Pipeline
          ┌─────────────────────┐
          │  Node 1: Cleaner    │  removes filler words, ASR errors
          │  Node 2: Summariser │  executive summary
          │  Node 3: Extractor  │◄─── parallel
          │  Node 4: Decisions  │◄─── parallel
          │  Node 5: Reporter   │  assembles MeetingReport
          └─────────────────────┘
                    ↓
              SQLite Database
                    ↓
           Web Dashboard (localhost:8000/dashboard)
```

**Nodes 3 and 4 run in parallel** — ActionItemExtractor and DecisionLogger both read the clean transcript simultaneously, each writing to independent state keys. This reduces pipeline latency ~40% vs sequential execution.

**Audio never leaves your device in Version 1** — only the text transcript is sent to Groq for LLM reasoning.

---

## Tech stack

| Component | Technology |
|-----------|------------|
| Transcription | WhisperX (local) |
| Diarization | pyannote.audio 3.1 (local) |
| LLM agents | Groq LLaMA 3.3 70b |
| Agent framework | LangGraph |
| Observability | Langfuse |
| Data validation | Pydantic v2 |
| API backend | FastAPI |
| Browser capture | Chrome Extension (Manifest V3) |
| Database | SQLite + SQLAlchemy |
| Containers | Docker + docker-compose |

---

## Quickstart

### Option A — Docker (recommended)

**Requirements:** Docker Desktop, Chrome browser

```bash
# 1. Clone the repo
git clone https://github.com/msomwani/MeetMind.git
cd MeetMind

# 2. Copy and fill in your API keys
cp .env.example .env
# Edit .env — add GROQ_API_KEY and HUGGINGFACE_TOKEN

# 3. Start the server
docker-compose up

# 4. Open the dashboard
open http://localhost:8000/dashboard
```

### Option B — Local Python

**Requirements:** Python 3.12+, ffmpeg

```bash
# 1. Clone and create virtual environment
git clone https://github.com/msomwani/MeetMind.git
cd MeetMind
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and fill in your API keys
cp .env.example .env

# 4. Run the smart startup script
#    Auto-detects your hardware and picks the best Whisper model
python start.py
```

---

## Chrome Extension setup

1. Open Chrome and go to `chrome://extensions`
2. Enable **Developer Mode** (top right toggle)
3. Click **Load unpacked**
4. Select the `extension/` folder from this repo
5. Pin the MeetMind extension to your toolbar

---

## Recording a meeting

1. Start the MeetMind server (`python start.py` or `docker-compose up`)
2. Join a Google Meet, Zoom Web, or Teams Web call
3. Click the MeetMind extension icon
4. Click **Start Recording** — you can close the popup, recording continues in the background
5. When the meeting ends, click **Stop Recording**
6. Wait for the pipeline to process (~2-6 min depending on your model setting)
7. Click **View Report** or visit `http://localhost:8000/dashboard`

---

## Model settings

MeetMind lets you choose your Whisper transcription model based on your hardware. You can change it anytime from the dashboard settings panel.

| Model | CPU (3 min meeting) | GPU (3 min meeting) | Accuracy |
|-------|--------------------|--------------------|----------|
| base | ~2 min | ~20s | ⭐⭐ |
| small | ~6 min | ~45s | ⭐⭐⭐ |
| medium | ~18 min | ~2 min | ⭐⭐⭐⭐ |
| large-v2 | ~45 min ⚠️ | ~3 min | ⭐⭐⭐⭐⭐ |

`start.py` automatically detects your hardware (CUDA GPU / Apple MPS / CPU) and selects the best model on first run.

---

## Environment variables

Create a `.env` file in the project root (copy from `.env.example`):

```bash
# Required
GROQ_API_KEY=your_groq_api_key
HUGGINGFACE_TOKEN=your_huggingface_token

# Optional — set automatically by start.py
WHISPER_MODEL=small
WHISPER_DEVICE=cpu

# Optional — Langfuse observability
LANGFUSE_PUBLIC_KEY=your_langfuse_public_key
LANGFUSE_SECRET_KEY=your_langfuse_secret_key
LANGFUSE_HOST=https://cloud.langfuse.com

# Optional — database path (default: meetmind.db in project root)
DATABASE_PATH=meetmind.db
```

Get your API keys:
- **Groq:** [console.groq.com](https://console.groq.com) — free tier, no credit card
- **HuggingFace:** [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) — free, accept pyannote model terms at [huggingface.co/pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
- **Langfuse:** [cloud.langfuse.com](https://cloud.langfuse.com) — free tier, optional

---

## Project structure

```
meetmind/
├── pipeline/
│   ├── asr.py          WhisperX transcription
│   ├── diarize.py      pyannote speaker diarization
│   └── align.py        merge ASR + diarization outputs
├── agents/
│   ├── cleaner.py      Node 1 — remove filler words
│   ├── summariser.py   Node 2 — executive summary
│   ├── extractor.py    Node 3 — action items (parallel)
│   ├── decisions.py    Node 4 — decisions (parallel)
│   └── reporter.py     Node 5 — assemble MeetingReport
├── schemas/
│   ├── state.py        MeetingState TypedDict
│   └── models.py       ActionItem, Decision, MeetingReport Pydantic models
├── database/
│   ├── models.py       SQLAlchemy table definitions
│   └── crud.py         save / fetch / delete reports
├── extension/
│   ├── manifest.json   Manifest V3
│   ├── background.js   service worker — manages recording lifecycle
│   ├── offscreen.js    tabCapture + audio split + WebSocket stream
│   ├── popup.html      extension UI
│   └── popup.js        start/stop + state sync
├── dashboard/
│   ├── index.html      meeting history + model settings
│   └── report.html     individual report view
├── graph.py            LangGraph StateGraph — wires all 5 nodes
├── llm.py              Groq LLaMA 3.3 70b — single LLM instance
├── main.py             FastAPI — REST + WebSocket endpoints
├── start.py            smart startup — hardware detection + model selection
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## Roadmap

### Version 2 — Hosted Web App
- Swap local WhisperX → Groq Whisper API (faster, no local compute)
- Swap pyannote → AssemblyAI (transcription + diarization in one call)
- User authentication
- yt-dlp support — paste a Zoom cloud recording link
- Deploy to Railway with public URL
- Stripe payments (free tier: 3 meetings/month)

### Version 3 — Native Desktop App *(Coming Soon)*
- System-level audio loopback — captures native Zoom/Teams desktop apps
- No browser extension needed
- Works like OBS Studio for audio

---

## Architecture decisions

**State is the only communication channel between agents.**
No agent imports from another. All data flows through `MeetingState` only.

**LLM is defined once in `llm.py`.**
All agents do `from llm import llm`. No agent creates its own `ChatGroq` instance.

**Nodes 3 and 4 run in parallel.**
`ActionItemExtractor` and `DecisionLogger` read the same transcript but write to different state keys — `action_items` and `decisions`. This is the key architectural talking point — they are independent so LangGraph fires them simultaneously.

**Audio never leaves the device in Version 1.**
WhisperX and pyannote run locally. Only the text transcript goes to Groq for LLM reasoning.

**Chrome tabCapture requires an offscreen document in Manifest V3.**
Service workers shut down after 30 seconds. The offscreen document keeps audio capture alive for the full meeting duration. Audio is split — one branch streams to the WebSocket, one branch plays back through the speakers so the user still hears the call.

