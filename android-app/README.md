# Elderly Companion — Android client

Pivoted here from the Tizen native watch app because Samsung discontinued the Samsung wearable-certificate
creation flow in Tizen Studio (no cert = no way to sideload a custom-built app onto the physical Galaxy Watch
Active2 anymore). This Android app implements the same client-side loop — record → send to server → play the
response — as a normal Android phone app, which only needs USB debugging, not a platform-specific signing
certificate. `watch-app/` is left in place for later; the server (`server/`) is unchanged and shared by both.

## Loop

Tap "Check in" → record ~5s via `MediaRecorder` (AAC/M4A) → POST multipart to the server's `/checkin` (OkHttp)
→ save the returned MP3 → play it via `MediaPlayer` → back to idle.

## Before running

Edit `SERVER_URL` in `app/src/main/java/com/example/elderlycompanion/NetworkClient.kt` to your laptop's LAN IP
(the phone and laptop must be on the same WiFi network, same as the original watch plan).

## Running it

1. Open the `android-app/` folder in Android Studio — it will prompt to install any missing SDK
   platform/build-tools and to generate the Gradle wrapper (this repo doesn't commit `gradlew`/the wrapper jar
   since they're binary/environment-specific; let Android Studio create them on first sync).
2. Enable Developer Options + USB debugging on the Android phone, connect via USB, accept the debugging
   prompt on the phone.
3. Run the `app` configuration — Android Studio builds a debug APK and installs/launches it, no certificate
   needed beyond the phone's own debug-signing key (created automatically).
4. On first "Check in" tap, accept the microphone permission prompt.

## Not done yet

- Only build-time source, not yet run on a real phone in this session (no Android SDK/JDK path configured on
  this machine before now — Android Studio should self-configure that on open).
- Same caveat as the original plan: `server/app/voice_emotion/model.py` has only been verified on a synthetic
  test clip, not real phone-mic audio yet.
