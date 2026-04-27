/**
 * offscreen.js
 *
 * Runs inside the offscreen document — survives full meeting duration.
 *
 * Responsibilities:
 *   1. Receives START_CAPTURE with a streamId from background.js
 *   2. Opens the media stream using the streamId (tabCapture audio)
 *   3. Connects a WebSocket to ws://localhost:8000/ws/audio
 *   4. Streams raw PCM audio chunks to the WebSocket
 *   5. On STOP_CAPTURE: sends "STOP" text message to WebSocket
 *   6. Waits for the report JSON from the server
 *   7. Sends REPORT_READY or ERROR back to background.js
 *
 * Audio pipeline inside this file:
 *   MediaStream (tabCapture)
 *     → AudioContext
 *     → ScriptProcessorNode (captures raw PCM float32)
 *     → Convert to Int16 PCM
 *     → Send as binary over WebSocket
 */

const WEBSOCKET_URL = "ws://localhost:8000/ws/audio";

let mediaStream    = null;
let audioContext   = null;
let processorNode  = null;
let websocket      = null;
let isRecording    = false;

// ---------------------------------------------------------------------------
// Message handler — receives from background.js
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {

  if (message.type === "START_CAPTURE") {
    startCapture(message.streamId)
      .then(() => sendResponse({ ok: true }))
      .catch((err) => {
        sendError(`Capture failed: ${err.message}`);
        sendResponse({ ok: false });
      });
    return true; // async response
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
  // Open the tab audio stream using the streamId from background.js
  // getUserMedia with chromeMediaSource + streamId is the Manifest V3 way
  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: streamId,
      },
    },
    video: false,
  });

  // Connect WebSocket
  websocket = new WebSocket(WEBSOCKET_URL);
  websocket.binaryType = "arraybuffer";

  await new Promise((resolve, reject) => {
    websocket.onopen = resolve;
    websocket.onerror = () => reject(new Error("WebSocket connection failed. Is the MeetMind server running?"));
    // Timeout after 5 seconds
    setTimeout(() => reject(new Error("WebSocket connection timed out")), 5000);
  });

  // Wait for server ready message
  await new Promise((resolve, reject) => {
    websocket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "ready") {
          console.log("MeetMind: WebSocket ready, session:", data.session_id);
          resolve();
        }
      } catch {
        reject(new Error("Unexpected server message"));
      }
    };
    setTimeout(() => reject(new Error("Server did not send ready signal")), 5000);
  });

  // Set up WebSocket message handler for the report
  websocket.onmessage = handleServerMessage;
  websocket.onerror   = () => sendError("WebSocket error during recording.");
  websocket.onclose   = () => {
    if (isRecording) {
      sendError("WebSocket closed unexpectedly during recording.");
    }
  };

  // Set up audio processing
  audioContext  = new AudioContext({ sampleRate: 48000 });
  const source  = audioContext.createMediaStreamSource(mediaStream);

  // ScriptProcessorNode: bufferSize 4096, 1 input channel, 1 output channel
  // Deprecated but still the most reliable cross-platform approach for raw PCM
  processorNode = audioContext.createScriptProcessor(4096, 1, 1);

  processorNode.onaudioprocess = (event) => {
    if (!isRecording || !websocket || websocket.readyState !== WebSocket.OPEN) return;

    const float32 = event.inputBuffer.getChannelData(0);
    const int16   = float32ToInt16(float32);
    websocket.send(int16.buffer);
  };

  source.connect(processorNode);
  processorNode.connect(audioContext.destination);

  isRecording = true;
  console.log("MeetMind: recording started.");
}

// ---------------------------------------------------------------------------
// Stop capture
// ---------------------------------------------------------------------------

function stopCapture() {
  if (!isRecording) return;

  isRecording = false;
  console.log("MeetMind: stopping capture, sending STOP to server…");

  // Disconnect audio nodes
  if (processorNode) {
    processorNode.disconnect();
    processorNode = null;
  }
  if (audioContext) {
    audioContext.close();
    audioContext = null;
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach(track => track.stop());
    mediaStream = null;
  }

  // Send STOP signal to server — triggers pipeline
  if (websocket && websocket.readyState === WebSocket.OPEN) {
    websocket.send("STOP");
    // Keep WebSocket open — server will send back the report
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
  /**
   * Converts Float32 PCM (range -1 to 1) to Int16 PCM.
   * WebSocket sends the raw Int16 buffer — main.py reassembles it into WAV.
   */
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