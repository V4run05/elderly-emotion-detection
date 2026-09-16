const API_URL = 'http://127.0.0.1:8000';

const DOM = {
    statusDot: document.querySelector('.dot'),
    statusText: document.querySelector('.status-text'),
    currentEmotion: document.getElementById('current-emotion'),
    confidenceFill: document.getElementById('confidence-fill'),
    currentConfidence: document.getElementById('current-confidence'),
    modalityBreakdown: document.getElementById('modality-breakdown'),
    eventsList: document.getElementById('events-list'),
    actionBanner: document.getElementById('actionable-banner'),
    bannerTitle: document.getElementById('banner-title'),
    bannerMessage: document.getElementById('banner-message'),
    bannerActions: document.getElementById('banner-actions')
};

// 1. Fetch State (Polls the backend for history and fused state)
setInterval(fetchState, 1000);

async function fetchState() {
    try {
        const response = await fetch(`${API_URL}/state`);
        if (!response.ok) throw new Error("Network error");
        
        const data = await response.json();
        DOM.statusDot.className = 'dot connected';
        DOM.statusText.textContent = 'Live';
        updateUI(data);
    } catch (err) {
        DOM.statusDot.className = 'dot disconnected';
        DOM.statusText.textContent = 'Disconnected';
    }
}

function updateUI(data) {
    const checkins = data.recent_checkins || [];
    if (checkins.length > 0) {
        const latest = checkins[0];
        DOM.currentEmotion.textContent = latest.emotion_label;
        const confPercent = Math.round(latest.confidence * 100);
        DOM.currentConfidence.textContent = confPercent;
        DOM.confidenceFill.style.width = `${confPercent}%`;
        
        DOM.modalityBreakdown.innerHTML = '';
        const activeMods = data.active_modalities || {};
        
        if (Object.keys(activeMods).length === 0) {
            DOM.modalityBreakdown.innerHTML = '<div class="modality-item">Waiting for data...</div>';
        } else {
            for (const [modality, details] of Object.entries(activeMods)) {
                const div = document.createElement('div');
                div.className = 'modality-item';
                div.style.alignItems = 'center';
                
                let confPct = Math.round(details.confidence * 100);
                let qualPct = Math.round(details.quality * 100);
                
                div.innerHTML = `
                    <span style="font-weight: bold; width: 60px;">${modality.toUpperCase()}</span> 
                    <span style="flex-grow: 1; text-align: center; font-size: 1.1rem; color: var(--primary);">
                        <strong>${details.label}</strong> (${confPct}%)
                    </span>
                    <span style="font-size: 0.85rem; color: var(--secondary);">Qual: ${qualPct}%</span>
                `;
                DOM.modalityBreakdown.appendChild(div);
            }
        }
        
        // Render Conversation History
        const dialogueContainer = document.getElementById('dialogue-container');
        if (data.conversation && data.conversation.length > 0) {
            dialogueContainer.innerHTML = '';
            data.conversation.forEach(turn => {
                const div = document.createElement('div');
                div.style.padding = '8px';
                div.style.borderRadius = '8px';
                div.style.marginBottom = '4px';
                
                if (turn.role === 'assistant') {
                    div.style.backgroundColor = '#e8f4f8';
                    div.style.borderLeft = '4px solid #4a90e2';
                    div.innerHTML = `<strong>Companion:</strong> ${turn.content}`;
                } else {
                    div.style.backgroundColor = '#f1f1f1';
                    div.style.borderLeft = '4px solid #999';
                    div.innerHTML = `<strong>User:</strong> ${turn.content}`;
                }
                dialogueContainer.appendChild(div);
            });
            // Auto scroll to bottom
            dialogueContainer.scrollTop = dialogueContainer.scrollHeight;
        } else {
            dialogueContainer.innerHTML = '<div style="color: #666; font-style: italic;">No active conversation...</div>';
        }
    }
    
    DOM.eventsList.innerHTML = '';
    const triggers = data.recent_triggers || [];
    triggers.slice(0, 5).forEach(t => {
        const div = document.createElement('div');
        let statusClass = t.status === 'PROMPT_USER' ? 'prompt' : (t.status === 'ESCALATED' ? 'escalated' : '');
        div.className = `event-item ${statusClass}`;
        const d = new Date(t.timestamp);
        div.innerHTML = `<span class="time-label">${d.toLocaleTimeString()}</span> <strong>${t.event_type}</strong> - ${t.status}`;
        DOM.eventsList.appendChild(div);
    });
    
    const state = data.trigger_state || {};
    if (state.active) {
        DOM.actionBanner.classList.remove('hidden');
        const isEscalated = triggers.length > 0 && triggers[0].status === 'ESCALATED' && triggers[0].event_type === state.event_type;
        
        if (isEscalated) {
            DOM.actionBanner.className = 'card escalated';
            DOM.bannerTitle.textContent = 'Caregiver Contacted';
            DOM.bannerMessage.textContent = `Trigger ${state.event_type} persisted. Initiating intervention protocol.`;
            DOM.bannerActions.classList.add('hidden');
        } else {
            DOM.actionBanner.className = 'card';
            DOM.bannerTitle.textContent = 'Active Concern Detected';
            DOM.bannerMessage.textContent = `Physiological trigger detected: ${state.event_type}. Companion is checking on the user...`;
            DOM.bannerActions.classList.remove('hidden');
        }
    } else {
        DOM.actionBanner.classList.add('hidden');
    }
}

async function resolveTrigger() {
    await fetch(`${API_URL}/reset`, { method: 'POST' });
    fetchState();
}

// 2. Built-in Physio Simulator (Sends Slider data to backend)
setInterval(sendPhysioData, 5000);

async function sendPhysioData() {
    const hr = parseInt(document.getElementById('slider-hr').value);
    const spo2 = parseInt(document.getElementById('slider-spo2').value);
    const accel = parseFloat(document.getElementById('slider-accel').value);
    const gsr = hr > 100 ? 0.8 : 0.5;

    // Generate synthetic arrays of length 100 to simulate a window of sensor data
    const len = 100;
    
    // As HR goes up, physiological arousal (variance) increases
    const bvp_var = hr > 90 ? 100 : 10;
    const gsr_var = hr > 90 ? 10 : 0.5;
    const gsr_base = hr > 90 ? 15.0 : 2.0;
    
    // As movement (accel) goes up, ACC variance increases
    const acc_var = accel * 5;
    
    const payload = {
        hr: hr,
        spo2: spo2,
        accel_magnitude: accel,
        acc_x: Array.from({length: len}, () => (Math.random() - 0.5) * acc_var),
        acc_y: Array.from({length: len}, () => (Math.random() - 0.5) * acc_var),
        acc_z: Array.from({length: len}, () => (Math.random() - 0.5) * acc_var),
        bvp: Array.from({length: len}, () => (Math.random() - 0.5) * bvp_var),
        gsr: Array.from({length: len}, () => gsr_base + Math.random() * gsr_var)
    };

    const formData = new FormData();
    formData.append('physio_json', JSON.stringify(payload));
    
    try {
        await fetch(API_URL + '/checkin', { method: 'POST', body: formData });
    } catch (err) {
        console.error("Physio send failed", err);
    }
}

// 3. Camera & Mic Logic
let videoStream;
let mediaRecorder;
let audioChunks = [];
let isRecording = false;

async function startCamera() {
    try {
        videoStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
        const video = document.getElementById('webcam-video');
        video.srcObject = videoStream;
        
        document.getElementById('webcam-video').classList.remove('hidden');
        document.getElementById('captured-image').classList.add('hidden');
        document.getElementById('captured-audio').classList.add('hidden');
        
        document.getElementById('btn-start-cam').classList.add('hidden');
        document.getElementById('btn-send-av').classList.remove('hidden');
        
        startRecordingLoop();
    } catch (err) {
        console.error("Camera access error:", err);
        alert("Camera start failed: " + err.message + "\n\n(If using a local IP, ensure you use localhost or HTTPS, as browsers block camera on insecure HTTP network IPs).");
    }
}

function startRecordingLoop() {
    audioChunks = [];
    isRecording = true;
    
    // We pass the full video+audio stream. 
    // Using a strict audio-only mimeType here causes Chrome to crash on .start() 
    // because it doesn't know what to do with the video track.
    mediaRecorder = new MediaRecorder(videoStream);
    
    mediaRecorder.ondataavailable = e => {
        if (e.data.size > 0) audioChunks.push(e.data);
    };
    
    // If start() fails, we gracefully log it. The UI will still capture the photo.
    try {
        mediaRecorder.start();
    } catch (e) {
        console.error("MediaRecorder failed to start:", e);
        isRecording = false; // Mark as failed so we don't try to stop it later
        alert("Audio recording failed to start. Your face will still be analyzed, but voice will be ignored.");
    }
}

async function stopAndSendAV() {
    const btn = document.getElementById('btn-send-av');
    btn.textContent = 'Processing...';
    btn.disabled = true;

    // Capture Image from the currently playing video regardless of audio
    const video = document.getElementById('webcam-video');
    const canvas = document.getElementById('webcam-canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video, 0, 0);
    
    canvas.toBlob(async (imageBlob) => {
        // Display captured image immediately
        const imgURL = URL.createObjectURL(imageBlob);
        document.getElementById('captured-image').src = imgURL;
        document.getElementById('captured-image').classList.remove('hidden');
        document.getElementById('webcam-video').classList.add('hidden');
        
        let audioBlob = new Blob([], { type: 'audio/webm' });
        
        // Handle audio if it actually recorded
        if (mediaRecorder && mediaRecorder.state === 'recording') {
            mediaRecorder.stop();
            // We have to wait for onstop to get the chunks
            await new Promise(resolve => {
                mediaRecorder.onstop = () => {
                    audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                    audioChunks = [];
                    
                    const audioURL = URL.createObjectURL(audioBlob);
                    document.getElementById('captured-audio').src = audioURL;
                    document.getElementById('captured-audio').classList.remove('hidden');
                    resolve();
                };
            });
        }
        
        // Release the camera and microphone completely IMMEDIATELY
        if (videoStream) {
            videoStream.getTracks().forEach(track => track.track && track.stop ? track.stop() : null);
            videoStream.getTracks().forEach(track => track.stop());
        }
        video.srcObject = null;
        isRecording = false;
        
        const formData = new FormData();
        formData.append('file', audioBlob, 'clip.webm');
        formData.append('image', imageBlob, 'face.jpg');
        
        try {
            await fetch(API_URL + '/checkin', { method: 'POST', body: formData });
        } catch (err) { console.error('Upload failed', err); }
        
        btn.textContent = 'Stop & Analyze AV';
        btn.disabled = false;
        document.getElementById('btn-send-av').classList.add('hidden');
        document.getElementById('btn-start-cam').classList.remove('hidden');
    }, 'image/jpeg');
}

// Start polling immediately
fetchState();

// 4. Two-Way Chat Communication
document.getElementById('btn-send-chat').addEventListener('click', async () => {
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text) return;
    
    input.value = '';
    input.disabled = true;
    const btn = document.getElementById('btn-send-chat');
    btn.textContent = '...';
    btn.disabled = true;
    
    try {
        const formData = new FormData();
        formData.append('text', text);
        await fetch(API_URL + '/chat', { method: 'POST', body: formData });
        fetchState(); // Instantly refresh conversation
    } catch (err) {
        console.error('Chat send failed', err);
    } finally {
        input.disabled = false;
        btn.textContent = 'Send';
        btn.disabled = false;
        input.focus();
    }
});

document.getElementById('chat-input').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') document.getElementById('btn-send-chat').click();
});

