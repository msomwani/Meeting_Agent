/**
 * popup.js
 *
 * Handles the extension popup UI.
 * Sends messages to background.js — never touches tabCapture directly.
 *
 * States:
 *   idle       — ready to record
 *   recording  — capturing audio, timer running
 *   processing — pipeline running on server
 *   done       — report ready
 *   error      — something went wrong
 */

const dot        = document.getElementById("dot");
const statusText = document.getElementById("statusText");
const mainBtn    = document.getElementById("mainBtn");
const viewBtn    = document.getElementById("viewBtn");
const timerEl    = document.getElementById("timer");

let timerInterval = null;
let secondsElapsed = 0;
let lastMeetingId = null;

// ---------------------------------------------------------------------------
// State management
// ---------------------------------------------------------------------------

function setState(state, message = "") {
  dot.className = `dot ${state}`;

  switch (state) {
    case "idle":
      statusText.textContent = "Ready to record";
      mainBtn.textContent = "⏺ Start Recording";
      mainBtn.className = "btn btn-record";
      mainBtn.disabled = false;
      timerEl.classList.remove("visible");
      viewBtn.style.display = "none";
      stopTimer();
      break;

    case "recording":
      statusText.textContent = "Recording in progress…";
      mainBtn.textContent = "⏹ Stop Recording";
      mainBtn.className = "btn btn-stop";
      mainBtn.disabled = false;
      timerEl.classList.add("visible");
      startTimer();
      break;

    case "processing":
      statusText.textContent = message || "Running AI pipeline…";
      mainBtn.textContent = "Processing…";
      mainBtn.disabled = true;
      timerEl.classList.remove("visible");
      stopTimer();
      break;

    case "done":
      statusText.textContent = message || "Report ready!";
      mainBtn.textContent = "⏺ Start New Recording";
      mainBtn.className = "btn btn-record";
      mainBtn.disabled = false;
      viewBtn.style.display = lastMeetingId ? "block" : "none";
      break;

    case "error":
      statusText.textContent = message || "Something went wrong.";
      mainBtn.textContent = "⏺ Try Again";
      mainBtn.className = "btn btn-record";
      mainBtn.disabled = false;
      timerEl.classList.remove("visible");
      stopTimer();
      break;
  }
}

// ---------------------------------------------------------------------------
// Timer
// ---------------------------------------------------------------------------

function startTimer() {
  secondsElapsed = 0;
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
  const response = await chrome.runtime.sendMessage({ type: "GET_STATE" });
  const currentState = response?.state || "idle";

  if (currentState === "recording") {
    // Stop recording
    setState("processing", "Stopping and processing…");
    chrome.runtime.sendMessage({ type: "STOP_RECORDING" });
  } else {
    // Start recording — get the active tab first
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    if (!tab?.id) {
      setState("error", "No active tab found.");
      return;
    }

    const supportedUrls = ["meet.google.com", "zoom.us", "teams.microsoft.com"];
    const isSupported = supportedUrls.some(url => tab.url?.includes(url));

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
// Listen for updates from background.js
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
// Sync state when popup opens
// ---------------------------------------------------------------------------

(async () => {
  const response = await chrome.runtime.sendMessage({ type: "GET_STATE" });
  if (response?.state) {
    setState(response.state, response.message);
    if (response.meetingId) {
      lastMeetingId = response.meetingId;
      viewBtn.style.display = "block";
    }
  }
})();