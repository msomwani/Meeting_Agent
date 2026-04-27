/**
 * background.js — Service Worker
 *
 * Owns the recording lifecycle completely.
 * Popup is just a display — it reads state, sends commands, then can close.
 * Recording continues in offscreen.js regardless of popup being open or not.
 *
 * Key behaviours:
 *   - chrome.storage.session persists state across popup open/close cycles
 *   - Keep-alive ping every 20s prevents service worker shutdown mid-meeting
 *   - Recording start time saved so popup timer resumes correctly on reopen
 */

// In-memory state (fast access while service worker is alive)
let currentState   = "idle";
let currentMessage = "";
let lastMeetingId  = null;

// Keep service worker alive during recording
let keepAliveInterval = null;

const OFFSCREEN_URL = chrome.runtime.getURL("offscreen.html");

// ---------------------------------------------------------------------------
// State — written to session storage so popup can read on reopen
// ---------------------------------------------------------------------------

function updateState(state, message = "", meetingId = null) {
  currentState   = state;
  currentMessage = message;
  if (meetingId) lastMeetingId = meetingId;

  chrome.storage.session.set({
    meetmind_state:     state,
    meetmind_message:   message,
    meetmind_meetingId: meetingId || lastMeetingId || null,
  });

  // Broadcast to popup if open — fails silently if closed
  chrome.runtime.sendMessage({
    type:      "STATE_UPDATE",
    state,
    message,
    meetingId: lastMeetingId,
  }).catch(() => {});
}

// ---------------------------------------------------------------------------
// Keep-alive — prevents Chrome killing service worker during long meetings
// ---------------------------------------------------------------------------

function startKeepAlive() {
  stopKeepAlive();
  keepAliveInterval = setInterval(() => {
    chrome.runtime.getPlatformInfo(() => {});
  }, 20000);
  console.log("MeetMind: keep-alive started.");
}

function stopKeepAlive() {
  if (keepAliveInterval) {
    clearInterval(keepAliveInterval);
    keepAliveInterval = null;
    console.log("MeetMind: keep-alive stopped.");
  }
}

// ---------------------------------------------------------------------------
// Offscreen document helpers
// ---------------------------------------------------------------------------

async function ensureOffscreenDocument() {
  const existing = await chrome.offscreen.hasDocument();
  if (!existing) {
    await chrome.offscreen.createDocument({
      url:           OFFSCREEN_URL,
      reasons:       [chrome.offscreen.Reason.USER_MEDIA],
      justification: "Capture meeting tab audio via tabCapture API",
    });
    console.log("MeetMind: offscreen document created.");
  }
}

async function closeOffscreenDocument() {
  const exists = await chrome.offscreen.hasDocument();
  if (exists) {
    await chrome.offscreen.closeDocument();
    console.log("MeetMind: offscreen document closed.");
  }
}

// ---------------------------------------------------------------------------
// Message handler
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {

  // Popup opened — return persisted state
  if (message.type === "GET_STATE") {
    chrome.storage.session.get(
      ["meetmind_state", "meetmind_message", "meetmind_meetingId"],
      (stored) => {
        sendResponse({
          state:     stored.meetmind_state     || currentState,
          message:   stored.meetmind_message   || currentMessage,
          meetingId: stored.meetmind_meetingId || lastMeetingId,
        });
      }
    );
    return true;
  }

  // Popup: start recording
  if (message.type === "START_RECORDING") {
    handleStartRecording(message.tabId);
    sendResponse({ ok: true });
    return true;
  }

  // Popup: stop recording
  if (message.type === "STOP_RECORDING") {
    handleStopRecording();
    sendResponse({ ok: true });
    return true;
  }

  // Offscreen: pipeline running
  if (message.type === "PROCESSING") {
    updateState("processing", "Running AI pipeline…");
    return true;
  }

  // Offscreen: report ready
  if (message.type === "REPORT_READY") {
    stopKeepAlive();
    const meetingId = message.meetingId;
    updateState("done", "✅ Report ready!", meetingId);
    chrome.runtime.sendMessage({
      type: "REPORT_READY", meetingId,
    }).catch(() => {});
    closeOffscreenDocument();
    return true;
  }

  // Offscreen: error
  if (message.type === "ERROR") {
    stopKeepAlive();
    const msg = message.message || "Pipeline error.";
    updateState("error", msg);
    chrome.runtime.sendMessage({ type: "ERROR", message: msg }).catch(() => {});
    closeOffscreenDocument();
    return true;
  }
});

// ---------------------------------------------------------------------------
// Start recording
// ---------------------------------------------------------------------------

async function handleStartRecording(tabId) {
  try {
    updateState("recording", "Recording in progress…");
    startKeepAlive();

    // Save start time so popup timer can resume correctly on reopen
    chrome.storage.session.set({ meetmind_recording_start: Date.now() });

    await ensureOffscreenDocument();

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

    await chrome.runtime.sendMessage({
      type:     "START_CAPTURE",
      streamId: streamId,
    });

    console.log("MeetMind: recording started for tab", tabId);

  } catch (err) {
    console.error("MeetMind: start recording error:", err);
    stopKeepAlive();
    chrome.storage.session.remove("meetmind_recording_start");
    updateState("error", `Failed to start: ${err.message}`);
    await closeOffscreenDocument();
  }
}

// ---------------------------------------------------------------------------
// Stop recording
// ---------------------------------------------------------------------------

async function handleStopRecording() {
  console.log("MeetMind: stopping recording…");
  chrome.storage.session.remove("meetmind_recording_start");
  updateState("processing", "Processing recording…");

  // Tell offscreen.js to stop — result comes back as REPORT_READY or ERROR
  await chrome.runtime.sendMessage({ type: "STOP_CAPTURE" }).catch(() => {});
}