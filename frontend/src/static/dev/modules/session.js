import {
  CONVERSATION_ACTIVITY_STORAGE_KEY,
  CONVERSATION_ID_STORAGE_KEY,
  SESSION_IDLE_MS
} from './config.js';

export function createSessionController({ state, services }) {
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
    state.conversation.activeId = (value || '').trim();

    if (!isStorageAvailable()) return;

    if (state.conversation.activeId) {
      window.sessionStorage.setItem(CONVERSATION_ID_STORAGE_KEY, state.conversation.activeId);
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
    return state.conversation.history.slice(-6);
  }

  function appendConversationTurn(role, content) {
    const text = (content || '').trim();
    if (!text) return;

    state.conversation.history.push({ role, content: text });
    if (state.conversation.history.length > 12) {
      state.conversation.history = state.conversation.history.slice(-12);
    }
    storeActivityNow();
  }

  function clearConversationState() {
    clearTimeout(state.conversation.sessionIdleTimer);
    state.conversation.history = [];
    state.conversation.contactFlowState = { stage: 'idle' };
    clearStoredConversationState();
    state.conversation.activeId = '';
  }

  function scheduleSessionIdleReset() {
    clearTimeout(state.conversation.sessionIdleTimer);
    state.conversation.sessionIdleTimer = setTimeout(() => {
      clearConversationState();
      services.chatUi?.resetConversationLayout();
      services.chatUi?.renderDebugStats(null);
    }, SESSION_IDLE_MS);
  }

  function hydrateConversationState() {
    if (shouldResetStoredConversation()) {
      clearStoredConversationState();
      return;
    }

    state.conversation.activeId = readStoredConversationId();
    if (state.conversation.activeId) {
      scheduleSessionIdleReset();
    }
  }

  function setContactFlowState(flowState) {
    state.conversation.contactFlowState = flowState && typeof flowState === 'object'
      ? flowState
      : { stage: 'idle' };
  }

  return {
    storeActivityNow,
    clearStoredConversationState,
    setActiveConversationId,
    buildRequestHistory,
    appendConversationTurn,
    clearConversationState,
    scheduleSessionIdleReset,
    hydrateConversationState,
    setContactFlowState
  };
}
