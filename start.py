"""
start.py

MeetMind smart startup script.

What it does:
    1. Detects your OS, CPU, RAM, and GPU
    2. Picks the best Whisper model for your hardware
    3. Shows you what was selected and why — with real timing estimates
    4. Lets you override the selection if you want
    5. Saves the choice to .env
    6. Starts the MeetMind server

Run with:
    python start.py
"""

import os
import sys
import platform
import subprocess
import shutil
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Model definitions — timing estimates for a 3-minute meeting
# ---------------------------------------------------------------------------

MODELS = {
    "base": {
        "name":        "base",
        "label":       "Base (Fastest)",
        "ram_required": 2,     # GB
        "cpu_time":    "~2 min for a 3 min meeting",
        "gpu_time":    "~20s for a 3 min meeting",
        "accuracy":    "⭐⭐ — misses words, struggles with accents and fast speech",
        "best_for":    "Quick tests, very low-end hardware",
        "warning":     "⚠️  Noticeable errors in real meetings",
    },
    "small": {
        "name":        "small",
        "label":       "Small (Balanced)",
        "ram_required": 4,
        "cpu_time":    "~6 min for a 3 min meeting",
        "gpu_time":    "~45s for a 3 min meeting",
        "accuracy":    "⭐⭐⭐ — decent accuracy, handles most accents",
        "best_for":    "CPU machines with 8GB+ RAM",
        "warning":     None,
    },
    "medium": {
        "name":        "medium",
        "label":       "Medium (Good)",
        "ram_required": 8,
        "cpu_time":    "~18 min for a 3 min meeting",
        "gpu_time":    "~2 min for a 3 min meeting",
        "accuracy":    "⭐⭐⭐⭐ — good accuracy, handles accents and crosstalk well",
        "best_for":    "Apple Silicon (M1/M2/M3) or NVIDIA GPU",
        "warning":     "⚠️  Too slow on CPU for real-time use",
    },
    "large-v2": {
        "name":        "large-v2",
        "label":       "Large-v2 (Best Quality)",
        "ram_required": 16,
        "cpu_time":    "~45 min for a 3 min meeting — not recommended on CPU",
        "gpu_time":    "~3 min for a 3 min meeting",
        "accuracy":    "⭐⭐⭐⭐⭐ — near-human accuracy, handles any accent",
        "best_for":    "NVIDIA GPU with 8GB+ VRAM",
        "warning":     "⚠️  Only use on GPU — CPU will be extremely slow",
    },
}

# ---------------------------------------------------------------------------
# Hardware detection
# ---------------------------------------------------------------------------

def get_ram_gb() -> float:
    try:
        import psutil
        return psutil.virtual_memory().total / (1024 ** 3)
    except ImportError:
        # Fallback without psutil
        if platform.system() == "Darwin":
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True
            )
            return int(result.stdout.strip()) / (1024 ** 3)
        elif platform.system() == "Linux":
            with open("/proc/meminfo") as f:
                for line in f:
                    if "MemTotal" in line:
                        return int(line.split()[1]) / (1024 ** 2)
    return 8.0  # safe default


def get_device() -> tuple[str, str]:
    """
    Returns (device, description) e.g. ("mps", "Apple M2 (MPS)")
    """
    try:
        import torch

        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            vram = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            return "cuda", f"NVIDIA {name} ({vram:.0f}GB VRAM)"

        if torch.backends.mps.is_available():
            chip = platform.processor() or "Apple Silicon"
            # ctranslate2 (WhisperX backend) does not support MPS — use cpu
            return "cpu", f"{chip} (Apple Silicon — WhisperX runs on CPU)"

    except ImportError:
        pass

    ram = get_ram_gb()
    cpu = platform.processor() or platform.machine()
    return "cpu", f"{cpu} — {ram:.0f}GB RAM"


def auto_select_model(device: str, ram_gb: float) -> str:
    """
    Picks the best model based on hardware.
    """
    if device == "cuda":
        return "large-v2"
    if device == "mps":
        return "medium"
    # CPU path — based on RAM
    if ram_gb >= 16:
        return "small"
    return "base"


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

def banner():
    print(f"""
{CYAN}{BOLD}
  ███╗   ███╗███████╗███████╗████████╗███╗   ███╗██╗███╗   ██╗██████╗
  ████╗ ████║██╔════╝██╔════╝╚══██╔══╝████╗ ████║██║████╗  ██║██╔══██╗
  ██╔████╔██║█████╗  █████╗     ██║   ██╔████╔██║██║██╔██╗ ██║██║  ██║
  ██║╚██╔╝██║██╔══╝  ██╔══╝     ██║   ██║╚██╔╝██║██║██║╚██╗██║██║  ██║
  ██║ ╚═╝ ██║███████╗███████╗   ██║   ██║ ╚═╝ ██║██║██║ ╚████║██████╔╝
  ╚═╝     ╚═╝╚══════╝╚══════╝   ╚═╝   ╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝╚═════╝
{RESET}
  {DIM}Privacy-first AI meeting intelligence — Version 1.0{RESET}
""")


def print_hardware(device: str, device_desc: str, ram_gb: float):
    print(f"{BOLD}Your hardware:{RESET}")
    print(f"  OS      : {platform.system()} {platform.release()}")
    print(f"  Device  : {device_desc}")
    print(f"  RAM     : {ram_gb:.1f} GB")
    print()


def print_model_table(selected: str):
    print(f"{BOLD}Available models:{RESET}")
    print(f"  {'#':<3} {'Model':<22} {'CPU time (3min mtg)':<26} {'Accuracy'}")
    print(f"  {'─'*3} {'─'*22} {'─'*26} {'─'*30}")

    for i, (key, m) in enumerate(MODELS.items(), 1):
        marker = f"{GREEN}▶ {RESET}" if key == selected else "  "
        warn   = f" {YELLOW}*{RESET}" if m["warning"] else ""
        print(f"  {marker}{i:<2} {m['label']:<22} {m['cpu_time']:<26} {m['accuracy']}{warn}")

    print()
    if any(m["warning"] for m in MODELS.values()):
        print(f"  {YELLOW}* See warning for this model{RESET}")
    print()


def print_selected_model(model_key: str, device: str):
    m = MODELS[model_key]
    timing = m["gpu_time"] if device != "cpu" else m["cpu_time"]

    print(f"{GREEN}{BOLD}✓ Selected model: {m['label']}{RESET}")
    print(f"  Accuracy  : {m['accuracy']}")
    print(f"  Speed     : {timing}")
    print(f"  Best for  : {m['best_for']}")
    if m["warning"]:
        print(f"  {YELLOW}{m['warning']}{RESET}")
    print()


# ---------------------------------------------------------------------------
# Save to .env
# ---------------------------------------------------------------------------

def save_to_env(model: str, device: str):
    env_path = ".env"
    lines = []

    if os.path.exists(env_path):
        with open(env_path) as f:
            lines = f.readlines()

    def update_or_add(lines, key, value):
        key_found = False
        new_lines = []
        for line in lines:
            if line.strip().startswith(f"{key}="):
                new_lines.append(f"{key}={value}\n")
                key_found = True
            else:
                new_lines.append(line)
        if not key_found:
            new_lines.append(f"{key}={value}\n")
        return new_lines

    lines = update_or_add(lines, "WHISPER_MODEL", model)
    lines = update_or_add(lines, "WHISPER_DEVICE", device)

    with open(env_path, "w") as f:
        f.writelines(lines)

    print(f"{DIM}  Saved WHISPER_MODEL={model} and WHISPER_DEVICE={device} to .env{RESET}")


# ---------------------------------------------------------------------------
# User override prompt
# ---------------------------------------------------------------------------

def prompt_override(auto_selected: str) -> str:
    model_keys = list(MODELS.keys())
    print(f"  Press {GREEN}Enter{RESET} to use the recommended model, or type 1-4 to change:")
    print(f"  ", end="")
    for i, key in enumerate(model_keys, 1):
        marker = f"[{GREEN}{i}{RESET}]" if key == auto_selected else f"[{i}]"
        print(f"{marker} {MODELS[key]['label']}  ", end="")
    print()

    choice = input("  Your choice: ").strip()

    if choice == "" or choice not in ["1", "2", "3", "4"]:
        return auto_selected

    selected = model_keys[int(choice) - 1]
    m = MODELS[selected]

    if m["warning"]:
        print(f"\n  {YELLOW}{m['warning']}{RESET}")
        confirm = input("  Proceed anyway? (y/N): ").strip().lower()
        if confirm != "y":
            print(f"  Reverting to recommended model: {MODELS[auto_selected]['label']}")
            return auto_selected

    return selected


# ---------------------------------------------------------------------------
# Start server
# ---------------------------------------------------------------------------

def start_server():
    print(f"\n{GREEN}{BOLD}Starting MeetMind server...{RESET}")
    print(f"  Dashboard : {CYAN}http://localhost:8000/dashboard{RESET}")
    print(f"  API docs  : {CYAN}http://localhost:8000/docs{RESET}")
    print(f"\n  {DIM}Press Ctrl+C to stop{RESET}\n")

    try:
        subprocess.run([
            sys.executable, "-m", "uvicorn",
            "main:app",
            "--host", "0.0.0.0",
            "--port", "8000",
            "--reload",
        ])
    except KeyboardInterrupt:
        print(f"\n\n{DIM}MeetMind stopped.{RESET}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    load_dotenv()

    banner()

    # V2 cloud mode — skip local model selection entirely
    if os.getenv("USE_LOCAL_MODELS", "true").lower() != "true":
        print(f"{CYAN}{BOLD}  ☁  Version 2 — Cloud Mode{RESET}")
        print(f"  {DIM}Transcription : Groq Whisper API (whisper-large-v3){RESET}")
        print(f"  {DIM}Diarization   : AssemblyAI{RESET}")
        print(f"  {DIM}No local models loaded.{RESET}\n")
        start_server()
        return

    # Detect hardware
    ram_gb = get_ram_gb()
    device, device_desc = get_device()

    print_hardware(device, device_desc, ram_gb)

    # Auto-select model
    auto_model = auto_select_model(device, ram_gb)

    print_model_table(auto_model)
    print_selected_model(auto_model, device)

    # Let user override
    final_model = prompt_override(auto_model)

    if final_model != auto_model:
        print(f"\n{GREEN}✓ Updated to: {MODELS[final_model]['label']}{RESET}")
        print_selected_model(final_model, device)

    # Save to .env
    save_to_env(final_model, device)

    # Start server
    start_server()


if __name__ == "__main__":
    main()