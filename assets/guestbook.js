/* 방명록 — poomasi.org/guestbook.html · 2026-08-20
 *
 * Supabase PostgREST 를 fetch 로 직접 부른다. 라이브러리 없음.
 *  - 읽기: guestbook_public 뷰 (email 컬럼이 아예 없다)
 *  - 쓰기: guestbook 테이블 INSERT 만 허용, 항상 status=pending 으로 들어간다
 *  - POST 에 'Prefer: return=representation' 을 넣으면 안 된다.
 *    응답을 돌려주려면 SELECT 권한이 필요한데 anon 에겐 없어서 401 이 난다.
 * anon 키는 공개되어도 되는 키다. 권한은 RLS 가 잡는다.
 */
(function () {
  'use strict';

  var API = 'https://tnivhcpjrhkmekcfqgdn.supabase.co/rest/v1';
  var ANON = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRuaXZoY3BqcmhrbWVrY2ZxZ2RuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE2NTc5MjMsImV4cCI6MjA4NzIzMzkyM30.yJ0_4Sg78p7oY89q7go3ab26PCPHnk1Q4ObZJIZEULA';
  var MIN_FILL_MS = 3000;   // 폼 로드 후 3초 미만 제출은 봇으로 본다

  var headers = { apikey: ANON, Authorization: 'Bearer ' + ANON };

  var $ = function (id) { return document.getElementById(id); };
  var loadedAt = Date.now();

  /* ---------- 목록 ---------- */

  function formatDate(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d)) return '';
    var p = function (n) { return n < 10 ? '0' + n : '' + n; };
    return d.getFullYear() + '.' + p(d.getMonth() + 1) + '.' + p(d.getDate());
  }

  function renderList(rows) {
    var list = $('gb-list');
    list.textContent = '';

    rows.forEach(function (row, i) {
      var li = document.createElement('li');
      li.className = 'gb-item';
      li.style.animationDelay = Math.min(i, 8) * 40 + 'ms';

      var head = document.createElement('div');
      head.className = 'gb-item-head';

      var name = document.createElement('span');
      name.className = 'gb-item-name';
      name.textContent = row.name;          // textContent — 방문자 입력을 HTML 로 해석하지 않는다
      head.appendChild(name);

      var when = formatDate(row.published_at);
      if (when) {
        var time = document.createElement('time');
        time.className = 'gb-item-date';
        time.setAttribute('datetime', row.published_at);
        time.textContent = when;
        head.appendChild(time);
      }

      var body = document.createElement('p');
      body.className = 'gb-item-body';
      body.textContent = row.body;

      li.appendChild(head);
      li.appendChild(body);
      list.appendChild(li);
    });

    list.hidden = rows.length === 0;
    $('gb-empty').hidden = rows.length > 0;
  }

  function loadList() {
    $('gb-loading').hidden = false;
    $('gb-listerror').hidden = true;

    return fetch(API + '/guestbook_public?select=id,name,body,published_at&order=published_at.desc', { headers: headers })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (rows) {
        $('gb-loading').hidden = true;
        renderList(rows);
      })
      .catch(function () {
        $('gb-loading').hidden = true;
        $('gb-list').hidden = true;
        $('gb-empty').hidden = true;
        $('gb-listerror').hidden = false;
      });
  }

  /* ---------- 폼 ---------- */

  function setError(fieldId, message) {
    var input = $(fieldId);
    var err = $(fieldId + '-err');
    if (message) {
      input.setAttribute('aria-invalid', 'true');
      err.textContent = message;
      err.hidden = false;
    } else {
      input.removeAttribute('aria-invalid');
      err.textContent = '';
      err.hidden = true;
    }
    return !message;
  }

  function validate() {
    var ok = true;
    var name = $('gb-name').value.trim();
    var email = $('gb-email').value.trim();
    var body = $('gb-body').value.trim();

    ok = setError('gb-name', name ? '' : '이름을 적어주세요.') && ok;
    ok = setError('gb-email',
      !email ? '이메일을 적어주세요.'
        : (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) ? '' : '이메일 형식을 확인해 주세요. 예: name@example.com')) && ok;
    ok = setError('gb-body', body ? '' : '내용을 적어주세요.') && ok;

    return ok ? { name: name, email: email, body: body } : null;
  }

  // 입력을 고치는 순간이 아니라 칸을 떠날 때 확인한다
  ['gb-name', 'gb-email', 'gb-body'].forEach(function (id) {
    $(id).addEventListener('blur', function () {
      if ($(id).getAttribute('aria-invalid') === 'true') validate();
    });
  });

  function formMessage(text) {
    var el = $('gb-formmsg');
    el.textContent = text || '';
    el.hidden = !text;
  }

  function showDone() {
    $('gb-form').hidden = true;
    $('gb-done').hidden = false;
    $('gb-done').querySelector('h3').setAttribute('tabindex', '-1');
    $('gb-done').querySelector('h3').focus();
  }

  $('gb-form').addEventListener('submit', function (e) {
    e.preventDefault();
    formMessage('');

    // ① 허니팟 — 사람 눈에 안 보이는 칸이 채워져 왔다. 조용히 버린다.
    if ($('gb-company').value !== '') {
      showDone();
      return;
    }

    // ② 최소 작성 시간
    if (Date.now() - loadedAt < MIN_FILL_MS) {
      formMessage('조금 천천히 보내주세요. 잠시 후 다시 눌러주시면 됩니다.');
      return;
    }

    var data = validate();
    if (!data) {
      var bad = document.querySelector('.gb-field [aria-invalid="true"]');
      if (bad) bad.focus();
      return;
    }

    var btn = $('gb-submit');
    btn.disabled = true;
    btn.classList.add('is-busy');
    btn.querySelector('.gb-submit-label').textContent = '보내는 중';

    fetch(API + '/guestbook', {
      method: 'POST',
      headers: {
        apikey: ANON,
        Authorization: 'Bearer ' + ANON,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(data)
    })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        showDone();
      })
      .catch(function () {
        formMessage('보내지 못했습니다. 네트워크를 확인하고 다시 눌러주세요.');
      })
      .then(function () {
        btn.disabled = false;
        btn.classList.remove('is-busy');
        btn.querySelector('.gb-submit-label').textContent = '남기기';
      });
  });

  $('gb-again').addEventListener('click', function () {
    $('gb-form').reset();
    ['gb-name', 'gb-email', 'gb-body'].forEach(function (id) { setError(id, ''); });
    formMessage('');
    loadedAt = Date.now();
    $('gb-done').hidden = true;
    $('gb-form').hidden = false;
    $('gb-name').focus();
  });

  loadList();
})();
