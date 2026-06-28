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
  const API_LOGIN = _apiBase + '/api/auth/login';
  const API_ME = _apiBase + '/api/coai/me';
  const API_FEEDBACK = _apiBase + '/api/coai/feedback';
  const HISTORY_KEY = 'coai_history';
  const STATE_KEY = 'coai_open';
  const TOKEN_KEY = 'coai_trainer_token';
  const PERSONA = 'coai';

  // ── 상태 ──
  let history = [];
  let isOpen = sessionStorage.getItem(STATE_KEY) === 'true';
  let isLoading = false;
  let welcomeSent = false;
  // 트레이너 환류: 로그인한 트레이너만 코멘트 가능
  let trainer = { token: localStorage.getItem(TOKEN_KEY) || null, name: null, isTrainer: false };

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

    /* ── 트레이너 환류 UI ── */
    #coai-trainer-badge {
      background: rgba(255,255,255,0.15); color: #fff; border: 1px solid rgba(255,255,255,0.3);
      border-radius: 12px; padding: 3px 10px; font-size: 11px; cursor: pointer;
      margin-left: auto; margin-right: 8px; white-space: nowrap;
    }
    #coai-trainer-badge.on { background: rgba(80,200,120,0.35); border-color: rgba(80,200,120,0.6); }
    .coai-login-form {
      background: #f6f7f9; border: 1px solid #dfe3e8; border-radius: 10px;
      padding: 12px; margin: 8px; display: flex; flex-direction: column; gap: 8px;
    }
    .coai-login-title { font-weight: 700; font-size: 13px; color: #333; }
    .coai-login-form input {
      border: 1px solid #cfd4da; border-radius: 8px; padding: 8px 10px; font-size: 13px; width: 100%; box-sizing: border-box;
    }
    .coai-login-row { display: flex; gap: 8px; }
    .coai-login-go, .coai-login-cancel {
      flex: 1; border: none; border-radius: 8px; padding: 8px; font-size: 13px; cursor: pointer;
    }
    .coai-login-go { background: #2f7d4f; color: #fff; }
    .coai-login-cancel { background: #e3e6ea; color: #333; }
    .coai-login-msg { font-size: 12px; color: #666; }
    .coai-login-msg.bad { color: #c0392b; }
    .coai-comment-bar { margin: 2px 8px 10px; }
    .coai-comment-open {
      background: none; border: 1px dashed #b9c0c8; color: #6b7480; border-radius: 8px;
      padding: 4px 10px; font-size: 12px; cursor: pointer;
    }
    .coai-comment-form {
      background: #f6f7f9; border: 1px solid #dfe3e8; border-radius: 10px; padding: 10px;
      display: flex; flex-direction: column; gap: 8px; margin-top: 6px;
    }
    .coai-tag-row { display: flex; gap: 10px; flex-wrap: wrap; }
    .coai-tag { font-size: 12px; color: #444; cursor: pointer; }
    .coai-ideal {
      border: 1px solid #cfd4da; border-radius: 8px; padding: 8px; font-size: 13px;
      min-height: 64px; resize: vertical; width: 100%; box-sizing: border-box; font-family: inherit;
    }
    .coai-comment-row { display: flex; gap: 8px; align-items: center; }
    .coai-comment-send { background: #2f7d4f; color: #fff; border: none; border-radius: 8px; padding: 7px 14px; font-size: 13px; cursor: pointer; }
    .coai-comment-cancel { background: #e3e6ea; color: #333; border: none; border-radius: 8px; padding: 7px 12px; font-size: 13px; cursor: pointer; }
    .coai-comment-msg { font-size: 12px; color: #666; }
    .coai-comment-msg.bad { color: #c0392b; }
    .coai-comment-done { font-size: 12px; color: #2f7d4f; font-weight: 600; }
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
    return div;
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
      var aiDiv = addMessage('assistant', answer);
      addRefs(data.refs);
      history.push({ role: 'assistant', content: answer });
      saveHistory();
      if (trainer.isTrainer && aiDiv) {
        attachCommentUI(aiDiv, query, answer, data.refs || []);
      }
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

  // ── 트레이너 인증 ──
  async function checkTrainer() {
    if (!trainer.token) {
      trainer.isTrainer = false; trainer.name = null; updateTrainerBadge(); return;
    }
    try {
      var r = await fetch(API_ME, { headers: { 'Authorization': 'Bearer ' + trainer.token } });
      if (r.ok) {
        var d = await r.json();
        trainer.isTrainer = !!d.is_trainer;
        trainer.name = d.name || null;
      } else {
        trainer.isTrainer = false;
      }
    } catch (_) {
      trainer.isTrainer = false;
    }
    updateTrainerBadge();
  }

  async function doLogin(email, password, msgEl) {
    if (!email || !password) {
      if (msgEl) { msgEl.textContent = '이메일과 비밀번호를 입력하세요.'; msgEl.className = 'coai-login-msg bad'; }
      return;
    }
    if (msgEl) { msgEl.textContent = '로그인 중...'; msgEl.className = 'coai-login-msg'; }
    try {
      var r = await fetch(API_LOGIN, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email, password: password })
      });
      var d = await r.json();
      if (!r.ok || !d.access_token) throw new Error(d.error || '로그인 실패');
      trainer.token = d.access_token;
      localStorage.setItem(TOKEN_KEY, trainer.token);
      await checkTrainer();
      if (!trainer.isTrainer) {
        if (msgEl) { msgEl.textContent = '로그인됐지만 트레이너 권한이 없습니다.'; msgEl.className = 'coai-login-msg bad'; }
        return;
      }
      hideLoginForm();
    } catch (e) {
      if (msgEl) { msgEl.textContent = '실패: ' + e.message; msgEl.className = 'coai-login-msg bad'; }
    }
  }

  function doLogout() {
    trainer = { token: null, name: null, isTrainer: false };
    localStorage.removeItem(TOKEN_KEY);
    updateTrainerBadge();
  }

  function updateTrainerBadge() {
    var hdr = document.getElementById('coai-header');
    if (!hdr) return;
    var badge = document.getElementById('coai-trainer-badge');
    if (!badge) {
      badge = document.createElement('button');
      badge.id = 'coai-trainer-badge';
      badge.type = 'button';
      badge.className = 'coai-trainer-badge';
      var closeB = document.getElementById('coai-close-btn');
      if (closeB) hdr.insertBefore(badge, closeB); else hdr.appendChild(badge);
      badge.addEventListener('click', function () {
        if (trainer.isTrainer) {
          if (confirm('트레이너 로그아웃할까요?')) doLogout();
        } else {
          toggleLoginForm();
        }
      });
    }
    badge.textContent = trainer.isTrainer ? ('✓ ' + (trainer.name || '트레이너')) : '🔑 트레이너';
    badge.classList.toggle('on', trainer.isTrainer);
  }

  function toggleLoginForm() {
    if (document.getElementById('coai-login-form')) { hideLoginForm(); return; }
    showLoginForm();
  }
  function hideLoginForm() {
    var f = document.getElementById('coai-login-form');
    if (f) f.remove();
  }
  function showLoginForm() {
    var f = document.createElement('div');
    f.id = 'coai-login-form';
    f.className = 'coai-login-form';
    f.innerHTML =
      '<div class="coai-login-title">트레이너 로그인</div>' +
      '<input type="email" class="coai-login-email" placeholder="이메일" autocomplete="username">' +
      '<input type="password" class="coai-login-pw" placeholder="비밀번호" autocomplete="current-password">' +
      '<div class="coai-login-row">' +
      '<button type="button" class="coai-login-go">로그인</button>' +
      '<button type="button" class="coai-login-cancel">취소</button></div>' +
      '<div class="coai-login-msg"></div>';
    messagesEl.parentNode.insertBefore(f, messagesEl);
    var msg = f.querySelector('.coai-login-msg');
    f.querySelector('.coai-login-go').addEventListener('click', function () {
      doLogin(f.querySelector('.coai-login-email').value.trim(),
              f.querySelector('.coai-login-pw').value, msg);
    });
    f.querySelector('.coai-login-cancel').addEventListener('click', hideLoginForm);
  }

  // ── 트레이너 코멘트(환류) ──
  var COMMENT_TAGS = ['오류', '부족', '톤·위험'];

  function attachCommentUI(aiDiv, question, aiAnswer, refs) {
    var bar = document.createElement('div');
    bar.className = 'coai-comment-bar';
    var openBtn = document.createElement('button');
    openBtn.type = 'button';
    openBtn.className = 'coai-comment-open';
    openBtn.textContent = '✏️ 코멘트';
    bar.appendChild(openBtn);
    messagesEl.appendChild(bar);
    openBtn.addEventListener('click', function () {
      if (bar.querySelector('.coai-comment-form')) return;
      openBtn.style.display = 'none';
      bar.appendChild(buildCommentForm(openBtn, question, aiAnswer, refs));
      scrollToBottom();
    });
    scrollToBottom();
  }

  function buildCommentForm(openBtn, question, aiAnswer, refs) {
    var form = document.createElement('div');
    form.className = 'coai-comment-form';
    var tagsHtml = COMMENT_TAGS.map(function (t) {
      return '<label class="coai-tag"><input type="checkbox" value="' + t + '"> ' + t + '</label>';
    }).join('');
    form.innerHTML =
      '<div class="coai-tag-row">' + tagsHtml + '</div>' +
      '<textarea class="coai-ideal" placeholder="이렇게 답했어야 합니다 (모범답안 — 권장)"></textarea>' +
      '<div class="coai-comment-row">' +
      '<button type="button" class="coai-comment-send">검토 요청</button>' +
      '<button type="button" class="coai-comment-cancel">취소</button>' +
      '<span class="coai-comment-msg"></span></div>';
    var sendB = form.querySelector('.coai-comment-send');
    var msg = form.querySelector('.coai-comment-msg');
    form.querySelector('.coai-comment-cancel').addEventListener('click', function () {
      form.remove(); openBtn.style.display = '';
    });
    sendB.addEventListener('click', function () {
      var tags = Array.prototype.slice
        .call(form.querySelectorAll('.coai-tag input:checked'))
        .map(function (c) { return c.value; });
      var ideal = form.querySelector('.coai-ideal').value.trim();
      if (!tags.length && !ideal) {
        msg.textContent = '태그나 모범답안 중 하나는 입력하세요.'; msg.className = 'coai-comment-msg bad'; return;
      }
      sendB.disabled = true; msg.textContent = '전송 중...'; msg.className = 'coai-comment-msg';
      submitFeedback(question, aiAnswer, refs, tags, ideal).then(function () {
        form.innerHTML = '<div class="coai-comment-done">검토 대기 등록됨 — 고맙습니다.</div>';
      }).catch(function (e) {
        msg.textContent = '실패: ' + e.message; msg.className = 'coai-comment-msg bad'; sendB.disabled = false;
      });
    });
    return form;
  }

  async function submitFeedback(question, aiAnswer, refs, tags, ideal) {
    var r = await fetch(API_FEEDBACK, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + (trainer.token || '')
      },
      body: JSON.stringify({
        question: question, ai_answer: aiAnswer, refs: refs, tags: tags, ideal_answer: ideal
      })
    });
    var d = {};
    try { d = await r.json(); } catch (_) {}
    if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
    return d;
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

  // ── 트레이너 배지/인증 초기화 (토큰 있으면 검증) ──
  updateTrainerBadge();
  checkTrainer();
})();
