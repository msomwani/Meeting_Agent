/**
 * popup.js
 *
 * Pure display layer — reads state from background.js, sends commands.
 * Closing the popup does NOT stop the recording.
 * When reopened mid-recording, it re-syncs and resumes showing the timer.
 */

const dot        = document.getElementById("dot");
const statusText = document.getElementById("statusText");
const mainBtn    = document.getElementById("mainBtn");
const viewBtn    = document.getElementById("viewBtn");
const timerEl    = document.getElementById("timer");

let timerInterval  = null;
let secondsElapsed = 0;
let lastMeetingId  = null;

// ---------------------------------------------------------------------------
// State management
// ---------------------------------------------------------------------------

function setState(state, message = "", resumeSeconds = 0) {
  dot.className = `dot ${state}`;

  switch (state) {
    case "idle":
      statusText.textContent = "Ready to record";
      mainBtn.textContent    = "⏺ Start Recording";
      mainBtn.className      = "btn btn-record";
      mainBtn.disabled       = false;
      timerEl.classList.remove("visible");
      viewBtn.style.display  = "none";
      stopTimer();
      break;

    case "recording":
      statusText.textContent = "Recording in progress…";
      mainBtn.textContent    = "⏹ Stop Recording";
      mainBtn.className      = "btn btn-stop";
      mainBtn.disabled       = false;
      timerEl.classList.add("visible");
      // Resume from where we were if popup was reopened
      startTimer(resumeSeconds);
      break;

    case "processing":
      statusText.textContent = message || "Running AI pipeline…";
      mainBtn.textContent    = "Processing…";
      mainBtn.disabled       = true;
      timerEl.classList.remove("visible");
      stopTimer();
      break;

    case "done":
      statusText.textContent = message || "Report ready!";
      mainBtn.textContent    = "⏺ Start New Recording";
      mainBtn.className      = "btn btn-record";
      mainBtn.disabled       = false;
      viewBtn.style.display  = lastMeetingId ? "block" : "none";
      stopTimer();
      break;

    case "error":
      statusText.textContent = message || "Something went wrong.";
      mainBtn.textContent    = "⏺ Try Again";
      mainBtn.className      = "btn btn-record";
      mainBtn.disabled       = false;
      timerEl.classList.remove("visible");
      stopTimer();
      break;
  }
}

// ---------------------------------------------------------------------------
// Timer
// ---------------------------------------------------------------------------

function startTimer(fromSeconds = 0) {
  stopTimer();
  secondsElapsed = fromSeconds;
  updateTimerDisplay();
  timerInterval = setInterval(() => {
    secondsElapsed++;
    updateTimerDisplay();
  }, 1000);
}

function stopTimer() {
  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }
}

function updateTimerDisplay() {
  const m = String(Math.floor(secondsElapsed / 60)).padStart(2, "0");
  const s = String(secondsElapsed % 60).padStart(2, "0");
  timerEl.textContent = `${m}:${s}`;
}

// ---------------------------------------------------------------------------
// Button handler
// ---------------------------------------------------------------------------

mainBtn.addEventListener("click", async () => {
  const response     = await chrome.runtime.sendMessage({ type: "GET_STATE" });
  const currentState = response?.state || "idle";

  if (currentState === "recording") {
    setState("processing", "Stopping and processing…");
    chrome.runtime.sendMessage({ type: "STOP_RECORDING" });
  } else {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    if (!tab?.id) {
      setState("error", "No active tab found.");
      return;
    }

    const supportedUrls = ["meet.google.com", "zoom.us", "teams.microsoft.com"];
    const isSupported   = supportedUrls.some(url => tab.url?.includes(url));

    if (!isSupported) {
      setState("error", "Open a Google Meet, Zoom, or Teams tab first.");
      return;
    }

    setState("recording");
    chrome.runtime.sendMessage({ type: "START_RECORDING", tabId: tab.id });
  }
});

// ---------------------------------------------------------------------------
// View report button
// ---------------------------------------------------------------------------

viewBtn.addEventListener("click", () => {
  if (lastMeetingId) {
    chrome.tabs.create({
      url: `http://localhost:8000/dashboard/report.html?id=${lastMeetingId}`
    });
  }
});

// ---------------------------------------------------------------------------
// Listen for live updates from background.js while popup is open
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === "STATE_UPDATE") {
    setState(message.state, message.message);
  }

  if (message.type === "REPORT_READY") {
    lastMeetingId = message.meetingId;
    setState("done", "✅ Report ready!");
    viewBtn.style.display = "block";
  }

  if (message.type === "ERROR") {
    setState("error", message.message || "Pipeline error.");
  }
});

// ---------------------------------------------------------------------------
// Sync state when popup opens — resumes correctly if recording is in progress
// ---------------------------------------------------------------------------

(async () => {
  const response = await chrome.runtime.sendMessage({ type: "GET_STATE" });

  if (response?.meetingId) {
    lastMeetingId = response.meetingId;
  }

  if (response?.state === "recording") {
    // Estimate elapsed time from session storage timestamp
    const stored = await chrome.storage.session.get("meetmind_recording_start");
    let elapsed = 0;
    if (stored.meetmind_recording_start) {
      elapsed = Math.floor((Date.now() - stored.meetmind_recording_start) / 1000);
    }
    setState("recording", "", elapsed);
  } else if (response?.state) {
    setState(response.state, response.message);
    if (response.meetingId) {
      viewBtn.style.display = "block";
    }
  }
})();