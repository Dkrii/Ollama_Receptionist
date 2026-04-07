const kioskRoot = document.getElementById('kioskRoot');
const chatBox = document.getElementById('chatBox');
const input = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const micBtn = document.getElementById('micBtn');
const micWrapper = document.getElementById('micWrapper');
const avatarEl = document.getElementById('kioskAvatar');
const debugStatsEl = document.getElementById('debugStats');
const CONVERSATION_ID_STORAGE_KEY = 'kioskConversationId';
const CONVERSATION_ACTIVITY_STORAGE_KEY = 'kioskConversationLastActivity';
const SESSION_IDLE_MS = 5 * 60 * 1000;

const AVATAR_STATES = ['IDLE', 'LISTENING', 'THINGKING', 'TALKING'];
const avatarCache = new Map();

let currentAvatarState = 'IDLE';
let isSending = false;
let speechQueue = [];
let isSpeakingQueue = false;
let speechResidualBuffer = '';
let conversationHistory = [];
let micRecognition = null;
let hasConversationStarted = false;
let conversationResetTimer = null;
let sessionIdleTimer = null;
let activeConversationId = '';

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
  activeConversationId = (value || '').trim();

  if (!isStorageAvailable()) return;

  if (activeConversationId) {
    window.sessionStorage.setItem(CONVERSATION_ID_STORAGE_KEY, activeConversationId);
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
  return conversationHistory.slice(-6);
}

function appendConversationTurn(role, content) {
  const text = (content || '').trim();
  if (!text) return;

  conversationHistory.push({ role, content: text });
  if (conversationHistory.length > 12) {
    conversationHistory = conversationHistory.slice(-12);
  }
  storeActivityNow();
}

function clearConversationState() {
  clearTimeout(sessionIdleTimer);
  conversationHistory = [];
  clearStoredConversationState();
  activeConversationId = '';
}

function scheduleSessionIdleReset() {
  clearTimeout(sessionIdleTimer);
  sessionIdleTimer = setTimeout(() => {
    clearConversationState();
    resetConversationLayout();
    renderDebugStats(null);
  }, SESSION_IDLE_MS);
}

function hydrateConversationState() {
  if (shouldResetStoredConversation()) {
    clearStoredConversationState();
    return;
  }

  activeConversationId = readStoredConversationId();
  if (activeConversationId) {
    scheduleSessionIdleReset();
  }
}

function getAvatarPath(state) {
  return `/static/kiosk/models/${state}.png`;
}

function colorDistance(r1, g1, b1, r2, g2, b2) {
  const dr = r1 - r2;
  const dg = g1 - g2;
  const db = b1 - b2;
  return Math.sqrt((dr * dr) + (dg * dg) + (db * db));
}

function getBorderPalette(data, width, height) {
  const bucketSize = 16;
  const buckets = new Map();
  const step = Math.max(1, Math.floor(Math.min(width, height) / 128));

  const addSample = (x, y) => {
    const index = (y * width + x) * 4;
    const r = data[index];
    const g = data[index + 1];
    const b = data[index + 2];
    const a = data[index + 3];
    if (a < 200) return;

    const key = [
      Math.round(r / bucketSize) * bucketSize,
      Math.round(g / bucketSize) * bucketSize,
      Math.round(b / bucketSize) * bucketSize
    ].join(',');

    const existing = buckets.get(key);
    if (existing) {
      existing.r += r;
      existing.g += g;
      existing.b += b;
      existing.count += 1;
    } else {
      buckets.set(key, { r, g, b, count: 1 });
    }
  };

  for (let x = 0; x < width; x += step) {
    addSample(x, 0);
    addSample(x, height - 1);
  }

  for (let y = 0; y < height; y += step) {
    addSample(0, y);
    addSample(width - 1, y);
  }

  return [...buckets.values()]
    .sort((left, right) => right.count - left.count)
    .slice(0, 6)
    .map((entry) => ({
      r: entry.r / entry.count,
      g: entry.g / entry.count,
      b: entry.b / entry.count
    }));
}

function isLikelyBackgroundPixel(data, index, palette) {
  const r = data[index];
  const g = data[index + 1];
  const b = data[index + 2];
  const a = data[index + 3];

  if (a < 18) return true;

  const maxChannel = Math.max(r, g, b);
  const minChannel = Math.min(r, g, b);
  const brightness = (r + g + b) / 3;
  const saturation = maxChannel - minChannel;
  const nearNeutral = saturation < 36;

  if (brightness > 238 && saturation < 24) {
    return true;
  }

  let nearestDistance = Infinity;
  for (const color of palette) {
    nearestDistance = Math.min(nearestDistance, colorDistance(r, g, b, color.r, color.g, color.b));
  }

  return nearNeutral && nearestDistance < 42;
}

function removeConnectedBackdrop(image) {
  const canvas = document.createElement('canvas');
  canvas.width = image.naturalWidth || image.width;
  canvas.height = image.naturalHeight || image.height;

  const context = canvas.getContext('2d', { willReadFrequently: true });
  context.drawImage(image, 0, 0);

  const frame = context.getImageData(0, 0, canvas.width, canvas.height);
  const { data, width, height } = frame;
  const palette = getBorderPalette(data, width, height);
  const visited = new Uint8Array(width * height);
  const queue = new Uint32Array(width * height);
  let queueStart = 0;
  let queueEnd = 0;

  const enqueueIfBackground = (x, y) => {
    const offset = y * width + x;
    if (visited[offset]) return;
    visited[offset] = 1;

    const index = offset * 4;
    if (!isLikelyBackgroundPixel(data, index, palette)) {
      return;
    }

    queue[queueEnd++] = offset;
  };

  for (let x = 0; x < width; x += 1) {
    enqueueIfBackground(x, 0);
    enqueueIfBackground(x, height - 1);
  }

  for (let y = 1; y < height - 1; y += 1) {
    enqueueIfBackground(0, y);
    enqueueIfBackground(width - 1, y);
  }

  while (queueStart < queueEnd) {
    const offset = queue[queueStart++];
    const index = offset * 4;
    data[index + 3] = 0;

    const x = offset % width;
    const y = Math.floor(offset / width);

    if (x > 0) enqueueIfBackground(x - 1, y);
    if (x + 1 < width) enqueueIfBackground(x + 1, y);
    if (y > 0) enqueueIfBackground(x, y - 1);
    if (y + 1 < height) enqueueIfBackground(x, y + 1);
  }

  context.putImageData(frame, 0, 0);
  return canvas.toDataURL('image/png');
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.decoding = 'async';
    image.onload = () => resolve(image);
    image.onerror = reject;
    image.src = src;
  });
}

async function preloadAvatarStates() {
  await Promise.all(
    AVATAR_STATES.map(async (state) => {
      const source = getAvatarPath(state);
      try {
        const image = await loadImage(source);
        avatarCache.set(state, removeConnectedBackdrop(image));
      } catch (error) {
        avatarCache.set(state, source);
      }
    })
  );

  setAvatarState(currentAvatarState);
}

function setAvatarState(state) {
  currentAvatarState = state;

  if (!avatarEl) return;

  const source = avatarCache.get(state) || getAvatarPath(state);
  if (avatarEl.src !== source) {
    avatarEl.src = source;
  }
  avatarEl.dataset.state = state;
}

function updateAvatarState() {
  const isSpeaking = isSpeakingQueue || (window.speechSynthesis && window.speechSynthesis.speaking);

  if (micWrapper && micWrapper.classList.contains('is-recording')) {
    setAvatarState('LISTENING');
  } else if (isSpeaking) {
    setAvatarState('TALKING');
  } else if (isSending) {
    setAvatarState('THINGKING');
  } else {
    setAvatarState('IDLE');
  }
}

function scrollChatToBottom() {
  if (!chatBox) return;
  chatBox.scrollTop = chatBox.scrollHeight;
}

function clearChat() {
  if (!chatBox) return;
  chatBox.innerHTML = '';
}

function resetConversationLayout() {
  hasConversationStarted = false;
  if (kioskRoot) {
    kioskRoot.classList.remove('has-conversation');
  }
  clearChat();
}

function isSpeechActive() {
  return Boolean(isSpeakingQueue || (window.speechSynthesis && window.speechSynthesis.speaking));
}

function finalizeConversationLayout() {
  if (!isSending && !isSpeechActive() && !micRecognition) {
    resetConversationLayout();
  }
}

function scheduleConversationReset(delay = 80) {
  clearTimeout(conversationResetTimer);
  conversationResetTimer = setTimeout(() => {
    finalizeConversationLayout();
  }, delay);
}

function activateConversationLayout() {
  clearTimeout(conversationResetTimer);
  if (hasConversationStarted) return;
  hasConversationStarted = true;
  if (kioskRoot) {
    kioskRoot.classList.add('has-conversation');
  }
}

function addBotBubble() {
  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble chat-bubble--bot';
  chatBox.appendChild(bubble);
  scrollChatToBottom();
  return bubble;
}

function renderDebugStats(stats = null) {
  if (!debugStatsEl) return;

  debugStatsEl.innerHTML = '';
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
    debugStatsEl.appendChild(li);
  });
}

function syncComposerState() {
  const hasMessage = Boolean(input && input.value.trim());

  if (sendBtn) {
    sendBtn.disabled = isSending || !hasMessage;
  }

  updateMicState();
}

function updateMicState() {
  const isSpeaking = isSpeakingQueue || (window.speechSynthesis && window.speechSynthesis.speaking);

  if (micBtn) {
    micBtn.disabled = isSending || isSpeaking;
  }

  updateAvatarState();
}

function setComposerBusy(busy) {
  isSending = busy;

  if (input) {
    input.disabled = busy;
  }

  syncComposerState();
}

function speakText(text) {
  if (!text || !window.speechSynthesis) return;

  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = 'id-ID';
  utter.onstart = updateMicState;
  utter.onend = () => {
    updateMicState();
    scheduleConversationReset(40);
  };
  utter.onerror = () => {
    updateMicState();
    scheduleConversationReset(40);
  };
  window.speechSynthesis.speak(utter);
  updateMicState();
}

function resetSpeechQueue() {
  speechQueue = [];
  isSpeakingQueue = false;
  speechResidualBuffer = '';

  if (window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }

  updateMicState();
}

function enqueueSpeechChunk(text) {
  if (!text || !window.speechSynthesis) return;

  speechResidualBuffer += text;
  const parts = speechResidualBuffer.split(/(?<=[.!?])\s+/);
  speechResidualBuffer = parts.pop() || '';

  for (const sentence of parts) {
    const clean = sentence.trim();
    if (clean) {
      speechQueue.push(clean);
    }
  }

  if (!isSpeakingQueue) {
    drainSpeechQueue();
  }
}

function flushSpeechRemainder() {
  const tail = speechResidualBuffer.trim();
  speechResidualBuffer = '';

  if (tail) {
    speechQueue.push(tail);
  }

  if (!isSpeakingQueue) {
    drainSpeechQueue();
  }
}

function drainSpeechQueue() {
  if (!window.speechSynthesis) return;
  if (!speechQueue.length) {
    isSpeakingQueue = false;
    updateMicState();
    scheduleConversationReset(40);
    return;
  }
  if (isSpeakingQueue) return;

  isSpeakingQueue = true;
  updateMicState();

  const next = speechQueue.shift();
  const utter = new SpeechSynthesisUtterance(next);
  utter.lang = 'id-ID';
  utter.onend = () => {
    isSpeakingQueue = false;
    updateMicState();
    drainSpeechQueue();
  };
  utter.onerror = () => {
    isSpeakingQueue = false;
    updateMicState();
    drainSpeechQueue();
  };
  window.speechSynthesis.speak(utter);
}

async function renderBotMessageWordByWord(message) {
  activateConversationLayout();
  const bubble = addBotBubble();
  bubble.textContent = message;
  scrollChatToBottom();
  scheduleConversationReset(40);
}

async function sendMessageNonStream(message, thinkingNode = null) {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      conversation_id: activeConversationId || null,
      history: buildRequestHistory()
    })
  });

  if (!response.ok) throw new Error('Gagal mendapatkan jawaban');

  const data = await response.json();
  const answer = data.answer || 'Terjadi kesalahan saat memproses pertanyaan.';
  setActiveConversationId(data.conversation_id || activeConversationId);
  activateConversationLayout();
  clearChat();
  const botBubble = addBotBubble();
  botBubble.textContent = answer;

  if (thinkingNode && thinkingNode.isConnected) {
    thinkingNode.remove();
  }

  appendConversationTurn('user', message);
  appendConversationTurn('assistant', answer);
  scheduleSessionIdleReset();
  scrollChatToBottom();
  speakText(answer);
  if (!window.speechSynthesis) {
    scheduleConversationReset(40);
  }
  renderDebugStats(null);
}

async function sendMessage() {
  if (isSending || !input) return;

  const message = input.value.trim();
  if (!message) return;

  clearChat();
  input.value = '';
  clearTimeout(sessionIdleTimer);
  storeActivityNow();
  setComposerBusy(true);
  resetSpeechQueue();

  const thinkingNode = null;
  let streamStarted = false;
  let botBubble = null;
  let finalAnswer = '';
  let streamEventError = '';

  const startTime = performance.now();
  let firstTokenTime = null;
  renderDebugStats(null);

  try {
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message,
        conversation_id: activeConversationId || null,
        history: buildRequestHistory()
      })
    });

    if (!response.ok) throw new Error('Gagal mendapatkan jawaban');
    if (!response.body || typeof response.body.getReader !== 'function') {
      throw new Error('Stream tidak tersedia');
    }

    streamStarted = true;

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
          setActiveConversationId(event.conversation_id || activeConversationId);
          scheduleSessionIdleReset();
        } else if (event.type === 'token') {
          const token = event.value || '';
          finalAnswer += token;

          if (finalAnswer.trim()) {
            if (!botBubble) {
              activateConversationLayout();
              botBubble = addBotBubble();
              firstTokenTime = performance.now();
              const ttft = firstTokenTime - startTime;
              renderDebugStats({
                ttft,
                totalTime: ttft,
                charCount: finalAnswer.length,
                charsPerSec: ttft > 0 ? (finalAnswer.length / (ttft / 1000)).toFixed(1) : 0
              });

              if (thinkingNode && thinkingNode.isConnected) {
                thinkingNode.remove();
              }
            }

            botBubble.textContent = finalAnswer;
            scrollChatToBottom();
            enqueueSpeechChunk(token);
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
        if (event.type === 'citations') {
          console.debug('Sumber RAG:', event.value || []);
        }
      } catch (parseError) {
      }
    }

    const endTime = performance.now();
    const totalTime = endTime - startTime;
    const ttft = firstTokenTime ? (firstTokenTime - startTime) : totalTime;
    renderDebugStats({
      ttft,
      totalTime,
      charCount: finalAnswer.length,
      charsPerSec: totalTime > 0 ? (finalAnswer.length / (totalTime / 1000)).toFixed(1) : 0
    });

    if (!finalAnswer.trim()) {
      finalAnswer = streamEventError || 'Terjadi kesalahan saat memproses pertanyaan.';
      if (!botBubble) {
        botBubble = addBotBubble();
      }
      botBubble.textContent = finalAnswer;
      if (thinkingNode && thinkingNode.isConnected) {
        thinkingNode.remove();
      }
      speakText(finalAnswer);
      if (!window.speechSynthesis) {
        scheduleConversationReset(40);
      }
    } else {
      if (thinkingNode && thinkingNode.isConnected) {
        thinkingNode.remove();
      }
      flushSpeechRemainder();
      if (!window.speechSynthesis) {
        scheduleConversationReset(40);
      }
    }

    appendConversationTurn('user', message);
    appendConversationTurn('assistant', finalAnswer);
    scheduleSessionIdleReset();
  } catch (error) {
    const hasPartialAnswer = Boolean(finalAnswer.trim());
    const fallbackMessage = 'Terjadi kesalahan saat memproses pertanyaan.';

    if (hasPartialAnswer) {
      if (thinkingNode && thinkingNode.isConnected) {
        thinkingNode.remove();
      }
      flushSpeechRemainder();
      return;
    }

    if (!streamStarted) {
      try {
        await sendMessageNonStream(message, thinkingNode);
        return;
      } catch (fallbackError) {
      }
    }

    resetSpeechQueue();

    if (thinkingNode && thinkingNode.isConnected) {
      clearChat();
      const fallbackBubble = addBotBubble();
      fallbackBubble.textContent = fallbackMessage;
      thinkingNode.remove();
      scrollChatToBottom();
    } else {
      renderBotMessageWordByWord(fallbackMessage);
    }

    speakText(fallbackMessage);
    if (!window.speechSynthesis) {
      scheduleConversationReset(40);
    }
  } finally {
    setComposerBusy(false);
    syncComposerState();
    input.focus();
  }
}

function setupSpeechRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) return null;

  const recognition = new SpeechRecognition();
  recognition.lang = 'id-ID';
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;
  return recognition;
}

function cleanupRecording() {
  if (micWrapper) {
    micWrapper.classList.remove('is-recording');
  }

  if (micBtn) {
    micBtn.classList.remove('is-recording');
  }

  if (input) {
    input.placeholder = 'Tulis pesan Anda...';
  }

  micRecognition = null;
  updateAvatarState();
}

function startRecording() {
  if (isSending || micRecognition) return;

  micRecognition = setupSpeechRecognition();
  if (!micRecognition) {
    alert('Speech recognition belum didukung browser ini.');
    return;
  }

  micRecognition.onresult = (event) => {
    if (event.results && event.results[0] && event.results[0][0]) {
      input.value = event.results[0][0].transcript;
      syncComposerState();
      sendMessage();
    }
  };

  micRecognition.onerror = () => {
    cleanupRecording();
  };

  micRecognition.onend = () => {
    cleanupRecording();
  };

  try {
    micRecognition.start();

    if (micWrapper) {
      micWrapper.classList.add('is-recording');
    }

    if (micBtn) {
      micBtn.classList.add('is-recording');
    }

    if (input) {
      input.placeholder = 'Mendengarkan... Lepas untuk mengirim';
    }

    updateAvatarState();
  } catch (error) {
    cleanupRecording();
  }
}

function stopRecording() {
  if (!micRecognition) return;

  try {
    micRecognition.stop();
  } catch (error) {
  }

  cleanupRecording();
}

sendBtn.addEventListener('click', sendMessage);

input.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});

input.addEventListener('input', syncComposerState);

micBtn.addEventListener('mousedown', startRecording);
micBtn.addEventListener('touchstart', (event) => {
  event.preventDefault();
  startRecording();
});

window.addEventListener('mouseup', () => {
  if (micRecognition) stopRecording();
});

micBtn.addEventListener('touchend', (event) => {
  event.preventDefault();
  stopRecording();
});

micBtn.addEventListener('touchcancel', (event) => {
  event.preventDefault();
  stopRecording();
});

if (window.speechSynthesis && typeof window.speechSynthesis.addEventListener === 'function') {
  window.speechSynthesis.addEventListener('voiceschanged', updateMicState);
}

syncComposerState();
updateAvatarState();
preloadAvatarStates();
hydrateConversationState();
