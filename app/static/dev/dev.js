const kioskRoot = document.getElementById('kioskRoot');
const chatBox = document.getElementById('chatBox');
const input = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const micBtn = document.getElementById('micBtn');
const micWrapper = document.getElementById('micWrapper');
const avatarEl = document.getElementById('kioskAvatar');
const debugStatsEl = document.getElementById('debugStats');
const debugRuntimeEl = document.getElementById('debugRuntime');
const faceIndicator = document.getElementById('faceIndicator');
const faceIndicatorText = document.getElementById('faceIndicatorText');
const faceCamera = document.getElementById('faceCamera');
const CONVERSATION_ID_STORAGE_KEY = 'kioskConversationId';
const CONVERSATION_ACTIVITY_STORAGE_KEY = 'kioskConversationLastActivity';
const SESSION_IDLE_MS = 5 * 60 * 1000;
const FACE_PROFILES_STORAGE_KEY = 'kioskFaceProfiles';
const FACE_DETECTION_INTERVAL_MS = 180;
const FACE_LOST_GRACE_MS = 1400;
const GREETING_COOLDOWN_MS = 12000;
const FACE_MATCH_THRESHOLD = 0.12;
const VAD_BASE_THRESHOLD = 0.02;
const VAD_DYNAMIC_MULTIPLIER = 2.2;
const VAD_MAX_THRESHOLD = 0.045;
const VAD_CALIBRATION_MS = 2200;
const VAD_SPEECH_START_MS = 240;
const VAD_SILENCE_END_MS = 900;
const STT_MIN_FINAL_CHARS = 3;
const VISION_CDN_VERSION = '0.10.14';
const FACE_MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite';

const AVATAR_STATES = ['IDLE', 'LISTENING', 'THINGKING', 'TALKING'];
const avatarCache = new Map();

let currentAvatarState = 'IDLE';
let isSending = false;
let isAssistantResponding = false;
let speechQueue = [];
let isSpeakingQueue = false;
let speechResidualBuffer = '';
let conversationHistory = [];
let hasConversationStarted = false;
let conversationResetTimer = null;
let sessionIdleTimer = null;
let activeConversationId = '';
let faceDetector = null;
let faceDetectionRafId = 0;
let lastFaceDetectionRunAt = 0;
let isFacePresent = false;
let lastFaceSeenAt = 0;
let lastGreetingAt = 0;
let currentVisitorKey = '';
let greetedInCurrentPresence = false;
let latestFaceSignature = null;
let knownFaceProfiles = [];
let faceCameraStream = null;
let autoRecognition = null;
let autoRecognitionActive = false;
let recognitionFinalTranscript = '';
let recognitionShouldSend = false;
let recognitionSendTimer = null;
let vadAudioContext = null;
let vadAnalyser = null;
let vadDataArray = null;
let vadMonitorRafId = 0;
let vadStream = null;
let vadVoiceAboveSince = 0;
let vadLastVoiceAt = 0;
let vadSpeechActive = false;
let vadNoiseFloor = 0.006;
let vadCalibrating = true;
let vadCalibrationStartedAt = 0;
let vadCalibrationSamples = 0;
let vadCalibrationSum = 0;
let vadLastResumeAttemptAt = 0;
let lastTranscriptPreview = '-';
let lastAutoSentMessage = '-';
let lastSttError = '-';
let lastVadRms = 0;
let lastDebugRenderAt = 0;
let contactFlowState = { stage: 'idle' };
let contactBusyFollowUpTimer = null;
let contactBusyCountdownInterval = null;
let isContactCountdownActive = false;
const DEBUG_REFRESH_MS = 180;

function setFaceIndicatorState(statusClass, label) {
  if (!faceIndicator || !faceIndicatorText) return;

  faceIndicator.classList.remove('is-searching', 'is-recognized', 'is-unknown', 'is-error');
  faceIndicator.classList.add(statusClass);
  faceIndicatorText.textContent = label;
}

function distance2D(left, right) {
  if (!left || !right) return 0;
  const dx = Number(left.x || 0) - Number(right.x || 0);
  const dy = Number(left.y || 0) - Number(right.y || 0);
  return Math.sqrt((dx * dx) + (dy * dy));
}

function buildFaceSignature(detection) {
  const keypoints = detection?.keypoints || [];
  if (keypoints.length < 6) return null;

  const rightEye = keypoints[0];
  const leftEye = keypoints[1];
  const nose = keypoints[2];
  const mouth = keypoints[3];
  const rightEar = keypoints[4];
  const leftEar = keypoints[5];

  const eyeDistance = distance2D(leftEye, rightEye);
  if (!eyeDistance) return null;

  const centerEye = {
    x: (Number(leftEye.x || 0) + Number(rightEye.x || 0)) / 2,
    y: (Number(leftEye.y || 0) + Number(rightEye.y || 0)) / 2
  };

  return [
    distance2D(leftEye, nose) / eyeDistance,
    distance2D(rightEye, nose) / eyeDistance,
    distance2D(centerEye, mouth) / eyeDistance,
    distance2D(leftEar, rightEar) / eyeDistance,
    distance2D(nose, mouth) / eyeDistance,
    Math.abs(Number(leftEye.y || 0) - Number(rightEye.y || 0)) / eyeDistance
  ].map((value) => Number(value.toFixed(6)));
}

function signatureDistance(left, right) {
  if (!Array.isArray(left) || !Array.isArray(right) || left.length !== right.length) {
    return Number.POSITIVE_INFINITY;
  }

  let total = 0;
  for (let index = 0; index < left.length; index += 1) {
    const diff = Number(left[index]) - Number(right[index]);
    total += (diff * diff);
  }
  return Math.sqrt(total / left.length);
}

function parseProfiles(rawProfiles) {
  if (!Array.isArray(rawProfiles)) return [];

  return rawProfiles
    .map((profile) => {
      const name = String(profile?.name || '').trim();
      const signature = Array.isArray(profile?.signature)
        ? profile.signature.map((value) => Number(value))
        : [];

      if (!name || signature.length !== 6 || signature.some((value) => Number.isNaN(value))) {
        return null;
      }

      return { name, signature };
    })
    .filter(Boolean);
}

function saveProfilesToStorage(profiles) {
  try {
    window.localStorage.setItem(FACE_PROFILES_STORAGE_KEY, JSON.stringify(profiles));
  } catch (error) {
  }
}

function loadProfilesFromStorage() {
  try {
    const value = window.localStorage.getItem(FACE_PROFILES_STORAGE_KEY);
    if (!value) return [];
    return parseProfiles(JSON.parse(value));
  } catch (error) {
    return [];
  }
}

async function loadKnownFaceProfiles() {
  const localProfiles = loadProfilesFromStorage();

  try {
    const response = await fetch('/static/dev/face-profiles.json', { cache: 'no-store' });
    if (!response.ok) {
      knownFaceProfiles = localProfiles;
      return;
    }

    const payload = await response.json();
    const fileProfiles = parseProfiles(payload?.profiles);
    const mergedByName = new Map();

    [...fileProfiles, ...localProfiles].forEach((profile) => {
      mergedByName.set(profile.name.toLowerCase(), profile);
    });

    knownFaceProfiles = [...mergedByName.values()];
  } catch (error) {
    knownFaceProfiles = localProfiles;
  }
}

function recognizeFaceFromSignature(signature) {
  if (!signature || !knownFaceProfiles.length) {
    return { recognized: false, name: '', distance: Number.POSITIVE_INFINITY };
  }

  let bestMatch = null;
  for (const profile of knownFaceProfiles) {
    const distance = signatureDistance(signature, profile.signature);
    if (!bestMatch || distance < bestMatch.distance) {
      bestMatch = { profile, distance };
    }
  }

  if (!bestMatch || bestMatch.distance > FACE_MATCH_THRESHOLD) {
    return { recognized: false, name: '', distance: bestMatch ? bestMatch.distance : Number.POSITIVE_INFINITY };
  }

  return {
    recognized: true,
    name: bestMatch.profile.name,
    distance: bestMatch.distance
  };
}

function buildGreetingMessage(identity) {
  if (identity.recognized) {
    return `Selamat datang kembali, ${identity.name}. Senang bertemu lagi, ada yang bisa saya bantu hari ini?`;
  }
  return 'Selamat datang di AKEBONO. Senang bertemu Anda, silakan sampaikan kebutuhan Anda.';
}

function emitSystemGreeting(message) {
  isAssistantResponding = true;
  recognitionFinalTranscript = '';
  lastTranscriptPreview = '-';
  clearTimeout(recognitionSendTimer);
  activateConversationLayout();
  clearChat();
  const bubble = addBotBubble();
  bubble.textContent = message;
  scrollChatToBottom();
  speakText(message);
  if (!window.speechSynthesis) {
    scheduleConversationReset(40);
  }
}

function maybeGreetVisitor(identity) {
  if (isSending || isAssistantResponding || isSpeechActive()) return;

  const now = Date.now();
  const visitorKey = identity.recognized
    ? `known:${identity.name.toLowerCase()}`
    : 'unknown';

  if (visitorKey !== currentVisitorKey) {
    greetedInCurrentPresence = false;
  }

  if (greetedInCurrentPresence) return;
  if (now - lastGreetingAt < GREETING_COOLDOWN_MS) return;

  greetedInCurrentPresence = true;
  currentVisitorKey = visitorKey;
  lastGreetingAt = now;

  emitSystemGreeting(buildGreetingMessage(identity));
}

function renderRuntimeDebug(force = false) {
  if (!debugRuntimeEl) return;

  const now = performance.now();
  if (!force && (now - lastDebugRenderAt) < DEBUG_REFRESH_MS) return;
  lastDebugRenderAt = now;

  const speechRecognitionAvailable = Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
  const rows = [
    ['FACE', isFacePresent ? 'detected' : 'none'],
    ['ANIM', currentAvatarState],
    ['RESPONDING', isAssistantResponding ? 'yes' : 'no'],
    ['STT_SUPPORT', speechRecognitionAvailable ? 'yes' : 'no'],
    ['STT_ACTIVE', autoRecognitionActive ? 'yes' : 'no'],
    ['VAD_SPEECH', vadSpeechActive ? 'yes' : 'no'],
    ['VAD_RMS', lastVadRms.toFixed(4)],
    ['VAD_TH', getVadThreshold().toFixed(4)],
    ['VAD_NOISE', vadNoiseFloor.toFixed(4)],
    ['TRANSCRIPT', lastTranscriptPreview || '-'],
    ['LAST_SENT', lastAutoSentMessage || '-'],
    ['STT_ERROR', lastSttError || '-']
  ];

  debugRuntimeEl.innerHTML = rows
    .map(([key, value]) => `<div class="kiosk-debug__row"><span class="kiosk-debug__key">${key}</span><span class="kiosk-debug__value">${String(value)}</span></div>`)
    .join('');
}

function handleFaceMissing() {
  if (!isFacePresent) {
    setFaceIndicatorState('is-searching', 'Mencari wajah...');
    return;
  }

  if ((Date.now() - lastFaceSeenAt) < FACE_LOST_GRACE_MS) {
    return;
  }

  isFacePresent = false;
  currentVisitorKey = '';
  greetedInCurrentPresence = false;
  setFaceIndicatorState('is-searching', 'Mencari wajah...');
  updateAvatarState();
  if (vadSpeechActive) {
    vadSpeechActive = false;
    stopAutoRecognition(false);
  }
  stopAutoRecognition(false);
  renderRuntimeDebug(true);
}

function handleFaceDetected(detection) {
  isFacePresent = true;
  lastFaceSeenAt = Date.now();
  updateAvatarState();

  latestFaceSignature = buildFaceSignature(detection);
  const identity = recognizeFaceFromSignature(latestFaceSignature);

  if (identity.recognized) {
    setFaceIndicatorState('is-recognized', `Dikenali: ${identity.name}`);
  } else {
    setFaceIndicatorState('is-unknown', 'Wajah terdeteksi');
  }

  maybeGreetVisitor(identity);
  syncAutoRecognitionState();
  renderRuntimeDebug();
}

function scheduleRecognitionSend() {
  clearTimeout(recognitionSendTimer);
  recognitionSendTimer = setTimeout(async () => {
    const transcript = recognitionFinalTranscript.trim();

    if (!transcript || transcript.length < STT_MIN_FINAL_CHARS) return;
    if (!isFacePresent || isSending || isAssistantResponding || isSpeechActive()) return;

    recognitionFinalTranscript = '';
    lastTranscriptPreview = transcript;
    lastAutoSentMessage = transcript;
    await sendMessage(transcript);
    renderRuntimeDebug(true);
  }, 700);
}

function syncAutoRecognitionState() {
  if (!isFacePresent || isSending || isAssistantResponding || isSpeechActive() || isContactCountdownActive) {
    stopAutoRecognition(false);
    return;
  }
  startAutoRecognition();
}

function setupAutoSpeechRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    setFaceIndicatorState('is-error', 'Browser tidak mendukung STT');
    return null;
  }

  const recognition = new SpeechRecognition();
  recognition.lang = 'id-ID';
  recognition.interimResults = true;
  recognition.continuous = true;
  recognition.maxAlternatives = 1;
  return recognition;
}

function startAutoRecognition() {
  if (autoRecognitionActive || isSending || isAssistantResponding || isSpeechActive() || isContactCountdownActive) return;

  if (!autoRecognition) {
    autoRecognition = setupAutoSpeechRecognition();
    if (!autoRecognition) {
      setFaceIndicatorState('is-error', 'STT browser tidak tersedia');
      return;
    }

    autoRecognition.onresult = (event) => {
      if (isAssistantResponding || isSending || isSpeechActive()) {
        return;
      }

      let finalText = '';
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        if (event.results[index].isFinal) {
          finalText += ` ${event.results[index][0].transcript || ''}`;
        }
      }
      if (finalText.trim()) {
        recognitionFinalTranscript = `${recognitionFinalTranscript} ${finalText}`.trim();
        lastTranscriptPreview = recognitionFinalTranscript;
        scheduleRecognitionSend();
        renderRuntimeDebug(true);
      }
    };

    autoRecognition.onerror = (event) => {
      autoRecognitionActive = false;
      lastSttError = String(event?.error || 'unknown');
      renderRuntimeDebug(true);
    };

    autoRecognition.onend = async () => {
      autoRecognitionActive = false;
      const shouldSend = recognitionShouldSend;
      recognitionShouldSend = false;

      const transcript = recognitionFinalTranscript.trim();
      recognitionFinalTranscript = '';
      clearTimeout(recognitionSendTimer);

      if (shouldSend && transcript.length >= STT_MIN_FINAL_CHARS && !isSending && !isSpeechActive() && isFacePresent) {
        lastAutoSentMessage = transcript;
        await sendMessage(transcript);
      }
      updateAvatarState();
      renderRuntimeDebug(true);

      if (isFacePresent && !isSending && !isAssistantResponding && !isSpeechActive()) {
        setTimeout(() => startAutoRecognition(), 250);
      }
    };
  }

  recognitionFinalTranscript = '';
  recognitionShouldSend = false;

  try {
    autoRecognition.start();
    autoRecognitionActive = true;
    lastSttError = '-';
    updateAvatarState();
    renderRuntimeDebug(true);
  } catch (error) {
    autoRecognitionActive = false;
    lastSttError = 'start-failed';
    renderRuntimeDebug(true);
  }
}

function stopAutoRecognition(shouldSend = true) {
  if (!autoRecognition || !autoRecognitionActive) return;
  recognitionShouldSend = shouldSend;
  clearTimeout(recognitionSendTimer);
  try {
    autoRecognition.stop();
  } catch (error) {
    autoRecognitionActive = false;
  }
  renderRuntimeDebug(true);
}

function getVadRmsLevel() {
  if (!vadAnalyser || !vadDataArray) return 0;
  vadAnalyser.getFloatTimeDomainData(vadDataArray);

  let sumSquares = 0;
  for (let index = 0; index < vadDataArray.length; index += 1) {
    const value = vadDataArray[index];
    sumSquares += value * value;
  }

  return Math.sqrt(sumSquares / vadDataArray.length);
}

function getVadThreshold() {
  const dynamicThreshold = Math.max(VAD_BASE_THRESHOLD, vadNoiseFloor * VAD_DYNAMIC_MULTIPLIER);
  return Math.min(VAD_MAX_THRESHOLD, dynamicThreshold);
}

function tryResumeVadAudioContext(force = false) {
  if (!vadAudioContext) return;
  if (vadAudioContext.state === 'running') return;

  const now = performance.now();
  if (!force && (now - vadLastResumeAttemptAt) < 1000) return;
  vadLastResumeAttemptAt = now;

  vadAudioContext.resume().catch(() => {
  });
}

function updateVadNoiseFloor(rms, now) {
  if (!Number.isFinite(rms) || rms <= 0) return;

  if (vadCalibrating) {
    if (!vadCalibrationStartedAt) {
      vadCalibrationStartedAt = now;
    }

    vadCalibrationSamples += 1;
    vadCalibrationSum += rms;

    if ((now - vadCalibrationStartedAt) >= VAD_CALIBRATION_MS && vadCalibrationSamples > 0) {
      const average = vadCalibrationSum / vadCalibrationSamples;
      vadNoiseFloor = Math.max(0.004, Math.min(0.03, average));
      vadCalibrating = false;
    }
    return;
  }

  if (rms < getVadThreshold()) {
    vadNoiseFloor = (vadNoiseFloor * 0.985) + (rms * 0.015);
  }
}

function monitorVadLoop() {
  vadMonitorRafId = window.requestAnimationFrame(monitorVadLoop);
  if (!vadAnalyser) return;
  tryResumeVadAudioContext();

  if (!vadAudioContext || vadAudioContext.state !== 'running') {
    return;
  }

  const now = performance.now();
  const shouldPause = !isFacePresent || isSending || isAssistantResponding || isSpeechActive();
  if (shouldPause) {
    vadVoiceAboveSince = 0;
    if (vadSpeechActive) {
      vadSpeechActive = false;
      stopAutoRecognition(false);
    }
    return;
  }

  const rms = getVadRmsLevel();
  lastVadRms = rms;
  updateVadNoiseFloor(rms, now);
  const isVoice = rms >= getVadThreshold();
  renderRuntimeDebug();

  if (isVoice) {
    vadLastVoiceAt = now;
    if (!vadVoiceAboveSince) {
      vadVoiceAboveSince = now;
    }

    if (!vadSpeechActive && (now - vadVoiceAboveSince) >= VAD_SPEECH_START_MS) {
      vadSpeechActive = true;
      startAutoRecognition();
    }
    return;
  }

  vadVoiceAboveSince = 0;
  if (vadSpeechActive && (now - vadLastVoiceAt) >= VAD_SILENCE_END_MS) {
    vadSpeechActive = false;
    stopAutoRecognition(true);
  }
}

async function initVAD() {
  try {
    vadStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
      },
      video: false
    });

    vadAudioContext = new (window.AudioContext || window.webkitAudioContext)();
    const source = vadAudioContext.createMediaStreamSource(vadStream);
    vadAnalyser = vadAudioContext.createAnalyser();
    vadAnalyser.fftSize = 1024;
    vadAnalyser.smoothingTimeConstant = 0.15;
    vadDataArray = new Float32Array(vadAnalyser.fftSize);
    source.connect(vadAnalyser);

    tryResumeVadAudioContext(true);
    window.addEventListener('pointerdown', () => tryResumeVadAudioContext(true), { passive: true });
    window.addEventListener('keydown', () => tryResumeVadAudioContext(true));

    vadCalibrating = true;
    vadCalibrationStartedAt = performance.now();
    vadCalibrationSamples = 0;
    vadCalibrationSum = 0;

    monitorVadLoop();
  } catch (error) {
    setFaceIndicatorState('is-error', 'Izin mikrofon ditolak');
  }
}

async function startFaceCamera() {
  if (!faceCamera || !navigator.mediaDevices?.getUserMedia) {
    setFaceIndicatorState('is-error', 'Kamera tidak tersedia');
    return false;
  }

  try {
    faceCameraStream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: 'user',
        width: { ideal: 640 },
        height: { ideal: 480 }
      },
      audio: false
    });
    faceCamera.srcObject = faceCameraStream;
    await faceCamera.play();
    return true;
  } catch (error) {
    setFaceIndicatorState('is-error', 'Izin kamera ditolak');
    return false;
  }
}

function runFaceDetectionLoop() {
  faceDetectionRafId = window.requestAnimationFrame(runFaceDetectionLoop);

  if (!faceDetector || !faceCamera || faceCamera.readyState < 2) {
    return;
  }

  const now = Date.now();
  if ((now - lastFaceDetectionRunAt) < FACE_DETECTION_INTERVAL_MS) {
    return;
  }
  lastFaceDetectionRunAt = now;

  try {
    const result = faceDetector.detectForVideo(faceCamera, performance.now());
    const detections = result?.detections || [];
    if (!detections.length) {
      handleFaceMissing();
      return;
    }

    handleFaceDetected(detections[0]);
  } catch (error) {
    setFaceIndicatorState('is-error', 'Deteksi wajah gagal');
  }
}

async function initFaceRecognition() {
  setFaceIndicatorState('is-searching', 'Inisialisasi kamera...');

  const cameraReady = await startFaceCamera();
  if (!cameraReady) return;

  await loadKnownFaceProfiles();

  try {
    const vision = await import(`https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VISION_CDN_VERSION}`);
    const resolver = await vision.FilesetResolver.forVisionTasks(
      `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VISION_CDN_VERSION}/wasm`
    );

    faceDetector = await vision.FaceDetector.createFromOptions(resolver, {
      baseOptions: { modelAssetPath: FACE_MODEL_URL },
      runningMode: 'VIDEO',
      minDetectionConfidence: 0.6
    });

    setFaceIndicatorState('is-searching', 'Mencari wajah...');
    runFaceDetectionLoop();
  } catch (error) {
    setFaceIndicatorState('is-error', 'Model wajah gagal dimuat');
  }
}

function registerFaceProfile(name) {
  const cleanedName = String(name || '').trim();
  if (!cleanedName || !latestFaceSignature) {
    return false;
  }

  const nextProfiles = knownFaceProfiles.filter((profile) => profile.name.toLowerCase() !== cleanedName.toLowerCase());
  nextProfiles.push({ name: cleanedName, signature: latestFaceSignature });
  knownFaceProfiles = nextProfiles;
  saveProfilesToStorage(knownFaceProfiles);
  return true;
}

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
}

function clearContactBusyFollowUp() {
  clearTimeout(contactBusyFollowUpTimer);
  contactBusyFollowUpTimer = null;
  clearInterval(contactBusyCountdownInterval);
  contactBusyCountdownInterval = null;
  isContactCountdownActive = false;
  syncComposerState();
}

function scheduleContactBusyFollowUp(followUp) {
  if (!followUp || typeof followUp !== 'object') return;

  const mode = String(followUp.mode || '').trim().toLowerCase();
  if (mode !== 'countdown-check' && mode !== 'timeout-check') return;

  const durationSeconds = mode === 'countdown-check'
    ? Math.max(1, Number(followUp.duration_seconds || 10))
    : Math.max(1, Math.round(Number(followUp.after_ms_max || followUp.after_ms_min || 10000) / 1000));
  const delay = durationSeconds * 1000;
  const timeoutMessage = String(followUp.message || '__contact_timeout__');
  const preCountdownAnswer = String(followUp.pre_countdown_answer || 'Mohon tunggu 10 detik, saya cek ketersediaannya dulu.').trim();

  clearContactBusyFollowUp();
  const snapshotState = JSON.parse(JSON.stringify(contactFlowState || { stage: 'idle' }));
  isContactCountdownActive = true;
  stopAutoRecognition(false);
  syncComposerState();

  activateConversationLayout();
  clearChat();
  const countdownBubble = addBotBubble();
  countdownBubble.textContent = `${preCountdownAnswer}\n\nHitung mundur: ${durationSeconds}`;
  scrollChatToBottom();

  let countdownValue = durationSeconds;
  contactBusyCountdownInterval = setInterval(() => {
    countdownValue -= 1;
    if (countdownValue < 0) {
      clearInterval(contactBusyCountdownInterval);
      contactBusyCountdownInterval = null;
      return;
    }
    countdownBubble.textContent = `${preCountdownAnswer}\n\nHitung mundur: ${countdownValue}`;
    scrollChatToBottom();
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

      activateConversationLayout();
      clearChat();
      const botBubble = addBotBubble();
      botBubble.textContent = answer;
      scrollChatToBottom();
      appendConversationTurn('assistant', answer);
      scheduleSessionIdleReset();
      speakText(answer);
      if (!window.speechSynthesis) {
        scheduleConversationReset(40);
      }
    } catch (error) {
    } finally {
      clearContactBusyFollowUp();
    }
  }, delay);
}

function scheduleSessionIdleReset() {
  clearTimeout(sessionIdleTimer);
  sessionIdleTimer = setTimeout(() => {
    clearConversationState();
    resetConversationLayout();
    renderDebugStats(null);
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

function getAvatarPath(state) {
  return `/static/kiosk/models/${state}.png`;
}

function colorDistance(r1, g1, b1, r2, g2, b2) {
  const dr = r1 - r2;
  const dg = g1 - g2;
  const db = b1 - b2;
  return Math.sqrt((dr * dr) + (dg * dg) + (db * db));
}

function getBorderPalette(data, width, height) {
  const bucketSize = 16;
  const buckets = new Map();
  const step = Math.max(1, Math.floor(Math.min(width, height) / 128));

  const addSample = (x, y) => {
    const index = (y * width + x) * 4;
    const r = data[index];
    const g = data[index + 1];
    const b = data[index + 2];
    const a = data[index + 3];
    if (a < 200) return;

    const key = [
      Math.round(r / bucketSize) * bucketSize,
      Math.round(g / bucketSize) * bucketSize,
      Math.round(b / bucketSize) * bucketSize
    ].join(',');

    const existing = buckets.get(key);
    if (existing) {
      existing.r += r;
      existing.g += g;
      existing.b += b;
      existing.count += 1;
    } else {
      buckets.set(key, { r, g, b, count: 1 });
    }
  };

  for (let x = 0; x < width; x += step) {
    addSample(x, 0);
    addSample(x, height - 1);
  }

  for (let y = 0; y < height; y += step) {
    addSample(0, y);
    addSample(width - 1, y);
  }

  return [...buckets.values()]
    .sort((left, right) => right.count - left.count)
    .slice(0, 6)
    .map((entry) => ({
      r: entry.r / entry.count,
      g: entry.g / entry.count,
      b: entry.b / entry.count
    }));
}

function isLikelyBackgroundPixel(data, index, palette) {
  const r = data[index];
  const g = data[index + 1];
  const b = data[index + 2];
  const a = data[index + 3];

  if (a < 18) return true;

  const maxChannel = Math.max(r, g, b);
  const minChannel = Math.min(r, g, b);
  const brightness = (r + g + b) / 3;
  const saturation = maxChannel - minChannel;
  const nearNeutral = saturation < 36;

  if (brightness > 238 && saturation < 24) {
    return true;
  }

  let nearestDistance = Infinity;
  for (const color of palette) {
    nearestDistance = Math.min(nearestDistance, colorDistance(r, g, b, color.r, color.g, color.b));
  }

  return nearNeutral && nearestDistance < 42;
}

function removeConnectedBackdrop(image) {
  const canvas = document.createElement('canvas');
  canvas.width = image.naturalWidth || image.width;
  canvas.height = image.naturalHeight || image.height;

  const context = canvas.getContext('2d', { willReadFrequently: true });
  context.drawImage(image, 0, 0);

  const frame = context.getImageData(0, 0, canvas.width, canvas.height);
  const { data, width, height } = frame;
  const palette = getBorderPalette(data, width, height);
  const visited = new Uint8Array(width * height);
  const queue = new Uint32Array(width * height);
  let queueStart = 0;
  let queueEnd = 0;

  const enqueueIfBackground = (x, y) => {
    const offset = y * width + x;
    if (visited[offset]) return;
    visited[offset] = 1;

    const index = offset * 4;
    if (!isLikelyBackgroundPixel(data, index, palette)) {
      return;
    }

    queue[queueEnd++] = offset;
  };

  for (let x = 0; x < width; x += 1) {
    enqueueIfBackground(x, 0);
    enqueueIfBackground(x, height - 1);
  }

  for (let y = 1; y < height - 1; y += 1) {
    enqueueIfBackground(0, y);
    enqueueIfBackground(width - 1, y);
  }

  while (queueStart < queueEnd) {
    const offset = queue[queueStart++];
    const index = offset * 4;
    data[index + 3] = 0;

    const x = offset % width;
    const y = Math.floor(offset / width);

    if (x > 0) enqueueIfBackground(x - 1, y);
    if (x + 1 < width) enqueueIfBackground(x + 1, y);
    if (y > 0) enqueueIfBackground(x, y - 1);
    if (y + 1 < height) enqueueIfBackground(x, y + 1);
  }

  context.putImageData(frame, 0, 0);
  return canvas.toDataURL('image/png');
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.decoding = 'async';
    image.onload = () => resolve(image);
    image.onerror = reject;
    image.src = src;
  });
}

async function preloadAvatarStates() {
  await Promise.all(
    AVATAR_STATES.map(async (state) => {
      const source = getAvatarPath(state);
      try {
        const image = await loadImage(source);
        avatarCache.set(state, removeConnectedBackdrop(image));
      } catch (error) {
        avatarCache.set(state, source);
      }
    })
  );

  setAvatarState(currentAvatarState);
}

function setAvatarState(state) {
  currentAvatarState = state;

  if (!avatarEl) return;

  const source = avatarCache.get(state) || getAvatarPath(state);
  if (avatarEl.src !== source) {
    avatarEl.src = source;
  }
  avatarEl.dataset.state = state;
}

function updateAvatarState() {
  const isSpeaking = isSpeakingQueue || (window.speechSynthesis && window.speechSynthesis.speaking);

  if (micWrapper && micWrapper.classList.contains('is-recording')) {
    setAvatarState('LISTENING');
  } else if (isSpeaking) {
    setAvatarState('TALKING');
  } else if (isAssistantResponding) {
    setAvatarState('THINGKING');
  } else if (isSending) {
    setAvatarState('THINGKING');
  } else if (isFacePresent) {
    setAvatarState('LISTENING');
  } else {
    setAvatarState('IDLE');
  }
}

function scrollChatToBottom() {
  if (!chatBox) return;
  chatBox.scrollTop = chatBox.scrollHeight;
}

function clearChat() {
  if (!chatBox) return;
  chatBox.innerHTML = '';
}

function resetConversationLayout() {
  hasConversationStarted = false;
  if (kioskRoot) {
    kioskRoot.classList.remove('has-conversation');
  }
  clearChat();
}

function isSpeechActive() {
  return Boolean(isSpeakingQueue || (window.speechSynthesis && window.speechSynthesis.speaking));
}

function finalizeConversationLayout() {
  if (!isSending && !isSpeechActive()) {
    isAssistantResponding = false;
    resetConversationLayout();
    updateMicState();
  }
}

function scheduleConversationReset(delay = 80) {
  clearTimeout(conversationResetTimer);
  conversationResetTimer = setTimeout(() => {
    finalizeConversationLayout();
  }, delay);
}

function activateConversationLayout() {
  clearTimeout(conversationResetTimer);
  if (hasConversationStarted) return;
  hasConversationStarted = true;
  if (kioskRoot) {
    kioskRoot.classList.add('has-conversation');
  }
}

function addBotBubble() {
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble chat-bubble--bot';
  chatBox.appendChild(bubble);
  scrollChatToBottom();
  return bubble;
}

function renderDebugStats(stats = null) {
  if (!debugStatsEl) return;

  debugStatsEl.innerHTML = '';
  if (!stats) return;

  const items = [
    `Waktu Mulai (TTFT): ${(stats.ttft / 1000).toFixed(2)} detik`,
    `Total Waktu: ${(stats.totalTime / 1000).toFixed(2)} detik`,
    `Hitungan Karakter: ${stats.charCount}`,
    `Kecepatan: ${stats.charsPerSec} char/detik`
  ];

  items.forEach((text) => {
    const li = document.createElement('li');
    li.textContent = text;
    debugStatsEl.appendChild(li);
  });
}

function syncComposerState() {
  const hasMessage = Boolean(input && input.value.trim());

  if (sendBtn) {
    sendBtn.disabled = isSending || !hasMessage;
  }

  updateMicState();
}

function updateMicState() {
  const isSpeaking = isSpeakingQueue || (window.speechSynthesis && window.speechSynthesis.speaking);

  if (micBtn) {
    micBtn.disabled = isSending || isAssistantResponding || isSpeaking || isContactCountdownActive;
  }

  updateAvatarState();
  syncAutoRecognitionState();
  renderRuntimeDebug();
}

function setComposerBusy(busy) {
  isSending = busy;

  if (input) {
    input.disabled = busy;
  }

  syncComposerState();
}

function speakText(text) {
  if (!text || !window.speechSynthesis) return;

  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = 'id-ID';
  utter.onstart = updateMicState;
  utter.onend = () => {
    updateMicState();
    scheduleConversationReset(0);
  };
  utter.onerror = () => {
    updateMicState();
    scheduleConversationReset(0);
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
    if (clean) {
      speechQueue.push(clean);
    }
  }

  if (!isSpeakingQueue) {
    drainSpeechQueue();
  }
}

function flushSpeechRemainder() {
  const tail = speechResidualBuffer.trim();
  speechResidualBuffer = '';

  if (tail) {
    speechQueue.push(tail);
  }

  if (!isSpeakingQueue) {
    drainSpeechQueue();
  }
}

function drainSpeechQueue() {
  if (!window.speechSynthesis) return;
  if (!speechQueue.length) {
    isSpeakingQueue = false;
    updateMicState();
    scheduleConversationReset(0);
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

async function renderBotMessageWordByWord(message) {
  activateConversationLayout();
  const bubble = addBotBubble();
  bubble.textContent = message;
  scrollChatToBottom();
  scheduleConversationReset(40);
}

async function sendMessageNonStream(message, thinkingNode = null) {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      conversation_id: activeConversationId || null,
      history: buildRequestHistory()
    })
  });

  if (!response.ok) throw new Error('Gagal mendapatkan jawaban');

  const data = await response.json();
  const answer = data.answer || 'Terjadi kesalahan saat memproses pertanyaan.';
  setActiveConversationId(data.conversation_id || activeConversationId);
  activateConversationLayout();
  clearChat();
  const botBubble = addBotBubble();
  botBubble.textContent = answer;

  if (thinkingNode && thinkingNode.isConnected) {
    thinkingNode.remove();
  }

  appendConversationTurn('user', message);
  appendConversationTurn('assistant', answer);
  scheduleSessionIdleReset();
  scrollChatToBottom();
  speakText(answer);
  if (!window.speechSynthesis) {
    scheduleConversationReset(40);
  }
  renderDebugStats(null);
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
  activateConversationLayout();
  clearChat();
  const botBubble = addBotBubble();
  botBubble.textContent = answer;
  scrollChatToBottom();
  appendConversationTurn('user', message);
  appendConversationTurn('assistant', answer);
  scheduleSessionIdleReset();
  speakText(answer);
  if (!window.speechSynthesis) {
    scheduleConversationReset(40);
  }

  if (data.follow_up && typeof data.follow_up === 'object') {
    scheduleContactBusyFollowUp(data.follow_up);
  }

  return true;
}

async function sendMessage(messageOverride = '') {
  if (isSending) return;

  const message = String(messageOverride || (input ? input.value : '')).trim();
  if (!message) return;

  clearChat();
  if (input) {
    input.value = '';
  }
  clearTimeout(sessionIdleTimer);
  storeActivityNow();
  isAssistantResponding = true;
  recognitionFinalTranscript = '';
  lastTranscriptPreview = '-';
  clearTimeout(recognitionSendTimer);
  setComposerBusy(true);
  resetSpeechQueue();

  const thinkingNode = null;
  let streamStarted = false;
  let botBubble = null;
  let finalAnswer = '';
  let streamEventError = '';

  const startTime = performance.now();
  let firstTokenTime = null;
  renderDebugStats(null);

  try {
    const handledByContactFlow = await tryHandleEmployeeContactFlow(message);
    if (handledByContactFlow) {
      renderDebugStats(null);
      return;
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

    streamStarted = true;

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

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
        } catch (parseError) {
          continue;
        }

        if (event.type === 'meta') {
          setActiveConversationId(event.conversation_id || activeConversationId);
          scheduleSessionIdleReset();
        } else if (event.type === 'token') {
          const token = event.value || '';
          finalAnswer += token;

          if (finalAnswer.trim()) {
            if (!botBubble) {
              activateConversationLayout();
              botBubble = addBotBubble();
              firstTokenTime = performance.now();
              const ttft = firstTokenTime - startTime;
              renderDebugStats({
                ttft,
                totalTime: ttft,
                charCount: finalAnswer.length,
                charsPerSec: ttft > 0 ? (finalAnswer.length / (ttft / 1000)).toFixed(1) : 0
              });

              if (thinkingNode && thinkingNode.isConnected) {
                thinkingNode.remove();
              }
            }

            botBubble.textContent = finalAnswer;
            scrollChatToBottom();
            enqueueSpeechChunk(token);
          }
        } else if (event.type === 'citations') {
          console.debug('Sumber RAG:', event.value || []);
        } else if (event.type === 'error') {
          streamEventError = event.value || 'Gagal mendapatkan jawaban';
        }
      }
    }

    if (buffer.trim()) {
      try {
        const event = JSON.parse(buffer.trim());
        if (event.type === 'citations') {
          console.debug('Sumber RAG:', event.value || []);
        }
      } catch (parseError) {
      }
    }

    const endTime = performance.now();
    const totalTime = endTime - startTime;
    const ttft = firstTokenTime ? (firstTokenTime - startTime) : totalTime;
    renderDebugStats({
      ttft,
      totalTime,
      charCount: finalAnswer.length,
      charsPerSec: totalTime > 0 ? (finalAnswer.length / (totalTime / 1000)).toFixed(1) : 0
    });

    if (!finalAnswer.trim()) {
      finalAnswer = streamEventError || 'Terjadi kesalahan saat memproses pertanyaan.';
      if (!botBubble) {
        botBubble = addBotBubble();
      }
      botBubble.textContent = finalAnswer;
      if (thinkingNode && thinkingNode.isConnected) {
        thinkingNode.remove();
      }
      speakText(finalAnswer);
      if (!window.speechSynthesis) {
        scheduleConversationReset(40);
      }
    } else {
      if (thinkingNode && thinkingNode.isConnected) {
        thinkingNode.remove();
      }
      flushSpeechRemainder();
      if (!window.speechSynthesis) {
        scheduleConversationReset(40);
      }
    }

    appendConversationTurn('user', message);
    appendConversationTurn('assistant', finalAnswer);
    scheduleSessionIdleReset();
  } catch (error) {
    const hasPartialAnswer = Boolean(finalAnswer.trim());
    const fallbackMessage = 'Terjadi kesalahan saat memproses pertanyaan.';

    if (hasPartialAnswer) {
      if (thinkingNode && thinkingNode.isConnected) {
        thinkingNode.remove();
      }
      flushSpeechRemainder();
      return;
    }

    if (!streamStarted) {
      try {
        await sendMessageNonStream(message, thinkingNode);
        return;
      } catch (fallbackError) {
      }
    }

    resetSpeechQueue();

    if (thinkingNode && thinkingNode.isConnected) {
      clearChat();
      const fallbackBubble = addBotBubble();
      fallbackBubble.textContent = fallbackMessage;
      thinkingNode.remove();
      scrollChatToBottom();
    } else {
      renderBotMessageWordByWord(fallbackMessage);
    }

    speakText(fallbackMessage);
    if (!window.speechSynthesis) {
      scheduleConversationReset(40);
    }
  } finally {
    setComposerBusy(false);
    syncComposerState();
    if (input) {
      input.focus();
    }
  }
}

if (sendBtn) {
  sendBtn.addEventListener('click', sendMessage);
}

if (input) {
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });

  input.addEventListener('input', syncComposerState);
}

if (window.speechSynthesis && typeof window.speechSynthesis.addEventListener === 'function') {
  window.speechSynthesis.addEventListener('voiceschanged', updateMicState);
}

syncComposerState();
updateAvatarState();
preloadAvatarStates();
hydrateConversationState();
initFaceRecognition();
initVAD();
renderRuntimeDebug(true);

window.devRegisterFaceProfile = registerFaceProfile;
