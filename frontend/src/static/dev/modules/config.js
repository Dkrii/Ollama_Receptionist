export const CONVERSATION_ID_STORAGE_KEY = 'kioskConversationId';
export const CONVERSATION_ACTIVITY_STORAGE_KEY = 'kioskConversationLastActivity';
export const SESSION_IDLE_MS = 5 * 60 * 1000;

export const FACE_PROFILES_STORAGE_KEY = 'kioskFaceProfiles';
export const FACE_DETECTION_INTERVAL_MS = 180;
export const FACE_LOST_GRACE_MS = 1400;
export const FACE_INPUT_ACTIVE_WINDOW_MS = FACE_DETECTION_INTERVAL_MS * 3;
export const GREETING_STABLE_MS = 3000;
export const GREETING_RESET_ABSENCE_MS = 8000;
export const GREETING_COOLDOWN_MS = 30000;
export const FACE_MATCH_THRESHOLD = 0.12;
export const FACE_ASSET_BASE_URL = '/static/dev/vendor/mediapipe';
export const FACE_VISION_BUNDLE_URL = `${FACE_ASSET_BASE_URL}/vision_bundle.mjs`;
export const FACE_WASM_BASE_URL = `${FACE_ASSET_BASE_URL}/wasm`;
export const FACE_MODEL_URL = `${FACE_ASSET_BASE_URL}/blaze_face_short_range.tflite`;

export const VAD_BASE_THRESHOLD = 0.004;
export const VAD_DYNAMIC_MULTIPLIER = 1.8;
export const VAD_MAX_THRESHOLD = 0.02;
export const VAD_CALIBRATION_MS = 2200;
export const VAD_SPEECH_START_MS = 240;
export const VAD_SILENCE_END_MS = 900;

export const STT_MIN_FINAL_CHARS = 3;
export const STT_FATAL_ERROR_CODES = new Set(['not-allowed', 'service-not-allowed', 'audio-capture']);
export const STT_FATAL_RETRY_BLOCK_MS = 8000;

export const DEBUG_REFRESH_MS = 180;
