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
const callPanel = document.getElementById('callPanel');
const callPanelEyebrow = document.getElementById('callPanelEyebrow');
const callPanelTitle = document.getElementById('callPanelTitle');
const callPanelStatus = document.getElementById('callPanelStatus');
const remoteMediaEl = document.getElementById('remoteMedia');
const CONVERSATION_ID_STORAGE_KEY = 'kioskConversationId';
const CONVERSATION_ACTIVITY_STORAGE_KEY = 'kioskConversationLastActivity';
const SESSION_IDLE_MS = 5 * 60 * 1000;
const FACE_PROFILES_STORAGE_KEY = 'kioskFaceProfiles';
const FACE_DETECTION_INTERVAL_MS = 180;
const FACE_LOST_GRACE_MS = 1400;
const GREETING_COOLDOWN_MS = 12000;
const FACE_MATCH_THRESHOLD = 0.12;
const VAD_BASE_THRESHOLD = 0.004;
const VAD_DYNAMIC_MULTIPLIER = 1.8;
const VAD_MAX_THRESHOLD = 0.02;
const VAD_CALIBRATION_MS = 2200;
const VAD_SPEECH_START_MS = 240;
const VAD_SILENCE_END_MS = 900;
const STT_MIN_FINAL_CHARS = 3;
const VISION_CDN_VERSION = '0.10.14';
const FACE_MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite';


let currentAvatarState = 'IDLE';
let avatarScene = null;
let avatarCamera = null;
let avatarRenderer = null;
let avatarMixer = null;
let avatarModel = null;
let avatarArmRig = null;
let avatarClock = null;
let avatarAnimationRafId = 0;
let avatarResizeObserver = null;
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
let recognitionStopRequested = false;
let recognitionFatalBlockedUntil = 0;
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
let currentCallSession = null;
let currentCallConnection = null;
let currentCallConnected = false;
let currentCallCompletionHandled = false;
let currentCallBackendStatus = 'idle';
let currentCallProvider = '';
let isStartingTwoWayCall = false;
let twilioDevice = null;
let telnyxClient = null;
let pendingCallAction = null;
let pendingFollowUp = null;
let callStatusPollTimer = null;
let callStartTimeout = null;
const DEBUG_REFRESH_MS = 180;
const STT_FATAL_ERROR_CODES = new Set(['not-allowed', 'service-not-allowed', 'audio-capture']);
const STT_FATAL_RETRY_BLOCK_MS = 8000;

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
  if (isSending || isAssistantResponding || isSpeechActive() || isCallActive()) return;

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
    ['CALL', currentCallSession ? (currentCallConnected ? 'connected' : 'active') : (isStartingTwoWayCall ? 'starting' : 'idle')],
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
  if (!isFacePresent || isSending || isAssistantResponding || isSpeechActive() || isCallActive()) {
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
  if (autoRecognitionActive || isSending || isAssistantResponding || isSpeechActive()) return;
  if (Date.now() < recognitionFatalBlockedUntil) return;

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
      const errorCode = String(event?.error || 'unknown').toLowerCase();
      if (errorCode === 'aborted' && recognitionStopRequested) {
        lastSttError = '-';
        return;
      }

      lastSttError = errorCode;
      if (STT_FATAL_ERROR_CODES.has(errorCode)) {
        recognitionFatalBlockedUntil = Date.now() + STT_FATAL_RETRY_BLOCK_MS;
      }
      renderRuntimeDebug(true);
    };

    autoRecognition.onend = async () => {
      autoRecognitionActive = false;
      recognitionStopRequested = false;
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

      if (isFacePresent && !isSending && !isAssistantResponding && !isSpeechActive() && Date.now() >= recognitionFatalBlockedUntil) {
        setTimeout(() => startAutoRecognition(), 250);
      }
    };
  }

  recognitionFinalTranscript = '';
  recognitionShouldSend = false;
  recognitionStopRequested = false;

  try {
    autoRecognition.start();
    autoRecognitionActive = true;
    lastSttError = '-';
    updateAvatarState();
    renderRuntimeDebug(true);
  } catch (error) {
    autoRecognitionActive = false;
    lastSttError = 'start-failed';
    recognitionFatalBlockedUntil = Date.now() + STT_FATAL_RETRY_BLOCK_MS;
    renderRuntimeDebug(true);
  }
}

function stopAutoRecognition(shouldSend = true) {
  if (!autoRecognition || !autoRecognitionActive) return;
  recognitionShouldSend = shouldSend;
  recognitionStopRequested = true;
  lastSttError = '-';
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
  if (isCallActive()) {
    vadVoiceAboveSince = 0;
    if (vadSpeechActive) {
      vadSpeechActive = false;
      stopAutoRecognition(false);
    }
    return;
  }
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
  conversationHistory = [];
  contactFlowState = { stage: 'idle' };
  clearStoredConversationState();
  activeConversationId = '';
}

function waitForSpeechPlaybackToFinish(onDone) {
  if (typeof onDone !== 'function') return;
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

function scheduleSessionIdleReset() {
  if (isCallActive()) return;
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

function resizeAvatarRenderer() {
  if (!avatarEl || !avatarRenderer || !avatarCamera) return;

  const width = Math.max(1, avatarEl.clientWidth);
  const height = Math.max(1, avatarEl.clientHeight);

  avatarRenderer.setSize(width, height, false);
  avatarCamera.aspect = width / height;
  avatarCamera.updateProjectionMatrix();
}

function toRad(deg) {
  return (deg * Math.PI) / 180;
}

function isLeftBone(name) {
  return /(left|kiri|_l\b|\.l\b|-l\b|\bl\b)/i.test(name);
}

function isRightBone(name) {
  return /(right|kanan|_r\b|\.r\b|-r\b|\br\b)/i.test(name);
}

function getPrimaryBoneChild(bone) {
  if (!bone) return null;
  for (const child of bone.children || []) {
    if (child?.isBone) return child;
  }
  return null;
}

function captureBoneDeltaY(parentBone, childBone) {
  if (!parentBone || !childBone) return 0;
  const parentPos = new THREE.Vector3();
  const childPos = new THREE.Vector3();
  parentBone.getWorldPosition(parentPos);
  childBone.getWorldPosition(childPos);
  return childPos.y - parentPos.y;
}

function findBestLoweringRotation(rootModel, bone, childBone, baseQuaternion, offsetRad) {
  if (!rootModel || !bone || !childBone || !baseQuaternion || !offsetRad) {
    return { axis: 'z', sign: 1 };
  }

  const originalQuaternion = bone.quaternion.clone();
  rootModel.updateMatrixWorld(true);
  const baselineDeltaY = captureBoneDeltaY(bone, childBone);

  let best = { axis: 'z', sign: 1, score: Number.NEGATIVE_INFINITY };
  const axes = ['x', 'y', 'z'];

  for (const axis of axes) {
    for (const sign of [1, -1]) {
      const offsetQuaternion = new THREE.Quaternion().setFromAxisAngle(BONE_AXIS_VECTORS[axis], sign * offsetRad);
      bone.quaternion.copy(baseQuaternion).multiply(offsetQuaternion);
      rootModel.updateMatrixWorld(true);
      const candidateDeltaY = captureBoneDeltaY(bone, childBone);
      const score = baselineDeltaY - candidateDeltaY;

      if (score > best.score) {
        best = { axis, sign, score };
      }
    }
  }

  bone.quaternion.copy(originalQuaternion);
  rootModel.updateMatrixWorld(true);
  return { axis: best.axis, sign: best.sign };
}

function buildAvatarArmRig(rootModel) {
  const bones = {
    leftUpper: null,
    rightUpper: null,
    leftFore: null,
    rightFore: null
  };

  rootModel.traverse((node) => {
    if (!node || !node.isBone || !node.name) return;
    const name = node.name.toLowerCase();

    const isUpper = /(upperarm|shoulder|clavicle|arm|lengan|bahu)/i.test(name)
      && !/(forearm|lowerarm|elbow|hand|wrist|siku|telapak)/i.test(name);
    const isFore = /(forearm|lowerarm|elbow|lenganbawah|siku)/i.test(name);

    if (isUpper && isLeftBone(name)) bones.leftUpper = node;
    if (isUpper && isRightBone(name)) bones.rightUpper = node;
    if (isFore && isLeftBone(name)) bones.leftFore = node;
    if (isFore && isRightBone(name)) bones.rightFore = node;
  });

  const upperOffset = toRad(AVATAR_ARM_POSE.upperArmDownDeg);
  const foreOffset = toRad(AVATAR_ARM_POSE.foreArmDownDeg);
  const rigEntries = [];

  const pushRigEntry = (bone, childBone, offsetRad) => {
    if (!bone || !offsetRad) return;
    const baseQuaternion = bone.quaternion.clone();
    const targetChild = childBone || getPrimaryBoneChild(bone);
    const { axis, sign } = findBestLoweringRotation(rootModel, bone, targetChild, baseQuaternion, offsetRad);
    rigEntries.push({ bone, baseQuaternion, axis, sign, offsetRad });
  };

  pushRigEntry(bones.leftUpper, bones.leftFore, upperOffset);
  pushRigEntry(bones.rightUpper, bones.rightFore, upperOffset);
  pushRigEntry(bones.leftFore, getPrimaryBoneChild(bones.leftFore), foreOffset);
  pushRigEntry(bones.rightFore, getPrimaryBoneChild(bones.rightFore), foreOffset);

  return {
    model: rootModel,
    entries: rigEntries
  };
}

function applyLoweredArmPose(rootModel) {
  if (!rootModel) return;

  if (!avatarArmRig || avatarArmRig.model !== rootModel) {
    avatarArmRig = buildAvatarArmRig(rootModel);
  }

  for (const entry of avatarArmRig.entries || []) {
    const offsetQuaternion = new THREE.Quaternion().setFromAxisAngle(
      BONE_AXIS_VECTORS[entry.axis] || BONE_AXIS_VECTORS.z,
      entry.sign * entry.offsetRad
    );
    entry.bone.quaternion.copy(entry.baseQuaternion).multiply(offsetQuaternion);
  }
}

function startAvatarAnimationLoop() {
  if (!avatarRenderer || !avatarScene || !avatarCamera || !avatarClock) return;

  const loop = () => {
    avatarAnimationRafId = window.requestAnimationFrame(loop);

    const delta = avatarClock.getDelta();
    if (avatarMixer) {
      avatarMixer.update(delta);
    }

    if (avatarModel) {
      applyLoweredArmPose(avatarModel);
    }

    avatarRenderer.render(avatarScene, avatarCamera);
  };

  if (avatarAnimationRafId) {
    window.cancelAnimationFrame(avatarAnimationRafId);
  }

  loop();
}

function initAvatar3D() {
  if (!avatarEl || avatarRenderer) return;

  const canvas = document.createElement('canvas');
  canvas.className = 'kiosk-avatar-canvas';
  avatarEl.innerHTML = '';
  avatarEl.appendChild(canvas);

  avatarRenderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  avatarRenderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

  avatarScene = new THREE.Scene();
  avatarCamera = new THREE.PerspectiveCamera(AVATAR_VIEW.cameraFov, 1, 0.1, 100);
  avatarCamera.position.set(
    AVATAR_VIEW.cameraPosition.x,
    AVATAR_VIEW.cameraPosition.y,
    AVATAR_VIEW.cameraPosition.z
  );

  const ambientLight = new THREE.AmbientLight(0xffffff, 1.35);
  avatarScene.add(ambientLight);

  const directionalLight = new THREE.DirectionalLight(0xffffff, 1.65);
  directionalLight.position.set(2.5, 4, 3.5);
  avatarScene.add(directionalLight);

  const loader = new GLTFLoader();
  loader.load(
    AVATAR_MODEL_URL,
    (gltf) => {
      avatarModel = gltf.scene;
      avatarArmRig = null;
      avatarModel.position.set(
        AVATAR_VIEW.modelPosition.x,
        AVATAR_VIEW.modelPosition.y,
        AVATAR_VIEW.modelPosition.z
      );
      avatarModel.scale.setScalar(AVATAR_VIEW.modelScale);
      avatarScene.add(avatarModel);

      if (gltf.animations && gltf.animations.length > 0) {
        avatarMixer = new THREE.AnimationMixer(avatarModel);
        avatarMixer.clipAction(gltf.animations[0]).play();
      }

      applyLoweredArmPose(avatarModel);
    },
    undefined,
    (error) => {
      console.warn('Gagal memuat avatar 3D Animasi-Akebono.glb', error);
    }
  );

  avatarClock = new THREE.Clock();
  resizeAvatarRenderer();
  startAvatarAnimationLoop();

  window.addEventListener('resize', resizeAvatarRenderer);

  if (window.ResizeObserver) {
    avatarResizeObserver = new window.ResizeObserver(() => {
      resizeAvatarRenderer();
    });
    avatarResizeObserver.observe(avatarEl);
  }
}

function preloadAvatarStates() {
  setAvatarState('IDLE');
}

function setAvatarState(state) {
  currentAvatarState = state;

  if (!avatarEl) return;

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
  if (isCallActive()) return;
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

function isCallActive() {
  return Boolean(currentCallSession || isStartingTwoWayCall);
}

function stopCallStatusPolling() {
  if (!callStatusPollTimer) return;
  window.clearInterval(callStatusPollTimer);
  callStatusPollTimer = null;
}

function stopCallStartTimeout() {
  if (!callStartTimeout) return;
  window.clearTimeout(callStartTimeout);
  callStartTimeout = null;
}

function setCallPanelVisible(visible) {
  if (!callPanel) return;
  callPanel.hidden = !visible;
}

function setCallPanelState(mode, title, status, eyebrow = 'Panduan resepsionis') {
  if (!callPanel || !callPanelTitle || !callPanelStatus || !callPanelEyebrow) return;

  setCallPanelVisible(true);
  callPanel.classList.remove('is-active', 'is-connected', 'is-failed', 'is-prompt');
  if (mode === 'active') {
    callPanel.classList.add('is-active');
  } else if (mode === 'connected') {
    callPanel.classList.add('is-active', 'is-connected');
  } else if (mode === 'failed') {
    callPanel.classList.add('is-active', 'is-failed');
  } else if (mode === 'prompt') {
    callPanel.classList.add('is-prompt');
  }

  callPanelEyebrow.textContent = eyebrow;
  callPanelTitle.textContent = title;
  callPanelStatus.textContent = status;
}

function resetCallPanel() {
  if (!callPanel || !callPanelTitle || !callPanelStatus || !callPanelEyebrow) return;
  callPanel.classList.remove('is-active', 'is-connected', 'is-failed', 'is-prompt');
  callPanelEyebrow.textContent = 'Panduan resepsionis';
  callPanelTitle.textContent = 'Belum ada sambungan aktif';
  callPanelStatus.textContent = 'Panduan singkat dan status sambungan akan tampil di sini saat diperlukan.';
  setCallPanelVisible(false);
}

function buildCallPanelTitle(callAction) {
  return String(callAction?.employee?.nama || 'Sambungan telepon');
}

function buildCallStatusText(status) {
  const normalized = String(status || '').trim().toLowerCase();
  if (normalized === 'preparing') return 'Menyiapkan sambungan';
  if (normalized === 'dialing_employee') return 'Menghubungi';
  if (normalized === 'ringing') return 'Berdering';
  if (normalized === 'connected') return 'Terhubung';
  if (normalized === 'busy') return 'Sedang sibuk';
  if (normalized === 'no_response') return 'Tidak merespons';
  if (normalized === 'failed') return 'Tidak terhubung';
  if (normalized === 'completed') return 'Panggilan selesai';
  return 'Menyiapkan sambungan';
}

function showPromptOverlay(followUp) {
  if (!followUp || currentCallSession) return;

  const eyebrow = String(followUp.eyebrow || 'Panduan resepsionis').trim() || 'Panduan resepsionis';
  const title = String(followUp.title || '').trim();
  const message = String(followUp.message || '').trim();
  if (!title && !message) return;

  setCallPanelState(
    'prompt',
    title || 'Panduan resepsionis',
    message || 'Silakan lanjutkan dengan jawaban Anda.',
    eyebrow
  );
}

function setCallStatusPanelState(mode, title, status) {
  setCallPanelState(mode, title, status, 'Sambungan resepsionis');
}

async function reportCallFailure(callSessionId, status = 'failed', reason = 'client_error') {
  const normalizedSessionId = String(callSessionId || '').trim();
  if (!normalizedSessionId) return;

  try {
    await fetch('/api/contact/call/fail', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        call_session_id: normalizedSessionId,
        status,
        reason,
      }),
    });
  } catch (error) {
  }
}

async function reportClientCallStatus({
  callSessionId,
  provider,
  status,
  providerCallId = '',
  providerPayload = null,
}) {
  const normalizedSessionId = String(callSessionId || '').trim();
  const normalizedStatus = String(status || '').trim().toLowerCase();
  if (!normalizedSessionId || !normalizedStatus) return;

  try {
    await fetch('/api/contact/call/client-status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        call_session_id: normalizedSessionId,
        provider: String(provider || '').trim().toLowerCase(),
        status: normalizedStatus,
        provider_call_id: String(providerCallId || '').trim(),
        provider_payload: providerPayload,
      }),
    });
  } catch (error) {
  }
}

function hasCallAttemptStarted() {
  const status = String(currentCallBackendStatus || '').trim().toLowerCase();
  return Boolean(currentCallConnected || (status && status !== 'preparing' && status !== 'idle'));
}

function suspendAudioForCall() {
  clearTimeout(conversationResetTimer);
  clearTimeout(sessionIdleTimer);
  resetSpeechQueue();
  isAssistantResponding = false;
  updateMicState();
}

async function fetchCallToken(callSessionId) {
  const response = await fetch(`/api/contact/call/token?call_session_id=${encodeURIComponent(callSessionId)}`);
  if (!response.ok) {
    let message = 'Gagal menyiapkan token telepon.';
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch (error) {
    }
    throw new Error(message);
  }
  const payload = await response.json();
  console.info('contact.call.token', {
    provider: payload?.provider || '-',
    hasToken: Boolean(payload?.token),
    tokenLength: String(payload?.token || '').length
  });
  return payload;
}

function getCallProviderName(callAction) {
  return String(callAction?.provider || 'twilio').trim().toLowerCase() || 'twilio';
}

function normalizeIndonesiaPhoneForDialer(value) {
  const compact = String(value || '').replace(/[^\d+]/g, '');
  if (!compact) return '';

  let phone = compact;
  if (phone.startsWith('+')) {
    phone = phone.slice(1);
  }

  if (phone.startsWith('0')) {
    phone = `62${phone.slice(1)}`;
  } else if (phone.startsWith('8')) {
    phone = `62${phone}`;
  }

  if (!/^\d{10,}$/.test(phone)) {
    return '';
  }
  return `+${phone}`;
}

function serializeTelnyxCall(call) {
  if (!call || typeof call !== 'object') return null;
  return {
    id: String(call.id || call.callID || call.callId || '').trim(),
    state: String(call.state || '').trim().toLowerCase(),
    prev_state: String(call.prevState || call.prev_state || '').trim().toLowerCase(),
    direction: String(call.direction || '').trim().toLowerCase(),
    destination_number: String(call.destinationNumber || '').trim(),
    caller_number: String(call.callerNumber || '').trim(),
    caller_name: String(call.callerName || '').trim(),
  };
}

function getTelnyxCallId(call) {
  const serialized = serializeTelnyxCall(call) || {};
  return String(serialized.id || '').trim();
}

function mapTelnyxCallState(rawState) {
  const normalized = String(rawState || '').trim().toLowerCase();
  if (normalized === 'new') return 'preparing';
  if (normalized === 'requesting' || normalized === 'trying' || normalized === 'recovering') return 'dialing_employee';
  if (normalized === 'ringing' || normalized === 'answering' || normalized === 'early') return 'ringing';
  if (normalized === 'active' || normalized === 'held') return 'connected';
  if (normalized === 'hangup' || normalized === 'destroy' || normalized === 'purge') return 'completed';
  if (normalized === 'busy' || normalized === 'rejected') return 'busy';
  if (normalized === 'timeout') return 'no_response';
  if (normalized === 'failed' || normalized === 'error') return 'failed';
  return 'failed';
}

async function refreshTwilioToken() {
  if (!twilioDevice || !currentCallSession?.call_session_id) return;
  try {
    const tokenPayload = await fetchCallToken(currentCallSession.call_session_id);
    if (!tokenPayload?.token || typeof twilioDevice.updateToken !== 'function') return;
    await twilioDevice.updateToken(tokenPayload.token);
  } catch (error) {
    console.warn('Twilio token refresh gagal', error);
  }
}

function cleanupTelnyxClient() {
  if (!telnyxClient) return;
  try {
    if (typeof telnyxClient.disconnect === 'function') {
      telnyxClient.disconnect();
    }
  } catch (error) {
  }
  telnyxClient = null;
}

function cleanupTwilioDevice() {
  if (!twilioDevice) return;
  try {
    if (typeof twilioDevice.destroy === 'function') {
      twilioDevice.destroy();
    }
  } catch (error) {
  }
  twilioDevice = null;
}

async function ensureTwilioDevice(callAction) {
  if (!window.Twilio?.Device) {
    console.error('Twilio Voice SDK belum termuat dari asset lokal /static/vendor/twilio/voice-sdk/twilio.min.js');
    throw new Error('SDK telepon belum termuat. Refresh halaman atau cek asset Twilio lokal.');
  }

  const tokenPayload = await fetchCallToken(callAction.call_session_id);
  if (twilioDevice && typeof twilioDevice.destroy === 'function') {
    try {
      twilioDevice.destroy();
    } catch (error) {
    }
  }

  twilioDevice = new window.Twilio.Device(tokenPayload.token, {
    closeProtection: true,
    logLevel: 1,
  });

  if (typeof twilioDevice.on === 'function') {
    twilioDevice.on('error', (error) => {
      if (!currentCallSession) return;
      finishActiveCall({
        mode: 'failed',
        title: buildCallPanelTitle(currentCallSession),
        detail: buildCallStatusText('failed'),
      });
    });
    twilioDevice.on('tokenWillExpire', refreshTwilioToken);
  }

  return twilioDevice;
}

function handleTelnyxNotification(notification) {
  if (!currentCallSession || !notification || notification.type !== 'callUpdate') return;

  const call = notification.call || null;
  if (!call) return;

  currentCallConnection = call;
  const rawState = String(call.state || '').trim().toLowerCase();
  const mappedStatus = mapTelnyxCallState(rawState);
  const providerCallId = getTelnyxCallId(call);
  const providerPayload = {
    type: String(notification.type || '').trim(),
    status: mappedStatus,
    raw_state: rawState,
    call: serializeTelnyxCall(call),
  };

  if (mappedStatus === 'dialing_employee' || mappedStatus === 'ringing') {
    stopCallStartTimeout();
    setCallStatusPanelState(
      'active',
      buildCallPanelTitle(currentCallSession),
      buildCallStatusText(mappedStatus)
    );
  } else if (mappedStatus === 'connected') {
    currentCallConnected = true;
    stopCallStartTimeout();
    setCallStatusPanelState(
      'connected',
      buildCallPanelTitle(currentCallSession),
      buildCallStatusText('connected')
    );
    updateMicState();
  }

  reportClientCallStatus({
    callSessionId: currentCallSession.call_session_id,
    provider: 'telnyx',
    status: mappedStatus,
    providerCallId,
    providerPayload,
  });

  if (mappedStatus === 'busy' || mappedStatus === 'no_response' || mappedStatus === 'failed') {
    finishActiveCall({
      mode: 'failed',
      title: buildCallPanelTitle(currentCallSession),
      detail: buildCallStatusText(mappedStatus),
    });
    return;
  }

  if (mappedStatus === 'completed') {
    finishActiveCall({
      mode: currentCallConnected ? 'ended' : 'failed',
      title: buildCallPanelTitle(currentCallSession),
      detail: buildCallStatusText(currentCallConnected ? 'completed' : 'failed'),
    });
  }
}

async function ensureTelnyxClient(callAction) {
  if (!window.TelnyxRTC) {
    throw new Error('SDK Telnyx belum termuat. Refresh halaman atau cek integrasi SDK Telnyx.');
  }

  const info = typeof window.TelnyxRTC.webRTCInfo === 'function'
    ? window.TelnyxRTC.webRTCInfo()
    : null;
  if (info && info.supportWebRTC === false) {
    throw new Error('Browser ini tidak mendukung Telnyx WebRTC.');
  }

  cleanupTelnyxClient();

  const tokenPayload = await fetchCallToken(callAction.call_session_id);
  telnyxClient = new window.TelnyxRTC({
    login_token: tokenPayload.token,
  });

  if (remoteMediaEl) {
    telnyxClient.remoteElement = remoteMediaEl.id;
  }

  return await new Promise((resolve, reject) => {
    const cleanupListeners = () => {
      if (!telnyxClient || typeof telnyxClient.off !== 'function') return;
      telnyxClient.off('telnyx.ready');
      telnyxClient.off('telnyx.error');
    };

    telnyxClient.on('telnyx.ready', () => {
      cleanupListeners();
      resolve({ client: telnyxClient, tokenPayload });
    });
    telnyxClient.on('telnyx.error', (error) => {
      cleanupListeners();
      reject(new Error(String(error?.message || 'Telnyx WebRTC gagal diinisialisasi.')));
    });
    telnyxClient.on('telnyx.notification', handleTelnyxNotification);

    try {
      telnyxClient.connect();
    } catch (error) {
      cleanupListeners();
      reject(error);
    }
  });
}

function applyFallbackAfterCall() {
  if (!currentCallSession?.fallbackFlowState) return;
  contactFlowState = currentCallSession.fallbackFlowState;
}

function showCallFallbackMessage(message) {
  const normalizedMessage = String(message || '').trim();
  if (!normalizedMessage) return;

  activateConversationLayout();
  const bubble = addBotBubble();
  bubble.textContent = normalizedMessage;
  scrollChatToBottom();
  appendConversationTurn('assistant', normalizedMessage);
  speakText(normalizedMessage);
}

function finishActiveCall({ mode, title, detail }) {
  if (!currentCallSession || currentCallCompletionHandled) return;

  currentCallCompletionHandled = true;
  isStartingTwoWayCall = false;
  stopCallStatusPolling();
  stopCallStartTimeout();
  const fallbackAnswer = String(currentCallSession?.fallbackAnswer || '').trim();
  const fallbackFollowUp = currentCallSession?.fallbackFollowUp || null;

  if (mode === 'connected') {
    setCallStatusPanelState('connected', title, detail);
    updateMicState();
    return;
  }

  if (mode === 'failed') {
    setCallStatusPanelState('failed', title, detail);
    applyFallbackAfterCall();
    if (fallbackAnswer) {
      showCallFallbackMessage(fallbackAnswer);
    }
  } else {
    setCallStatusPanelState('idle', title, detail);
    contactFlowState = { stage: 'idle' };
  }

  if (currentCallProvider === 'twilio') {
    cleanupTwilioDevice();
  } else if (currentCallProvider === 'telnyx') {
    cleanupTelnyxClient();
  }

  currentCallSession = null;
  currentCallConnection = null;
  currentCallConnected = false;
  currentCallBackendStatus = 'idle';
  currentCallProvider = '';
  resetCallPanel();
  if (mode === 'failed') {
    showPromptOverlay(fallbackFollowUp);
  }
  updateMicState();
}

function wireTwilioCallEvents(connection) {
  if (!connection || typeof connection.on !== 'function' || !currentCallSession) return;

  connection.on('ringing', () => {
    if (!currentCallSession) return;
    setCallStatusPanelState(
      'active',
      buildCallPanelTitle(currentCallSession),
      buildCallStatusText('ringing')
    );
  });

  connection.on('accept', () => {
    if (!currentCallSession) return;
    currentCallConnected = true;
    stopCallStartTimeout();
    setCallStatusPanelState(
      'connected',
      buildCallPanelTitle(currentCallSession),
      buildCallStatusText('connected')
    );
    updateMicState();
  });

  connection.on('disconnect', () => {
    if (!currentCallSession) return;
    if (!currentCallConnected && !hasCallAttemptStarted()) {
      return;
    }
    const title = currentCallConnected
      ? buildCallPanelTitle(currentCallSession)
      : buildCallPanelTitle(currentCallSession);
    const detail = currentCallConnected
      ? buildCallStatusText('completed')
      : buildCallStatusText('failed');
    if (!currentCallConnected) {
      reportCallFailure(currentCallSession.call_session_id, 'failed', 'browser_disconnect');
    }
    finishActiveCall({
      mode: currentCallConnected ? 'ended' : 'failed',
      title,
      detail,
    });
  });

  connection.on('cancel', () => {
    if (!currentCallSession) return;
    if (!hasCallAttemptStarted()) {
      return;
    }
    reportCallFailure(currentCallSession.call_session_id, 'failed', 'call_cancelled');
    finishActiveCall({
      mode: 'failed',
      title: buildCallPanelTitle(currentCallSession),
      detail: buildCallStatusText('failed'),
    });
  });

  connection.on('reject', () => {
    if (!currentCallSession) return;
    if (!hasCallAttemptStarted()) {
      return;
    }
    reportCallFailure(currentCallSession.call_session_id, 'busy', 'call_rejected');
    finishActiveCall({
      mode: 'failed',
      title: buildCallPanelTitle(currentCallSession),
      detail: buildCallStatusText('busy'),
    });
  });

  connection.on('error', (error) => {
    if (!currentCallSession) return;
    if (!hasCallAttemptStarted()) {
      return;
    }
    const reason = String(error?.code || error?.message || 'device_error').trim().toLowerCase();
    reportCallFailure(currentCallSession.call_session_id, 'failed', reason);
    finishActiveCall({
      mode: 'failed',
      title: buildCallPanelTitle(currentCallSession),
      detail: buildCallStatusText('failed'),
    });
  });
}

async function fetchCallStatus(callSessionId) {
  const response = await fetch(`/api/contact/call/status?call_session_id=${encodeURIComponent(callSessionId)}`);
  if (!response.ok) {
    throw new Error('Gagal menyinkronkan status panggilan.');
  }
  const payload = await response.json();
  return payload?.call || null;
}

function applyPolledCallStatus(callRecord) {
  if (!currentCallSession || !callRecord) return;

  const status = String(callRecord.call_status || '').trim().toLowerCase();
  currentCallBackendStatus = status || currentCallBackendStatus;
  const title = buildCallPanelTitle(currentCallSession);

  if (status === 'preparing' || status === 'dialing_employee' || status === 'ringing') {
    if (status !== 'preparing') {
      stopCallStartTimeout();
    }
    setCallStatusPanelState('active', title, buildCallStatusText(status));
    return;
  }

  if (status === 'connected') {
    currentCallConnected = true;
    stopCallStartTimeout();
    setCallStatusPanelState('connected', title, buildCallStatusText(status));
    updateMicState();
    return;
  }

  if (status === 'busy' || status === 'no_response' || status === 'failed') {
    finishActiveCall({
      mode: 'failed',
      title,
      detail: buildCallStatusText(status),
    });
    return;
  }

  if (status === 'completed') {
    finishActiveCall({
      mode: 'ended',
      title,
      detail: buildCallStatusText(status),
    });
  }
}

function startCallStatusPolling(callSessionId) {
  stopCallStatusPolling();
  if (!callSessionId) return;

  callStatusPollTimer = window.setInterval(async () => {
    if (!currentCallSession || currentCallCompletionHandled) {
      stopCallStatusPolling();
      return;
    }

    try {
      const callRecord = await fetchCallStatus(callSessionId);
      applyPolledCallStatus(callRecord);
    } catch (error) {
    }
  }, 1500);
}

function startCallConnectTimeout(callAction) {
  stopCallStartTimeout();
  callStartTimeout = window.setTimeout(() => {
    if (!currentCallSession || currentCallCompletionHandled || currentCallConnected) return;
    reportCallFailure(callAction.call_session_id, 'failed', 'connect_timeout');
    finishActiveCall({
      mode: 'failed',
      title: buildCallPanelTitle(callAction),
      detail: buildCallStatusText('failed'),
    });
  }, 15000);
}

async function startTwoWayCall(callAction) {
  if (!callAction?.call_session_id || !callAction?.employee) return;

  isStartingTwoWayCall = true;
  currentCallSession = {
    ...callAction,
    fallbackFlowState: callAction.fallback_flow_state || null,
    fallbackAnswer: callAction.fallback_answer || '',
    fallbackFollowUp: callAction.fallback_follow_up || null,
  };
  currentCallConnection = null;
  currentCallConnected = false;
  currentCallCompletionHandled = false;
  currentCallBackendStatus = 'preparing';
  currentCallProvider = getCallProviderName(callAction);

  suspendAudioForCall();
  activateConversationLayout();
  setCallStatusPanelState(
    'active',
    buildCallPanelTitle(callAction),
    buildCallStatusText('preparing')
  );
  startCallStatusPolling(callAction.call_session_id);
  startCallConnectTimeout(callAction);

  try {
    if (currentCallProvider === 'telnyx') {
      const { client, tokenPayload } = await ensureTelnyxClient(callAction);
      const destinationNumber = normalizeIndonesiaPhoneForDialer(callAction?.employee?.nomor_wa || '');
      if (!destinationNumber) {
        throw new Error('Nomor telepon karyawan tidak valid untuk Telnyx.');
      }

      const callerNumber = normalizeIndonesiaPhoneForDialer(tokenPayload?.caller_number || '');
      const callOptions = { destinationNumber };
      if (callerNumber) {
        callOptions.callerNumber = callerNumber;
      }

      currentCallConnection = client.newCall(callOptions);
      isStartingTwoWayCall = false;
      return;
    }

    if (currentCallProvider !== 'twilio') {
      throw new Error(`provider_${currentCallProvider || 'unknown'}_not_supported`);
    }

      const device = await ensureTwilioDevice(callAction);
      const connection = await device.connect({
        params: {
          call_session_id: callAction.call_session_id,
        },
      });
      currentCallConnection = connection;
      isStartingTwoWayCall = false;
      wireTwilioCallEvents(connection);
  } catch (error) {
    reportCallFailure(
      callAction.call_session_id,
      'failed',
      String(error?.message || 'client_start_failed').trim().toLowerCase().replace(/\s+/g, '_')
    );
    if (currentCallProvider === 'telnyx') {
      cleanupTelnyxClient();
    }
    isStartingTwoWayCall = false;
    finishActiveCall({
      mode: 'failed',
      title: buildCallPanelTitle(callAction),
      detail: buildCallStatusText('failed'),
    });
  }
}

function syncComposerState() {
  const hasMessage = Boolean(input && input.value.trim());

  if (sendBtn) {
    sendBtn.disabled = isSending || isCallActive() || !hasMessage;
  }

  updateMicState();
}

function updateMicState() {
  const isSpeaking = isSpeakingQueue || (window.speechSynthesis && window.speechSynthesis.speaking);

  if (micBtn) {
    micBtn.disabled = isSending || isAssistantResponding || isSpeaking || isCallActive();
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

function speakText(text, options = {}) {
  const onEnd = typeof options.onEnd === 'function' ? options.onEnd : null;
  if (!text || !window.speechSynthesis) {
    if (onEnd) {
      onEnd();
    }
    return;
  }

  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = 'id-ID';
  utter.onstart = updateMicState;
  utter.onend = () => {
    updateMicState();
    scheduleConversationReset(0);
    if (onEnd) {
      onEnd();
    }
  };
  utter.onerror = () => {
    updateMicState();
    scheduleConversationReset(0);
    if (onEnd) {
      onEnd();
    }
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

async function sendMessage(messageOverride = '') {
  if (isSending || isCallActive()) return;

  const message = String(messageOverride || (input ? input.value : '')).trim();
  if (!message) return;

  clearChat();
  if (!currentCallSession) {
    resetCallPanel();
  }
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
  let botBubble = null;
  let finalAnswer = '';
  let streamEventError = '';
  pendingCallAction = null;
  pendingFollowUp = null;

  const startTime = performance.now();
  let firstTokenTime = null;
  renderDebugStats(null);

  try {
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message,
        conversation_id: activeConversationId || null,
        history: buildRequestHistory(),
        flow_state: contactFlowState || { stage: 'idle' }
      })
    });

    if (!response.ok) throw new Error('Gagal mendapatkan jawaban');
    if (!response.body || typeof response.body.getReader !== 'function') {
      throw new Error('Stream tidak tersedia');
    }

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
          if (event.flow_state && typeof event.flow_state === 'object') {
            contactFlowState = event.flow_state;
          } else {
            contactFlowState = { stage: 'idle' };
          }
          scheduleSessionIdleReset();
        } else if (event.type === 'action') {
          if (event.value && event.value.type === 'start_two_way_call') {
            pendingCallAction = event.value;
          }
        } else if (event.type === 'follow_up') {
          pendingFollowUp = event.value || null;
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
            if (!pendingCallAction) {
              enqueueSpeechChunk(token);
            }
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
        if (event.type === 'meta') {
          setActiveConversationId(event.conversation_id || activeConversationId);
          if (event.flow_state && typeof event.flow_state === 'object') {
            contactFlowState = event.flow_state;
          } else {
            contactFlowState = { stage: 'idle' };
          }
        } else if (event.type === 'action') {
          if (event.value && event.value.type === 'start_two_way_call') {
            pendingCallAction = event.value;
          }
        } else if (event.type === 'follow_up') {
          pendingFollowUp = event.value || null;
        } else if (event.type === 'citations') {
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
      if (pendingCallAction) {
        speechResidualBuffer = '';
      } else {
        flushSpeechRemainder();
      }
      if (!window.speechSynthesis && !pendingCallAction) {
        scheduleConversationReset(40);
      }
    }

    appendConversationTurn('user', message);
    appendConversationTurn('assistant', finalAnswer);
    scheduleSessionIdleReset();

    if (pendingCallAction) {
      await startTwoWayCall(pendingCallAction);
    } else if (pendingFollowUp) {
      showPromptOverlay(pendingFollowUp);
    } else if (!currentCallSession) {
      resetCallPanel();
    }
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
resetCallPanel();
preloadAvatarStates();
hydrateConversationState();
initFaceRecognition();
initVAD();
renderRuntimeDebug(true);

window.devRegisterFaceProfile = registerFaceProfile;
