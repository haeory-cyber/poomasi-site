/**
 * 품아이 챗 위젯 — poomai-widget.js
 * seed.poomasi.org 전 페이지에 삽입하는 플로팅 챗 위젯
 * 단일 파일, 순수 JS, 프레임워크 없음
 */
(function () {
  'use strict';

  // ── 상수 ──
  // 같은 도메인이면 상대경로, 다른 도메인이면 절대경로
  var _apiBase = (window.location.hostname === 'seed.poomasi.org')
    ? '' : 'https://seed.poomasi.org';
  const API_CHAT = _apiBase + '/api/chat';
  const API_LOGIN = _apiBase + '/api/auth/login';
  const TOKEN_KEY = 'poomai_token';
  const EMAIL_KEY = 'poomai_email';
  const HISTORY_KEY = 'poomai_history';
  const STATE_KEY = 'poomai_open';

  // ── 상태 ──
  let token = localStorage.getItem(TOKEN_KEY) || '';
  let userEmail = localStorage.getItem(EMAIL_KEY) || '';
  let history = [];
  let isOpen = sessionStorage.getItem(STATE_KEY) === 'true';
  let isLoading = false;
  let showLoginForm = false;
  let pretextReady = false;
  let pretextPrepare = null;
  let pretextLayout = null;
  let welcomeSent = false;

  // sessionStorage에서 히스토리 복원
  try {
    const saved = sessionStorage.getItem(HISTORY_KEY);
    if (saved) {
      history = JSON.parse(saved);
      if (history.length > 0) welcomeSent = true;
    }
  } catch (_) { /* 무시 */ }

  // ── pretext 동적 로드 (fallback 대비) ──
  (async function loadPretext() {
    try {
      const mod = await import('https://esm.sh/@chenglou/pretext');
      pretextPrepare = mod.prepare;
      pretextLayout = mod.layout;
      pretextReady = true;
    } catch (_) {
      // CDN 장애 시 fallback 사용
      pretextReady = false;
    }
  })();

  // ── CSS 삽입 ──
  const STYLE = document.createElement('style');
  STYLE.textContent = `
    /* 품아이 위젯 전체 */
    #poomai-widget-root {
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
    #poomai-fab {
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
    #poomai-fab:hover {
      transform: scale(1.08);
      background: #d48f4a;
    }
    #poomai-fab:active {
      transform: scale(0.95);
    }
    #poomai-fab .fab-icon {
      font-size: 28px;
      line-height: 1;
      transition: opacity 0.15s ease;
    }
    #poomai-fab .fab-close {
      font-size: 24px;
      color: #0f0b07;
      font-weight: 700;
    }

    /* 챗 패널 */
    #poomai-panel {
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
      animation: poomai-slide-up 0.25s ease-out;
    }
    #poomai-panel.open {
      display: flex;
    }

    @keyframes poomai-slide-up {
      from { opacity: 0; transform: translateY(12px); }
      to { opacity: 1; transform: translateY(0); }
    }

    /* 헤더 */
    #poomai-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 16px;
      background: #1e1510;
      border-bottom: 1px solid rgba(196, 128, 58, 0.2);
      flex-shrink: 0;
    }
    #poomai-header-title {
      font-family: 'Noto Serif KR', serif;
      font-size: 16px;
      font-weight: 700;
      color: #f2ead8;
    }
    #poomai-header-actions {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .poomai-header-btn {
      background: none;
      border: none;
      color: #b8a88a;
      cursor: pointer;
      padding: 4px 8px;
      border-radius: 6px;
      font-size: 13px;
      font-family: 'Noto Sans KR', sans-serif;
      transition: color 0.15s ease, background 0.15s ease;
    }
    .poomai-header-btn:hover {
      color: #f2ead8;
      background: rgba(196, 128, 58, 0.15);
    }
    #poomai-close-btn {
      font-size: 18px;
      padding: 2px 6px;
    }

    /* 로그인 폼 */
    #poomai-login-form {
      display: none;
      flex-direction: column;
      gap: 8px;
      padding: 12px 16px;
      background: #1e1510;
      border-bottom: 1px solid rgba(196, 128, 58, 0.2);
      flex-shrink: 0;
    }
    #poomai-login-form.show {
      display: flex;
    }
    #poomai-login-form input {
      background: #0f0b07;
      border: 1px solid rgba(196, 128, 58, 0.3);
      border-radius: 6px;
      padding: 8px 12px;
      color: #f2ead8;
      font-size: 13px;
      font-family: 'Noto Sans KR', sans-serif;
      outline: none;
      transition: border-color 0.15s ease;
    }
    #poomai-login-form input:focus {
      border-color: #c4803a;
    }
    #poomai-login-form input::placeholder {
      color: #b8a88a;
      opacity: 0.6;
    }
    #poomai-login-submit {
      background: #c4803a;
      color: #0f0b07;
      border: none;
      border-radius: 6px;
      padding: 8px;
      font-size: 13px;
      font-weight: 500;
      font-family: 'Noto Sans KR', sans-serif;
      cursor: pointer;
      transition: background 0.15s ease;
    }
    #poomai-login-submit:hover {
      background: #d48f4a;
    }
    #poomai-login-submit:disabled {
      background: #5a4a3a;
      cursor: not-allowed;
    }
    #poomai-login-error {
      color: #b83a2a;
      font-size: 12px;
      display: none;
    }

    /* 메시지 영역 */
    #poomai-messages {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      scrollbar-width: thin;
      scrollbar-color: rgba(196,128,58,0.3) transparent;
    }
    #poomai-messages::-webkit-scrollbar {
      width: 5px;
    }
    #poomai-messages::-webkit-scrollbar-track {
      background: transparent;
    }
    #poomai-messages::-webkit-scrollbar-thumb {
      background: rgba(196,128,58,0.3);
      border-radius: 3px;
    }

    /* 메시지 버블 */
    .poomai-msg {
      max-width: 85%;
      padding: 10px 14px;
      border-radius: 12px;
      font-size: 13.5px;
      line-height: 1.65;
      word-break: break-word;
      white-space: pre-wrap;
    }
    .poomai-msg-ai {
      align-self: flex-start;
      background: rgba(61, 92, 53, 0.25);
      border: 1px solid rgba(90, 138, 78, 0.15);
    }
    .poomai-msg-user {
      align-self: flex-end;
      background: rgba(45, 31, 20, 0.6);
      border: 1px solid rgba(196, 128, 58, 0.15);
    }
    .poomai-msg a {
      color: #e8a55a;
      text-decoration: underline;
      text-decoration-color: rgba(232, 165, 90, 0.4);
    }
    .poomai-msg a:hover {
      text-decoration-color: #e8a55a;
    }
    .poomai-msg strong {
      color: #f2ead8;
      font-weight: 600;
    }
    .poomai-msg em {
      color: #b8a88a;
    }

    /* 타이핑 인디케이터 */
    .poomai-typing {
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
    .poomai-typing-dots {
      display: flex;
      gap: 3px;
    }
    .poomai-typing-dots span {
      width: 5px;
      height: 5px;
      background: #b8a88a;
      border-radius: 50%;
      animation: poomai-dot 1.2s infinite;
    }
    .poomai-typing-dots span:nth-child(2) { animation-delay: 0.2s; }
    .poomai-typing-dots span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes poomai-dot {
      0%, 60%, 100% { opacity: 0.3; transform: scale(0.8); }
      30% { opacity: 1; transform: scale(1); }
    }

    /* 에러 메시지 */
    .poomai-msg-error {
      align-self: center;
      background: rgba(184, 58, 42, 0.15);
      border: 1px solid rgba(184, 58, 42, 0.3);
      color: #e8a55a;
      font-size: 12.5px;
      text-align: center;
      padding: 8px 14px;
      border-radius: 8px;
    }

    /* 인증 필요 안내 */
    .poomai-msg-auth {
      align-self: center;
      background: rgba(196, 128, 58, 0.1);
      border: 1px solid rgba(196, 128, 58, 0.25);
      color: #e8a55a;
      font-size: 12.5px;
      text-align: center;
      padding: 8px 14px;
      border-radius: 8px;
      cursor: pointer;
    }
    .poomai-msg-auth:hover {
      background: rgba(196, 128, 58, 0.18);
    }

    /* 입력 영역 */
    #poomai-input-area {
      display: flex;
      align-items: flex-end;
      gap: 8px;
      padding: 12px 16px;
      background: #1e1510;
      border-top: 1px solid rgba(196, 128, 58, 0.2);
      flex-shrink: 0;
    }
    #poomai-textarea {
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
    #poomai-textarea:focus {
      border-color: #c4803a;
    }
    #poomai-textarea::placeholder {
      color: #b8a88a;
      opacity: 0.5;
    }
    #poomai-send-btn {
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
    #poomai-send-btn:hover {
      background: #d48f4a;
    }
    #poomai-send-btn:disabled {
      background: #5a4a3a;
      cursor: not-allowed;
      opacity: 0.6;
    }
    #poomai-send-btn svg {
      width: 18px;
      height: 18px;
    }

    /* 모바일 전체화면 */
    @media (max-width: 480px) {
      #poomai-widget-root {
        bottom: 16px;
        right: 16px;
      }
      #poomai-panel {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        width: 100vw;
        height: 100vh;
        border-radius: 0;
        border: none;
        animation: poomai-fade-in 0.2s ease-out;
      }
      @keyframes poomai-fade-in {
        from { opacity: 0; }
        to { opacity: 1; }
      }
    }
  `;
  document.head.appendChild(STYLE);

  // ── DOM 생성 ──
  const ROOT = document.createElement('div');
  ROOT.id = 'poomai-widget-root';

  ROOT.innerHTML = `
    <div id="poomai-panel">
      <div id="poomai-header">
        <span id="poomai-header-title">품아이</span>
        <div id="poomai-header-actions">
          <button class="poomai-header-btn" id="poomai-auth-btn" type="button"></button>
          <button class="poomai-header-btn" id="poomai-close-btn" type="button" aria-label="닫기">&times;</button>
        </div>
      </div>
      <div id="poomai-login-form">
        <input type="email" id="poomai-login-email" placeholder="이메일" autocomplete="email">
        <input type="password" id="poomai-login-pw" placeholder="비밀번호" autocomplete="current-password">
        <div id="poomai-login-error"></div>
        <button type="button" id="poomai-login-submit">로그인</button>
      </div>
      <div id="poomai-messages"></div>
      <div id="poomai-input-area">
        <textarea id="poomai-textarea" placeholder="무엇이든 물어보세요..." rows="1"></textarea>
        <button id="poomai-send-btn" type="button" aria-label="전송">
          <svg viewBox="0 0 24 24" fill="none" stroke="#0f0b07" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M22 2L11 13"/>
            <path d="M22 2L15 22L11 13L2 9L22 2Z"/>
          </svg>
        </button>
      </div>
    </div>
    <button id="poomai-fab" type="button" aria-label="품아이 채팅">
      <span class="fab-icon">&#x1F33E;</span>
    </button>
  `;

  document.body.appendChild(ROOT);

  // ── 요소 참조 ──
  const fab = document.getElementById('poomai-fab');
  const panel = document.getElementById('poomai-panel');
  const closeBtn = document.getElementById('poomai-close-btn');
  const authBtn = document.getElementById('poomai-auth-btn');
  const loginForm = document.getElementById('poomai-login-form');
  const loginEmail = document.getElementById('poomai-login-email');
  const loginPw = document.getElementById('poomai-login-pw');
  const loginSubmit = document.getElementById('poomai-login-submit');
  const loginError = document.getElementById('poomai-login-error');
  const messagesEl = document.getElementById('poomai-messages');
  const textarea = document.getElementById('poomai-textarea');
  const sendBtn = document.getElementById('poomai-send-btn');

  // ── 인증 UI 갱신 ──
  function updateAuthUI() {
    if (token && userEmail) {
      authBtn.textContent = userEmail.split('@')[0];
      authBtn.title = '로그아웃: ' + userEmail;
    } else {
      authBtn.textContent = '로그인';
      authBtn.title = '로그인';
    }
  }
  updateAuthUI();

  // ── 페이지 맥락 환영 메시지 ──
  function getWelcomeMessage() {
    var path = window.location.pathname;
    if (path.indexOf('/store') !== -1) return '발주나 재고 관련 궁금한 거 있으세요?';
    if (path.indexOf('/work') !== -1) return '오늘의 경영 현황이 궁금하신가요?';
    return '안녕하세요! 무엇이 궁금하신가요?';
  }

  // ── 안전한 마크다운 렌더링 ──
  function renderMarkdown(text) {
    // XSS 방지: HTML 엔티티 이스케이프 먼저
    var safe = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');

    // 볼드: **text**
    safe = safe.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // 이탤릭: *text* (볼드가 아닌 단일 * 만)
    safe = safe.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '<em>$1</em>');
    // 인라인 코드: `code`
    safe = safe.replace(/`([^`]+)`/g, '<code style="background:rgba(196,128,58,0.15);padding:1px 5px;border-radius:3px;font-size:12.5px;">$1</code>');
    // URL → 링크 (http/https)
    safe = safe.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
    // 줄바꿈
    safe = safe.replace(/\n/g, '<br>');

    return safe;
  }

  // ── 메시지 추가 ──
  function addMessage(role, text) {
    var div = document.createElement('div');
    div.className = 'poomai-msg ' + (role === 'user' ? 'poomai-msg-user' : 'poomai-msg-ai');

    if (role === 'user') {
      div.textContent = text;
    } else {
      div.innerHTML = renderMarkdown(text);
    }

    messagesEl.appendChild(div);
    scrollToBottom();
  }

  function addErrorMessage(text) {
    var div = document.createElement('div');
    div.className = 'poomai-msg-error';
    div.textContent = text;
    messagesEl.appendChild(div);
    scrollToBottom();
  }

  function addAuthMessage() {
    var div = document.createElement('div');
    div.className = 'poomai-msg-auth';
    div.textContent = '로그인이 필요합니다. 여기를 눌러 로그인하세요.';
    div.addEventListener('click', function () {
      toggleLoginForm(true);
    });
    messagesEl.appendChild(div);
    scrollToBottom();
  }

  // ── 타이핑 인디케이터 ──
  function showTyping() {
    var div = document.createElement('div');
    div.className = 'poomai-typing';
    div.id = 'poomai-typing-indicator';
    div.innerHTML = '<div class="poomai-typing-dots"><span></span><span></span><span></span></div> 지혜를 모으는 중...';
    messagesEl.appendChild(div);
    scrollToBottom();
  }

  function hideTyping() {
    var el = document.getElementById('poomai-typing-indicator');
    if (el) el.remove();
  }

  // ── 스크롤 ──
  function scrollToBottom() {
    requestAnimationFrame(function () {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    });
  }

  // ── 히스토리 저장 ──
  function saveHistory() {
    try {
      sessionStorage.setItem(HISTORY_KEY, JSON.stringify(history));
    } catch (_) { /* 용량 초과 무시 */ }
  }

  // ── 히스토리에서 메시지 복원 ──
  function restoreMessages() {
    messagesEl.innerHTML = '';
    for (var i = 0; i < history.length; i++) {
      addMessage(history[i].role, history[i].content);
    }
  }

  // ── textarea 높이 조절 ──
  function adjustTextareaHeight() {
    var el = textarea;
    var text = el.value;
    var lineH = 22;
    var minH = 38;
    var maxH = 124; // ~5줄

    if (pretextReady && pretextPrepare && pretextLayout) {
      try {
        var prepared = pretextPrepare(text || ' ', '14px "Noto Sans KR"');
        var result = pretextLayout(prepared, el.clientWidth - 24, lineH);
        var h = Math.min(Math.max(result.height + 16, minH), maxH);
        el.style.height = h + 'px';
        return;
      } catch (_) {
        // fallback
      }
    }

    // fallback: scrollHeight
    el.style.height = minH + 'px';
    var scrollH = el.scrollHeight;
    el.style.height = Math.min(Math.max(scrollH, minH), maxH) + 'px';
  }

  // ── SMS 액션 (engine 안 거치고 위젯이 store.html sendSms 직접 호출) ──
  // 보고체→평서체 (engine.py _normalize_reported_speech 17개 규칙 1:1 포팅)
  function normalizeReportedSpeech(text) {
    var rules = [
      [/되었다고$/,'됐어요'], [/되었었다고$/,'됐었어요'], [/됐다고$/,'됐어요'],
      [/했다고$/,'했어요'], [/왔다고$/,'왔어요'], [/갔다고$/,'갔어요'],
      [/였다고$/,'였어요'], [/었다고$/,'었어요'], [/았다고$/,'았어요'],
      [/있다고$/,'있어요'], [/없다고$/,'없어요'], [/한다고$/,'해요'],
      [/온다고$/,'와요'], [/간다고$/,'가요'], [/된다고$/,'돼요'],
      [/(\S)이라고$/,'$1이에요'], [/(\S)라고$/,'$1예요'],
      [/다고$/,'다'],
    ];
    for (var i = 0; i < rules.length; i++) {
      var nt = text.replace(rules[i][0], rules[i][1]);
      if (nt !== text) return nt;
    }
    return text;
  }

  // 메시지 본문 추출 (engine.py _extract_msg_text 포팅)
  function extractSmsBody(query) {
    var qm = query.match(/["'](.*?)["']/);
    if (qm) return qm[1].trim();
    var bm = query.match(/(?:에게|한테|께)\s*(.+?)(?:\s*(?:문자보내|문자 보내|알려줘|알려 줘|전달해|전달 해|문자주세요|문자 주세요|문자))/);
    if (bm) return normalizeReportedSpeech(bm[1].trim());
    return query.trim();
  }

  // SMS intent 매칭 (engine.py _detect_sms_intent 포팅)
  // 반환: null | {mode:'name'|'producer'|'item', value, message}
  function detectSmsIntent(query) {
    var SMS_KW = ['문자','문자보내','문자 보내','sms','SMS','알림보내','알림 보내','문자메시지'];
    var ql = query.toLowerCase();
    var hasSms = SMS_KW.some(function(k){ return ql.indexOf(k.toLowerCase()) !== -1; });
    var hasNotify = (query.indexOf('알려줘') !== -1 || query.indexOf('알려 줘') !== -1 || query.indexOf('알림') !== -1);
    if (!hasSms && !hasNotify) return null;

    var groupMarkers = ['단골조합원','단골고객','단골들','단골 분','단골님','단골에게','단골한테','고객들','고객한테'];
    var isGroup = groupMarkers.some(function(m){ return query.indexOf(m) !== -1; });

    // 개별 발송: 이름 + 조합원/씨/님 (그룹 표지 없을 때)
    if (!isGroup) {
      var im = query.match(/([가-힣]{2,4})\s*(?:조합원|씨|님)(?!들)/);
      if (im && im[1] !== '단골' && im[1] !== '고객') {
        return { mode: 'name', value: im[1], message: extractSmsBody(query) };
      }
    }

    // 그룹 발송
    var groupKw = ['단골','고객','자주 사','자주사','사람들','들한테'];
    var hasGroupKw = groupKw.some(function(k){ return query.indexOf(k) !== -1; });
    if (isGroup || hasGroupKw) {
      // producer 우선
      var pm = query.match(/([가-힣]{2,4})\s*(?:생산자|농부|농가|농민)/);
      if (pm) return { mode: 'producer', value: pm[1], message: extractSmsBody(query) };
      // item
      var stop = ['단골','고객','문자','보내','알려','조합원','사람들','오늘','입고','됐다','됐어','왔어','알림','메시지','생산자','농부','농가','농민'];
      var words = query.match(/[가-힣]{2,6}/g) || [];
      var item = null;
      for (var w = 0; w < words.length; w++) {
        if (stop.indexOf(words[w]) === -1 && words[w].length >= 2) { item = words[w]; break; }
      }
      return { mode: 'item', value: item, message: extractSmsBody(query) };
    }
    return null;
  }

  // SMS 액션 상태 (동명이인 후보 보관용)
  var smsState = {
    pendingCandidates: null,  // [{member_id, member_name, phone_masked}]
    pendingMessage: null,
    sessionCounter: 0,
  };

  // hidden iframe으로 store.html 호출 → postMessage 결과 수신
  function fireSmsIframe(urlParams, sessionId) {
    return new Promise(function(resolve) {
      var iframe = document.createElement('iframe');
      iframe.style.display = 'none';
      iframe.src = '/seed/store.html?' + urlParams.toString();

      var done = false;
      var timer = setTimeout(function() {
        if (done) return;
        done = true;
        cleanup();
        resolve({ type: 'poomai-sms-result', ok: false, error: 'timeout' });
      }, 25000);

      function onMsg(ev) {
        if (!ev.data || ev.data.source !== 'poomai-store') return;
        if (ev.data.session_id !== sessionId) return;
        if (done) return;
        done = true;
        clearTimeout(timer);
        cleanup();
        resolve(ev.data);
      }
      function cleanup() {
        window.removeEventListener('message', onMsg);
        try { iframe.remove(); } catch(_) {}
      }
      window.addEventListener('message', onMsg);
      document.body.appendChild(iframe);
    });
  }

  // SMS intent 처리 (engine 우회)
  async function handleSmsIntent(intent) {
    var sessionId = 'sms-' + (++smsState.sessionCounter) + '-' + Date.now();
    var params = new URLSearchParams();
    params.set('sms_text', intent.message);
    params.set('auto_send', '1');
    params.set('session_id', sessionId);
    if (intent.mode === 'name') params.set('name', intent.value);
    else if (intent.mode === 'producer') params.set('producer', intent.value);
    else if (intent.mode === 'item') params.set('item', intent.value);

    showTyping();
    var result = await fireSmsIframe(params, sessionId);
    hideTyping();

    if (result.type === 'poomai-sms-ambiguous') {
      smsState.pendingCandidates = result.candidates;
      smsState.pendingMessage = intent.message;
      var lines = result.candidates.map(function(c, i) {
        return (i+1) + '. ' + c.member_name + ' — ' + c.phone_masked;
      }).join('\n');
      var msg = result.name + ' 님이 ' + result.candidates.length + '명 있어요:\n' + lines + '\n몇 번으로 보낼까요?';
      addMessage('assistant', msg);
      history.push({ role: 'assistant', content: msg });
      saveHistory();
      return;
    }
    if (result.type === 'poomai-sms-result' && result.ok) {
      var line;
      if (result.recipient_count) {
        line = '✅ ' + result.recipient_name + ' ' + result.recipient_count + '명에게 보냈어요.\n내용: ' + result.message;
      } else {
        line = '✅ ' + (result.recipient_name || '수신자') + ' (' + (result.phone_masked || '') + ')에게 보냈어요.\n내용: ' + result.message;
      }
      addMessage('assistant', line);
      history.push({ role: 'assistant', content: line });
      saveHistory();
      return;
    }
    var errMsg = '발송 실패: ' + (result.error || '알 수 없는 오류');
    addMessage('assistant', errMsg);
    history.push({ role: 'assistant', content: errMsg });
    saveHistory();
  }

  // 동명이인 선택 처리 ("1", "2" 같은 숫자 입력)
  async function handleSmsAmbiguousPick(query) {
    var nm = query.trim().match(/^\d+$/);
    if (!nm || !smsState.pendingCandidates) return false;
    var idx = parseInt(query.trim(), 10) - 1;
    if (idx < 0 || idx >= smsState.pendingCandidates.length) return false;
    var picked = smsState.pendingCandidates[idx];
    var message = smsState.pendingMessage;
    smsState.pendingCandidates = null;
    smsState.pendingMessage = null;

    var sessionId = 'sms-' + (++smsState.sessionCounter) + '-' + Date.now();
    var params = new URLSearchParams();
    params.set('member_id', picked.member_id);
    params.set('sms_text', message);
    params.set('auto_send', '1');
    params.set('session_id', sessionId);

    showTyping();
    var result = await fireSmsIframe(params, sessionId);
    hideTyping();

    var line;
    if (result.type === 'poomai-sms-result' && result.ok) {
      line = '✅ ' + (result.recipient_name || picked.member_name) + ' (' + (result.phone_masked || picked.phone_masked) + ')에게 보냈어요.\n내용: ' + message;
    } else {
      line = '발송 실패: ' + (result.error || '알 수 없는 오류');
    }
    addMessage('assistant', line);
    history.push({ role: 'assistant', content: line });
    saveHistory();
    return true;
  }

  // ── API: 채팅 ──
  async function sendChat(query) {
    if (isLoading || !query.trim()) return;

    isLoading = true;
    sendBtn.disabled = true;

    // 사용자 메시지 추가
    addMessage('user', query);
    history.push({ role: 'user', content: query });
    saveHistory();

    // 1) 동명이인 후보 대기 중이면 숫자 선택 처리
    if (smsState.pendingCandidates) {
      var picked = await handleSmsAmbiguousPick(query);
      if (picked) {
        isLoading = false;
        sendBtn.disabled = false;
        textarea.focus();
        return;
      }
    }

    // 2) SMS intent 매칭 → 위젯이 직접 처리 (engine 우회)
    var smsIntent = detectSmsIntent(query);
    if (smsIntent) {
      try {
        await handleSmsIntent(smsIntent);
      } catch (e) {
        console.error('SMS handle error:', e);
        addErrorMessage('SMS 처리 중 오류: ' + (e.message || e));
      } finally {
        isLoading = false;
        sendBtn.disabled = false;
        textarea.focus();
      }
      return;
    }

    showTyping();

    try {
      var headers = { 'Content-Type': 'application/json' };
      if (token) {
        headers['Authorization'] = 'Bearer ' + token;
      }

      var response = await fetch(API_CHAT, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({
          query: query,
          history: history.slice(0, -1), // 현재 메시지 제외한 이전 히스토리
          page_context: window.location.pathname
        })
      });

      hideTyping();

      if (!response.ok) {
        var errData;
        try { errData = await response.json(); } catch (_) { errData = {}; }

        if (errData.auth_required) {
          addAuthMessage();
        } else {
          addErrorMessage(errData.error || '요청 처리 중 문제가 발생했습니다.');
        }
        // 실패한 사용자 메시지 히스토리에서 제거
        history.pop();
        saveHistory();
        return;
      }

      var data = await response.json();
      var answer = data.answer || '응답을 받지 못했습니다.';

      addMessage('assistant', answer);
      history.push({ role: 'assistant', content: answer });
      saveHistory();

    } catch (err) {
      hideTyping();
      addErrorMessage('연결이 불안정합니다. 다시 시도해주세요.');
      // 실패한 사용자 메시지 히스토리에서 제거
      history.pop();
      saveHistory();
    } finally {
      isLoading = false;
      sendBtn.disabled = false;
      textarea.focus();
    }
  }

  // ── API: 로그인 ──
  async function doLogin() {
    var email = loginEmail.value.trim();
    var pw = loginPw.value;

    if (!email || !pw) {
      showLoginError('이메일과 비밀번호를 입력해주세요.');
      return;
    }

    loginSubmit.disabled = true;
    loginSubmit.textContent = '로그인 중...';
    hideLoginError();

    try {
      var response = await fetch(API_LOGIN, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email, password: pw })
      });

      if (!response.ok) {
        var errData;
        try { errData = await response.json(); } catch (_) { errData = {}; }
        showLoginError(errData.error || '로그인에 실패했습니다.');
        return;
      }

      var data = await response.json();
      token = data.access_token;
      userEmail = data.user_email || email;

      localStorage.setItem(TOKEN_KEY, token);
      localStorage.setItem(EMAIL_KEY, userEmail);

      updateAuthUI();
      toggleLoginForm(false);
      loginPw.value = '';

      addMessage('assistant', userEmail.split('@')[0] + '님, 로그인되었습니다.');

    } catch (err) {
      showLoginError('연결이 불안정합니다. 다시 시도해주세요.');
    } finally {
      loginSubmit.disabled = false;
      loginSubmit.textContent = '로그인';
    }
  }

  function doLogout() {
    token = '';
    userEmail = '';
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(EMAIL_KEY);
    updateAuthUI();
    toggleLoginForm(false);
    addMessage('assistant', '로그아웃되었습니다.');
  }

  // ── 로그인 폼 토글 ──
  function toggleLoginForm(show) {
    if (show === undefined) show = !showLoginForm;
    showLoginForm = show;
    if (show) {
      loginForm.classList.add('show');
      loginEmail.focus();
    } else {
      loginForm.classList.remove('show');
      hideLoginError();
    }
  }

  function showLoginError(msg) {
    loginError.textContent = msg;
    loginError.style.display = 'block';
  }

  function hideLoginError() {
    loginError.style.display = 'none';
  }

  // ── 패널 열기/닫기 ──
  function openPanel() {
    isOpen = true;
    panel.classList.add('open');
    fab.innerHTML = '<span class="fab-icon fab-close">&times;</span>';
    sessionStorage.setItem(STATE_KEY, 'true');

    // 히스토리 복원
    if (history.length > 0) {
      restoreMessages();
    }

    // 환영 메시지 (최초 1회)
    if (!welcomeSent) {
      welcomeSent = true;
      addMessage('assistant', getWelcomeMessage());
    }

    textarea.focus();
    scrollToBottom();
  }

  function closePanel() {
    isOpen = false;
    panel.classList.remove('open');
    fab.innerHTML = '<span class="fab-icon">&#x1F33E;</span>';
    sessionStorage.setItem(STATE_KEY, 'false');
    showLoginForm = false;
    loginForm.classList.remove('show');
  }

  // ── 이벤트 바인딩 ──

  // FAB 클릭
  fab.addEventListener('click', function (e) {
    e.stopPropagation();
    e.preventDefault();
    if (isOpen) {
      closePanel();
    } else {
      openPanel();
    }
  });

  // 닫기 버튼
  closeBtn.addEventListener('click', function () {
    closePanel();
  });

  // 로그인/로그아웃 버튼
  authBtn.addEventListener('click', function () {
    if (token) {
      doLogout();
    } else {
      toggleLoginForm();
    }
  });

  // 로그인 제출
  loginSubmit.addEventListener('click', function () {
    doLogin();
  });

  // 로그인 폼 Enter 키
  loginPw.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      doLogin();
    }
  });

  loginEmail.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      loginPw.focus();
    }
  });

  // 전송 버튼
  sendBtn.addEventListener('click', function () {
    var text = textarea.value.trim();
    if (text) {
      textarea.value = '';
      adjustTextareaHeight();
      sendChat(text);
    }
  });

  // textarea 키보드
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

  // textarea 높이 자동 조절
  textarea.addEventListener('input', function () {
    adjustTextareaHeight();
  });

  // ── 초기 상태 복원 ──
  if (isOpen) {
    openPanel();
  }

})();
