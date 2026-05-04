/**
 * background.js — Service Worker
 *
 * Owns the recording lifecycle completely.
 * Popup is just a display — it reads state, sends commands, then can close.
 * Recording continues in offscreen.js regardless of popup being open or not.
 *
 * Auto-stop behaviour:
 *   - If the recorded tab is closed → auto-stop and run pipeline
 *   - If the recorded tab navigates away from Meet/Zoom/Teams → auto-stop
 *   - User closing popup does NOT stop the recording
 */

let currentState   = "idle";
let currentMessage = "";
let lastMeetingId  = null;
let recordingTabId = null;      // track which tab we're recording

let keepAliveInterval = null;

const OFFSCREEN_URL  = chrome.runtime.getURL("offscreen.html");
const SUPPORTED_URLS = ["meet.google.com", "zoom.us", "teams.microsoft.com"];

// ---------------------------------------------------------------------------
// State — persisted to session storage so popup reads it on reopen
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

  chrome.runtime.sendMessage({
    type: "STATE_UPDATE", state, message, meetingId: lastMeetingId,
  }).catch(() => {});
}

// ---------------------------------------------------------------------------
// Auto-stop listeners
// ---------------------------------------------------------------------------

// Tab closed — stop recording if it's the tab we're capturing
chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === recordingTabId && currentState === "recording") {
    console.log("MeetMind: meeting tab closed — auto-stopping recording.");
    updateState("processing", "Meeting ended — processing recording…");
    handleStopRecording(/* autoStopped= */ true);
  }
});

// NOTE: We intentionally do NOT listen to chrome.tabs.onUpdated for auto-stop.
// During screen sharing the user frequently switches tabs — that should never
// trigger a stop. Tab close (onRemoved above) is the only unambiguous signal
// that a meeting has actually ended.

// ---------------------------------------------------------------------------
// Keep-alive
// ---------------------------------------------------------------------------

function startKeepAlive() {
  stopKeepAlive();
  keepAliveInterval = setInterval(() => {
    chrome.runtime.getPlatformInfo(() => {});
  }, 20000);
}

function stopKeepAlive() {
  if (keepAliveInterval) {
    clearInterval(keepAliveInterval);
    keepAliveInterval = null;
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
  }
}

async function closeOffscreenDocument() {
  const exists = await chrome.offscreen.hasDocument();
  if (exists) await chrome.offscreen.closeDocument();
}

// ---------------------------------------------------------------------------
// Message handler
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {

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

  if (message.type === "START_RECORDING") {
    handleStartRecording(message.tabId);
    sendResponse({ ok: true });
    return true;
  }

  if (message.type === "STOP_RECORDING") {
    handleStopRecording();
    sendResponse({ ok: true });
    return true;
  }

  if (message.type === "PROCESSING") {
    updateState("processing", "Running AI pipeline…");
    return true;
  }

  if (message.type === "REPORT_READY") {
    stopKeepAlive();
    recordingTabId = null;
    const meetingId = message.meetingId;
    // Check before updateState changes currentState
    const newRecordingActive = currentState === "recording";
    updateState("done", "✅ Report ready!", meetingId);
    chrome.runtime.sendMessage({ type: "REPORT_READY", meetingId }).catch(() => {});
    if (!newRecordingActive) closeOffscreenDocument();
    return true;
  }

  if (message.type === "ERROR") {
    stopKeepAlive();
    recordingTabId = null;
    const msg = message.message || "Pipeline error.";
    const newRecordingActive = currentState === "recording";
    updateState("error", msg);
    chrome.runtime.sendMessage({ type: "ERROR", message: msg }).catch(() => {});
    if (!newRecordingActive) closeOffscreenDocument();
    return true;
  }
});

// ---------------------------------------------------------------------------
// Start recording
// ---------------------------------------------------------------------------

async function handleStartRecording(tabId) {
  try {
    recordingTabId = tabId;   // remember which tab we're watching
    updateState("recording", "Recording in progress…");
    startKeepAlive();

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

    await chrome.runtime.sendMessage({ type: "START_CAPTURE", streamId });
    console.log("MeetMind: recording started for tab", tabId);

  } catch (err) {
    console.error("MeetMind: start recording error:", err);
    stopKeepAlive();
    recordingTabId = null;
    chrome.storage.session.remove("meetmind_recording_start");
    updateState("error", `Failed to start: ${err.message}`);
    await closeOffscreenDocument();
  }
}

// ---------------------------------------------------------------------------
// Stop recording
// ---------------------------------------------------------------------------

async function handleStopRecording(autoStopped = false) {
  console.log(`MeetMind: stopping recording (auto: ${autoStopped})…`);
  chrome.storage.session.remove("meetmind_recording_start");

  if (!autoStopped) {
    // Manual stop — update state here
    // Auto-stop already updated state before calling this
    updateState("processing", "Processing recording…");
  }

  await chrome.runtime.sendMessage({ type: "STOP_CAPTURE" }).catch(() => {});
}