/**
 * 코아이 챗 위젯 — coai-widget.js
 * coai.poomasi.org (주민운동 도메인 AI) 전용 플로팅 챗 위젯.
 *
 * 품아이 위젯(poomai-widget.js)과 완전 분리된 경량 버전:
 *   - 로그인/인증 없음 (공개 주민운동 RAG)
 *   - 매장 빠른동작(발주·단골·문자·태그·조합원말씀) 전부 제거 → 품앗이생협·매장 정보 노출 0
 *   - persona='coai' 고정 → 백엔드 CoaiEngine(주민운동 컬렉션) 경로만 탐
 *   - 모든 DOM id/class는 coai- 프리픽스 → 품아이 위젯과 충돌 0
 * 단일 파일, 순수 JS, 프레임워크 없음.
 */
(function () {
  'use strict';

  // ── 상수 ──
  var _apiBase = (window.location.hostname === 'seed.poomasi.org')
    ? '' : 'https://seed.poomasi.org';
  const API_CHAT = _apiBase + '/api/chat';
  const HISTORY_KEY = 'coai_history';
  const STATE_KEY = 'coai_open';
  const PERSONA = 'coai';

  // ── 상태 ──
  let history = [];
  let isOpen = sessionStorage.getItem(STATE_KEY) === 'true';
  let isLoading = false;
  let welcomeSent = false;

  // sessionStorage에서 히스토리 복원
  try {
    const saved = sessionStorage.getItem(HISTORY_KEY);
    if (saved) {
      history = JSON.parse(saved);
      if (history.length > 0) welcomeSent = true;
    }
  } catch (_) { /* 무시 */ }

  // 트레이너(교육훈련가)용 시작 질문 칩 — 현장 교육에 쓸 산출물 요청 (매장 액션 아님)
  const QUICK_PROMPTS = [
    "'주민은 누구인가' 강의안",
    '주민조직화 워크숍 설계',
    '의식화 교육 실습 아이디어',
    'CO방법론 10단계 강의안',
  ];

  // ── CSS 삽입 ──
  const STYLE = document.createElement('style');
  STYLE.textContent = `
    #coai-widget-root {
      position: fixed;
      bottom: 24px;
      right: 24px;
      z-index: 10001;
      font-family: 'Noto Sans KR', sans-serif;
      font-size: 14px;
      line-height: 1.6;
      color: #f2ead8;
    }

    /* 플로팅 버튼 */
    #coai-fab {
      width: 60px;
      height: 60px;
      border-radius: 50%;
      background: #c4803a;
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 4px 20px rgba(0,0,0,0.5);
      transition: transform 0.2s ease, background 0.2s ease;
      position: relative;
    }
    #coai-fab:hover { transform: scale(1.08); background: #d48f4a; }
    #coai-fab:active { transform: scale(0.95); }
    #coai-fab .fab-icon { font-size: 26px; line-height: 1; transition: opacity 0.15s ease; }
    #coai-fab .fab-close { font-size: 24px; color: #0f0b07; font-weight: 700; }

    /* 챗 패널 */
    #coai-panel {
      display: none;
      flex-direction: column;
      width: 380px;
      height: 520px;
      background: #0f0b07;
      border: 1px solid rgba(196, 128, 58, 0.3);
      border-radius: 12px;
      overflow: hidden;
      box-shadow: 0 8px 40px rgba(0,0,0,0.6);
      position: absolute;
      bottom: 72px;
      right: 0;
      animation: coai-slide-up 0.25s ease-out;
    }
    #coai-panel.open { display: flex; }
    @keyframes coai-slide-up {
      from { opacity: 0; transform: translateY(12px); }
      to { opacity: 1; transform: translateY(0); }
    }

    /* 헤더 */
    #coai-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 16px;
      background: #1e1510;
      border-bottom: 1px solid rgba(196, 128, 58, 0.2);
      flex-shrink: 0;
    }
    #coai-header-title {
      font-family: 'Noto Serif KR', serif;
      font-size: 16px;
      font-weight: 700;
      color: #f2ead8;
    }
    #coai-header-sub {
      font-size: 11.5px;
      color: #b8a88a;
      margin-left: 8px;
      font-weight: 400;
    }
    .coai-header-btn {
      background: none;
      border: none;
      color: #b8a88a;
      cursor: pointer;
      padding: 2px 6px;
      border-radius: 6px;
      font-size: 18px;
      font-family: 'Noto Sans KR', sans-serif;
      transition: color 0.15s ease, background 0.15s ease;
    }
    .coai-header-btn:hover { color: #f2ead8; background: rgba(196, 128, 58, 0.15); }

    /* 메시지 영역 */
    #coai-messages {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      scrollbar-width: thin;
      scrollbar-color: rgba(196,128,58,0.3) transparent;
    }
    #coai-messages::-webkit-scrollbar { width: 5px; }
    #coai-messages::-webkit-scrollbar-track { background: transparent; }
    #coai-messages::-webkit-scrollbar-thumb { background: rgba(196,128,58,0.3); border-radius: 3px; }

    /* 메시지 버블 */
    .coai-msg {
      max-width: 85%;
      padding: 10px 14px;
      border-radius: 12px;
      font-size: 13.5px;
      line-height: 1.65;
      word-break: break-word;
      white-space: pre-wrap;
    }
    .coai-msg-ai {
      align-self: flex-start;
      background: rgba(61, 92, 53, 0.25);
      border: 1px solid rgba(90, 138, 78, 0.15);
    }
    .coai-msg-user {
      align-self: flex-end;
      background: rgba(45, 31, 20, 0.6);
      border: 1px solid rgba(196, 128, 58, 0.15);
    }
    .coai-msg a {
      color: #e8a55a;
      text-decoration: underline;
      text-decoration-color: rgba(232, 165, 90, 0.4);
    }
    .coai-msg a:hover { text-decoration-color: #e8a55a; }
    .coai-msg strong { color: #f2ead8; font-weight: 600; }
    .coai-msg em { color: #b8a88a; }

    /* 참고자료 */
    .coai-refs {
      align-self: flex-start;
      max-width: 85%;
      font-size: 11.5px;
      color: #b8a88a;
      padding: 2px 4px;
      margin-top: -6px;
    }
    .coai-refs strong { color: #e8c48a; font-weight: 600; }

    /* 타이핑 인디케이터 */
    .coai-typing {
      align-self: flex-start;
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 10px 14px;
      background: rgba(61, 92, 53, 0.15);
      border-radius: 12px;
      color: #b8a88a;
      font-size: 13px;
    }
    .coai-typing-dots { display: flex; gap: 3px; }
    .coai-typing-dots span {
      width: 5px; height: 5px;
      background: #b8a88a;
      border-radius: 50%;
      animation: coai-dot 1.2s infinite;
    }
    .coai-typing-dots span:nth-child(2) { animation-delay: 0.2s; }
    .coai-typing-dots span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes coai-dot {
      0%, 60%, 100% { opacity: 0.3; transform: scale(0.8); }
      30% { opacity: 1; transform: scale(1); }
    }

    /* 에러 메시지 */
    .coai-msg-error {
      align-self: center;
      background: rgba(184, 58, 42, 0.15);
      border: 1px solid rgba(184, 58, 42, 0.3);
      color: #e8a55a;
      font-size: 12.5px;
      text-align: center;
      padding: 8px 14px;
      border-radius: 8px;
    }

    /* 빠른 질문 칩 */
    #coai-quick-btns {
      display: flex;
      gap: 6px;
      padding: 8px 16px 4px;
      background: #1e1510;
      border-top: 1px solid rgba(196, 128, 58, 0.12);
      overflow-x: auto;
      flex-shrink: 0;
      scrollbar-width: none;
      -ms-overflow-style: none;
    }
    #coai-quick-btns::-webkit-scrollbar { display: none; }
    .coai-quick-btn {
      flex-shrink: 0;
      background: rgba(196, 128, 58, 0.12);
      border: 1px solid rgba(196, 128, 58, 0.3);
      border-radius: 14px;
      color: #e8c48a;
      font-size: 12px;
      font-family: 'Noto Sans KR', sans-serif;
      padding: 4px 12px;
      cursor: pointer;
      transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
      white-space: nowrap;
      line-height: 1.6;
    }
    .coai-quick-btn:hover {
      background: rgba(196, 128, 58, 0.25);
      border-color: #c4803a;
      color: #f2ead8;
    }
    .coai-quick-btn:active { background: rgba(196, 128, 58, 0.35); }

    /* 입력 영역 */
    #coai-input-area {
      display: flex;
      align-items: flex-end;
      gap: 8px;
      padding: 12px 16px;
      background: #1e1510;
      border-top: 1px solid rgba(196, 128, 58, 0.2);
      flex-shrink: 0;
    }
    #coai-textarea {
      flex: 1;
      resize: none;
      background: #0f0b07;
      border: 1px solid rgba(196, 128, 58, 0.3);
      border-radius: 8px;
      padding: 8px 12px;
      color: #f2ead8;
      font-size: 14px;
      font-family: 'Noto Sans KR', sans-serif;
      line-height: 1.57;
      outline: none;
      overflow-y: auto;
      min-height: 38px;
      max-height: 124px;
      height: 38px;
      transition: border-color 0.15s ease;
    }
    #coai-textarea:focus { border-color: #c4803a; }
    #coai-textarea::placeholder { color: #b8a88a; opacity: 0.5; }
    #coai-send-btn {
      width: 38px;
      height: 38px;
      border-radius: 8px;
      background: #c4803a;
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
      transition: background 0.15s ease, opacity 0.15s ease;
    }
    #coai-send-btn:hover { background: #d48f4a; }
    #coai-send-btn:disabled { background: #5a4a3a; cursor: not-allowed; opacity: 0.6; }
    #coai-send-btn svg { width: 18px; height: 18px; }

    /* 모바일 전체화면 (버블 모드) */
    @media (max-width: 480px) {
      #coai-widget-root { bottom: 16px; right: 16px; }
      #coai-panel {
        position: fixed;
        top: 0; left: 0; right: 0; bottom: 0;
        width: 100vw; height: 100vh;
        border-radius: 0; border: none;
        animation: coai-fade-in 0.2s ease-out;
      }
      @keyframes coai-fade-in {
        from { opacity: 0; }
        to { opacity: 1; }
      }
    }

    /* ── 풀스크린 모드 (전용 챗 페이지용) ── */
    #coai-chat-main #coai-widget-root {
      position: static;
      width: 100%;
      height: 100%;
    }
    #coai-chat-main .coai-fullscreen-panel {
      position: relative !important;
      top: 0 !important; bottom: auto !important;
      left: auto !important; right: auto !important;
      width: 100% !important; height: 100% !important;
      min-height: 520px;
      max-width: 100% !important; max-height: none !important;
      border-radius: 8px !important;
      border: 1px solid rgba(196,128,58,0.25) !important;
      display: flex !important;
      flex-direction: column;
      opacity: 1 !important;
      transform: none !important;
      visibility: visible !important;
      pointer-events: auto !important;
      box-shadow: 0 8px 40px rgba(0,0,0,0.5) !important;
    }
    #coai-chat-main #coai-messages { flex: 1; min-height: 300px; }
  `;
  document.head.appendChild(STYLE);

  // ── fullscreen 모드 감지 ──
  const _thisScript = document.currentScript
    || document.querySelector('script[src*="coai-widget.js"]');
  const _isFullscreen = _thisScript && _thisScript.getAttribute('data-mode') === 'fullscreen';
  const _targetSelector = _thisScript && _thisScript.getAttribute('data-target');
  const _targetEl = _targetSelector ? document.querySelector(_targetSelector) : null;

  // 빠른 질문 칩 HTML
  const _quickBtnsHtml = QUICK_PROMPTS.map(function (q) {
    return '<button class="coai-quick-btn" type="button" data-q="' + q.replace(/"/g, '&quot;') + '">' + q + '</button>';
  }).join('');

  const _sendSvg = `<svg viewBox="0 0 24 24" fill="none" stroke="#0f0b07" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M22 2L11 13"/>
              <path d="M22 2L15 22L11 13L2 9L22 2Z"/>
            </svg>`;

  // ── DOM 생성 ──
  const ROOT = document.createElement('div');
  ROOT.id = 'coai-widget-root';

  if (_isFullscreen && _targetEl) {
    // 풀스크린 모드: FAB 없이 target 컨테이너에 직접 패널 마운트
    ROOT.innerHTML = `
      <div id="coai-panel" class="coai-fullscreen-panel">
        <div id="coai-header">
          <span><span id="coai-header-title">코아이</span><span id="coai-header-sub">주민운동 트레이너 AI</span></span>
        </div>
        <div id="coai-messages"></div>
        <div id="coai-quick-btns">${_quickBtnsHtml}</div>
        <div id="coai-input-area">
          <textarea id="coai-textarea" placeholder="무엇이든 물어보세요..." rows="1"></textarea>
          <button id="coai-send-btn" type="button" aria-label="전송">${_sendSvg}</button>
        </div>
      </div>
    `;
    _targetEl.appendChild(ROOT);
  } else {
    // 기본 버블 모드
    ROOT.innerHTML = `
      <button id="coai-fab" type="button" aria-label="코아이와 대화"><span class="fab-icon">&#x1F91D;</span></button>
      <div id="coai-panel">
        <div id="coai-header">
          <span><span id="coai-header-title">코아이</span><span id="coai-header-sub">주민운동 트레이너 AI</span></span>
          <button class="coai-header-btn" id="coai-close-btn" type="button" aria-label="닫기">&times;</button>
        </div>
        <div id="coai-messages"></div>
        <div id="coai-quick-btns">${_quickBtnsHtml}</div>
        <div id="coai-input-area">
          <textarea id="coai-textarea" placeholder="무엇이든 물어보세요..." rows="1"></textarea>
          <button id="coai-send-btn" type="button" aria-label="전송">${_sendSvg}</button>
        </div>
      </div>
    `;
    document.body.appendChild(ROOT);
  }

  // ── 요소 참조 ──
  const fab = document.getElementById('coai-fab');
  const panel = document.getElementById('coai-panel');
  const closeBtn = document.getElementById('coai-close-btn');
  const messagesEl = document.getElementById('coai-messages');
  const quickBtns = document.getElementById('coai-quick-btns');
  const textarea = document.getElementById('coai-textarea');
  const sendBtn = document.getElementById('coai-send-btn');

  // ── 안전한 마크다운 렌더링 ──
  function renderMarkdown(text) {
    var safe = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
    safe = safe.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    safe = safe.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '<em>$1</em>');
    safe = safe.replace(/`([^`]+)`/g, '<code style="background:rgba(196,128,58,0.15);padding:1px 5px;border-radius:3px;font-size:12.5px;">$1</code>');
    safe = safe.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
    safe = safe.replace(/\n/g, '<br>');
    return safe;
  }

  // ── 메시지 추가 ──
  function addMessage(role, text) {
    var div = document.createElement('div');
    div.className = 'coai-msg ' + (role === 'user' ? 'coai-msg-user' : 'coai-msg-ai');
    if (role === 'user') {
      div.textContent = text;
    } else {
      div.innerHTML = renderMarkdown(text);
    }
    messagesEl.appendChild(div);
    scrollToBottom();
  }

  // ── 참고자료 표시 (주민운동 출처 grounding) ──
  function addRefs(refs) {
    if (!refs || !refs.length) return;
    var titles = [];
    for (var i = 0; i < refs.length && titles.length < 3; i++) {
      var t = (refs[i] && refs[i].title) || '';
      if (t && titles.indexOf(t) === -1) titles.push(t);
    }
    if (!titles.length) return;
    var div = document.createElement('div');
    div.className = 'coai-refs';
    div.innerHTML = '<strong>참고</strong> · ' + titles.map(function (t) {
      return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }).join(' · ');
    messagesEl.appendChild(div);
    scrollToBottom();
  }

  function addErrorMessage(text) {
    var div = document.createElement('div');
    div.className = 'coai-msg-error';
    div.textContent = text;
    messagesEl.appendChild(div);
    scrollToBottom();
  }

  // ── 타이핑 인디케이터 ──
  function showTyping() {
    var div = document.createElement('div');
    div.className = 'coai-typing';
    div.id = 'coai-typing-indicator';
    div.innerHTML = '<div class="coai-typing-dots"><span></span><span></span><span></span></div> 지혜를 모으는 중...';
    messagesEl.appendChild(div);
    scrollToBottom();
  }
  function hideTyping() {
    var el = document.getElementById('coai-typing-indicator');
    if (el) el.remove();
  }

  // ── 스크롤 ──
  function scrollToBottom() {
    requestAnimationFrame(function () {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    });
  }

  // ── 히스토리 ──
  function saveHistory() {
    try { sessionStorage.setItem(HISTORY_KEY, JSON.stringify(history)); } catch (_) {}
  }
  function restoreMessages() {
    messagesEl.innerHTML = '';
    for (var i = 0; i < history.length; i++) {
      addMessage(history[i].role, history[i].content);
    }
  }

  // ── textarea 높이 조절 ──
  function adjustTextareaHeight() {
    textarea.style.height = 'auto';
    var h = Math.min(textarea.scrollHeight, 124);
    textarea.style.height = Math.max(h, 38) + 'px';
  }

  // ── API: 채팅 (persona=coai 고정, 매장/품앗이 경로 미접촉) ──
  async function sendChat(query) {
    if (isLoading || !query.trim()) return;
    isLoading = true;
    sendBtn.disabled = true;

    addMessage('user', query);
    history.push({ role: 'user', content: query });
    saveHistory();
    showTyping();

    try {
      var response = await fetch(API_CHAT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: query,
          history: history.slice(0, -1),
          persona: PERSONA
        })
      });
      hideTyping();

      if (!response.ok) {
        var errData;
        try { errData = await response.json(); } catch (_) { errData = {}; }
        addErrorMessage(errData.error || '요청 처리 중 문제가 발생했습니다.');
        history.pop();
        saveHistory();
        return;
      }

      var data = await response.json();
      var answer = data.answer || '응답을 받지 못했습니다.';
      addMessage('assistant', answer);
      addRefs(data.refs);
      history.push({ role: 'assistant', content: answer });
      saveHistory();
    } catch (err) {
      hideTyping();
      addErrorMessage('연결이 불안정합니다. 다시 시도해주세요.');
      history.pop();
      saveHistory();
    } finally {
      isLoading = false;
      sendBtn.disabled = false;
      textarea.focus();
    }
  }

  // ── 패널 열기/닫기 ──
  function openPanel() {
    isOpen = true;
    panel.classList.add('open');
    if (fab) fab.innerHTML = '<span class="fab-icon fab-close">&times;</span>';
    sessionStorage.setItem(STATE_KEY, 'true');

    if (history.length > 0) restoreMessages();
    if (!welcomeSent) {
      welcomeSent = true;
      addMessage('assistant', '안녕하세요. 주민운동교육원 트레이너를 위한 AI, 코아이입니다.\n강의안·워크숍 설계 등 현장 교육에 쓸 무엇이든 함께 만들어요.');
    }
    textarea.focus();
    scrollToBottom();
  }

  function closePanel() {
    isOpen = false;
    panel.classList.remove('open');
    if (fab) fab.innerHTML = '<span class="fab-icon">&#x1F91D;</span>';
    sessionStorage.setItem(STATE_KEY, 'false');
  }

  // 코아이 랜딩의 [data-chat] CTA가 위젯을 직접 열도록 전역 노출
  window.__coaiWidgetOpen = openPanel;

  // ── 이벤트 바인딩 ──
  if (quickBtns) {
    quickBtns.addEventListener('click', function (e) {
      var btn = e.target.closest('.coai-quick-btn');
      if (!btn) return;
      var q = btn.getAttribute('data-q');
      if (!q || isLoading) return;
      if (!isOpen) openPanel();
      sendChat(q);
    });
  }

  if (fab) {
    fab.addEventListener('click', function (e) {
      e.stopPropagation();
      e.preventDefault();
      if (isOpen) closePanel(); else openPanel();
    });
  }
  if (closeBtn) {
    closeBtn.addEventListener('click', function () { closePanel(); });
  }

  sendBtn.addEventListener('click', function () {
    var text = textarea.value.trim();
    if (text) {
      textarea.value = '';
      adjustTextareaHeight();
      sendChat(text);
    }
  });

  textarea.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      var text = textarea.value.trim();
      if (text && !isLoading) {
        textarea.value = '';
        adjustTextareaHeight();
        sendChat(text);
      }
    }
  });
  textarea.addEventListener('input', function () { adjustTextareaHeight(); });

  // ── 초기 상태 복원 ──
  if (_isFullscreen && _targetEl) {
    openPanel();
  } else if (isOpen) {
    openPanel();
  }
})();
