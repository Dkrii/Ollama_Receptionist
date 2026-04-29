import { createAvatarController } from './avatar.js';
import { createChatStreamController } from './chat-stream.js';
import { createChatUiController } from './chat-ui.js';
import { createDebugController } from './debug.js';
import { getDevKioskElements } from './elements.js';
import { createFaceController } from './face.js';
import { createDevKioskState } from './state.js';
import { createSessionController } from './session.js';
import { createVoiceController } from './voice.js';

export function createDevKioskApp() {
  const elements = getDevKioskElements();
  const state = createDevKioskState();
  const services = {};

  let voiceController = null;

  function isAssistantBusy() {
    return state.assistant.isSending
      || state.assistant.isAssistantResponding
      || (voiceController?.isSpeechActive() || false);
  }

  function isResponseInFlight() {
    return state.assistant.isSending;
  }

  function updateMicState() {
    if (elements.voiceIndicator) {
      elements.voiceIndicator.classList.toggle('is-listening', state.recognition.active);
    }

    services.avatar?.updateAvatarState();
    services.voice?.syncAutoRecognitionState();
    services.debug?.renderRuntimeDebug();
  }

  function syncComposerState() {
    updateMicState();
  }

  function setComposerBusy(busy) {
    state.assistant.isSending = busy;
    syncComposerState();
  }

  services.app = {
    isAssistantBusy,
    isResponseInFlight,
    updateMicState,
    syncComposerState,
    setComposerBusy
  };

  services.avatar = createAvatarController({ elements, state, services });
  services.chatUi = createChatUiController({ elements, state, services });
  services.session = createSessionController({ state, services });
  services.debug = createDebugController({ elements, state, services });
  voiceController = createVoiceController({ state, services });
  services.voice = voiceController;
  services.chatStream = createChatStreamController({ state, services });
  services.face = createFaceController({ elements, state, services });

  function start() {
    if (window.speechSynthesis && typeof window.speechSynthesis.addEventListener === 'function') {
      window.speechSynthesis.addEventListener('voiceschanged', updateMicState);
    }

    syncComposerState();
    services.avatar.updateAvatarState();
    services.avatar.preloadAvatarStates();
    services.session.hydrateConversationState();
    services.face.initFaceRecognition();
    services.voice.initVAD();
    services.debug.renderRuntimeDebug(true);
  }

  return {
    start,
    registerFaceProfile: services.face.registerFaceProfile
  };
}
