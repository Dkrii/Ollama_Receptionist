import {
  FACE_DETECTION_INTERVAL_MS,
  FACE_INPUT_ACTIVE_WINDOW_MS,
  FACE_LOST_GRACE_MS,
  FACE_MATCH_THRESHOLD,
  FACE_MODEL_URL,
  FACE_PROFILES_STORAGE_KEY,
  FACE_VISION_BUNDLE_URL,
  FACE_WASM_BASE_URL,
  GREETING_COOLDOWN_MS,
  GREETING_RESET_ABSENCE_MS,
  GREETING_STABLE_MS,
} from "./config.js";

export function createFaceController({ elements, state, services }) {
  function setFaceIndicatorState(statusClass, label) {
    if (!elements.faceIndicator || !elements.faceIndicatorText) return;

    elements.faceIndicator.classList.remove(
      "is-searching",
      "is-recognized",
      "is-unknown",
      "is-error",
    );
    elements.faceIndicator.classList.add(statusClass);
    elements.faceIndicatorText.textContent = label;
    state.face.lastError =
      statusClass === "is-error" ? label || "unknown" : "-";
  }

  function hasFreshFaceDetection(now = Date.now()) {
    return (
      state.face.isPresent &&
      now - state.face.lastSeenAt <= FACE_INPUT_ACTIVE_WINDOW_MS
    );
  }

  function hasStableFacePresence(now = Date.now()) {
    return (
      state.face.isPresent &&
      Boolean(state.face.detectedSinceAt) &&
      now - state.face.detectedSinceAt >= GREETING_STABLE_MS
    );
  }

  function canEmitGreeting(now = Date.now()) {
    return (
      hasStableFacePresence(now) &&
      !state.face.greetedInCurrentPresence &&
      !(services.app?.isAssistantBusy() || false) &&
      now - state.face.lastGreetingAt >= GREETING_COOLDOWN_MS
    );
  }

  function resetGreetingPresenceState(resetCooldown = false) {
    state.face.greetedInCurrentPresence = false;
    if (resetCooldown) {
      state.face.lastGreetingAt = 0;
    }
  }

  function renderFacePresenceState(identity = null, now = Date.now()) {
    if (!state.face.isPresent || !hasStableFacePresence(now)) {
      setFaceIndicatorState("is-searching", "Mencari wajah...");
      return;
    }

    if (identity?.recognized) {
      setFaceIndicatorState("is-recognized", `Dikenali: ${identity.name}`);
      return;
    }

    setFaceIndicatorState("is-unknown", "Wajah terdeteksi");
  }

  function distance2D(left, right) {
    if (!left || !right) return 0;
    const dx = Number(left.x || 0) - Number(right.x || 0);
    const dy = Number(left.y || 0) - Number(right.y || 0);
    return Math.sqrt(dx * dx + dy * dy);
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
      y: (Number(leftEye.y || 0) + Number(rightEye.y || 0)) / 2,
    };

    return [
      distance2D(leftEye, nose) / eyeDistance,
      distance2D(rightEye, nose) / eyeDistance,
      distance2D(centerEye, mouth) / eyeDistance,
      distance2D(leftEar, rightEar) / eyeDistance,
      distance2D(nose, mouth) / eyeDistance,
      Math.abs(Number(leftEye.y || 0) - Number(rightEye.y || 0)) / eyeDistance,
    ].map((value) => Number(value.toFixed(6)));
  }

  function signatureDistance(left, right) {
    if (
      !Array.isArray(left) ||
      !Array.isArray(right) ||
      left.length !== right.length
    ) {
      return Number.POSITIVE_INFINITY;
    }

    let total = 0;
    for (let index = 0; index < left.length; index += 1) {
      const diff = Number(left[index]) - Number(right[index]);
      total += diff * diff;
    }
    return Math.sqrt(total / left.length);
  }

  function parseProfiles(rawProfiles) {
    if (!Array.isArray(rawProfiles)) return [];

    return rawProfiles
      .map((profile) => {
        const name = String(profile?.name || "").trim();
        const signature = Array.isArray(profile?.signature)
          ? profile.signature.map((value) => Number(value))
          : [];

        if (
          !name ||
          signature.length !== 6 ||
          signature.some((value) => Number.isNaN(value))
        ) {
          return null;
        }

        return { name, signature };
      })
      .filter(Boolean);
  }

  function saveProfilesToStorage(profiles) {
    try {
      window.localStorage.setItem(
        FACE_PROFILES_STORAGE_KEY,
        JSON.stringify(profiles),
      );
    } catch (error) {}
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
      const response = await fetch("/static/dev/face-profiles.json", {
        cache: "no-store",
      });
      if (!response.ok) {
        state.face.knownProfiles = localProfiles;
        return;
      }

      const payload = await response.json();
      const fileProfiles = parseProfiles(payload?.profiles);
      const mergedByName = new Map();

      [...fileProfiles, ...localProfiles].forEach((profile) => {
        mergedByName.set(profile.name.toLowerCase(), profile);
      });

      state.face.knownProfiles = [...mergedByName.values()];
    } catch (error) {
      state.face.knownProfiles = localProfiles;
    }
  }

  function recognizeFaceFromSignature(signature) {
    if (!signature || !state.face.knownProfiles.length) {
      return {
        recognized: false,
        name: "",
        distance: Number.POSITIVE_INFINITY,
      };
    }

    let bestMatch = null;
    for (const profile of state.face.knownProfiles) {
      const distance = signatureDistance(signature, profile.signature);
      if (!bestMatch || distance < bestMatch.distance) {
        bestMatch = { profile, distance };
      }
    }

    if (!bestMatch || bestMatch.distance > FACE_MATCH_THRESHOLD) {
      return {
        recognized: false,
        name: "",
        distance: bestMatch ? bestMatch.distance : Number.POSITIVE_INFINITY,
      };
    }

    return {
      recognized: true,
      name: bestMatch.profile.name,
      distance: bestMatch.distance,
    };
  }

  function buildGreetingMessage(identity) {
    if (identity.recognized) {
      return `Selamat datang kembali, ${identity.name}. Senang bertemu lagi, ada yang bisa saya bantu hari ini?`;
    }
    return "Halo, ada yang bisa saya bantu hari ini?";
  }

  function emitSystemGreeting(message) {
    state.assistant.isAssistantResponding = true;
    services.voice?.clearRecognitionDraft();
    services.chatUi?.activateConversationLayout();
    services.chatUi?.clearChat();
    const bubble = services.chatUi?.addBotBubble();
    services.chatUi?.setBubbleText(bubble, message);
    services.chatUi?.scrollChatToBottom();
    services.voice?.speakText(message);
    if (!window.speechSynthesis) {
      services.chatUi?.scheduleConversationReset(40);
    }
  }

  function maybeGreetVisitor(identity) {
    const now = Date.now();
    if (!canEmitGreeting(now)) return;

    state.face.greetedInCurrentPresence = true;
    state.face.lastGreetingAt = now;

    emitSystemGreeting(buildGreetingMessage(identity));
  }

  function handleFaceMissing() {
    if (!state.face.isPresent) {
      if (!state.face.lostSinceAt) {
        state.face.lostSinceAt = Date.now();
      }
      if (Date.now() - state.face.lostSinceAt >= GREETING_RESET_ABSENCE_MS) {
        resetGreetingPresenceState(true);
      }
      renderFacePresenceState();
      services.voice?.clearRecognitionDraft();
      services.voice?.stopAutoRecognition(false);
      return;
    }

    if (Date.now() - state.face.lastSeenAt < FACE_LOST_GRACE_MS) {
      return;
    }

    state.face.isPresent = false;
    state.face.detectedSinceAt = 0;
    state.face.lostSinceAt = Date.now();
    renderFacePresenceState();
    services.voice?.clearRecognitionDraft();
    services.avatar?.updateAvatarState();
    if (state.vad.speechActive) {
      state.vad.speechActive = false;
      services.voice?.stopAutoRecognition(false);
    }
    services.voice?.stopAutoRecognition(false);
    services.debug?.renderRuntimeDebug(true);
  }

  function handleFaceDetected(detection) {
    const now = Date.now();
    if (!state.face.isPresent) {
      state.face.detectedSinceAt = now;
    }
    state.face.isPresent = true;
    state.face.lastSeenAt = now;
    state.face.lostSinceAt = 0;
    services.avatar?.updateAvatarState();

    state.face.latestSignature = buildFaceSignature(detection);
    const identity = recognizeFaceFromSignature(state.face.latestSignature);
    renderFacePresenceState(identity, now);

    maybeGreetVisitor(identity);
    services.voice?.syncAutoRecognitionState();
    services.debug?.renderRuntimeDebug();
  }

  async function startFaceCamera() {
    if (!elements.faceCamera || !navigator.mediaDevices?.getUserMedia) {
      setFaceIndicatorState("is-error", "Kamera tidak tersedia");
      return false;
    }

    try {
      state.face.cameraStream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: "user",
          width: { ideal: 640 },
          height: { ideal: 480 },
        },
        audio: false,
      });
      elements.faceCamera.srcObject = state.face.cameraStream;
      await elements.faceCamera.play();
      return true;
    } catch (error) {
      setFaceIndicatorState("is-error", "Izin kamera ditolak");
      return false;
    }
  }

  function runFaceDetectionLoop() {
    state.face.detectionRafId =
      window.requestAnimationFrame(runFaceDetectionLoop);

    if (
      !state.face.detector ||
      !elements.faceCamera ||
      elements.faceCamera.readyState < 2
    ) {
      return;
    }

    const now = Date.now();
    if (now - state.face.lastDetectionRunAt < FACE_DETECTION_INTERVAL_MS) {
      return;
    }
    state.face.lastDetectionRunAt = now;

    try {
      const result = state.face.detector.detectForVideo(
        elements.faceCamera,
        performance.now(),
      );
      const detections = result?.detections || [];
      if (!detections.length) {
        handleFaceMissing();
        return;
      }

      handleFaceDetected(detections[0]);
    } catch (error) {
      setFaceIndicatorState("is-error", "Deteksi wajah gagal");
    }
  }

  async function initFaceRecognition() {
    setFaceIndicatorState("is-searching", "Inisialisasi kamera...");

    const cameraReady = await startFaceCamera();
    if (!cameraReady) return;

    await loadKnownFaceProfiles();

    try {
      const vision = await import(FACE_VISION_BUNDLE_URL);
      const resolver =
        await vision.FilesetResolver.forVisionTasks(FACE_WASM_BASE_URL);

      state.face.detector = await vision.FaceDetector.createFromOptions(
        resolver,
        {
          baseOptions: { modelAssetPath: FACE_MODEL_URL },
          runningMode: "VIDEO",
          minDetectionConfidence: 0.6,
        },
      );

      setFaceIndicatorState("is-searching", "Mencari wajah...");
      runFaceDetectionLoop();
    } catch (error) {
      setFaceIndicatorState("is-error", "Model wajah gagal dimuat");
    }
  }

  function registerFaceProfile(name) {
    const cleanedName = String(name || "").trim();
    if (!cleanedName || !state.face.latestSignature) {
      return false;
    }

    const nextProfiles = state.face.knownProfiles.filter(
      (profile) => profile.name.toLowerCase() !== cleanedName.toLowerCase(),
    );
    nextProfiles.push({
      name: cleanedName,
      signature: state.face.latestSignature,
    });
    state.face.knownProfiles = nextProfiles;
    saveProfilesToStorage(state.face.knownProfiles);
    return true;
  }

  return {
    setFaceIndicatorState,
    hasFreshFaceDetection,
    hasStableFacePresence,
    initFaceRecognition,
    registerFaceProfile,
  };
}
