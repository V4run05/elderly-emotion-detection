# Watch Setup Guide: Galaxy Watch Active2 + Tizen Studio

**Device:** Samsung Galaxy Watch Active2 (SM-R830), Tizen OS 5.5.

## Part 1 — Install Tizen Studio

1. Download and install Tizen Studio from the official Tizen developer site.
2. In Package Manager, install the **Tizen Wearable SDK** (Main SDK) and the **Samsung Certificate Extension
   SDK** (Extension SDK) — the latter is easy to miss, it's not in the default package list.

## Part 2 — Certificates (need both)

1. **Author certificate** — Tools → Certificate Manager → Tizen (author) certificate, self-signed, no account
   needed.
2. **Samsung certificate** — needs the watch's DUID (get it after Part 3, from Settings → About watch → Status,
   or Certificate Manager will prompt for it). Requires a free Samsung developer account
   (developer.samsung.com). Without this, the app builds but won't install on the physical watch.

## Part 3 — Enable Developer Mode on the watch

1. Settings → About watch → Software → tap "Software version" 5-7 times until "Developer options enabled."
2. Enable Developer options → Debugging, Debug over Wi-Fi.
3. Connections → Wi-Fi → set to "Always on" (revert to Auto after development — drains battery).

## Part 4 — Connect over WiFi

1. Connect the watch to the same WiFi network as the laptop.
2. `sdb connect <watch-ip>:26101` (or use Tizen Studio's Remote Device Manager, which auto-scans).
3. Accept the "Always allow" debugging popup on the watch screen — if `sdb devices` shows `unauthorized`,
   disconnect/reconnect to retrigger the popup.

## Part 5 — Create the project in Tizen Studio

1. File → New → Tizen Project → Native Application → Wearable → "Basic UI Application" template.
2. Replace the generated placeholder source with the actual project source from `watch-app/`. Keep
   `.cproject`/`.project`/`project_def.prop` as generated.
3. Confirm `tizen-manifest.xml` declares the `recorder` and `internet` privileges.

## Part 6 — First deploy

Right-click project → Run As → Tizen Native Application → select the watch. Accept mic/network permission
popups on first launch.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `sdb devices` shows `unauthorized` | "Always allow" popup wasn't accepted — disconnect/reconnect. |
| Builds but won't install | Missing/mismatched Samsung certificate or DUID. |
| Connection drops mid-session | WiFi not "Always on", or watch screen slept. |
| Watch not visible in Remote Device Manager | Not on the same WiFi network, or Debug over Wi-Fi not enabled. |
| App crashes on launch | Check Tizen Studio's Log view (`dlog_print()` output) for the real error. |
