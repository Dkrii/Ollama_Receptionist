const SPOKEN_SUMMARY_MAX_CHARS = 220;
const DEFAULT_RESET_DELAY_MS = 6000;
const OPTIONS_RESET_DELAY_MS = 30000;
const NUMBER_WORDS = {
  1: 'satu',
  2: 'dua',
  3: 'tiga'
};

function normalizeSpokenText(text) {
  return String(text || '')
    .replace(/\s+/g, ' ')
    .trim();
}

function hasNumberedOptions(text) {
  return countNumberedOptions(text) > 0;
}

function countNumberedOptions(text) {
  const numbers = new Set();
  const matches = String(text || '').matchAll(/(?:^|\n)\s*(\d+)\.\s+/g);
  for (const match of matches) {
    const number = Number.parseInt(match[1], 10);
    if (Number.isInteger(number) && number > 0) {
      numbers.add(number);
    }
  }
  return numbers.size;
}

function formatOptionNumberList(count) {
  const numbers = Array.from({ length: count }, (_, index) => NUMBER_WORDS[index + 1] || String(index + 1));
  if (numbers.length <= 1) return numbers[0] || '';
  if (numbers.length === 2) return `${numbers[0]} atau ${numbers[1]}`;
  return `${numbers.slice(0, -1).join(', ')}, atau ${numbers[numbers.length - 1]}`;
}

function buildNumberedOptionsSummary(answer) {
  const optionCount = countNumberedOptions(answer);
  if (optionCount <= 0) return '';
  if (optionCount === 1) return 'Saya menemukan satu pilihan. Saya bantu lanjutkan dengan pilihan ini, ya?';
  return `Saya menemukan ${optionCount} pilihan. Silakan pilih nomor ${formatOptionNumberList(optionCount)}.`;
}

function limitToWordBoundary(text, maxChars = SPOKEN_SUMMARY_MAX_CHARS) {
  const normalized = normalizeSpokenText(text);
  if (normalized.length <= maxChars) return normalized;

  const candidate = normalized.slice(0, maxChars).trimEnd();
  const lastSpaceIndex = candidate.lastIndexOf(' ');
  if (lastSpaceIndex < Math.floor(maxChars * 0.6)) return candidate;
  return candidate.slice(0, lastSpaceIndex).trimEnd();
}

function firstSentences(text, maxSentences = 2) {
  const normalized = normalizeSpokenText(text);
  if (!normalized) return '';

  const matches = normalized.match(/[^.!?]+[.!?]+/g) || [];
  if (!matches.length) return normalized;
  return matches.slice(0, maxSentences).join(' ');
}

function buildSpokenSummary(answer) {
  const normalized = normalizeSpokenText(answer);
  if (!normalized) return '';
  if (hasNumberedOptions(answer)) return buildNumberedOptionsSummary(answer);
  if (normalized.length <= SPOKEN_SUMMARY_MAX_CHARS) return normalized;

  return limitToWordBoundary(firstSentences(normalized) || normalized);
}

function getConversationResetDelay(answer) {
  if (hasNumberedOptions(answer)) return OPTIONS_RESET_DELAY_MS;
  return DEFAULT_RESET_DELAY_MS;
}

export function createChatStreamController({ state, services }) {
  async function sendMessage(messageOverride = '', options = {}) {
    if (state.assistant.isSending) return;

    const message = String(messageOverride || '').trim();
    if (!message) return;
    const existingUserBubble = options.userBubble?.isConnected ? options.userBubble : null;

    services.chatUi?.activateConversationLayout();
    if (existingUserBubble) {
      existingUserBubble.textContent = message;
      existingUserBubble.classList.remove('is-draft');
      services.chatUi?.scrollChatToBottom();
    } else {
      services.chatUi?.clearChat();
      services.chatUi?.addUserBubble(message);
    }
    clearTimeout(state.conversation.sessionIdleTimer);
    services.session?.storeActivityNow();
    state.assistant.isAssistantResponding = true;
    state.recognition.finalTranscript = '';
    state.recognition.interimTranscript = '';
    state.recognition.draftText = '';
    state.recognition.lastPreview = '-';
    if (state.recognition.draftBubble === existingUserBubble) {
      state.recognition.draftBubble = null;
    }
    clearTimeout(state.recognition.sendTimer);
    services.app?.setComposerBusy(true);
    services.voice?.resetSpeechQueue();

    const thinkingNode = null;
    let botBubble = null;
    let finalAnswer = '';
    let streamEventError = '';

    const startTime = performance.now();
    let firstTokenTime = null;
    services.chatUi?.renderDebugStats(null);

    try {
      const response = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          conversation_id: state.conversation.activeId || null,
          history: services.session?.buildRequestHistory() || [],
          flow_state: state.conversation.contactFlowState || { stage: 'idle' }
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
            services.session?.setActiveConversationId(event.conversation_id || state.conversation.activeId);
            services.session?.setContactFlowState(event.flow_state);
            services.session?.scheduleSessionIdleReset();
          } else if (event.type === 'token') {
            const token = event.value || '';
            finalAnswer += token;

            if (finalAnswer.trim()) {
              if (!botBubble) {
                services.chatUi?.activateConversationLayout();
                botBubble = services.chatUi?.addBotBubble();
                firstTokenTime = performance.now();
                const ttft = firstTokenTime - startTime;
                services.chatUi?.renderDebugStats({
                  ttft,
                  totalTime: ttft,
                  charCount: finalAnswer.length,
                  charsPerSec: ttft > 0 ? (finalAnswer.length / (ttft / 1000)).toFixed(1) : 0
                });

                if (thinkingNode && thinkingNode.isConnected) {
                  thinkingNode.remove();
                }
              }

              services.chatUi?.setBubbleText(botBubble, finalAnswer);
              services.chatUi?.scrollChatToBottom();
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
            services.session?.setActiveConversationId(event.conversation_id || state.conversation.activeId);
            services.session?.setContactFlowState(event.flow_state);
          } else if (event.type === 'citations') {
            console.debug('Sumber RAG:', event.value || []);
          }
        } catch (parseError) {
        }
      }

      const endTime = performance.now();
      const totalTime = endTime - startTime;
      const ttft = firstTokenTime ? (firstTokenTime - startTime) : totalTime;
      services.chatUi?.renderDebugStats({
        ttft,
        totalTime,
        charCount: finalAnswer.length,
        charsPerSec: totalTime > 0 ? (finalAnswer.length / (totalTime / 1000)).toFixed(1) : 0
      });

      if (!finalAnswer.trim()) {
        finalAnswer = streamEventError || 'Terjadi kesalahan saat memproses pertanyaan.';
        if (!botBubble) {
          botBubble = services.chatUi?.addBotBubble();
        }
        services.chatUi?.setBubbleText(botBubble, finalAnswer);
        if (thinkingNode && thinkingNode.isConnected) {
          thinkingNode.remove();
        }
        services.voice?.speakText(finalAnswer, {
          onEnd: () => services.chatUi?.scheduleConversationReset(DEFAULT_RESET_DELAY_MS)
        });
        if (!window.speechSynthesis) {
          services.chatUi?.scheduleConversationReset(DEFAULT_RESET_DELAY_MS);
        }
      } else {
        if (thinkingNode && thinkingNode.isConnected) {
          thinkingNode.remove();
        }
        services.voice?.speakText(buildSpokenSummary(finalAnswer), {
          onEnd: () => services.chatUi?.scheduleConversationReset(getConversationResetDelay(finalAnswer))
        });
        if (!window.speechSynthesis) {
          services.chatUi?.scheduleConversationReset(getConversationResetDelay(finalAnswer));
        }
      }

      services.session?.appendConversationTurn('user', message);
      services.session?.appendConversationTurn('assistant', finalAnswer);
      services.session?.scheduleSessionIdleReset();
    } catch (error) {
      const hasPartialAnswer = Boolean(finalAnswer.trim());
      const fallbackMessage = 'Terjadi kesalahan saat memproses pertanyaan.';

      if (hasPartialAnswer) {
        if (thinkingNode && thinkingNode.isConnected) {
          thinkingNode.remove();
        }
        services.voice?.speakText(buildSpokenSummary(finalAnswer), {
          onEnd: () => services.chatUi?.scheduleConversationReset(getConversationResetDelay(finalAnswer))
        });
        return;
      }

      services.voice?.resetSpeechQueue();

      if (thinkingNode && thinkingNode.isConnected) {
        services.chatUi?.clearChat();
        const fallbackBubble = services.chatUi?.addBotBubble();
        services.chatUi?.setBubbleText(fallbackBubble, fallbackMessage);
        thinkingNode.remove();
        services.chatUi?.scrollChatToBottom();
      } else {
        services.chatUi?.renderBotMessageWordByWord(fallbackMessage);
      }

      services.voice?.speakText(fallbackMessage, {
        onEnd: () => services.chatUi?.scheduleConversationReset(DEFAULT_RESET_DELAY_MS)
      });
      if (!window.speechSynthesis) {
        services.chatUi?.scheduleConversationReset(DEFAULT_RESET_DELAY_MS);
      }
    } finally {
      services.app?.setComposerBusy(false);
      services.app?.syncComposerState();
    }
  }

  return {
    sendMessage
  };
}
