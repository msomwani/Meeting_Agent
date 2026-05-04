const WEBSOCKET_URL = "ws://localhost:8000/ws/audio";
const API_URL       = "http://localhost:8000";

let tabStream        = null;
let micStream        = null;
let audioContext     = null;
let mediaRecorder    = null;
let speakerAudio     = null;
let websocket        = null;
let isRecording      = false;
let currentSessionId = null;

// ---------------------------------------------------------------------------
// Message handler
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "START_CAPTURE") {
    startCapture(message.streamId)
      .then(() => sendResponse({ ok: true }))
      .catch((err) => {
        // Release any resources that were allocated before the failure
        if (speakerAudio) { speakerAudio.pause(); speakerAudio.srcObject = null; speakerAudio = null; }
        if (tabStream)    { tabStream.getTracks().forEach(t => t.stop()); tabStream = null; }
        if (micStream)    { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
        if (audioContext) { audioContext.close(); audioContext = null; }
        if (websocket)    { websocket.close(); websocket = null; }
        isRecording = false;
        sendError(`Capture failed: ${err.message}`);
        sendResponse({ ok: false });
      });
    return true;
  }

  if (message.type === "STOP_CAPTURE") {
    stopCapture();
    sendResponse({ ok: true });
    return true;
  }
});

// ---------------------------------------------------------------------------
// Start capture
// ---------------------------------------------------------------------------

async function startCapture(streamId) {

  // ── 1. Tab audio stream (other people's voices) ───────────────────────────
  tabStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: {
        chromeMediaSource:   "tab",
        chromeMediaSourceId: streamId,
      },
    },
    video: false,
  });

  // ── 2. Microphone stream (your voice) ─────────────────────────────────────
  // Request mic separately — if user denies, we fall back to tab-only
  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        sampleRate:       48000,
      },
      video: false,
    });
    console.log("MeetMind: microphone captured.");
  } catch (err) {
    console.warn("MeetMind: microphone not available, capturing tab audio only:", err.message);
    micStream = null;
  }

  // ── 3. Speaker playback (tab audio only — no mic echo) ────────────────────
  speakerAudio = new Audio();
  speakerAudio.srcObject = tabStream;
  speakerAudio.volume    = 1.0;
  try {
    await speakerAudio.play();
    console.log("MeetMind: speaker playback started.");
  } catch (err) {
    console.warn("MeetMind: speaker playback failed (non-fatal):", err.message);
  }

  // ── 4. Mix tab + mic into a single stream ─────────────────────────────────
  audioContext = new AudioContext({ sampleRate: 48000 });

  const destination = audioContext.createMediaStreamDestination();

  // Connect tab audio to mixer
  const tabSource = audioContext.createMediaStreamSource(tabStream);
  tabSource.connect(destination);

  // Connect mic to mixer (if available)
  if (micStream) {
    const micSource = audioContext.createMediaStreamSource(micStream);
    micSource.connect(destination);
  }

  const mixedStream = destination.stream;

  // ── 5. WebSocket connection ───────────────────────────────────────────────
  websocket = new WebSocket(WEBSOCKET_URL);
  websocket.binaryType = "arraybuffer";

  await new Promise((resolve, reject) => {
    websocket.onopen  = resolve;
    websocket.onerror = () => reject(new Error(
      "WebSocket connection failed. Is the MeetMind server running on port 8000?"
    ));
    setTimeout(() => reject(new Error("WebSocket connection timed out")), 5000);
  });

  await new Promise((resolve, reject) => {
    websocket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "ready") {
          currentSessionId = data.session_id;
          console.log("MeetMind: WebSocket ready, session:", currentSessionId);
          resolve();
        }
      } catch {
        reject(new Error("Unexpected server message during handshake"));
      }
    };
    setTimeout(() => reject(new Error("Server did not send ready signal")), 5000);
  });

  websocket.onmessage = handleServerMessage;
  websocket.onerror   = () => sendError("WebSocket error during recording.");
  websocket.onclose   = () => {
    if (isRecording) sendError("WebSocket closed unexpectedly.");
  };

  // ── 6. MediaRecorder on the MIXED stream ──────────────────────────────────
  const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
    ? "audio/webm;codecs=opus"
    : "audio/webm";

  mediaRecorder = new MediaRecorder(mixedStream, {
    mimeType,
    audioBitsPerSecond: 128000,
  });

  mediaRecorder.ondataavailable = (event) => {
    if (
      event.data &&
      event.data.size > 0 &&
      websocket &&
      websocket.readyState === WebSocket.OPEN
    ) {
      event.data.arrayBuffer().then(buf => websocket.send(buf));
    }
  };

  mediaRecorder.onerror = (err) => {
    console.error("MeetMind: MediaRecorder error:", err);
    sendError("Recording error — please try again.");
  };

  // Collect chunks every 500ms
  mediaRecorder.start(500);
  isRecording = true;

  console.log(`MeetMind: recording started — tab + ${micStream ? "mic" : "no mic"} (${mimeType})`);
}

// ---------------------------------------------------------------------------
// Stop capture
// ---------------------------------------------------------------------------

function stopCapture() {
  if (!isRecording) return;
  isRecording = false;

  console.log("MeetMind: stopping capture…");

  // Stop speaker
  if (speakerAudio) {
    speakerAudio.pause();
    speakerAudio.srcObject = null;
    speakerAudio = null;
  }

  // Stop recorder — wait for onstop before sending STOP to server
  // This ensures all buffered chunks are delivered first
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.onstop = () => {
      console.log("MeetMind: MediaRecorder stopped, sending STOP to server.");
      if (websocket && websocket.readyState === WebSocket.OPEN) {
        websocket.send("STOP");
      }

      // Clean up audio context
      if (audioContext) {
        audioContext.close();
        audioContext = null;
      }
    };
    mediaRecorder.stop();
  }

  // Stop all tracks
  if (tabStream) { tabStream.getTracks().forEach(t => t.stop()); tabStream = null; }
  if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
}

// ---------------------------------------------------------------------------
// Handle server messages after STOP
// ---------------------------------------------------------------------------

function handleServerMessage(event) {
  try {
    const data = JSON.parse(event.data);

    if (data.type === "accepted") {
      console.log("MeetMind: accepted, polling for report…");
      websocket.close();
      chrome.runtime.sendMessage({ type: "PROCESSING" });
      pollForReport(data.session_id);
    }

    if (data.type === "error") {
      websocket.close();
      sendError(data.message);
    }

  } catch (err) {
    console.error("MeetMind: failed to parse server message:", err);
  }
}

// ---------------------------------------------------------------------------
// Poll for report
// ---------------------------------------------------------------------------

function pollForReport(sessionId) {
  const expectedFilename = `extension_${sessionId.slice(0, 8)}.wav`;
  let attempts     = 0;
  const maxAttempts = 72;

  const interval = setInterval(async () => {
    attempts++;
    try {
      // Check session status first — gives immediate feedback on pipeline failure
      const statusRes = await fetch(`${API_URL}/sessions/${sessionId}/status`);
      const status    = await statusRes.json();

      if (status.status === "error") {
        clearInterval(interval);
        sendError(`Pipeline failed: ${status.message || "Unknown error. Check server logs."}`);
        return;
      }

      if (status.status === "done") {
        const res      = await fetch(`${API_URL}/meetings`);
        const meetings = await res.json();
        const match    = meetings.find(m => m.audio_filename === expectedFilename);
        if (match) {
          clearInterval(interval);
          chrome.runtime.sendMessage({ type: "REPORT_READY", meetingId: match.meeting_id });
          return;
        }
      }

      if (attempts >= maxAttempts) {
        clearInterval(interval);
        sendError("Processing timed out — check the dashboard manually.");
      }
    } catch (err) {
      console.warn(`MeetMind: poll attempt ${attempts} failed:`, err.message);
      if (attempts >= maxAttempts) {
        clearInterval(interval);
        sendError("Processing timed out — check the dashboard manually.");
      }
    }
  }, 10000);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function sendError(message) {
  chrome.runtime.sendMessage({ type: "ERROR", message });
}