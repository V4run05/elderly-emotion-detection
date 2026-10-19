# Project Spec: "I'm Fine", detecting hidden low mood in older adults

> **What this file is:** what we are building and why: the problem, the method, the rules,
> the hardware plan and the open questions. For *how the code is organised* see
> [ARCHITECTURE.md](ARCHITECTURE.md); for *how to run it* see [SETUP.md](SETUP.md).
> Update this file whenever scope, method, thresholds or the hardware plan change.

---

## 1. Summary

A voice companion for older adults who live alone: someone to talk to about anything, any time,
who knows them and remembers what they say. Underneath, it compares **what they say** (their
words) with **how they seem** (voice tone and facial expression). Once a day it naturally asks how
they're feeling. When someone keeps saying "I'm fine" but repeatedly seems low, it quietly alerts
their family. A single bad moment doesn't trigger an alert; a pattern over several days does.

**Course context:** Cognitive Robotics project. At the last review the professor asked us to
(1) identify **one core problem** older people face that relates to emotion detection and solve
it, and (2) include **real hardware**, with a Raspberry Pi available. This spec is the answer to both.
Current phase: **laptop version for testing and demos** (Pi integration next, see §9).

## 2. The core problem

**Older adults often hide low mood, and the people around them miss it.**

- Many older people play down how they feel. They don't want to burden their family, they
  grew up when mental-health struggles carried more stigma, or they see low mood as a normal
  part of ageing. "I'm fine" is the default answer.
- Depression in later life often shows up differently: tiredness, withdrawal, physical
  complaints, flat affect. Obvious sadness is less common, so it is easy to miss.
- For someone living alone, family contact is often a short phone call. Asking "How are you?"
  gets "I'm fine", and the conversation moves on.
- Existing emotion-detection demos read **one moment**. A single reading says little about
  mood, and it ignores the most informative signal here: the gap between what is said and
  what is shown.

> TODO for the report: back these points with citations (late-life depression
> under-recognition, under-reporting/stoicism in older adults, somatic presentation). Don't
> quote statistics without a source.

## 3. Who it is for

| Role | Needs |
|---|---|
| **Older adult** (primary user), living alone | A friend to talk to: one button (or typing), no screens to learn, nothing that feels like a test or a form. |
| **Family member / caregiver** (secondary user) | To know early, and without false alarms, when the person may be struggling but not saying so. |

## 4. The solution

1. **An open conversation, whenever they like.** The person talks to a companion ("Asha") about
   anything (their day, family, memories, a recipe, old songs) for as long as they want, by voice or
   by typing. Asha keeps the thread of the conversation and knows them (§6.6).
2. **Once a day, the check-in question, asked naturally:** the first conversation of the day opens
   with "how are you feeling today?". That answer is the main "what they say" signal. Later
   conversations that day just say hello.
3. **Per spoken message, three readings:**
   - **Words:** speech-to-text, then sentiment (positive ↔ negative), plus detection of classic
     reassurance phrases ("I'm fine", "don't worry about me", "can't complain").
   - **Voice tone:** speech emotion model on the audio.
   - **Face:** facial expression model on 3 camera frames taken while they answer.
4. **Masking check:** if the words say *fine* but voice and face say *low*, the message is
   flagged **masked**. For a whole conversation: "said" comes from the answer to the daily
   question (or all messages if there was none), "seemed" from every spoken message.
5. **A good listener's reply:** the companion is told privately how the person seems. When
   masking is detected it does **not** contradict them. It makes room for them to open up: it
   normalises off days and asks one gentle, concrete question (sleep, food, who they've talked to).
6. **Trend, not moment:** messages roll up into conversations, and conversations into days. The family
   dashboard shows a 14-day "said vs seemed" chart and raises an alert only on a **pattern**.
7. **Safety net:** any mention of self-harm raises an **urgent** alert immediately.
8. **A real companion, not a generic assistant** (§6.6): a setup page (or a spoken "get to know you") captures who the person is,
   the people in their life, their routine, interests, what cheers them up, medicines and topics
   to handle gently. The companion remembers what they tell it (people, plans, events), follows up
   on it, checks on reminders when they're due, and suggests things to do when they seem low.
9. **Personal baseline** (§6.5): "seems low" is judged against the person's own normal, not a
   fixed number, because the models may read an older face or voice as flat or sad every day.

## 5. A conversation, step by step

1. The person presses **Start talking** (later: a physical button on the Pi).
2. Asha greets them. First conversation of the day: a personal greeting that ends with "how are you
   feeling today?" (e.g. "Good afternoon, Lakshmi Amma. Kamala will be over for tea this evening.
   How are you feeling today?"). Later that day: a casual hello.
3. The device listens. Recording stops about 1.8 s after they stop talking (or they press "I'm
   done"). It grabs 3 camera frames while they speak. If they say nothing for ~12 s, it pauses
   (press Talk to continue). They can also type.
4. The server analyses the message and Asha replies out loud in about 2 s (voice starts streaming
   ~0.5 s later); each word of the reply lights up on screen as it's spoken, and **Let me talk**
   interrupts her without ending the conversation. Replies are short (≤3 sentences); long answers come
   in parts ("Would you like the next steps?"). Then it listens again. By default it's just a friendly conversation: it answers what
   they ask, reacts, adds its own thoughts. Emotional support only comes in when needed (§6.6), and a
   remembered event or a due reminder is mentioned at most once a day.
5. Every 4 messages and when the conversation ends, a background step stores new memories,
   reminders confirmed, wellbeing signals (sleep, appetite, pain, social contact, loneliness) and a
   one-line summary.
6. **End conversation** → Asha says goodbye. The family dashboard updates.

## 6. Method

### 6.1 Signals and models

| Signal | Model | Output |
|---|---|---|
| Words | Groq Whisper `whisper-large-v3` (speech→text), then `cardiffnlp/twitter-roberta-base-sentiment-latest` | verbal valence = P(positive) − P(negative), in [−1, 1] |
| Reassurance | Regex list of minimising phrases, incl. Indian English ("okay only", "what to say") ([masking.py](../server/app/analysis/masking.py)) | list of phrases found |
| Voice tone | `autrainer/msp-podcast-emo-class-big4-w2v2-l-emo` (wav2vec2-large, trained on real, unscripted podcast speech) | 4-class probabilities |
| Face | OpenCV YuNet face detector + `trpakov/vit-face-expression` (ViT, 7 classes reduced to 4) | 4-class probabilities, averaged over frames |

Shared 4 classes: **Anger, Happiness, Neutral, Sadness.**

### 6.2 From emotions to one "seemed" score

- Each class has a valence: Happiness +1, Neutral 0, Sadness −1, Anger −0.5. Anger is
  negative, but low mood rather than irritation is the target, so it gets less weight.
- **Fusion** of voice and face: weight wᵢ = qualityᵢ × confidenceᵢ, normalised, then a per-class
  weighted average. Voice quality = loudness (RMS) of the clip. Face quality = share of frames
  with a face × detector score. A missing channel drops out.
- **Non-verbal valence** = valence of the fused distribution, in [−1, 1]. The voice and face valences
  are also kept separately for the personal baseline (§6.5).
- **Readings:** a spoken message counts as a reading only with at least `MIN_READING_SECONDS` (0.4 s) of
  actual speech, which drops near-empty readings ("hmm"). Measured on whole clips: sad vs neutral AUC stays 0.75–0.79 from 0.6 s of speech up; a higher cut-off would mostly drop sad answers, because quiet speech measures shorter.
- **"I'm fine, but…":** if a reassurance is followed by "but / though / except / just" and the part after it has an
  emotion word ("miss", "lonely") or reads clearly negative (≤ −0.4), that part counts and it isn't a reassurance (they are opening up). Mild minimising ("just a bit tired") stays a reassurance.

### 6.3 The masking rule (same rule for an answer, a session and a day)

| Term | Definition | Default |
|---|---|---|
| says OK | verbal valence ≥ `SAYS_OK_THRESHOLD` **or** a reassurance phrase was used | 0.10 |
| seems low | below the person's own normal by the personal drop (§6.5); before calibration, fused valence ≤ `LOW_NONVERBAL_THRESHOLD` | −0.55 until calibrated (measured, EVALUATION.md §3) |
| openly not OK | verbal valence ≤ `NEGATIVE_VERBAL_THRESHOLD` | −0.20 |
| gap | verbal − non-verbal ≥ `MASKING_GAP_THRESHOLD` | 0.50 |

- **masked** = says OK **and** seems low **and** the gap is large enough
- **low** = seems low, or openly not OK
- **ok** = everything else

Masking score (0–1) for display = gap ÷ 2, counted only when the person presents as OK.

A **session** uses the averages of its readings; a **day** uses the averages of its sessions, weighted
by their number of readings. Both are classified with the same rule. Typed-only days have no reading
but still count for the safety flag.

### 6.4 Family alert levels

Computed over the last `ALERT_WINDOW_DAYS` (7) calendar days:

| Level | When |
|---|---|
| **urgent** | any conversation in the window tripped the self-harm screen |
| **alert** | ≥ 3 concerning (low or masked) days **with** ≥ 2 masked, **or** ≥ 4 low days |
| **watch** | no conversation for ≥ 2 days, **or** ≥ 2 concerning days |
| **ok** | none of the above |
| **none** | no conversations yet |

All numbers live in [server/app/config.py](../server/app/config.py) and can be overridden via `.env`.
The low line, the baseline settings and the reading length were set from the evaluation on real
data (EVALUATION.md); the alert counts are still heuristics (see §12).

### 6.5 Personal baseline

The voice and face models were trained mostly on younger, expressive people. For an older person
they may read every day as flat (≈0) or even sad (<0). A fixed low line then never fires for a
"flat" person, or fires every day for a "reads sad" person.

- **Per channel:** voice and face each get their own baseline from the first `BASELINE_SESSIONS` (7)
  conversations with a reading on that channel. The two sit at very different levels (voice ≈ −0.3, face
  ≈ +0.3), so one fused baseline moved whenever the camera was off or the face wasn't found.
- **normal** = median valence; **spread** = 1.4826 × median absolute deviation; **drop** =
  max(`BASELINE_MIN_DROP` 0.12, `BASELINE_SPREAD_K` 2 × spread).
- **Seems low** = the reading is at least *drop* below normal. `BASELINE_COMBINE=voice`: the voice decides,
  the face only when there is no voice reading. The masking rule then runs on "compared with normal"
  (normal = 0).
- Before calibration the fixed −0.55 is used on the fused value. The dashboard says which is in use.
- **Why voice decides** (`evaluation/channel_sim.py`: real CREMA-D voices + real faces of people 60+,
  14 days, 3 answers a day, the face kept normal during the low week, i.e. masking):

| Camera | Old fused baseline | Average of channels | Either channel | **Voice decides** |
|---|---|---|---|---|
| always on | 27% caught / 8% false | 16% / 4% | 78% / 22% | **72% / 7%** |
| on some days | 72% / **36%** | 50% / 5% | 72% / 17% | **70% / 9%** |
| on only after calibration | **2%** / 0% | 71% / 8% | 71% / 8% | **71% / 8%** |

  Averaging dilutes the drop in the voice when the face stays normal; "either channel" doubles false
  alerts (the simulated faces vary more than one real person's would, so this may overstate it).
  k = 1.5 would catch 86% but with 14% false alerts; we chose fewer false alerts.

**Evaluation** (`server/scripts/evaluate_baseline.py`, synthetic): 300 people per profile; everyone
keeps *saying* they're fine; half stay well, half drop by 0.25 after week 1 (results for drops of
0.15 and 0.35 in CHANGELOG):

| Reads as | Method | False flags (well days) | Detected (episode days) | False alerts (well people) | Alerted (episode people) |
|---|---|---|---|---|---|
| expressive (+0.30) | fixed | 0% | 2% | 0% | 0% |
| | **baseline** | 1% | 30% | 0% | **63%** |
| flat (0.00) | fixed | 0% | 80% | 0% | 100% |
| | **baseline** | 3% | 94% | 3% | 99% |
| reads sad (−0.30) | fixed | **89%** | 100% | **100%** | 100% |
| | **baseline** | 6% | 83% | 10% | 96% |

The fixed line is useless for a person the models read as sad (it alerts on everyone) and blind
to drops in an expressive person. The baseline fixes both at a small cost (≤ 10% false alerts).
This is a check of the decision logic on synthetic data, not evidence about real people.

### 6.6 The companion: profile, memory, reminders, suggestions

- **Two ways to set up:** the setup form, or a spoken "get to know you" conversation where Asha
  asks up to 10 questions (their name, what to call the companion, story, living situation,
  important people, usual day, interests, what cheers them up, medicines/tasks, topics to avoid) and fills the profile from the answers,
  saving after each one. Already-known topics are skipped; "skip" works; it isn't counted in the mood trend.
- **Profile (setup page):** name and how to address them, pronouns, age, city, languages, life
  story, living situation; people in their life (name, relation, notes, birthday); routine;
  interests; what cheers them up; activities to suggest; health notes; topics to handle gently;
  medicines/routines as reminders; companion name, voice and personality (warm / cheerful / calm);
  family contact.
- **Every reply** is generated with the profile, what the companion remembers, the date/time, the
  recent conversation (last 20 exchanges), the emotional guidance (masked / low / ok) and optional
  hints (§5 step 4). Rules: follow their lead, English only, 2–3 spoken sentences, at most one
  question, use names, never invent facts (including song or film titles), never sound like an
  assistant, never name emotions, never diagnose, never give medical advice.
- **When support comes in** (`plan.support`): only for (a) distress in their words (negative sentiment
  and an emotion word such as lonely, miss, sad, worried), (b) the last four spoken messages all reading
  low, or (c) a low/masked answer to the daily question. Asha listens first; a concrete suggestion only
  if support is still needed on the next message, at most once every 5 messages. Single-message voice
  readings alone never trigger it (they are too noisy).
- **Reply model:** `gpt-oss-120b` and `gpt-oss-20b` are asked at the same time; 120b's reply is used
  if it arrives within 3 s, otherwise 20b's. 120b was clearly better in testing (more natural,
  culturally fitting, fewer made-up facts) but sometimes took 7–10 s; 20b is ~1 s every time.
- **Greeting:** the server picks something real and timely to mention (an event today, yesterday or
  tomorrow, or a birthday within 2 days) or nothing at all. The LLM is never left to "find a hook",
  because when it was, it invented one.
- **Memory step** (every 4 messages and at the end of a conversation, background, `gpt-oss-120b`, strict JSON): new memories
  (people, events with resolved dates, preferences, health), reminders confirmed done, wellbeing
  signals, a one-line summary. Only what the person said; duplicates and profile facts skipped.
  Family can see and remove every memory on the dashboard.
- **Reminders:** daily, chosen weekdays, or once. Status per day: done / due / soon / later. Confirmed
  in conversation (memory step) or ticked on the dashboard. Times are spoken as "5:30 pm".
- **Wellbeing signals:** sleep, appetite, pain, social contact and loneliness, counted per day on the
  dashboard. These are classic warning signs of late-life depression, so they back up the mood trend.

## 7. Feature status (laptop version)

| Feature | Status |
|---|---|
| Browser talk page (laptop webcam + mic), auto-stop on silence, 3 frames per spoken message | done |
| Voice, face and text models, loaded once at startup, ~3 s per answer | done |
| Masking detection + reassurance phrases | done |
| Emotion-aware companion replies (masked / low / ok guidance, closing turn) | done |
| Spoken replies (natural neural voice via edge-tts; gTTS and browser speech as fallbacks; Groq Orpheus optional) | done |
| Conversation + daily aggregation, family alert levels, no-conversation detection | done |
| Self-harm keyword screen → urgent alert | done |
| Family dashboard (alert, 14-day chart, table view, conversation history) | done |
| Demo history seeding (clearly labelled synthetic data) | done |
| HTTPS mode so a phone browser can be the device | done (not yet tried on a real phone) |
| Raspberry Pi hardware (button, LED, sensors) | **next phase**, see §9 |
| Real notifications to family (SMS/Telegram) | not started; dashboard only |
| Personal baseline (compare to the person's own normal) | done (§6.5), on by default |
| Setup page: profile, people, routine, interests, reminders, companion voice + personality | done |
| Personalised replies and greeting (profile + memory + per-turn plan) | done |
| Memory from conversations (people, events, preferences, health) + recall | done |
| Reminders: brought up in conversation, confirmed automatically, managed on the dashboard | done |
| Activity suggestions and cheer-up ideas | done |
| Wellbeing signals (sleep, appetite, pain, social contact, loneliness) on the dashboard | done |
| "Get to know you" spoken setup | done |
| Open-ended conversation (voice or typing), check-in question once a day, auto-pause, goodbye | done |
| Full-width, larger layout for older readers; streamed voice (~0.5 s to first audio) | done |
| More feature ideas | see §13 |

## 8. Out of scope (for now)

- Clinical diagnosis or screening claims. This is an early-warning aid, not a medical device.
- Languages other than English (Whisper is forced to English).
- Multiple users per device or user accounts / login.
- Heart rate and other physiological signals. Possible later via a Pi sensor (§9).

## 9. Hardware plan (Raspberry Pi)

### Can we use our phone's camera, mic and speaker with a Raspberry Pi?

**Yes.** The cleanest way needs no extra code beyond what exists: the phone opens the
talk page in its browser over HTTPS (`python run_server.py --https`), so the phone *is*
the camera, mic and speaker. Other options:

| Option | How | Verdict |
|---|---|---|
| **A. Phone browser as the terminal** | Phone opens `https://<server-ip>:8443`; the existing page works as-is | **Recommended.** Works today, best camera/mic quality, no app to build |
| B. Phone as an IP camera streaming to the Pi | Apps like IP Webcam / DroidCam stream video+audio; the Pi pulls the stream | Fragile: app-dependent, laggy, and these apps don't play audio back, so the Pi still needs a speaker |
| C. USB webcam + USB mic + speaker on the Pi | Pi becomes a standalone device | Most robust and self-contained; needs a small Python client (`clients/pi/`) |

**Important:** if the phone does all the sensing and the Pi only relays network traffic, the Pi
adds nothing, and it will look that way at the review. The Pi needs **its own physical job**:

- **Big physical "Talk to Asha" button** (GPIO) to start a conversation, the most elder-friendly input there is.
- **LED ring / status light**: listening, thinking, speaking, and "please check in today".
- **PIR motion sensor**: notice the person is up and about, then prompt a morning chat;
  "no movement all day" strengthens the no-conversation alert.
- *(Optional)* **MAX30102 pulse sensor** (I2C): heart rate as a fourth signal.

**Where the models run:** on the laptop for now. wav2vec2-large is too heavy for a Pi 4 at
conversational speed; a Pi 5 (8 GB) might manage it, but that has to be measured before we rely
on it. Because the server is device-agnostic, moving it onto a Pi later is a deployment change,
not a code change. The integration design is in [ARCHITECTURE.md §9](ARCHITECTURE.md#9-devices-and-the-raspberry-pi-integration-path).

**Pi model:** not yet confirmed by the team. Check before ordering sensors.

## 10. Ethics and privacy

- **Consent:** the older person must know the device listens and looks while they answer,
  and that family sees a summary. It is not covert monitoring.
- **No raw media stored by default:** only transcripts and derived scores are saved
  (`KEEP_MEDIA=false`). The camera and mic are on only during a conversation.
- **Not a diagnosis:** the dashboard says "seemed low", never "is depressed". The companion never names
  emotions back to the person or contradicts them.
- **Safety:** self-harm mentions trigger an urgent alert and a supportive reply that points to
  family and helplines. The screen is keyword-based and **will miss indirect phrasing**.
- **What the companion remembers:** memories, summaries and wellbeing signals are visible to family
  on the dashboard, and any memory can be removed there. The person should know the companion
  remembers what they say and that family can see it.
- **Profile data** (health notes, sensitive topics) is used only to make the companion considerate;
  it never gives medical advice and never raises sensitive topics itself.
- **Cloud services:** audio is sent to Groq for transcription and text to Groq's LLM. Say this in
  any consent material; a fully local version would need local Whisper/LLM.

## 11. Evaluation and demo plan

**Live demo (about 5 min):**
1. Seed the masked scenario (`python scripts/seed_demo.py`) and show the dashboard: a good week,
   then a week of "I'm fine" while "seemed" drops. The alert is raised.
2. Have a live conversation; answer the daily question cheerfully and sincerely: shows **ok**.
3. On a fresh day (or after clearing data), say "I'm fine, nothing to worry about" in a flat, tired voice with a
   neutral or sad face: shows **masked**, and Asha gently probes instead of moving on.
4. Back on the dashboard, today's point appears.

**Done (2026-10-19):** see [EVALUATION.md](EVALUATION.md). Voice model on CREMA-D (4,900 clips, ages 20–74),
face age bias on UTKFace, words + self-harm screen, 8 simulated conversations, latency. Main results:
the fixed low line gives 88% false family alerts on real voices; the personal baseline gives 12% false and
62% of low weeks caught (87% at 6 spoken answers a day); older non-smiling faces read as sad ~2× as often;
the keyword self-harm screen catches 1 of 12 indirect statements (an LLM screen: 11 of 12).

**Evaluation still to do before the final review:**
- Scripted test set: teammates record N answers in each condition (sincere-positive,
  masked, openly-low) and we report masking-detection precision/recall per condition.
- Threshold sweep on that set (`SAYS_OK`, `LOW_NONVERBAL`, `GAP`) to pick defensible values.
- Latency per answer (already logged per stage in the server log).

## 12. Known limitations and open questions

1. **Thresholds are only partly calibrated.** Tested on acted speech (CREMA-D, EVALUATION.md §3), not on
   older adults. Needs the teammate set and a real pilot (§11).
2. **Models weren't trained on older adults.** Older faces and voices may read as sadder or flatter
   than they are (the "age bias" question from the original proposal). **Partly addressed** by the
   personal baseline (§6.5). Measured (EVALUATION.md §3–4): the voice model shows no clear age trend up to 74
   but reads all speech as negative (neutral ≈ −0.34); the face model reads non-smiling faces over 50 as sad ~2×
   as often as faces in their 20s–30s. Remaining risk: if the person is
   already low during the 5 calibration conversations, that becomes their "normal" (reset = clear history).
3. **The voice model reads speech as negative.** On real acted speech (CREMA-D) neutral voices average
   −0.34 and a third are labelled sad; happy speech is recognised only 11% of the time. Sad vs neutral is still
   separable (AUC 0.75), so only "lower than this person's normal" is meaningful (EVALUATION.md §3).
4. **English only**, and an Indian-English voice by default (`TTS_EDGE_VOICE=en-IN-NeerjaNeural`).
5. **Cloud dependency:** Groq (speech-to-text + LLM) and the voice service (edge-tts, an unofficial
   use of Microsoft Edge's read-aloud service) need internet; Groq needs a key. If edge-tts stops
   working, gTTS and then the browser voice take over automatically.
6. **Anger valence (−0.5)** is a design choice; revisit if anger shows up a lot in real data.
7. **Self-harm screen is keyword-based.** Measured: 75% of direct and 8% of indirect statements caught
   (EVALUATION.md §5). An LLM screen (gpt-oss-safeguard-20b) caught 100% / 92% with no false alarms: planned fix.
8. **Memory can be wrong.** The memory step is an LLM and can mis-summarise; family can remove
   wrong memories on the dashboard. Replies can still occasionally get details wrong.
9. **English only** for speech recognition, replies and voice, even if the profile lists other languages.
10. **Free Groq budget runs out** after ~80 replies/day; the companion then answers "I didn't quite catch that"
    to everything (EVALUATION.md §6–7). Needs a fallback model and an honest message.

## 13. Feature ideas (backlog)

Ranked by value for the core problem vs effort. Not built yet.

1. **Messages from family, relayed by the companion:** "Priya says she'll call you tonight." A text
   box on the dashboard; the companion mentions it in the next conversation. Low effort, high warmth.
2. **Alerts that reach family:** SMS / WhatsApp / Telegram to the family contact on *alert* or
   *urgent*, plus a weekly digest (mood trend, reminders kept, highlights).
3. ~~"Get to know you" first conversation~~: **done** (§6.6).
4. **Proactive chats (with the Raspberry Pi):** a chime and light at their usual time; a motion
   sensor notices they're up; a physical button starts the chat.
5. **Wellbeing trends:** sleep / appetite / pain over weeks next to the mood chart.
6. **Medication adherence view:** a week grid of reminders kept, for family.
7. **Good moments log:** things that made them happy this week, shared with family.
8. **Reminiscence prompts:** family uploads old photos; the companion asks about them (fits the
   memory feature).
9. **Light cognitive activities:** word games, trivia about their era, a gentle memory quiz.
10. **Weather and local hooks:** "It's cold today, keep your knee warm."
11. **Multilingual:** Tamil / Hindi speech recognition, replies and voices (needs a multilingual
    sentiment model for the masking check).
12. **Caregiver notes:** family adds context ("her sister is unwell") the companion should know.
