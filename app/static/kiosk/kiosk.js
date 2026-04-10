import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

// --- THREE JS INITIALIZATION ---
let renderer, scene, camera, avatarModel, avatarMixer;
const blendshapeSettings = { jawInfluence: 0 };

function init3D() {
  const canvas = document.getElementById('avatarCanvas');
  const container = document.getElementById('avatarContainer');
  const placeholder = document.getElementById('avatarPlaceholder');
  if (!canvas) return;

  renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  
  function resize() {
    renderer.setSize(container.clientWidth, container.clientHeight);
    if(camera) {
      camera.aspect = container.clientWidth / container.clientHeight;
      camera.updateProjectionMatrix();
    }
  }
  window.addEventListener('resize', resize);

  scene = new THREE.Scene();
  
  camera = new THREE.PerspectiveCamera(40, container.clientWidth / container.clientHeight, 0.1, 100);
  camera.position.set(0, 1.39, 1.2); // Adjust height to face level

  const ambientLight = new THREE.AmbientLight(0xffffff, 1.5);
  scene.add(ambientLight);
  const dirLight = new THREE.DirectionalLight(0xffffff, 2.0);
  dirLight.position.set(2, 2, 5);
  scene.add(dirLight);

  const loader = new GLTFLoader();
  loader.load('/static/kiosk/models/avatar.glb', (gltf) => {
    avatarModel = gltf.scene;
    avatarModel.position.set(0, 0, 0); // Offset down so camera points at chest/head
    scene.add(avatarModel);

    // Buka dan putar animasi bawaan dari Blender (misal 'Viky Character')
    if (gltf.animations && gltf.animations.length > 0) {
      avatarMixer = new THREE.AnimationMixer(avatarModel);
      let clip = gltf.animations.find(c => c.name.toLowerCase().includes('viky'));
      if (!clip) clip = gltf.animations[0];

      if (clip) {
        const action = avatarMixer.clipAction(clip);
        action.play();
      }
    }
    
    if (placeholder) placeholder.style.opacity = '0';
    setTimeout(() => { if (placeholder) placeholder.style.display = 'none'; }, 500);
  }, undefined, (error) => {
    console.warn('Menunggu file avatar 3D (avatar.glb) untuk dirender...', error);
    if (placeholder) {
      const p = placeholder.querySelector('p');
      if(p) p.textContent = '⚠️ Menunggu 3D Model ⚠️';
    }
  });

  resize();

  let lastTime = performance.now();
  function animate() {
    requestAnimationFrame(animate);
    const time = performance.now();
    const dt = (time - lastTime) / 1000;
    lastTime = time;

    // Putar frame animasi (seperti gerak napas badannya)
    if (avatarMixer) {
      avatarMixer.update(dt);
    }

    // Simulate Lip Sync if speaking
    let targetJaw = 0;
    const isSpeaking = isSpeakingQueue || (window.speechSynthesis && window.speechSynthesis.speaking);
    if (isSpeaking) {
      // Procedural noise: simple sine waves combination for jaw movement
      const wave = Math.sin(time * 0.015) * Math.sin(time * 0.008);
      targetJaw = (wave + 1) * 0.35; // 0 to 0.7
    }
    
    // Smooth transition
    blendshapeSettings.jawInfluence += (targetJaw - blendshapeSettings.jawInfluence) * 15 * dt;

    if (avatarModel) {
      avatarModel.traverse((child) => {
        if (child.isMesh && child.morphTargetDictionary) {
          // Fallback to multiple common slider names
          const keys = Object.keys(child.morphTargetDictionary);
          const jawKey = keys.find(k => {
            const low = k.toLowerCase();
            return low.includes('jaw') || low.includes('mouthopen') || low.includes('aa') || low.includes('viseme');
          });
          
          if (jawKey) {
            const index = child.morphTargetDictionary[jawKey];
            child.morphTargetInfluences[index] = blendshapeSettings.jawInfluence;
          }
        }
      });
    }

    renderer.render(scene, camera);
  }
  animate();
}

document.addEventListener('DOMContentLoaded', init3D);
// --- END THREE JS ---

const subtitlesBox = document.getElementById('subtitlesBox');
const countdownBox = document.getElementById('countdownBox');
const micBtn = document.getElementById('micBtn');
const micHint = document.getElementById('micHint');
const systemStatus = document.getElementById('systemStatus');
const CONVERSATION_ID_STORAGE_KEY = 'kioskConversationId';
const CONVERSATION_ACTIVITY_STORAGE_KEY = 'kioskConversationLastActivity';
const SESSION_IDLE_MS = 5 * 60 * 1000;

let isSending = false;
let speechQueue = [];
let isSpeakingQueue = false;
let speechResidualBuffer = '';
let conversationHistory = [];
let sessionIdleTimer = null;
let activeConversationId = '';
let contactFlowState = { stage: 'idle' };
let contactBusyFollowUpTimer = null;
let contactBusyCountdownInterval = null;
let isContactCountdownActive = false;

function isStorageAvailable() {
  return typeof window.sessionStorage !== 'undefined';
}

function readStoredConversationId() {
  if (!isStorageAvailable()) return '';
  return window.sessionStorage.getItem(CONVERSATION_ID_STORAGE_KEY) || '';
}

function readStoredActivityAt() {
  if (!isStorageAvailable()) return 0;
  return Number(window.sessionStorage.getItem(CONVERSATION_ACTIVITY_STORAGE_KEY) || 0);
}

function storeActivityNow() {
  if (!isStorageAvailable()) return;
  window.sessionStorage.setItem(CONVERSATION_ACTIVITY_STORAGE_KEY, String(Date.now()));
}

function clearStoredConversationState() {
  if (!isStorageAvailable()) return;
  window.sessionStorage.removeItem(CONVERSATION_ID_STORAGE_KEY);
  window.sessionStorage.removeItem(CONVERSATION_ACTIVITY_STORAGE_KEY);
}

function setActiveConversationId(value) {
  activeConversationId = (value || '').trim();

  if (!isStorageAvailable()) return;

  if (activeConversationId) {
    window.sessionStorage.setItem(CONVERSATION_ID_STORAGE_KEY, activeConversationId);
    storeActivityNow();
    return;
  }

  clearStoredConversationState();
}

function shouldResetStoredConversation() {
  const storedConversationId = readStoredConversationId();
  const lastActivityAt = readStoredActivityAt();
  if (!storedConversationId || !lastActivityAt) return false;
  return (Date.now() - lastActivityAt) >= SESSION_IDLE_MS;
}

function buildRequestHistory() {
  return conversationHistory.slice(-6);
}

function appendConversationTurn(role, content) {
  const text = (content || '').trim();
  if (!text) return;
  conversationHistory.push({ role, content: text });
  if (conversationHistory.length > 12) {
    conversationHistory = conversationHistory.slice(-12);
  }
  storeActivityNow();
}

function clearConversationState() {
  clearTimeout(sessionIdleTimer);
  clearTimeout(contactBusyFollowUpTimer);
  clearInterval(contactBusyCountdownInterval);
  contactBusyCountdownInterval = null;
  isContactCountdownActive = false;
  conversationHistory = [];
  contactFlowState = { stage: 'idle' };
  clearStoredConversationState();
  activeConversationId = '';
  updateMicState();
}

function clearContactBusyFollowUp() {
  clearTimeout(contactBusyFollowUpTimer);
  contactBusyFollowUpTimer = null;
  clearInterval(contactBusyCountdownInterval);
  contactBusyCountdownInterval = null;
  isContactCountdownActive = false;
  if (countdownBox) {
    countdownBox.innerHTML = '';
    countdownBox.hidden = true;
  }
  updateMicState();
}

function renderContactCountdown(currentSecond, totalSeconds) {
  if (!countdownBox) return;
  countdownBox.hidden = false;
  countdownBox.innerHTML = '';

  const wrap = document.createElement('div');
  wrap.className = 'kiosk-countdown';

  const number = document.createElement('div');
  number.className = 'kiosk-countdown__number';
  number.textContent = String(currentSecond);

  const label = document.createElement('div');
  label.className = 'kiosk-countdown__label';
  label.textContent = `📞 Menghubungi... ${currentSecond}/${totalSeconds} detik`;

  wrap.appendChild(number);
  wrap.appendChild(label);
  countdownBox.appendChild(wrap);
}

function waitForCurrentSpeechToFinish(onDone) {
  if (!window.speechSynthesis) {
    onDone();
    return;
  }

  const startedAt = Date.now();
  const maxWaitMs = 20000;

  const intervalId = setInterval(() => {
    const stillSpeaking = isSpeakingQueue || window.speechSynthesis.speaking || window.speechSynthesis.pending;
    if (!stillSpeaking || (Date.now() - startedAt) >= maxWaitMs) {
      clearInterval(intervalId);
      onDone();
    }
  }, 120);
}

function scheduleContactBusyFollowUp(followUp) {
  if (!followUp || followUp.mode !== 'countdown-check') return;

  const durationSeconds = Math.max(1, Number(followUp.duration_seconds || 10));
  const delay = durationSeconds * 1000;
  const timeoutMessage = String(followUp.message || '__contact_timeout__');
  const preCountdownAnswer = String(followUp.pre_countdown_answer || '').trim();

  clearContactBusyFollowUp();
  const snapshotState = JSON.parse(JSON.stringify(contactFlowState || { stage: 'idle' }));
  isContactCountdownActive = true;
  if (micRecognition) {
    stopRecording();
  }
  updateMicState();

  const startCountdown = () => {
    let currentSecond = durationSeconds;
    renderContactCountdown(currentSecond, durationSeconds);
    setThinkingStatus(`Menghubungi karyawan... ${currentSecond}/${durationSeconds}`);
    contactBusyCountdownInterval = setInterval(() => {
      currentSecond -= 1;
      if (currentSecond >= 0) {
        renderContactCountdown(currentSecond, durationSeconds);
        setThinkingStatus(`Menghubungi karyawan... ${currentSecond}/${durationSeconds}`);
        return;
      }
      clearInterval(contactBusyCountdownInterval);
      contactBusyCountdownInterval = null;
    }, 1000);

    contactBusyFollowUpTimer = setTimeout(async () => {
      try {
        const response = await fetch('/api/chat/contact-flow', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: timeoutMessage,
            conversation_id: activeConversationId || null,
            history: buildRequestHistory(),
            flow_state: snapshotState
          })
        });

        if (!response.ok) return;
        const data = await response.json();
        setActiveConversationId(data.conversation_id || activeConversationId);

        if (data.flow_state && typeof data.flow_state === 'object') {
          contactFlowState = data.flow_state;
        } else {
          contactFlowState = { stage: 'idle' };
        }

        if (!data.handled) return;

        const answer = String(data.answer || '').trim();
        if (!answer) return;

        setSubtitle(answer, 'bot');
        appendConversationTurn('assistant', answer);
        scheduleSessionIdleReset();
        speakText(answer);
      } catch (error) {
      } finally {
        clearContactBusyFollowUp();
      }
    }, delay);
  };

  if (preCountdownAnswer) {
    setSubtitle(preCountdownAnswer, 'bot');
    appendConversationTurn('assistant', preCountdownAnswer);
    speakText(preCountdownAnswer, { onEnd: startCountdown });
    return;
  }

  waitForCurrentSpeechToFinish(startCountdown);
}

function scheduleSessionIdleReset() {
  clearTimeout(sessionIdleTimer);
  sessionIdleTimer = setTimeout(() => {
    clearConversationState();
    setThinkingStatus();
    if (subtitlesBox) {
      subtitlesBox.innerHTML = '';
    }
    const glassPanel = document.getElementById('glassPanel');
    if (glassPanel) {
      glassPanel.classList.remove('is-expanded');
    }
  }, SESSION_IDLE_MS);
}

function hydrateConversationState() {
  if (shouldResetStoredConversation()) {
    clearStoredConversationState();
    return;
  }

  activeConversationId = readStoredConversationId();
  if (activeConversationId) {
    scheduleSessionIdleReset();
  }
}

function setThinkingStatus(text = '') {
  if (!systemStatus) return;
  systemStatus.textContent = text;
  systemStatus.hidden = !text;
}

setThinkingStatus();

// Subtitle updates
function setSubtitle(text, role = 'bot') {
  setThinkingStatus();
  if (countdownBox) {
    countdownBox.innerHTML = '';
    countdownBox.hidden = true;
  }
  subtitlesBox.innerHTML = '';
  const span = document.createElement('span');
  span.className = `kiosk-subtitle__text kiosk-subtitle__text--${role}`;
  span.textContent = text;
  subtitlesBox.appendChild(span);
}

function setThinking() {
  if (countdownBox) {
    countdownBox.innerHTML = '';
    countdownBox.hidden = true;
  }
  subtitlesBox.innerHTML = `
    <span class="kiosk-typing-indicator" aria-label="Berpikir...">
       <span class="kiosk-dot"></span>
       <span class="kiosk-dot"></span>
       <span class="kiosk-dot"></span>
    </span>
  `;
  setThinkingStatus('AI Sedang Berpikir...');
}

// Mic & TTS State management
function updateMicState() {
  const isSpeaking = isSpeakingQueue || (window.speechSynthesis && window.speechSynthesis.speaking);
  if (micBtn) {
    micBtn.disabled = isSending || isSpeaking || isContactCountdownActive;
  }
  if (micHint) {
    micHint.textContent = isContactCountdownActive ? 'Mohon tunggu, sedang menghubungi...' : 'Tahan untuk bicara';
  }
}

// Speech Synthesis
function speakText(text, options = {}) {
  const onEnd = typeof options.onEnd === 'function' ? options.onEnd : null;
  if (!text || !window.speechSynthesis) {
    if (onEnd) onEnd();
    return;
  }
  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = 'id-ID';
  utter.onstart = updateMicState;
  utter.onend = () => {
    updateMicState();
    if (onEnd) onEnd();
  };
  utter.onerror = () => {
    updateMicState();
    if (onEnd) onEnd();
  };
  window.speechSynthesis.speak(utter);
  updateMicState();
}

function resetSpeechQueue() {
  speechQueue = [];
  isSpeakingQueue = false;
  speechResidualBuffer = '';
  if (window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
  updateMicState();
}

function enqueueSpeechChunk(text) {
  if (!text || !window.speechSynthesis) return;
  speechResidualBuffer += text;
  const parts = speechResidualBuffer.split(/(?<=[.!?])\s+/);
  speechResidualBuffer = parts.pop() || '';
  for (const sentence of parts) {
    const clean = sentence.trim();
    if (clean) speechQueue.push(clean);
  }
  if (!isSpeakingQueue) drainSpeechQueue();
}

function flushSpeechRemainder() {
  const tail = speechResidualBuffer.trim();
  speechResidualBuffer = '';
  if (tail) speechQueue.push(tail);
  if (!isSpeakingQueue) drainSpeechQueue();
}

function drainSpeechQueue() {
  if (!window.speechSynthesis) return;
  if (!speechQueue.length) {
    isSpeakingQueue = false;
    updateMicState();
    return;
  }
  if (isSpeakingQueue) return;

  isSpeakingQueue = true;
  updateMicState();
  const next = speechQueue.shift();
  const utter = new SpeechSynthesisUtterance(next);
  utter.lang = 'id-ID';
  utter.onend = () => {
    isSpeakingQueue = false;
    updateMicState();
    drainSpeechQueue();
  };
  utter.onerror = () => {
    isSpeakingQueue = false;
    updateMicState();
    drainSpeechQueue();
  };
  window.speechSynthesis.speak(utter);
}

async function tryHandleEmployeeContactFlow(message) {
  const response = await fetch('/api/chat/contact-flow', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      conversation_id: activeConversationId || null,
      history: buildRequestHistory(),
      flow_state: contactFlowState || { stage: 'idle' }
    })
  });

  if (!response.ok) {
    throw new Error('Gagal memproses alur hubungi karyawan');
  }

  const data = await response.json();
  setActiveConversationId(data.conversation_id || activeConversationId);

  if (data.flow_state && typeof data.flow_state === 'object') {
    contactFlowState = data.flow_state;
  } else {
    contactFlowState = { stage: 'idle' };
  }

  if (contactFlowState.stage !== 'contacting_unavailable_pending') {
    clearContactBusyFollowUp();
  }

  if (!data.handled) {
    return false;
  }

  const answer = String(data.answer || '').trim() || 'Baik, silakan ulangi permintaannya.';
  setSubtitle(answer, 'bot');
  appendConversationTurn('user', message);
  appendConversationTurn('assistant', answer);
  scheduleSessionIdleReset();
  speakText(answer);

  if (data.follow_up && typeof data.follow_up === 'object') {
    scheduleContactBusyFollowUp(data.follow_up);
  }

  return true;
}

function shouldProbeContactFlow(message) {
  const activeStages = new Set([
    'await_disambiguation',
    'await_confirmation',
    'contacting_unavailable_pending',
    'await_unavailable_choice',
    'await_waiter_name',
    'await_message_name',
    'await_message_goal'
  ]);

  const currentStage = String((contactFlowState && contactFlowState.stage) || 'idle').trim().toLowerCase();
  if (activeStages.has(currentStage)) {
    return true;
  }

  const normalized = String(message || '').toLowerCase().trim();
  if (!normalized) {
    return false;
  }

  const markers = [
    'hubungi', 'kontak', 'sambungkan', 'telepon', 'telpon', 'panggil',
    'ketemu', 'bertemu', 'temui', 'menemui', 'jumpa',
    'mau ngobrol', 'ingin ngobrol', 'mau bicara', 'ingin bicara',
    'orangnya', 'orang itu', 'timnya', 'tim itu', 'yang ngurus', 'yang urus'
  ];

  return markers.some((marker) => normalized.includes(marker));
}

// Messaging Logic
async function sendMessage(message) {
  if (isSending) return;
  if (!message.trim()) return;

  isSending = true;
  clearTimeout(sessionIdleTimer);
  storeActivityNow();
  updateMicState();
  resetSpeechQueue();
  
  // Expand glass panel to show AI response
  const glassPanel = document.getElementById('glassPanel');
  if (glassPanel) glassPanel.classList.add('is-expanded');

  setThinking();
  
  let finalAnswer = '';
  let streamEventError = '';

  try {
    if (shouldProbeContactFlow(message)) {
      const handledByContactFlow = await tryHandleEmployeeContactFlow(message);
      if (handledByContactFlow) {
        return;
      }
    }

    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message,
        conversation_id: activeConversationId || null,
        history: buildRequestHistory()
      })
    });

    if (!response.ok) throw new Error('Gagal mendapatkan jawaban');
    if (!response.body || typeof response.body.getReader !== 'function') {
      throw new Error('Stream tidak tersedia');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    
    subtitlesBox.innerHTML = '';
    const answerSpan = document.createElement('span');
    answerSpan.className = 'kiosk-subtitle__text kiosk-subtitle__text--bot';
    subtitlesBox.appendChild(answerSpan);

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;

        let event;
        try {
          event = JSON.parse(trimmed);
        } catch (parseError) { continue; }
        
        if (event.type === 'meta') {
          setActiveConversationId(event.conversation_id || activeConversationId);
          scheduleSessionIdleReset();
        } else if (event.type === 'token') {
          const token = event.value || '';
          if (token) {
            setThinkingStatus();
          }
          finalAnswer += token;
          if (finalAnswer.trim()) {
            answerSpan.textContent = finalAnswer;
            subtitlesBox.scrollTop = subtitlesBox.scrollHeight;
            enqueueSpeechChunk(token);
          }
        } else if (event.type === 'error') {
          streamEventError = event.value || 'Gagal merespon.';
        }
      }
    }

    if (!finalAnswer.trim()) {
      finalAnswer = streamEventError || 'Maaf, saya tidak mengerti.';
      setSubtitle(finalAnswer, 'bot');
      speakText(finalAnswer);
    } else {
      flushSpeechRemainder();
    }
    appendConversationTurn('user', message);
    appendConversationTurn('assistant', finalAnswer);
    scheduleSessionIdleReset();
  } catch (err) {
    const fallback = 'Terjadi kesalahan sistem, mohon coba lagi.';
    setSubtitle(fallback, 'error');
    resetSpeechQueue();
    speakText(fallback);
  } finally {
    isSending = false;
    setThinkingStatus();
    updateMicState();
  }
}

// STT Logic
let micRecognition = null;
let sttFinalTranscript = '';
let sttInterimTranscript = '';
let sttSubmitted = false;
let sttStopRequested = false;

function resetSttBuffers() {
  sttFinalTranscript = '';
  sttInterimTranscript = '';
  sttSubmitted = false;
  sttStopRequested = false;
}

function submitTranscriptIfAny() {
  if (sttSubmitted) return;
  const transcript = `${sttFinalTranscript} ${sttInterimTranscript}`.trim();
  if (!transcript) return;
  sttSubmitted = true;
  sendMessage(transcript);
}

function setupSpeechRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) return null;
  const recognition = new SpeechRecognition();
  recognition.lang = 'id-ID';
  recognition.interimResults = true; // Show interim for Kiosk
  recognition.maxAlternatives = 1;
  return recognition;
}

function startRecording() {
  if (isSending || micRecognition || isContactCountdownActive) return;
  resetSttBuffers();
  micRecognition = setupSpeechRecognition();
  if (!micRecognition) {
    alert('Speech recognition belum didukung browser ini.');
    return;
  }

  micRecognition.onresult = (event) => {
    sttInterimTranscript = '';

    for (let i = event.resultIndex; i < event.results.length; ++i) {
      if (event.results[i].isFinal) {
        sttFinalTranscript += ` ${event.results[i][0].transcript}`;
      } else {
        sttInterimTranscript += ` ${event.results[i][0].transcript}`;
      }
    }

    // Auto-send when engine already marks the latest chunk as final.
    if (event.results[event.results.length - 1].isFinal) {
      submitTranscriptIfAny();
      try { micRecognition.stop(); } catch (e) {}
    }
  };

  micRecognition.onerror = (event) => {
    const errorCode = String(event?.error || '').toLowerCase();
    if (errorCode === 'aborted' && sttStopRequested) {
      submitTranscriptIfAny();
      cleanupRecording();
      return;
    }
    cleanupRecording();
  };
  micRecognition.onend = () => {
    submitTranscriptIfAny();
    cleanupRecording();
  };

  try {
    micRecognition.start();
    micBtn.classList.add('is-recording');
    micHint.textContent = "Lepas untuk mengirim";
    
    // Collapse card saat bertanya
    const glassPanel = document.getElementById('glassPanel');
    if (glassPanel) glassPanel.classList.remove('is-expanded');
    
  } catch (err) {
    cleanupRecording();
  }
}

function stopRecording() {
  if (!micRecognition) return;
  sttStopRequested = true;
  try { micRecognition.stop(); } catch (err) {}
}

function cleanupRecording() {
  micBtn.classList.remove('is-recording');
  micRecognition = null;
  sttInterimTranscript = '';
  sttStopRequested = false;
  updateMicState();
}

// Event Listeners
micBtn.addEventListener('mousedown', startRecording);
micBtn.addEventListener('touchstart', (e) => {
  e.preventDefault();
  startRecording();
});

window.addEventListener('mouseup', () => { if (micRecognition) stopRecording(); });
micBtn.addEventListener('touchend', (e) => { e.preventDefault(); stopRecording(); });
micBtn.addEventListener('touchcancel', (e) => { e.preventDefault(); stopRecording(); });
hydrateConversationState();
