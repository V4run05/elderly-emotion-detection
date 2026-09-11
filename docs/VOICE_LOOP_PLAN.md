# Plan: Voice-In, Emotion-Aware LLM-Out, Spoken-On-Watch Closed Loop

**Scope note:** This is the current, narrowed focus — audio in, emotion recognition, LLM response, spoken back
on the watch speaker. Heart rate and any multimodal fusion are explicitly **out of scope for now** (Phase 2,
future work) — this plan is deliberately single-modality (voice only) so the hardest new unknowns (real audio
capture and real audio playback on physical watch hardware) get proven first, before adding complexity.

---

## 1. The closed loop, in one sentence

User taps a button on the watch → watch records their voice → sends it to a laptop server → server detects
emotion from voice, generates an empathetic LLM response conditioned on that emotion, converts the response to
speech → sends the audio back → watch plays it through its own speaker.

---

## 2. End-to-end data flow

```
[Watch] user taps "check-in"
   |
   v
[Watch] record_audio() -- Tizen Recorder API, ~4-6s clip, saved to app-private storage as input.wav/m4a
   |
   v
[Watch] send_audio() -- HTTP POST multipart file upload, libcurl, to http://<laptop-ip>:8000/checkin
   |
   v  (WiFi, same local network)
[Server] FastAPI /checkin endpoint receives the audio file
   |
   +--> preprocess_audio() -- librosa: resample to 16kHz mono (the format the pretrained model expects)
   |
   +--> voice_emotion_model() -- pretrained wav2vec2 model (audEERING, trained on MSP-Podcast --
   |       real spontaneous podcast speech, not acted -- no training required, load + infer directly)
   |       -> returns {emotion_label, confidence, all_class_probs}
   |
   +--> log_to_mood_history() -- SQLite, timestamped (kept for future trend use, not required for output)
   |
   +--> build_prompt() -- inserts emotion_label (+ recent mood history if present) into an LLM prompt template
   |
   +--> call_llm() -- LLM API call -> response_text
   |
   +--> synthesize_speech() -- TTS (gTTS to start) -> response_audio.mp3
   |
   v
[Server] HTTP response: raw audio bytes, Content-Type: audio/mpeg
   |
   v  (WiFi)
[Watch] receive_audio() -- save response bytes to app-private storage as response.mp3
   |
   v
[Watch] play_audio() -- Tizen native Player API -> plays through the watch's built-in speaker
```

(See project repo history / teammate handoff doc for full API spec, timeline, risks, and deferred Phase 2 work.)
