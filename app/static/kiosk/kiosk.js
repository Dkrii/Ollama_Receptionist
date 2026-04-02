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
const micBtn = document.getElementById('micBtn');
const micHint = document.getElementById('micHint');
const systemStatus = document.getElementById('systemStatus');

let isSending = false;
let speechQueue = [];
let isSpeakingQueue = false;
let speechResidualBuffer = '';

// Subtitle updates
function setSubtitle(text, role = 'bot') {
  subtitlesBox.innerHTML = '';
  const span = document.createElement('span');
  span.className = `kiosk-subtitle__text kiosk-subtitle__text--${role}`;
  span.textContent = text;
  subtitlesBox.appendChild(span);
}

function setThinking() {
  subtitlesBox.innerHTML = `
    <span class="kiosk-typing-indicator" aria-label="Berpikir...">
       <span class="kiosk-dot"></span>
       <span class="kiosk-dot"></span>
       <span class="kiosk-dot"></span>
    </span>
  `;
  if (systemStatus) {
    systemStatus.textContent = "AI Sedang Berpikir...";
  }
}

// Mic & TTS State management
function updateMicState() {
  const isSpeaking = isSpeakingQueue || (window.speechSynthesis && window.speechSynthesis.speaking);
  if (micBtn) {
    micBtn.disabled = isSending || isSpeaking;
  }
}

function setSystemBusy(busy) {
  isSending = busy;
  if (!busy && systemStatus) {
    systemStatus.textContent = "";
  }
  updateMicState();
}

// Speech Synthesis
function speakText(text) {
  if (!text || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = 'id-ID';
  utter.onstart = updateMicState;
  utter.onend = updateMicState;
  utter.onerror = updateMicState;
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

// Messaging Logic
async function sendMessage(message) {
  if (isSending) return;
  if (!message.trim()) return;

  setSystemBusy(true);
  resetSpeechQueue();
  
  // Expand glass panel to show AI response
  const glassPanel = document.getElementById('glassPanel');
  if (glassPanel) glassPanel.classList.add('is-expanded');

  setThinking();
  
  let finalAnswer = '';
  let streamEventError = '';

  try {
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message })
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
        
        if (event.type === 'token') {
          const token = event.value || '';
          finalAnswer += token;
          if (finalAnswer.trim()) {
            if (systemStatus && systemStatus.textContent !== "") {
              systemStatus.textContent = "";
            }
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
  } catch (err) {
    const fallback = 'Terjadi kesalahan sistem, mohon coba lagi.';
    setSubtitle(fallback, 'error');
    resetSpeechQueue();
    speakText(fallback);
  } finally {
    setSystemBusy(false);
  }
}

// STT Logic
let micRecognition = null;

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
  if (isSending || micRecognition) return;
  micRecognition = setupSpeechRecognition();
  if (!micRecognition) {
    alert('Speech recognition belum didukung browser ini.');
    return;
  }

  micRecognition.onresult = (event) => {
    let interimTranscript = '';
    let finalTranscript = '';

    for (let i = event.resultIndex; i < event.results.length; ++i) {
      if (event.results[i].isFinal) {
        finalTranscript += event.results[i][0].transcript;
      } else {
        interimTranscript += event.results[i][0].transcript;
      }
    }
    
    // Show what user is saying in real-time
    // Di-disable sesuai request, pengguna tidak perlu melihat pertanyaannya
    /*
    const displayTxt = finalTranscript || interimTranscript;
    if (displayTxt) {
      setSubtitle(`"${displayTxt}"`, 'user');
    }
    */
    
    // Auto-send when speech engine decides it's final
    if (finalTranscript.trim() && event.results[event.results.length - 1].isFinal) {
      sendMessage(finalTranscript);
      try { micRecognition.stop(); } catch(e) {}
    }
  };

  micRecognition.onerror = () => cleanupRecording();
  micRecognition.onend = () => cleanupRecording();

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
  try { micRecognition.stop(); } catch (err) {}
  cleanupRecording();
}

function cleanupRecording() {
  micBtn.classList.remove('is-recording');
  micHint.textContent = "Tahan untuk bicara";
  micRecognition = null;
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
