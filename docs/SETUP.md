# Setup & Execution Guide

This guide explains how to run the Elderly Companion POC locally.

## 1. Backend Server Setup

The backend handles the multimodal fusion, machine learning models, trigger state, and LLM conversations.

**Prerequisites:**
- Python 3.11+
- FFmpeg installed on your system path (required for audio transcoding).

**Steps:**
1. Navigate to the `server` directory:
   ```bash
   cd server
   ```
2. Create and activate a virtual environment (already configured if you ran the initial setup):
   ```bash
   python -m venv venv
   # Windows:
   .\venv\Scripts\activate
   # macOS/Linux:
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Place the `WESAD` dataset directory inside the root project folder (next to `server/`).
5. (Optional, already done during initial setup) Train the physiological model:
   ```bash
   python scripts/train_wesad.py
   ```
6. Start the FastAPI server:
   ```bash
   uvicorn app.main:app --reload
   ```
   The backend will run on `http://127.0.0.1:8000`.

## 2. Live Dashboard

The dashboard provides a calm, monitoring view of the companion's status, mood trends, and active triggers.

1. Navigate to the `dashboard` directory:
   ```bash
   cd dashboard
   ```
2. Start a simple local web server:
   ```bash
   python -m http.server 3000
   ```
3. Open `http://localhost:3000` in your web browser.

## 3. Wokwi Hardware Simulation

The Wokwi simulation mocks the wearable physiological sensors (HR, SpO2, GSR, Accelerometer) and sends data directly to the backend.

1. Ensure the backend is running.
2. In the `wokwi` folder, open `diagram.json` and `sketch.ino` in the Wokwi VS Code extension or web editor.
3. Configure the `WIFI_SSID` (usually `"Wokwi-GUEST"` in simulation) and update the `SERVER_URL` in `sketch.ino` to match your laptop's local IP address (e.g., `http://192.168.x.x:8000/checkin`).
4. Start the simulation. You can use the virtual potentiometers to adjust HR, SpO2, and GSR live to trigger the companion's proactive escalation states!
