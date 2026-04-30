import {
  STT_FATAL_ERROR_CODES,
  STT_FATAL_RETRY_BLOCK_MS,
  STT_MIN_FINAL_CHARS,
  VAD_BASE_THRESHOLD,
  VAD_CALIBRATION_MS,
  VAD_DYNAMIC_MULTIPLIER,
  VAD_MAX_THRESHOLD,
  VAD_SILENCE_END_MS,
  VAD_SPEECH_START_MS
} from './config.js';

export function createVoiceController({ state, services }) {
  function reportAudioSubsystemIssue(code, message, error = null) {
    state.recognition.lastError = code || 'unknown';
    if (error) {
      console.warn(message, error);
    } else {
      console.warn(message);
    }
    services.debug?.renderRuntimeDebug(true);
  }

  function isSpeechRecognitionSupported() {
    return Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
  }

  function canAcceptSpeechInput() {
    return state.vad.isReady
      && isSpeechRecognitionSupported()
      && Date.now() >= state.recognition.fatalBlockedUntil;
  }

  function shouldPauseVoiceInput(now = Date.now()) {
    return !(services.face?.hasStableFacePresence(now) || false)
      || !(services.face?.hasFreshFaceDetection(now) || false)
      || state.assistant.isSending
      || isSpeechActive();
  }

  function canRunVoiceInput(now = Date.now()) {
    return !shouldPauseVoiceInput(now) && canAcceptSpeechInput();
  }

  function clearRecognitionDraft() {
    state.recognition.finalTranscript = '';
    state.recognition.interimTranscript = '';
    state.recognition.draftText = '';
    state.recognition.lastPreview = '-';
    clearTimeout(state.recognition.sendTimer);
    services.chatUi?.clearRecognitionDraftBubble();
  }

  function scheduleRecognitionSend() {
    clearTimeout(state.recognition.sendTimer);
    state.recognition.sendTimer = setTimeout(async () => {
      const transcript = state.recognition.finalTranscript.trim();

      if (!transcript || transcript.length < STT_MIN_FINAL_CHARS) return;
      if (shouldPauseVoiceInput()) {
        clearRecognitionDraft();
        return;
      }

      const userBubble = services.chatUi?.finalizeRecognitionDraft(transcript) || null;
      state.recognition.finalTranscript = '';
      state.recognition.interimTranscript = '';
      state.recognition.lastPreview = transcript;
      state.recognition.lastSent = transcript;
      await services.chatStream?.sendMessage(transcript, { userBubble });
      services.debug?.renderRuntimeDebug(true);
    }, 700);
  }

  function syncAutoRecognitionState() {
    if (shouldPauseVoiceInput()) {
      stopAutoRecognition(false);
      return;
    }
    startAutoRecognition();
  }

  function setupAutoSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      reportAudioSubsystemIssue('unsupported', 'SpeechRecognition browser tidak tersedia');
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
    if (
      state.recognition.active
      || shouldPauseVoiceInput()
    ) return;

    if (!state.recognition.instance) {
      state.recognition.instance = setupAutoSpeechRecognition();
      if (!state.recognition.instance) {
        services.avatar?.updateAvatarState();
        services.debug?.renderRuntimeDebug(true);
        return;
      }

      state.recognition.instance.onresult = (event) => {
        if (shouldPauseVoiceInput()) {
          clearRecognitionDraft();
          stopAutoRecognition(false);
          return;
        }

        let finalText = '';
        let interimText = '';
        for (let index = event.resultIndex; index < event.results.length; index += 1) {
          const transcriptText = event.results[index][0].transcript || '';
          if (event.results[index].isFinal) {
            finalText += ` ${transcriptText}`;
          } else {
            interimText += ` ${transcriptText}`;
          }
        }
        state.recognition.interimTranscript = interimText.trim();
        if (finalText.trim()) {
          state.recognition.finalTranscript = `${state.recognition.finalTranscript} ${finalText}`.trim();
        }

        const liveTranscript = `${state.recognition.finalTranscript} ${state.recognition.interimTranscript}`.trim();
        if (liveTranscript) {
          state.recognition.lastPreview = liveTranscript;
          services.chatUi?.renderRecognitionDraft(liveTranscript);
          services.debug?.renderRuntimeDebug(true);
        }

        if (finalText.trim()) {
          scheduleRecognitionSend();
        }
      };

      state.recognition.instance.onerror = (event) => {
        state.recognition.active = false;
        const errorCode = String(event?.error || 'unknown').toLowerCase();
        if (errorCode === 'aborted' && state.recognition.stopRequested) {
          state.recognition.lastError = '-';
          return;
        }

        state.recognition.lastError = errorCode;
        if (STT_FATAL_ERROR_CODES.has(errorCode)) {
          state.recognition.fatalBlockedUntil = Date.now() + STT_FATAL_RETRY_BLOCK_MS;
        }
        clearRecognitionDraft();
        services.debug?.renderRuntimeDebug(true);
      };

      state.recognition.instance.onend = async () => {
        state.recognition.active = false;
        state.recognition.stopRequested = false;
        const shouldSend = state.recognition.shouldSend;
        state.recognition.shouldSend = false;

        const transcript = state.recognition.finalTranscript.trim();
        const userBubble = shouldSend && transcript.length >= STT_MIN_FINAL_CHARS && !shouldPauseVoiceInput()
          ? services.chatUi?.finalizeRecognitionDraft(transcript) || null
          : null;

        if (shouldSend && transcript.length >= STT_MIN_FINAL_CHARS && !shouldPauseVoiceInput()) {
          state.recognition.finalTranscript = '';
          state.recognition.interimTranscript = '';
          state.recognition.draftText = '';
          state.recognition.lastPreview = transcript;
          clearTimeout(state.recognition.sendTimer);
          state.recognition.lastSent = transcript;
          await services.chatStream?.sendMessage(transcript, { userBubble });
        } else {
          clearRecognitionDraft();
        }
        services.avatar?.updateAvatarState();
        services.debug?.renderRuntimeDebug(true);

        if (canRunVoiceInput()) {
          setTimeout(() => startAutoRecognition(), 250);
        }
      };
    }

    clearRecognitionDraft();
    state.recognition.shouldSend = false;
    state.recognition.stopRequested = false;

    try {
      state.recognition.instance.start();
      state.recognition.active = true;
      state.recognition.lastError = '-';
      services.avatar?.updateAvatarState();
      services.debug?.renderRuntimeDebug(true);
    } catch (error) {
      state.recognition.active = false;
      state.recognition.lastError = 'start-failed';
      state.recognition.fatalBlockedUntil = Date.now() + STT_FATAL_RETRY_BLOCK_MS;
      services.debug?.renderRuntimeDebug(true);
    }
  }

  function stopAutoRecognition(shouldSend = true) {
    if (!state.recognition.instance || !state.recognition.active) return;
    state.recognition.shouldSend = shouldSend;
    state.recognition.stopRequested = true;
    state.recognition.lastError = '-';
    if (!shouldSend) {
      clearRecognitionDraft();
    }
    try {
      state.recognition.instance.stop();
    } catch (error) {
      state.recognition.active = false;
    }
    services.debug?.renderRuntimeDebug(true);
  }

  function getVadRmsLevel() {
    if (!state.vad.analyser || !state.vad.dataArray) return 0;
    state.vad.analyser.getFloatTimeDomainData(state.vad.dataArray);

    let sumSquares = 0;
    for (let index = 0; index < state.vad.dataArray.length; index += 1) {
      const value = state.vad.dataArray[index];
      sumSquares += value * value;
    }

    return Math.sqrt(sumSquares / state.vad.dataArray.length);
  }

  function getVadThreshold() {
    const dynamicThreshold = Math.max(VAD_BASE_THRESHOLD, state.vad.noiseFloor * VAD_DYNAMIC_MULTIPLIER);
    return Math.min(VAD_MAX_THRESHOLD, dynamicThreshold);
  }

  function tryResumeVadAudioContext(force = false) {
    if (!state.vad.audioContext) return;
    if (state.vad.audioContext.state === 'running') return;

    const now = performance.now();
    if (!force && (now - state.vad.lastResumeAttemptAt) < 1000) return;
    state.vad.lastResumeAttemptAt = now;

    state.vad.audioContext.resume().catch(() => {
    });
  }

  function updateVadNoiseFloor(rms, now) {
    if (!Number.isFinite(rms) || rms <= 0) return;

    if (state.vad.calibrating) {
      if (!state.vad.calibrationStartedAt) {
        state.vad.calibrationStartedAt = now;
      }

      state.vad.calibrationSamples += 1;
      state.vad.calibrationSum += rms;

      if ((now - state.vad.calibrationStartedAt) >= VAD_CALIBRATION_MS && state.vad.calibrationSamples > 0) {
        const average = state.vad.calibrationSum / state.vad.calibrationSamples;
        state.vad.noiseFloor = Math.max(0.004, Math.min(0.03, average));
        state.vad.calibrating = false;
      }
      return;
    }

    if (rms < getVadThreshold()) {
      state.vad.noiseFloor = (state.vad.noiseFloor * 0.985) + (rms * 0.015);
    }
  }

  function monitorVadLoop() {
    state.vad.monitorRafId = window.requestAnimationFrame(monitorVadLoop);
    if (!state.vad.analyser) return;
    tryResumeVadAudioContext();

    if (!state.vad.audioContext || state.vad.audioContext.state !== 'running') {
      return;
    }

    const now = performance.now();
    const shouldPause = shouldPauseVoiceInput();
    if (shouldPause) {
      state.vad.voiceAboveSince = 0;
      if (state.vad.speechActive) {
        state.vad.speechActive = false;
        stopAutoRecognition(false);
      }
      return;
    }

    const rms = getVadRmsLevel();
    state.vad.lastRms = rms;
    updateVadNoiseFloor(rms, now);
    const isVoice = rms >= getVadThreshold();
    services.debug?.renderRuntimeDebug();

    if (isVoice) {
      state.vad.lastVoiceAt = now;
      if (!state.vad.voiceAboveSince) {
        state.vad.voiceAboveSince = now;
      }

      if (!state.vad.speechActive && (now - state.vad.voiceAboveSince) >= VAD_SPEECH_START_MS) {
        state.vad.speechActive = true;
        startAutoRecognition();
      }
      return;
    }

    state.vad.voiceAboveSince = 0;
    if (state.vad.speechActive && (now - state.vad.lastVoiceAt) >= VAD_SILENCE_END_MS) {
      state.vad.speechActive = false;
      stopAutoRecognition(true);
    }
  }

  async function initVAD() {
    try {
      state.vad.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        },
        video: false
      });

      state.vad.audioContext = new (window.AudioContext || window.webkitAudioContext)();
      const source = state.vad.audioContext.createMediaStreamSource(state.vad.stream);
      state.vad.analyser = state.vad.audioContext.createAnalyser();
      state.vad.analyser.fftSize = 1024;
      state.vad.analyser.smoothingTimeConstant = 0.15;
      state.vad.dataArray = new Float32Array(state.vad.analyser.fftSize);
      source.connect(state.vad.analyser);

      tryResumeVadAudioContext(true);
      window.addEventListener('pointerdown', () => tryResumeVadAudioContext(true), { passive: true });
      window.addEventListener('keydown', () => tryResumeVadAudioContext(true));

      state.vad.calibrating = true;
      state.vad.calibrationStartedAt = performance.now();
      state.vad.calibrationSamples = 0;
      state.vad.calibrationSum = 0;
      state.vad.isReady = true;
      state.recognition.lastError = '-';

      monitorVadLoop();
      services.debug?.renderRuntimeDebug(true);
    } catch (error) {
      state.vad.isReady = false;
      reportAudioSubsystemIssue('mic-denied', 'Izin mikrofon ditolak atau audio input tidak tersedia', error);
    }
  }

  function isSpeechActive() {
    return Boolean(state.speech.isSpeaking || (window.speechSynthesis && window.speechSynthesis.speaking));
  }

  function speakText(text, options = {}) {
    const onEnd = typeof options.onEnd === 'function' ? options.onEnd : null;
    if (!text || !window.speechSynthesis) {
      if (onEnd) {
        onEnd();
      }
      return;
    }

    stopAutoRecognition(false);
    state.speech.isSpeaking = true;
    window.speechSynthesis.cancel();
    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = 'id-ID';
    utter.onstart = () => {
      state.speech.isSpeaking = true;
      stopAutoRecognition(false);
      services.app?.updateMicState();
    };
    utter.onend = () => {
      state.speech.isSpeaking = false;
      services.app?.updateMicState();
      if (onEnd) {
        onEnd();
      }
    };
    utter.onerror = () => {
      state.speech.isSpeaking = false;
      services.app?.updateMicState();
      if (onEnd) {
        onEnd();
      }
    };
    window.speechSynthesis.speak(utter);
    services.app?.updateMicState();
  }

  function resetSpeechQueue() {
    state.speech.isSpeaking = false;

    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }

    services.app?.updateMicState();
  }

  return {
    reportAudioSubsystemIssue,
    isSpeechRecognitionSupported,
    canAcceptSpeechInput,
    shouldPauseVoiceInput,
    canRunVoiceInput,
    clearRecognitionDraft,
    syncAutoRecognitionState,
    startAutoRecognition,
    stopAutoRecognition,
    getVadThreshold,
    initVAD,
    isSpeechActive,
    speakText,
    resetSpeechQueue
  };
}
