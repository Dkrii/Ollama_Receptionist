export function createDevKioskState() {
  return {
    avatar: {
      currentState: 'IDLE'
    },
    assistant: {
      isSending: false,
      isAssistantResponding: false
    },
    speech: {
      queue: [],
      isSpeakingQueue: false,
      residualBuffer: '',
      bargeInBlockedUntil: 0,
      suppressNextTtsEndReset: false
    },
    conversation: {
      history: [],
      hasStarted: false,
      resetTimer: null,
      sessionIdleTimer: null,
      activeId: '',
      contactFlowState: { stage: 'idle' }
    },
    face: {
      detector: null,
      detectionRafId: 0,
      lastDetectionRunAt: 0,
      isPresent: false,
      lastSeenAt: 0,
      lastGreetingAt: 0,
      greetedInCurrentPresence: false,
      detectedSinceAt: 0,
      lostSinceAt: 0,
      latestSignature: null,
      knownProfiles: [],
      cameraStream: null,
      lastError: '-'
    },
    recognition: {
      instance: null,
      active: false,
      stopRequested: false,
      fatalBlockedUntil: 0,
      finalTranscript: '',
      interimTranscript: '',
      draftBubble: null,
      draftText: '',
      shouldSend: false,
      sendTimer: null,
      lastPreview: '-',
      lastSent: '-',
      lastError: '-'
    },
    vad: {
      audioContext: null,
      analyser: null,
      dataArray: null,
      monitorRafId: 0,
      stream: null,
      isReady: false,
      voiceAboveSince: 0,
      lastVoiceAt: 0,
      speechActive: false,
      noiseFloor: 0.006,
      calibrating: true,
      calibrationStartedAt: 0,
      calibrationSamples: 0,
      calibrationSum: 0,
      lastResumeAttemptAt: 0,
      lastRms: 0
    },
    debug: {
      lastRenderAt: 0
    }
  };
}
