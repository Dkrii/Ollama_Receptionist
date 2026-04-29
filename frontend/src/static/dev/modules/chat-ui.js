export function createChatUiController({ elements, state, services }) {
  function scrollChatToBottom() {
    if (!elements.chatBox) return;
    elements.chatBox.scrollTop = elements.chatBox.scrollHeight;
  }

  function clearChat() {
    if (!elements.chatBox) return;
    elements.chatBox.innerHTML = '';
    state.recognition.draftBubble = null;
    state.recognition.draftText = '';
  }

  function resetConversationLayout() {
    state.conversation.hasStarted = false;
    if (elements.kioskRoot) {
      elements.kioskRoot.classList.remove('has-conversation');
    }
    clearChat();
  }

  function finalizeConversationLayout() {
    if (!state.assistant.isSending && !(services.voice?.isSpeechActive() || false)) {
      state.assistant.isAssistantResponding = false;
      resetConversationLayout();
      services.app?.updateMicState();
    }
  }

  function scheduleConversationReset(delay = 80) {
    clearTimeout(state.conversation.resetTimer);
    state.conversation.resetTimer = setTimeout(() => {
      finalizeConversationLayout();
    }, delay);
  }

  function activateConversationLayout() {
    clearTimeout(state.conversation.resetTimer);
    if (state.conversation.hasStarted) return;
    state.conversation.hasStarted = true;
    if (elements.kioskRoot) {
      elements.kioskRoot.classList.add('has-conversation');
    }
  }

  function addBotBubble() {
    if (!elements.chatBox) return null;

    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble chat-bubble--bot';
    const role = document.createElement('span');
    role.className = 'bubble-role';
    role.textContent = 'Resepsionis';
    const textEl = document.createElement('div');
    textEl.className = 'bubble-text';
    bubble.appendChild(role);
    bubble.appendChild(textEl);
    bubble._textEl = textEl;
    elements.chatBox.appendChild(bubble);
    scrollChatToBottom();
    return bubble;
  }

  function setBubbleText(bubble, text) {
    if (!bubble) return;
    const el = bubble._textEl || bubble;
    el.textContent = text;
  }

  function addUserBubble(message) {
    if (!elements.chatBox || !message) return null;
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble chat-bubble--user';
    bubble.textContent = message;
    elements.chatBox.appendChild(bubble);
    scrollChatToBottom();
    return bubble;
  }

  function clearRecognitionDraftBubble() {
    state.recognition.interimTranscript = '';
    state.recognition.draftText = '';
    if (state.recognition.draftBubble && state.recognition.draftBubble.isConnected) {
      state.recognition.draftBubble.remove();
    }
    state.recognition.draftBubble = null;
  }

  function renderRecognitionDraft(text) {
    const draftText = String(text || '').trim();
    if (!draftText || !elements.chatBox) {
      clearRecognitionDraftBubble();
      return null;
    }

    activateConversationLayout();
    if (!state.recognition.draftBubble || !state.recognition.draftBubble.isConnected) {
      clearChat();
      state.recognition.draftBubble = addUserBubble(draftText);
      state.recognition.draftBubble?.classList.add('is-draft');
    } else if (state.recognition.draftText !== draftText) {
      state.recognition.draftBubble.textContent = draftText;
    }
    state.recognition.draftText = draftText;
    scrollChatToBottom();
    return state.recognition.draftBubble;
  }

  function finalizeRecognitionDraft(text) {
    const finalText = String(text || '').trim();
    if (!finalText) {
      clearRecognitionDraftBubble();
      return null;
    }

    if (!state.recognition.draftBubble || !state.recognition.draftBubble.isConnected) {
      activateConversationLayout();
      clearChat();
      state.recognition.draftBubble = addUserBubble(finalText);
    } else {
      state.recognition.draftBubble.textContent = finalText;
    }
    state.recognition.draftBubble?.classList.remove('is-draft');
    const finalizedBubble = state.recognition.draftBubble;
    state.recognition.draftBubble = null;
    state.recognition.draftText = '';
    state.recognition.interimTranscript = '';
    scrollChatToBottom();
    return finalizedBubble;
  }

  function renderDebugStats(stats = null) {
    if (!elements.debugStatsEl) return;

    elements.debugStatsEl.innerHTML = '';
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
      elements.debugStatsEl.appendChild(li);
    });
  }

  async function renderBotMessageWordByWord(message) {
    activateConversationLayout();
    const bubble = addBotBubble();
    setBubbleText(bubble, message);
    scrollChatToBottom();
    scheduleConversationReset(40);
  }

  return {
    scrollChatToBottom,
    clearChat,
    resetConversationLayout,
    finalizeConversationLayout,
    scheduleConversationReset,
    activateConversationLayout,
    addBotBubble,
    setBubbleText,
    addUserBubble,
    clearRecognitionDraftBubble,
    renderRecognitionDraft,
    finalizeRecognitionDraft,
    renderDebugStats,
    renderBotMessageWordByWord
  };
}
