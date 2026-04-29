import { DEBUG_REFRESH_MS } from './config.js';

export function createDebugController({ elements, state, services }) {
  function renderRuntimeDebug(force = false) {
    if (!elements.debugRuntimeEl) return;

    const now = performance.now();
    if (!force && (now - state.debug.lastRenderAt) < DEBUG_REFRESH_MS) return;
    state.debug.lastRenderAt = now;

    const speechRecognitionAvailable = services.voice?.isSpeechRecognitionSupported() || false;
    const rows = [
      ['FACE', state.face.isPresent ? 'detected' : 'none'],
      ['FACE_FRESH', services.face?.hasFreshFaceDetection() ? 'yes' : 'no'],
      ['FACE_STABLE', services.face?.hasStableFacePresence() ? 'yes' : 'no'],
      ['FACE_ERR', state.face.lastError || '-'],
      ['ANIM', state.avatar.currentState],
      ['RESPONDING', state.assistant.isAssistantResponding ? 'yes' : 'no'],
      ['AUDIO_READY', services.voice?.canAcceptSpeechInput() ? 'yes' : 'no'],
      ['STT_SUPPORT', speechRecognitionAvailable ? 'yes' : 'no'],
      ['STT_ACTIVE', state.recognition.active ? 'yes' : 'no'],
      ['VAD_SPEECH', state.vad.speechActive ? 'yes' : 'no'],
      ['VAD_RMS', state.vad.lastRms.toFixed(4)],
      ['VAD_TH', (services.voice?.getVadThreshold() || 0).toFixed(4)],
      ['VAD_NOISE', state.vad.noiseFloor.toFixed(4)],
      ['TRANSCRIPT', state.recognition.lastPreview || '-'],
      ['LAST_SENT', state.recognition.lastSent || '-'],
      ['STT_ERROR', state.recognition.lastError || '-']
    ];

    elements.debugRuntimeEl.innerHTML = rows
      .map(([key, value]) => `<div class="kiosk-debug__row"><span class="kiosk-debug__key">${key}</span><span class="kiosk-debug__value">${String(value)}</span></div>`)
      .join('');
  }

  return {
    renderRuntimeDebug
  };
}
