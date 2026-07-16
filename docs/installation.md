# Installation & Setup Guide — ALOY Version 1.0

This document provides step-by-step instructions to configure, install, and run ALOY on your local machine.

---

## 📋 Prerequisites

ALOY runs completely on your local hardware. Before installing, ensure your system meets the following specifications:
* **Python**: Version 3.11.x (highly recommended). Python 3.12 is also supported.
* **Ollama**: Installed and running in the background. Download from [ollama.com](https://ollama.com/).
* **Memory (RAM)**: 16 GB minimum (32 GB recommended to run 14B models comfortably).
* **GPU**: Dedicated NVIDIA GPU with 8+ GB VRAM (for CUDA acceleration) or Apple Silicon Mac (M1/M2/M3 with unified memory).

---

## 💻 OS-Specific Installation

### 1. Windows Setup

1. **Open PowerShell as Administrator** and install Python 3.11 (if not already installed). We recommend using winget:
   ```powershell
   winget install Python.Python.3.11
   ```

2. **Clone the Repository**:
   ```powershell
   git clone https://github.com/dhanush-a/aloy.git
   cd aloy
   ```

3. **Configure Virtual Environment**:
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

4. **Install Requirements**:
   ```powershell
   pip install -r requirements.txt
   ```

---

### 2. macOS Setup

1. **Install Homebrew** (if not installed) and Python 3.11:
   ```bash
   brew install python@3.11
   ```

2. **Clone and Configure**:
   ```bash
   git clone https://github.com/dhanush-a/aloy.git
   cd aloy
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install Requirements**:
   ```bash
   pip install -r requirements.txt
   ```

---

### 3. Linux Setup (Ubuntu/Debian)

1. **Install System Dependencies & Python**:
   ```bash
   sudo apt update
   sudo apt install -y python3.11 python3.11-venv python3.11-dev build-essential
   ```

2. **Clone and Configure**:
   ```bash
   git clone https://github.com/dhanush-a/aloy.git
   cd aloy
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install Requirements**:
   ```bash
   pip install -r requirements.txt
   ```

---

## 📥 Model Installation

Verify that Ollama is active. Open a shell and pull the primary conversation, coding, reasoning, and text embedding models:

```bash
# Pull primary conversation model (Qwen 3 14B, ~9GB)
ollama pull qwen3:14b

# Pull code generation model (Qwen 2.5 Coder 14B, ~9GB)
ollama pull qwen2.5-coder:14b

# Pull reasoning model (DeepSeek R1 14B, ~9GB)
ollama pull deepseek-r1:14b

# Pull text embedding model (Nomic Embed Text, ~270MB)
ollama pull nomic-embed-text:latest
```

---

## 🏃 Running the Application

To start the ALOY web dashboard and API server:

```bash
uvicorn api.server:app --host 127.0.0.1 --port 8000 --reload
```

Once running, navigate to `http://localhost:8000` to interact with the ALOY Dashboard.

---

*Designed and developed by Dhanush A.*
