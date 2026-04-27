const WEBSOCKET_URL = "ws://localhost:8000/ws/audio";

let mediaStream       = null;
let audioContext      = null;
let processorNode     = null;
let destinationNode   = null;   // for speaker playback
let speakerAudio      = null;   // <audio> element for playback
let websocket         = null;
let isRecording       = false;

// ---------------------------------------------------------------------------
// Message handler
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {

  if (message.type === "START_CAPTURE") {
    startCapture(message.streamId)
      .then(() => sendResponse({ ok: true }))
      .catch((err) => {
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
  // Open tab audio stream
  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: {
        chromeMediaSource:   "tab",
        chromeMediaSourceId: streamId,
      },
    },
    video: false,
  });

  // Connect WebSocket
  websocket = new WebSocket(WEBSOCKET_URL);
  websocket.binaryType = "arraybuffer";

  await new Promise((resolve, reject) => {
    websocket.onopen  = resolve;
    websocket.onerror = () => reject(new Error(
      "WebSocket connection failed. Is the MeetMind server running on port 8000?"
    ));
    setTimeout(() => reject(new Error("WebSocket connection timed out")), 5000);
  });

  // Wait for server ready signal
  await new Promise((resolve, reject) => {
    websocket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "ready") {
          console.log("MeetMind: WebSocket ready, session:", data.session_id);
          resolve();
        }
      } catch {
        reject(new Error("Unexpected server message during handshake"));
      }
    };
    setTimeout(() => reject(new Error("Server did not send ready signal")), 5000);
  });

  // Set up ongoing WebSocket message handler (for report after STOP)
  websocket.onmessage = handleServerMessage;
  websocket.onerror   = () => sendError("WebSocket error during recording.");
  websocket.onclose   = () => {
    if (isRecording) sendError("WebSocket closed unexpectedly.");
  };

  // ── Audio graph ──────────────────────────────────────────────────────────
  audioContext = new AudioContext({ sampleRate: 48000 });
  const source = audioContext.createMediaStreamSource(mediaStream);

  // Branch 1 — capture branch → WebSocket
  processorNode = audioContext.createScriptProcessor(4096, 1, 1);
  processorNode.onaudioprocess = (event) => {
    if (!isRecording || !websocket || websocket.readyState !== WebSocket.OPEN) return;
    const float32 = event.inputBuffer.getChannelData(0);
    const int16   = float32ToInt16(float32);
    websocket.send(int16.buffer);
  };

  // Branch 2 — playback branch → speakers
  // MediaStreamDestinationNode creates a new MediaStream from the audio graph
  // which we feed into an <audio> element so the user still hears the call
  destinationNode = audioContext.createMediaStreamDestination();

  // Wire both branches from the same source
  source.connect(processorNode);
  source.connect(destinationNode);

  // ScriptProcessor needs to connect to destination to stay active
  // but we use a gain node set to 0 so it doesn't double-play
  const silentGain = audioContext.createGain();
  silentGain.gain.value = 0;
  processorNode.connect(silentGain);
  silentGain.connect(audioContext.destination);

  // Play the audio through speakers via an <audio> element
  speakerAudio = new Audio();
  speakerAudio.srcObject = destinationNode.stream;
  speakerAudio.volume    = 1.0;

  // Autoplay requires user gesture — in offscreen context this is allowed
  // because the offscreen document was created in response to user action
  try {
    await speakerAudio.play();
    console.log("MeetMind: speaker playback started.");
  } catch (err) {
    // Non-fatal — recording still works, user just won't hear audio
    console.warn("MeetMind: speaker playback failed (non-fatal):", err.message);
  }

  isRecording = true;
  console.log("MeetMind: recording started with audio split.");
}

// ---------------------------------------------------------------------------
// Stop capture
// ---------------------------------------------------------------------------

function stopCapture() {
  if (!isRecording) return;
  isRecording = false;

  console.log("MeetMind: stopping capture, sending STOP to server…");

  // Stop speaker playback
  if (speakerAudio) {
    speakerAudio.pause();
    speakerAudio.srcObject = null;
    speakerAudio = null;
  }

  // Disconnect audio nodes
  if (processorNode) {
    processorNode.disconnect();
    processorNode = null;
  }
  if (destinationNode) {
    destinationNode.disconnect();
    destinationNode = null;
  }
  if (audioContext) {
    audioContext.close();
    audioContext = null;
  }

  // Stop media tracks
  if (mediaStream) {
    mediaStream.getTracks().forEach(track => track.stop());
    mediaStream = null;
  }

  // Signal server to run pipeline
  if (websocket && websocket.readyState === WebSocket.OPEN) {
    websocket.send("STOP");
    // Keep WebSocket open — server sends report back
  }
}

// ---------------------------------------------------------------------------
// Handle server messages after STOP
// ---------------------------------------------------------------------------

function handleServerMessage(event) {
  try {
    const data = JSON.parse(event.data);

    if (data.type === "processing") {
      console.log("MeetMind: server is processing…");
      chrome.runtime.sendMessage({ type: "PROCESSING" });
    }

    if (data.type === "report") {
      console.log("MeetMind: report received:", data.payload?.meeting_id);
      websocket.close();
      chrome.runtime.sendMessage({
        type:      "REPORT_READY",
        meetingId: data.payload?.meeting_id,
        report:    data.payload,
      });
    }

    if (data.type === "error") {
      console.error("MeetMind: server error:", data.message);
      websocket.close();
      sendError(data.message);
    }

  } catch (err) {
    console.error("MeetMind: failed to parse server message:", err);
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function float32ToInt16(float32Array) {
  const int16 = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i++) {
    const clamped = Math.max(-1, Math.min(1, float32Array[i]));
    int16[i] = clamped < 0 ? clamped * 32768 : clamped * 32767;
  }
  return int16;
}

function sendError(message) {
  chrome.runtime.sendMessage({ type: "ERROR", message });
}