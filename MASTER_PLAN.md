# Meeting Intelligence Agent(MeetMind) — Master Plan
> Save this file. Read it when we drift. Every decision is final unless both of us agree to change it.

---

## Product Vision — One Sentence

A privacy-first, open-source meeting intelligence agent that invisibly captures Google Meet / Zoom Web / Teams Web audio via a Chrome extension, runs it through a local AI pipeline, and produces a structured report with summary, action items, and decisions — all on the user's machine, nothing leaves their device.

---

## Product Name (working title)
**MeetMind** — The Invisible Open-Source Notetaker

---

## What This Is NOT
- Not a calendar bot (no Zoom API approval needed)
- Not a file uploader only (the extension solves automatic capture)
- Not a cloud SaaS (Version 1 is fully local)
- Not a Chrome extension that injects into Meet's page (we use tabCapture API at browser level)

---

## The Two Versions — Final Decision

### Version 1 — Local Privacy App (BUILD THIS FIRST)
- Chrome extension captures Google Meet / Zoom Web / Teams Web tab audio
- Streams audio to local Python backend via WebSocket
- All AI processing runs on user's machine
- WhisperX for transcription (local)
- pyannote for diarization (local)
- Groq LLaMA 3.3 70b for LLM agents (only text goes to Groq, never audio)
- LangGraph 5-node agent pipeline
- Langfuse observability (traces only, no audio)
- Simple web dashboard at localhost:8000
- SQLite for meeting history
- Docker for easy installation

**User flow:**
```
Install Chrome extension (one time)
Install Docker + run docker-compose up (one time)
Join Google Meet → click extension icon → click Record
Meeting ends → click Stop
Report appears at localhost:8000
```

### Version 2 — Hosted Web App (BUILD AFTER VERSION 1 IS COMPLETE)
- Same Python pipeline, same agents, same graph
- Only change: swap local Whisper + pyannote for Groq Whisper API + AssemblyAI
- Hosted on Railway, public URL
- User auth (email + password)
- Pre-processed demo meetings in a demo account for recruiter demos
- Stripe payments (free tier: 3 meetings/month, pro: unlimited)
- yt-dlp support: paste a Zoom cloud recording link instead of uploading

**The one flag that controls everything:**
```bash
USE_LOCAL_MODELS=true   # Version 1
USE_LOCAL_MODELS=false  # Version 2
```

---

## Phase 2 — Native Desktop App (POST-GRADUATION, NOT IN SCOPE NOW)
- Lightweight desktop app (Python or Rust) for capturing native Zoom / Teams desktop apps
- System-level audio loopback — works like OBS Studio
- Mention in README as "Coming Soon"
- Do NOT build this now

---

## Current Build Status

| File | Status |
|------|--------|
| requirements.txt | ✅ Done |
| .env + .gitignore | ✅ Done |
| schemas/models.py | ✅ Done |
| schemas/state.py | ✅ Done |
| llm.py | ✅ Done |
| pipeline/asr.py | ✅ Done |
| pipeline/diarize.py | ✅ Done |
| pipeline/align.py | ⏳ NEXT |
| agents/cleaner.py | ❌ Not started |
| agents/summariser.py | ❌ Not started |
| agents/extractor.py | ❌ Not started |
| agents/decisions.py | ❌ Not started |
| agents/reporter.py | ❌ Not started |
| graph.py | ❌ Not started |
| main.py | ❌ Not started |
| extension/ | ❌ Not started |
| dashboard/ | ❌ Not started |
| database/ | ❌ Not started |
| Dockerfile | ❌ Not started |
| README.md | ❌ Not started |

---

## Complete File Structure — Final

```
meeting_agent/
    schemas/
        __init__.py
        state.py              MeetingState TypedDict
        models.py             ActionItem, Decision, MeetingReport, SpeakerProfile

    pipeline/
        __init__.py
        asr.py                WhisperX local (V1) / Groq Whisper API (V2)
        diarize.py            pyannote local (V1) / AssemblyAI (V2)
        align.py              merge Whisper + pyannote outputs — SAME FOR BOTH
        recorder.py           sounddevice live recording — V1 only, week 3

    agents/
        __init__.py
        cleaner.py            Node 1 — clean transcript
        summariser.py         Node 2 — executive summary
        extractor.py          Node 3 — action items (parallel)
        decisions.py          Node 4 — decisions made (parallel with Node 3)
        reporter.py           Node 5 — assemble final report

    graph.py                  LangGraph StateGraph — wires all 5 nodes
    llm.py                    Groq LLaMA 3.3 70b — single LLM instance

    database/
        __init__.py
        models.py             SQLAlchemy — users + meetings tables
        crud.py               save/fetch reports

    main.py                   FastAPI — REST endpoints + WebSocket for extension

    dashboard/
        index.html            login page
        app.html              meeting history dashboard
        report.html           individual report view
        static/               CSS + JS

    extension/
        manifest.json         Manifest V3
        popup.html            extension popup UI
        popup.js              start/stop recording, show status
        background.js         service worker — manages capture lifecycle
        offscreen.html        keeps audio capture alive full meeting duration
        offscreen.js          chrome.tabCapture + streams to backend WebSocket

    Dockerfile
    docker-compose.yml
    .env
    .env.example              safe to commit — shows what keys are needed
    requirements.txt
    README.md
```

---

## Build Order — DO NOT SKIP STEPS

### Stage 1 — Complete the Python pipeline
1. `pipeline/align.py` — merge Whisper + pyannote outputs into labelled transcript
2. Test align end-to-end on test.m4a
3. Commit

### Stage 2 — Build the 5 LangGraph agents
1. `agents/cleaner.py` — Node 1, cleans transcript
2. `agents/summariser.py` — Node 2, executive summary
3. `agents/extractor.py` — Node 3, action items (Pydantic validated)
4. `agents/decisions.py` — Node 4, decisions (runs PARALLEL with Node 3)
5. `agents/reporter.py` — Node 5, assembles MeetingReport
6. Test each agent individually before moving to the next
7. Commit each file separately

### Stage 3 — Wire LangGraph + Langfuse
1. `graph.py` — StateGraph with all 5 nodes, parallel branching for 3+4
2. Add Langfuse CallbackHandler to graph.py
3. Run full pipeline on test.m4a — verify report output
4. Screenshot Langfuse dashboard — this is a portfolio asset
5. Commit

### Stage 4 — Database + FastAPI backend
1. `database/models.py` + `database/crud.py` — SQLite, users + meetings tables
2. `main.py` — FastAPI with REST endpoints + WebSocket endpoint for extension audio stream
3. Test audio upload → pipeline → report via API
4. Commit

### Stage 5 — Chrome Extension
1. `extension/manifest.json` — Manifest V3, declare tabCapture + offscreen permissions
2. `extension/offscreen.html` + `extension/offscreen.js` — audio capture (IMPORTANT: tabCapture needs offscreen document in Manifest V3 to survive full meeting duration)
3. `extension/background.js` — service worker, manages capture lifecycle
4. `extension/popup.html` + `extension/popup.js` — UI for start/stop
5. Test on a real Google Meet call
6. Commit

### Stage 6 — Web Dashboard
1. `dashboard/` — clean HTML + Tailwind CSS (NOT Gradio — needs to look professional)
2. Login page, meeting history, individual report view
3. Pre-load 3 demo meetings for recruiter demos
4. Commit

### Stage 7 — Polish + Ship Version 1
1. `Dockerfile` + `docker-compose.yml`
2. `README.md` with architecture diagram, setup instructions, Loom demo video
3. Test: clone fresh repo, docker-compose up, full pipeline works
4. Push to GitHub
5. Version 1 complete

### Stage 8 — Version 2 (after Version 1 is fully working)
1. Add Groq Whisper API mode to `pipeline/asr.py`
2. Add AssemblyAI mode to `pipeline/diarize.py`
3. Set USE_LOCAL_MODELS=false, test full pipeline
4. Add user auth to dashboard
5. Add yt-dlp link support
6. Deploy to Railway
7. Pre-load demo account with 3 processed meetings
8. Add Stripe payments (optional)

---

## Tech Stack — Final, No Changes

| Component | Technology | Why |
|-----------|------------|-----|
| Transcription (V1) | WhisperX local | Free, private, runs on device |
| Transcription (V2) | Groq Whisper API | Fast, free tier, no local compute |
| Diarization (V1) | pyannote local | Best open-source, free |
| Diarization (V2) | AssemblyAI | Transcription + diarization in one call |
| LLM agents | Groq LLaMA 3.3 70b | Free tier, fast, good JSON output |
| Agent framework | LangGraph | Stateful graph, parallel nodes, production standard |
| Observability | Langfuse | Traces all node calls, latency, tokens, free tier |
| Data validation | Pydantic v2 | Validates all LLM outputs, prevents silent failures |
| API backend | FastAPI | REST + WebSocket, async, production grade |
| Frontend | HTML + Tailwind | Professional look for recruiter demos |
| Extension | Chrome Manifest V3 | tabCapture API, works on Meet/Zoom/Teams web |
| Database | SQLite + SQLAlchemy | Zero setup, single file, meeting history |
| Containers | Docker + docker-compose | One command install for users |
| Deployment (V2) | Railway | Connects to GitHub, free tier, public URL |

---

## Key Architecture Decisions — Never Change These

**1. State is the only communication channel between agents**
No agent imports from another agent. All data flows through MeetingState only.

**2. LLM is defined once in llm.py**
All agents do `from llm import llm`. No agent creates its own ChatGroq instance.

**3. Nodes 3 and 4 run in parallel**
ActionItemExtractor and DecisionLogger read the same transcript but write to different state keys. This is your key interview talking point — explain why they're independent.

**4. Audio never leaves the device in Version 1**
WhisperX and pyannote run locally. Only the text transcript goes to Groq for LLM reasoning.

**5. USE_LOCAL_MODELS flag controls the entire audio layer**
Swap from local to cloud by changing one line in .env. Agents, graph, everything else is untouched.

**6. Chrome tabCapture requires an offscreen document in Manifest V3**
Service workers shut down after 30 seconds. The offscreen document keeps audio capture alive for the full meeting. Do not try to do tabCapture from a service worker directly.

---

## The Chrome Extension — Critical Technical Detail

`chrome.tabCapture` in Manifest V3 cannot be triggered from a popup directly. The flow is:

```
User clicks popup button
    ↓
popup.js sends message to background.js (service worker)
    ↓
background.js creates an offscreen document
    ↓
offscreen.js calls chrome.tabCapture.capture()
    ↓
offscreen.js streams audio chunks to main.py WebSocket
    ↓
When user clicks Stop:
    offscreen.js stops capture
    main.py saves accumulated audio as WAV
    Runs through run_asr_pipeline()
    LangGraph pipeline executes
    Report saved to SQLite
    Dashboard updates
```

---

## Rules — Read This When We Drift

1. **Build Version 1 first, completely.** Do not add Version 2 features until a real meeting produces a clean report through the full pipeline including the Chrome extension.

2. **Build order is fixed.** align.py → agents (1→2→3+4→5) → graph.py → database → main.py → extension → dashboard → Docker. Do not skip ahead.

3. **Test every file before moving to the next.** Write a test_ file, run it, see clean output, delete it, commit, then move on.

4. **Commit after every file.** Format: `feat: add [filename] — [one sentence what it does]`

5. **Agents share nothing except State.** No cross-imports between agent files.

6. **LLM imported from llm.py only.** Never instantiate ChatGroq inside an agent file.

7. **The torchcodec warning is harmless.** Ignore it. WhisperX works fine without it.

8. **If stuck for more than 30 minutes, stop and paste the exact error.** Do not keep trying random fixes.

9. **Phase 2 (native desktop app) is not in scope.** Mention it in README as Coming Soon. Do not build it.

10. **Do not add features that are not in this plan without writing them down here first.**

---

## Resume Bullets — Copy When Done

```
• Built a privacy-first meeting intelligence system — Chrome extension 
  captures Google Meet tab audio via chrome.tabCapture API, streams to 
  a local FastAPI WebSocket, runs through WhisperX ASR + pyannote speaker 
  diarization + a LangGraph 5-node multi-agent pipeline — no audio ever 
  leaves the user's machine

• Designed parallel agent execution in LangGraph — ActionItemExtractor 
  and DecisionLogger run concurrently over the same transcript, each 
  writing to independent state keys, reducing pipeline latency ~40% vs 
  sequential execution

• Integrated Langfuse observability across all 5 agent nodes — tracked 
  p50/p95 latency per node, token cost per run, and full prompt/response 
  traces; used LLM-as-judge scoring on a 10-meeting evaluation dataset

• Architected a single codebase for two deployment modes — swap 
  local WhisperX + pyannote for Groq Whisper API + AssemblyAI with one 
  environment variable; deployed Version 2 as a hosted SaaS on Railway

• Stack: Python, LangGraph, WhisperX, pyannote.audio, Groq LLaMA 3.3 70b, 
  Langfuse, FastAPI, Chrome Extensions (Manifest V3), SQLite, 
  Docker, Tailwind CSS, Railway
```

---

## Recruiter Demo Flow — Version 2

```
Send recruiter: meetingagent.railway.app
Credentials:   demo@meetingagent.app / demo123

They log in → see 3 pre-processed meetings:
  - "Acme Q3 Planning" — 45 min, 4 speakers
  - "Engineering Standup" — 12 min, 3 speakers
  - "Product Review" — 28 min, 2 speakers

They click one → full report:
  - Executive summary
  - Action items with owners and deadlines
  - Decisions made
  - Full speaker-labelled transcript
  - Link to Langfuse trace showing all 5 agent nodes

Demo video of Chrome extension embedded on landing page
```

---

## Timeline

| Week | Goal |
|------|------|
| Week 1 | align.py + all 5 agents + graph.py working on test.m4a |
| Week 2 | database + FastAPI backend + WebSocket endpoint |
| Week 3 | Chrome extension working on a real Google Meet call |
| Week 4 | Web dashboard + Docker + README + Version 1 complete |
| Week 5-6 | Version 2: swap audio layer + deploy to Railway + demo account |

---

*Last updated: April 2026*
*Do not change this plan mid-build. If a decision needs to change, update this file first and note why.*
