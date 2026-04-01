const chatBox = document.getElementById('chatBox');
const input = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const micBtn = document.getElementById('micBtn');
const citationsEl = document.getElementById('citations');

let isSending = false;
let speechQueue = [];
let isSpeakingQueue = false;
let speechResidualBuffer = '';

function addBubble(text, role) {
  const row = document.createElement('div');
  row.className = `vr-chat__row vr-chat__row--${role}`;

  const bubble = document.createElement('div');
  bubble.className = `bubble ${role} vr-chat__bubble vr-chat__bubble--${role}`;
  bubble.textContent = text;

  row.appendChild(bubble);
  chatBox.appendChild(row);
  chatBox.scrollTop = chatBox.scrollHeight;
  return bubble;
}

function addBotBubble() {
  const row = document.createElement('div');
  row.className = 'vr-chat__row vr-chat__row--bot';

  const bubble = document.createElement('div');
  bubble.className = 'bubble bot vr-chat__bubble vr-chat__bubble--bot';

  row.appendChild(bubble);
  chatBox.appendChild(row);
  chatBox.scrollTop = chatBox.scrollHeight;
  return bubble;
}

function addThinkingBubble() {
  const row = document.createElement('div');
  row.className = 'vr-chat__row vr-chat__row--bot';

  const bubble = document.createElement('div');
  bubble.className = 'bubble bot vr-chat__bubble vr-chat__bubble--bot vr-chat__bubble--thinking';
  bubble.setAttribute('aria-label', 'Bot sedang menyiapkan jawaban');
  bubble.innerHTML = `
    <span class="vr-chat__typing" aria-hidden="true">
      <span class="vr-chat__dot"></span>
      <span class="vr-chat__dot"></span>
      <span class="vr-chat__dot"></span>
    </span>
  `;

  row.appendChild(bubble);
  chatBox.appendChild(row);
  chatBox.scrollTop = chatBox.scrollHeight;
  return row;
}

function setComposerBusy(busy) {
  isSending = busy;
  sendBtn.disabled = busy;
  micBtn.disabled = busy;
  input.disabled = busy;
}

function speakText(text) {
  if (!text || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = 'id-ID';
  window.speechSynthesis.speak(utter);
}

function resetSpeechQueue() {
  speechQueue = [];
  isSpeakingQueue = false;
  speechResidualBuffer = '';
  if (window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
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
  if (!window.speechSynthesis || isSpeakingQueue) return;
  if (!speechQueue.length) return;

  isSpeakingQueue = true;
  const next = speechQueue.shift();
  const utter = new SpeechSynthesisUtterance(next);
  utter.lang = 'id-ID';
  utter.onend = () => {
    isSpeakingQueue = false;
    drainSpeechQueue();
  };
  utter.onerror = () => {
    isSpeakingQueue = false;
    drainSpeechQueue();
  };
  window.speechSynthesis.speak(utter);
}

async function renderBotMessageWordByWord(message) {
  const bubble = addBotBubble();
  bubble.textContent = message;
  chatBox.scrollTop = chatBox.scrollHeight;
}

function renderCitations(citations) {
  citationsEl.innerHTML = '';
  if (!citations || !citations.length) {
    const li = document.createElement('li');
    li.textContent = 'Tidak ada sumber relevan.';
    citationsEl.appendChild(li);
    return;
  }

  citations.forEach((item) => {
    const li = document.createElement('li');
    const source = item?.metadata?.source || 'unknown';
    const score = item?.score ?? 0;
    li.textContent = `${source} (score: ${score})`;
    citationsEl.appendChild(li);
  });
}

async function sendMessageNonStream(message, thinkingNode = null) {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message })
  });

  if (!response.ok) throw new Error('Gagal mendapatkan jawaban');

  const data = await response.json();
  const answer = data.answer || 'Terjadi kesalahan saat memproses pertanyaan.';
  const botBubble = addBotBubble();
  botBubble.textContent = answer;
  if (thinkingNode && thinkingNode.isConnected) {
    thinkingNode.remove();
  }
  chatBox.scrollTop = chatBox.scrollHeight;
  speakText(answer);
  renderCitations(data.citations || []);
}

async function sendMessage() {
  if (isSending) return;

  const message = input.value.trim();
  if (!message) return;

  addBubble(message, 'user');
  input.value = '';
  setComposerBusy(true);
  resetSpeechQueue();
  const thinkingNode = addThinkingBubble();
  let streamStarted = false;
  let botBubble = null;
  let finalAnswer = '';
  let streamEventError = '';

  try {
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message })
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
        if (event.type === 'token') {
          const token = event.value || '';
          finalAnswer += token;

          if (finalAnswer.trim()) {
            if (!botBubble) {
              botBubble = addBotBubble();
            }
            botBubble.textContent = finalAnswer;
            chatBox.scrollTop = chatBox.scrollHeight;
            enqueueSpeechChunk(token);
          }
        } else if (event.type === 'citations') {
          renderCitations(event.value || []);
        } else if (event.type === 'error') {
          streamEventError = event.value || 'Gagal mendapatkan jawaban';
        }
      }
    }

    if (buffer.trim()) {
      try {
        const event = JSON.parse(buffer.trim());
        if (event.type === 'citations') {
          renderCitations(event.value || []);
        }
      } catch (parseError) {
      }
    }

    if (!finalAnswer.trim()) {
      finalAnswer = streamEventError || 'Terjadi kesalahan saat memproses pertanyaan.';
      if (!botBubble) {
        botBubble = addBotBubble();
      }
      botBubble.textContent = finalAnswer;
      if (thinkingNode.isConnected) {
        thinkingNode.remove();
      }
      speakText(finalAnswer);
    } else {
      if (thinkingNode.isConnected) {
        thinkingNode.remove();
      }
      flushSpeechRemainder();
    }
  } catch (err) {
    const hasPartialAnswer = Boolean(finalAnswer.trim());
    const fallbackMessage = 'Terjadi kesalahan saat memproses pertanyaan.';

    if (hasPartialAnswer) {
      if (thinkingNode.isConnected) {
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
    if (thinkingNode.isConnected) {
      const fallbackBubble = addBotBubble();
      fallbackBubble.textContent = fallbackMessage;
      thinkingNode.remove();
      chatBox.scrollTop = chatBox.scrollHeight;
    } else {
      renderBotMessageWordByWord(fallbackMessage);
    }
    speakText(fallbackMessage);
  } finally {
    setComposerBusy(false);
    input.focus();
  }
}

sendBtn.addEventListener('click', sendMessage);

input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

micBtn.addEventListener('click', () => {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    alert('Speech recognition belum didukung browser ini.');
    return;
  }

  const recognition = new SpeechRecognition();
  recognition.lang = 'id-ID';
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;
  recognition.start();

  recognition.onresult = (event) => {
    input.value = event.results[0][0].transcript;
  };
});
