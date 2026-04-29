export function createAvatarController({ elements, state, services }) {
  function preloadAvatarStates() {
    setAvatarState('IDLE');
  }

  function setAvatarState(nextState) {
    state.avatar.currentState = nextState;

    if (!elements.avatarEl) return;
    elements.avatarEl.dataset.state = nextState;
  }

  function updateAvatarState() {
    const isSpeaking = services.voice?.isSpeechActive() || false;
    const isReadyForListening = (services.face?.hasStableFacePresence() || false)
      && !(services.app?.isAssistantBusy() || false);
    const isListening = state.recognition.active || state.vad.speechActive || isReadyForListening;

    if (isSpeaking) {
      setAvatarState('TALKING');
    } else if (state.assistant.isAssistantResponding) {
      setAvatarState('THINGKING');
    } else if (state.assistant.isSending) {
      setAvatarState('THINGKING');
    } else if (isListening) {
      setAvatarState('LISTENING');
    } else {
      setAvatarState('IDLE');
    }
  }

  return {
    preloadAvatarStates,
    setAvatarState,
    updateAvatarState
  };
}
