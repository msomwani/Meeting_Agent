/**
 * background.js — Service Worker
 *
 * Manages the recording lifecycle.
 * Service workers shut down after ~30s of inactivity, so audio capture
 * lives in the offscreen document (offscreen.js), not here.
 *
 * This file:
 *   - Receives messages from popup.js
 *   - Creates/destroys the offscreen document
 *   - Forwards START/STOP to offscreen.js
 *   - Forwards report/error back to popup.js
 *   - Tracks global state so popup can sync on open
 */

// Global state — persists as long as service worker is alive
let currentState  = "idle";
let currentMessage = "";
let lastMeetingId  = null;

const OFFSCREEN_URL = chrome.runtime.getURL("offscreen.html");

// ---------------------------------------------------------------------------
// State helpers
// ---------------------------------------------------------------------------

function updateState(state, message = "", meetingId = null) {
  currentState   = state;
  currentMessage = message;
  if (meetingId) lastMeetingId = meetingId;

  // Broadcast to popup if it's open
  chrome.runtime.sendMessage({
    type:      "STATE_UPDATE",
    state,
    message,
    meetingId: lastMeetingId,
  }).catch(() => {
    // Popup might be closed — that's fine
  });
}

// ---------------------------------------------------------------------------
// Offscreen document helpers
// ---------------------------------------------------------------------------

async function ensureOffscreenDocument() {
  const existing = await chrome.offscreen.hasDocument();
  if (!existing) {
    await chrome.offscreen.createDocument({
      url:    OFFSCREEN_URL,
      reasons: [chrome.offscreen.Reason.USER_MEDIA],
      justification: "Capture meeting tab audio via tabCapture API",
    });
  }
}

async function closeOffscreenDocument() {
  const exists = await chrome.offscreen.hasDocument();
  if (exists) {
    await chrome.offscreen.closeDocument();
  }
}

// ---------------------------------------------------------------------------
// Message handler — receives from popup.js and offscreen.js
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {

  // --- Popup requests current state ---
  if (message.type === "GET_STATE") {
    sendResponse({
      state:     currentState,
      message:   currentMessage,
      meetingId: lastMeetingId,
    });
    return true;
  }

  // --- Popup: start recording ---
  if (message.type === "START_RECORDING") {
    handleStartRecording(message.tabId);
    sendResponse({ ok: true });
    return true;
  }

  // --- Popup: stop recording ---
  if (message.type === "STOP_RECORDING") {
    handleStopRecording();
    sendResponse({ ok: true });
    return true;
  }

  // --- Offscreen: pipeline is processing ---
  if (message.type === "PROCESSING") {
    updateState("processing", "Running AI pipeline…");
    return true;
  }

  // --- Offscreen: report is ready ---
  if (message.type === "REPORT_READY") {
    const meetingId = message.meetingId;
    updateState("done", "✅ Report ready!", meetingId);

    // Also send specific REPORT_READY so popup can show view button
    chrome.runtime.sendMessage({
      type:      "REPORT_READY",
      meetingId: meetingId,
    }).catch(() => {});

    closeOffscreenDocument();
    return true;
  }

  // --- Offscreen: error ---
  if (message.type === "ERROR") {
    updateState("error", message.message || "Pipeline error.");
    chrome.runtime.sendMessage({
      type:    "ERROR",
      message: message.message,
    }).catch(() => {});
    closeOffscreenDocument();
    return true;
  }
});

// ---------------------------------------------------------------------------
// Start recording flow
// ---------------------------------------------------------------------------

async function handleStartRecording(tabId) {
  try {
    updateState("recording", "Recording in progress…");

    // Create offscreen document first
    await ensureOffscreenDocument();

    // Get a tabCapture stream ID for the target tab
    // This must be called from background.js — not from offscreen
    const streamId = await new Promise((resolve, reject) => {
      chrome.tabCapture.getMediaStreamId(
        { targetTabId: tabId },
        (id) => {
          if (chrome.runtime.lastError) {
            reject(new Error(chrome.runtime.lastError.message));
          } else {
            resolve(id);
          }
        }
      );
    });

    // Send stream ID to offscreen.js — it will open the media stream
    await chrome.runtime.sendMessage({
      type:     "START_CAPTURE",
      streamId: streamId,
    });

  } catch (err) {
    console.error("Start recording error:", err);
    updateState("error", `Failed to start: ${err.message}`);
    await closeOffscreenDocument();
  }
}

// ---------------------------------------------------------------------------
// Stop recording flow
// ---------------------------------------------------------------------------

async function handleStopRecording() {
  updateState("processing", "Processing recording…");

  // Tell offscreen.js to stop and send STOP to the WebSocket
  await chrome.runtime.sendMessage({ type: "STOP_CAPTURE" }).catch(() => {});
  // offscreen.js will send REPORT_READY or ERROR back when done
}