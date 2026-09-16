# Elderly Companion POC

A multimodal emotion-aware virtual companion for the elderly.

**Pivot Note:** The original `watch-app` (Tizen C++) approach was discontinued because Tizen code-signing certificates are no longer issued for older Samsung watches (e.g., Active2). We pivoted to a laptop (camera + mic) and a Wokwi ESP32 simulation for physiological sensors to create this robust Proof of Concept (POC).

## System Architecture

1. **Input Layer (Multimodal):**
   - **Voice:** Laptop microphone (processed via Hugging Face `wav2vec2` for emotion and energy for SNR/quality).
   - **Face:** Laptop camera (MediaPipe FaceMesh for detection/quality + ViT for emotion).
   - **Physiological:** Wokwi ESP32 simulation sending HR, SpO2, GSR, and Accelerometer data. Processed via a RandomForest model trained on the WESAD dataset.
2. **Fusion Layer:**
   - A dynamic, quality-weighted fusion pipeline normalizes the confidence/quality scores from all three modalities to produce a single reliable emotion state.
3. **Response & Escalation Layer:**
   - Uses an LLM to generate emotionally aware responses.
   - Monitors for physiological triggers (e.g., HR spikes, sudden falls).
   - Triggers are handled via a 2-stage escalation flow: (1) Prompt the user, (2) If no response, escalate to a caregiver/calming intervention.
4. **Dashboard:**
   - A live monitoring interface styled with the Matcha design system, displaying mood history, live sensor states, and system escalations.

## Setup Instructions

Please see [docs/SETUP.md](docs/SETUP.md) for detailed instructions on how to install dependencies, train the physiological model, run the backend, and start the dashboard & Wokwi simulation.
