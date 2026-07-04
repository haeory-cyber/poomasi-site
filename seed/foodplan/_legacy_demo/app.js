// ===== 데이터 =====

const COLORS = {
  primary: '#1B5E20',
  primaryLight: '#4CAF50',
  accent: '#BF6A1F',
  success: '#2E7D32',
  warning: '#F57C00',
  danger: '#C62828',
  neutral: '#9E9E9E',
};

const dashboardData = {
  kpi: [
    { label: '오늘의 임박', value: '18건', delta: '+3 ▲', deltaClass: 'delta-up', icon: '⏰' },
    { label: '못난이·과잉 접수', value: '5건', delta: '금주 누적 12건', deltaClass: 'delta-neutral', icon: '🥕' },
    { label: '예약 완료', value: '23건', delta: '픽업 15 / 배송 8', deltaClass: 'delta-neutral', icon: '📦' },
    { label: 'CO₂ 절감', value: '127.4kg', delta: '누적 · 환경부 배출계수', deltaClass: 'delta-up', icon: '🌿' },
  ],
  chartWeekly: {
    labels: ['6/3', '6/4', '6/5', '6/6', '6/7', '6/8', '6/9'],
    data: [12, 9, 15, 11, 14, 16, 18],
  },
  chartCategory: {
    labels: ['야채', '과일', '정육', '수산', '기타'],
    data: [45, 25, 15, 10, 5],
    colors: ['#1B5E20', '#4CAF50', '#BF6A1F', '#1565C0', '#9E9E9E'],
  },
  activityLog: [
    { time: '09:00', activity: 'POS 임박 자동 추출 완료 (18건)', status: 'success' },
    { time: '09:15', activity: '회원 알림톡 발송 (342명)', status: 'success' },
    { time: '10:30', activity: '김○○ 농가 못난이 접수 (감자 50kg)', status: 'processing' },
    { time: '11:00', activity: '예약 픽업 7건 완료', status: 'success' },
    { time: '14:00', activity: '박○○ 농가 과잉 접수 (방울토마토 30kg)', status: 'processing' },
  ],
};

const imminentData = {
  summary: '자동 추출 시간: 오늘 09:00 | 총 18건 | 알림 완료 9건 | 예약중 4건',
  items: [
    { name: '시금치 500g', category: '야채', inDate: '6/7', days: 2, price: 3500, discount: 30, status: 'done' },
    { name: '방울토마토 1팩', category: '과일', inDate: '6/6', days: 3, price: 5000, discount: 50, status: 'reserved' },
    { name: '깻잎 1봉', category: '야채', inDate: '6/7', days: 2, price: 2000, discount: 30, status: 'done' },
    { name: '사과 3입', category: '과일', inDate: '6/5', days: 4, price: 8000, discount: 50, status: 'dispose' },
    { name: '돼지 목살 300g', category: '정육', inDate: '6/8', days: 1, price: 9800, discount: 15, status: 'done' },
    { name: '오이 3개', category: '야채', inDate: '6/6', days: 3, price: 2500, discount: 50, status: 'reserved' },
    { name: '당근 1봉', category: '야채', inDate: '6/7', days: 2, price: 1800, discount: 30, status: 'done' },
    { name: '고등어 1마리', category: '수산', inDate: '6/8', days: 1, price: 6500, discount: 15, status: 'waiting' },
    { name: '감자 1kg', category: '야채', inDate: '6/5', days: 4, price: 3000, discount: 50, status: 'dispose' },
    { name: '양배추 1통', category: '야채', inDate: '6/7', days: 2, price: 4500, discount: 30, status: 'done' },
    { name: '딸기 500g', category: '과일', inDate: '6/8', days: 1, price: 7000, discount: 15, status: 'waiting' },
    { name: '부추 1단', category: '야채', inDate: '6/6', days: 3, price: 2200, discount: 50, status: 'done' },
    { name: '한우 등심 200g', category: '정육', inDate: '6/7', days: 2, price: 15000, discount: 30, status: 'reserved' },
    { name: '배 2입', category: '과일', inDate: '6/6', days: 3, price: 6000, discount: 50, status: 'reserved' },
    { name: '쪽파 1봉', category: '야채', inDate: '6/7', days: 2, price: 1500, discount: 30, status: 'done' },
  ],
};

const uglyData = {
  today: { received: 5, completed: 3, pending: 2 },
  monthly: { received: 28, completed: 25, rejected: 3 },
  items: [
    { farmer: '김○○(65세)', product: '감자', amount: 50, reason: '못난이(외관 불량)', shipDate: '6/11', discount: 40, status: 'checking' },
    { farmer: '박○○(72세)', product: '방울토마토', amount: 30, reason: '과잉(출하 집중)', shipDate: '6/10', discount: 35, status: 'done' },
    { farmer: '이○○(58세)', product: '깻잎', amount: 20, reason: '못난이(크기 미달)', shipDate: '6/12', discount: 45, status: 'checking' },
    { farmer: '최○○(68세)', product: '양파', amount: 80, reason: '과잉(출하 집중)', shipDate: '6/10', discount: 30, status: 'done' },
    { farmer: '정○○(61세)', product: '애호박', amount: 25, reason: '못난이(형태 불량)', shipDate: '6/11', discount: 40, status: 'done' },
  ],
};

const notifyData = {
  kpi: [
    { label: '오늘 발송', value: '342명', sub: '알림톡 298 + SMS 44' },
    { label: '열람률', value: '67.3%', sub: '230명 확인' },
    { label: '예약 전환', value: '23건', sub: '전환율 6.7%' },
  ],
  history: [
    { time: '09:15', message: '임박 농산물 18건 알림', recipients: 342, status: 'success' },
    { time: '10:45', message: '못난이 감자 50kg 특가', recipients: 342, status: 'success' },
    { time: '11:00', message: '과잉 방울토마토 30kg', recipients: 342, status: 'success' },
  ],
  timeSlots: [
    { slot: '10:00~12:00', pickup: 5, delivery: 2 },
    { slot: '12:00~14:00', pickup: 4, delivery: 3 },
    { slot: '14:00~16:00', pickup: 3, delivery: 2 },
    { slot: '16:00~18:00', pickup: 3, delivery: 1 },
  ],
  reservations: [
    { member: '조○○', items: '시금치 500g, 당근 1봉', count: 2, type: '픽업', slot: '10:00~12:00', status: 'done' },
    { member: '한○○', items: '방울토마토 1팩', count: 1, type: '배송', slot: '12:00~14:00', status: 'delivering' },
    { member: '윤○○', items: '한우 등심 200g', count: 1, type: '픽업', slot: '14:00~16:00', status: 'waiting' },
    { member: '강○○', items: '딸기 500g, 깻잎 1봉', count: 2, type: '픽업', slot: '10:00~12:00', status: 'done' },
    { member: '신○○', items: '감자 1kg', count: 1, type: '배송', slot: '12:00~14:00', status: 'done' },
    { member: '오○○', items: '사과 3입, 오이 3개', count: 2, type: '픽업', slot: '14:00~16:00', status: 'waiting' },
    { member: '배○○', items: '부추 1단', count: 1, type: '픽업', slot: '16:00~18:00', status: 'waiting' },
    { member: '임○○', items: '돼지 목살 300g, 배 2입', count: 2, type: '배송', slot: '16:00~18:00', status: 'delivering' },
  ],
};

const farmData = {
  kpi: [
    { label: '참여 농가', value: '84곳', sub: '고령농 39곳 (46.4%)' },
    { label: '월간 보고 발송', value: '6월 1주 완료', sub: '3건 / 84곳' },
    { label: '누적 CO₂ 절감', value: '127.4kg', sub: '환경부 배출계수 기준' },
  ],
  chartWaste: {
    labels: ['2월', '3월', '4월', '5월', '6월'],
    datasets: [
      { label: '야채', data: [45, 62, 78, 55, 48], color: '#1B5E20' },
      { label: '과일', data: [28, 35, 42, 38, 31], color: '#4CAF50' },
      { label: '정육', data: [15, 20, 18, 22, 17], color: '#BF6A1F' },
    ],
  },
  chartCO2: {
    labels: ['5/5', '5/12', '5/19', '5/26', '6/2', '6/9'],
    data: [15.2, 38.4, 62.1, 89.3, 108.7, 127.4],
  },
  farmers: [
    { name: '김○○', age: 65, products: '감자, 고구마', imminent: 12, sold: 10, saved: 45.2, status: 'done' },
    { name: '박○○', age: 72, products: '방울토마토', imminent: 8, sold: 7, saved: 28.5, status: 'done' },
    { name: '이○○', age: 58, products: '깻잎, 시금치', imminent: 15, sold: 13, saved: 52.1, status: 'done' },
    { name: '최○○', age: 68, products: '양파, 감자', imminent: 6, sold: 5, saved: 22.8, status: 'waiting' },
    { name: '정○○', age: 61, products: '애호박', imminent: 9, sold: 8, saved: 31.4, status: 'done' },
    { name: '권○○', age: 74, products: '배추, 무', imminent: 11, sold: 9, saved: 38.2, status: 'done' },
    { name: '황○○', age: 55, products: '딸기', imminent: 7, sold: 6, saved: 24.9, status: 'waiting' },
    { name: '류○○', age: 69, products: '부추, 깻잎', imminent: 13, sold: 11, saved: 43.6, status: 'done' },
  ],
};

// ===== 유틸 =====

function getTodayString() {
  const d = new Date();
  const days = ['일요일', '월요일', '화요일', '수요일', '목요일', '금요일', '토요일'];
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${days[d.getDay()]}`;
}

function statusBadge(status) {
  const map = {
    done: '<span class="badge badge-success">✅ 알림완료</span>',
    reserved: '<span class="badge badge-warning">🟡 예약중</span>',
    dispose: '<span class="badge badge-danger">🔴 폐기예정</span>',
    waiting: '<span class="badge badge-neutral">⚪ 대기</span>',
    checking: '<span class="badge badge-warning">🟡 확인중</span>',
    delivering: '<span class="badge badge-info">🚛 배송중</span>',
  };
  return map[status] || status;
}

function activityStatusBadge(status) {
  if (status === 'success') return '<span class="badge badge-success">✅</span>';
  if (status === 'processing') return '<span class="badge badge-warning">🔶 처리중</span>';
  return '';
}

function formatPrice(n) {
  return n.toLocaleString() + '원';
}

// ===== 차트 인스턴스 =====
let chartWeekly = null;
let chartCategory = null;
let chartWaste = null;
let chartCO2 = null;

function destroyChart(instance) {
  if (instance) { try { instance.destroy(); } catch (e) {} }
}

// ===== 탭 렌더 함수 =====

function renderDashboard() {
  const container = document.getElementById('content-area');

  const kpiHtml = dashboardData.kpi.map(k => `
    <div class="kpi-card">
      <div class="kpi-icon">${k.icon}</div>
      <div class="kpi-body">
        <div class="kpi-label">${k.label}</div>
        <div class="kpi-value">${k.value}</div>
        <div class="kpi-delta ${k.deltaClass}">${k.delta}</div>
      </div>
    </div>
  `).join('');

  const logHtml = dashboardData.activityLog.map(l => `
    <tr>
      <td class="log-time">${l.time}</td>
      <td>${l.activity}</td>
      <td>${activityStatusBadge(l.status)}</td>
    </tr>
  `).join('');

  container.innerHTML = `
    <div class="section-header">
      <h2>오늘의 현황</h2>
      <span class="section-sub">실시간 운영 모니터링</span>
    </div>

    <div class="kpi-grid">${kpiHtml}</div>

    <div class="chart-row">
      <div class="chart-card">
        <div class="chart-title">최근 7일 임박 발생 추이</div>
        <div class="chart-wrapper"><canvas id="chartWeekly"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">카테고리별 비율</div>
        <div class="chart-wrapper"><canvas id="chartCategory"></canvas></div>
      </div>
    </div>

    <div class="table-card">
      <div class="table-header-row">
        <span class="table-title">최근 활동 로그</span>
      </div>
      <table class="data-table">
        <thead>
          <tr><th>시간</th><th>활동</th><th>상태</th></tr>
        </thead>
        <tbody>${logHtml}</tbody>
      </table>
    </div>
  `;

  destroyChart(chartWeekly);
  destroyChart(chartCategory);

  chartWeekly = new Chart(document.getElementById('chartWeekly'), {
    type: 'bar',
    data: {
      labels: dashboardData.chartWeekly.labels,
      datasets: [{
        label: '임박 건수',
        data: dashboardData.chartWeekly.data,
        backgroundColor: COLORS.primary,
        borderRadius: 6,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 800, easing: 'easeOutQuart' },
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, grid: { color: '#f0f0f0' } },
        x: { grid: { display: false } },
      },
    },
  });

  chartCategory = new Chart(document.getElementById('chartCategory'), {
    type: 'doughnut',
    data: {
      labels: dashboardData.chartCategory.labels,
      datasets: [{
        data: dashboardData.chartCategory.data,
        backgroundColor: dashboardData.chartCategory.colors,
        borderWidth: 2,
        borderColor: '#fff',
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { animateRotate: true, duration: 900 },
      plugins: {
        legend: { position: 'bottom', labels: { padding: 14, font: { size: 12 }, usePointStyle: true, pointStyle: 'circle' } },
      },
      cutout: '55%',
    },
  });
}

function renderImminent(filter) {
  const container = document.getElementById('content-area');
  filter = filter || 'all';

  const filterDef = {
    all: { label: '전체', fn: () => true },
    d1: { label: '1일 임박', fn: i => i.days === 1 },
    d2: { label: '2일 임박', fn: i => i.days === 2 },
    d3: { label: '3일+', fn: i => i.days >= 3 },
  };

  const counts = {
    all: imminentData.items.length,
    d1: imminentData.items.filter(i => i.days === 1).length,
    d2: imminentData.items.filter(i => i.days === 2).length,
    d3: imminentData.items.filter(i => i.days >= 3).length,
  };

  const filtered = imminentData.items.filter(filterDef[filter].fn);

  const filterHtml = Object.entries(filterDef).map(([key, val]) => `
    <button class="filter-btn ${filter === key ? 'active' : ''}" onclick="renderImminent('${key}')">
      ${val.label} <span class="filter-count">${counts[key]}</span>
    </button>
  `).join('');

  const rowHtml = filtered.map(item => {
    const discountPrice = Math.floor(item.price * (1 - item.discount / 100));
    const dayBadge = item.days === 1
      ? '<span class="day-badge day-1">1일</span>'
      : item.days === 2
        ? '<span class="day-badge day-2">2일</span>'
        : '<span class="day-badge day-3">3일+</span>';
    return `
      <tr>
        <td><strong>${item.name}</strong></td>
        <td>${item.category}</td>
        <td>${item.inDate}</td>
        <td>${dayBadge}</td>
        <td>${formatPrice(item.price)}</td>
        <td><span class="discount-badge">${item.discount}%</span></td>
        <td class="price-discounted">${formatPrice(discountPrice)}</td>
        <td>${statusBadge(item.status)}</td>
      </tr>
    `;
  }).join('');

  container.innerHTML = `
    <div class="section-header">
      <h2>임박 관리</h2>
      <span class="section-sub">POS 자동 추출 · 할인 단계별 관리</span>
    </div>

    <div class="summary-bar">
      <span class="summary-icon">ℹ️</span>
      ${imminentData.summary}
    </div>

    <div class="filter-bar">${filterHtml}</div>

    <div class="table-card">
      <table class="data-table">
        <thead>
          <tr>
            <th>품목</th><th>카테고리</th><th>입고일</th><th>진열일수</th>
            <th>현재가</th><th>할인율</th><th>할인가</th><th>상태</th>
          </tr>
        </thead>
        <tbody>${rowHtml}</tbody>
      </table>
    </div>

    <div class="discount-rule-card">
      <span class="rule-title">할인 기준</span>
      <span class="day-badge day-1">1일 → 15%</span>
      <span class="day-badge day-2">2일 → 30%</span>
      <span class="day-badge day-3">3일+ → 50%</span>
    </div>
  `;
}

function renderUgly() {
  const container = document.getElementById('content-area');

  const rowHtml = uglyData.items.map(item => `
    <tr>
      <td>${item.farmer}</td>
      <td>${item.product}</td>
      <td>${item.amount}kg</td>
      <td>${item.reason}</td>
      <td>${item.shipDate}</td>
      <td><span class="discount-badge">${item.discount}%</span></td>
      <td>${statusBadge(item.status)}</td>
    </tr>
  `).join('');

  container.innerHTML = `
    <div class="section-header">
      <h2>못난이·과잉 관리</h2>
      <span class="section-sub">농가 통보 접수 및 등록 관리</span>
    </div>

    <div class="two-col-cards">
      <div class="stat-card stat-card-primary">
        <div class="stat-card-title">오늘 접수 현황</div>
        <div class="stat-row"><span>접수</span><strong>${uglyData.today.received}건</strong></div>
        <div class="stat-row"><span>처리완료</span><strong class="text-success">${uglyData.today.completed}건</strong></div>
        <div class="stat-row"><span>대기</span><strong class="text-warning">${uglyData.today.pending}건</strong></div>
      </div>
      <div class="stat-card stat-card-accent">
        <div class="stat-card-title">이번 달 누적</div>
        <div class="stat-row"><span>접수</span><strong>${uglyData.monthly.received}건</strong></div>
        <div class="stat-row"><span>처리완료</span><strong class="text-success">${uglyData.monthly.completed}건</strong></div>
        <div class="stat-row"><span>반려</span><strong class="text-danger">${uglyData.monthly.rejected}건</strong></div>
      </div>
    </div>

    <div class="table-card">
      <div class="table-header-row">
        <span class="table-title">접수 목록</span>
        <button class="btn-primary" onclick="showModal()">+ 신규 등록</button>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>농가</th><th>품목</th><th>수량(kg)</th><th>사유</th>
            <th>출하예정일</th><th>할인율</th><th>상태</th>
          </tr>
        </thead>
        <tbody>${rowHtml}</tbody>
      </table>
    </div>

    <div id="ugly-modal" class="modal-overlay hidden" onclick="closeModal(event)">
      <div class="modal-box">
        <div class="modal-title">신규 못난이·과잉 등록</div>
        <div class="form-group">
          <label>품목</label>
          <input type="text" class="form-input" placeholder="예: 감자">
        </div>
        <div class="form-group">
          <label>수량 (kg)</label>
          <input type="number" class="form-input" placeholder="예: 50">
        </div>
        <div class="form-group">
          <label>사유</label>
          <select class="form-input">
            <option>못난이(외관 불량)</option>
            <option>못난이(크기 미달)</option>
            <option>못난이(형태 불량)</option>
            <option>과잉(출하 집중)</option>
          </select>
        </div>
        <div class="form-group">
          <label>출하예정일</label>
          <input type="date" class="form-input">
        </div>
        <div class="modal-actions">
          <button class="btn-secondary" onclick="closeModal()">취소</button>
          <button class="btn-primary" onclick="closeModal()">등록</button>
        </div>
      </div>
    </div>
  `;
}

function renderNotify() {
  const container = document.getElementById('content-area');

  const kpiHtml = notifyData.kpi.map(k => `
    <div class="kpi-card-sm">
      <div class="kpi-label">${k.label}</div>
      <div class="kpi-value">${k.value}</div>
      <div class="kpi-delta delta-neutral">${k.sub}</div>
    </div>
  `).join('');

  const historyHtml = notifyData.history.map(h => `
    <div class="notify-history-item">
      <span class="log-time">${h.time}</span>
      <span class="notify-msg">${h.message}</span>
      <span class="notify-recipients">${h.recipients}명 발송</span>
      <span class="badge badge-success">✅ 완료</span>
    </div>
  `).join('');

  const slotHtml = notifyData.timeSlots.map(s => `
    <tr>
      <td>${s.slot}</td>
      <td><strong>${s.pickup}건</strong></td>
      <td><strong>${s.delivery}건</strong></td>
    </tr>
  `).join('');

  const reservationHtml = notifyData.reservations.map(r => `
    <tr>
      <td>${r.member}</td>
      <td>${r.items}</td>
      <td>${r.count}건</td>
      <td>${r.type === '픽업' ? '🏪 픽업' : '🚛 배송'}</td>
      <td>${r.slot}</td>
      <td>${statusBadge(r.status)}</td>
    </tr>
  `).join('');

  container.innerHTML = `
    <div class="section-header">
      <h2>알림·예약 관리</h2>
      <span class="section-sub">회원 알림 발송 및 예약 현황</span>
    </div>

    <div class="kpi-grid-3">${kpiHtml}</div>

    <div class="two-col-layout">
      <div class="table-card">
        <div class="table-title" style="padding: 16px 20px 8px; font-weight:600;">알림 발송 이력</div>
        <div class="notify-history">${historyHtml}</div>
      </div>
      <div class="table-card">
        <div class="table-title" style="padding: 16px 20px 8px; font-weight:600;">시간대별 예약</div>
        <table class="data-table">
          <thead>
            <tr><th>시간대</th><th>픽업</th><th>배송</th></tr>
          </thead>
          <tbody>${slotHtml}</tbody>
        </table>
      </div>
    </div>

    <div class="table-card" style="margin-top:16px;">
      <div class="table-header-row">
        <span class="table-title">예약 상세</span>
      </div>
      <table class="data-table">
        <thead>
          <tr><th>회원</th><th>품목</th><th>수량</th><th>유형</th><th>시간대</th><th>상태</th></tr>
        </thead>
        <tbody>${reservationHtml}</tbody>
      </table>
    </div>
  `;
}

function renderFarm() {
  const container = document.getElementById('content-area');

  const kpiHtml = farmData.kpi.map(k => `
    <div class="kpi-card-sm">
      <div class="kpi-label">${k.label}</div>
      <div class="kpi-value">${k.value}</div>
      <div class="kpi-delta delta-up">${k.sub}</div>
    </div>
  `).join('');

  const farmerHtml = farmData.farmers.map(f => `
    <tr>
      <td>${f.name}</td>
      <td>${f.age}세</td>
      <td>${f.products}</td>
      <td>${f.imminent}</td>
      <td>${f.sold}</td>
      <td>${f.saved}kg</td>
      <td>${f.status === 'done' ? '<span class="badge badge-success">📊 보고완료</span>' : '<span class="badge badge-neutral">⏳ 보고대기</span>'}</td>
    </tr>
  `).join('');

  container.innerHTML = `
    <div class="section-header">
      <h2>농가 환류</h2>
      <span class="section-sub">농가별 결과 보고 및 환경 효과 측정</span>
    </div>

    <div class="kpi-grid-3">${kpiHtml}</div>

    <div class="chart-row">
      <div class="chart-card">
        <div class="chart-title">월별 폐기 절감량 (kg)</div>
        <div class="chart-wrapper"><canvas id="chartWaste"></canvas></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">CO₂ 절감 누적 (kg)</div>
        <div class="chart-wrapper"><canvas id="chartCO2"></canvas></div>
      </div>
    </div>

    <div class="table-card">
      <div class="table-header-row">
        <span class="table-title">농가별 리포트</span>
        <span class="table-sub">총 ${farmData.farmers.length}곳 표시 (전체 84곳)</span>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>농가</th><th>나이</th><th>주 출하품목</th>
            <th>임박 발생(건)</th><th>판매 완료(건)</th><th>판매 손실 절감</th><th>상태</th>
          </tr>
        </thead>
        <tbody>${farmerHtml}</tbody>
      </table>
    </div>
  `;

  destroyChart(chartWaste);
  destroyChart(chartCO2);

  chartWaste = new Chart(document.getElementById('chartWaste'), {
    type: 'bar',
    data: {
      labels: farmData.chartWaste.labels,
      datasets: farmData.chartWaste.datasets.map(ds => ({
        label: ds.label,
        data: ds.data,
        backgroundColor: ds.color,
        borderRadius: 4,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 800 },
      plugins: { legend: { position: 'top' } },
      scales: {
        x: { stacked: false, grid: { display: false } },
        y: { beginAtZero: true, grid: { color: '#f0f0f0' } },
      },
    },
  });

  chartCO2 = new Chart(document.getElementById('chartCO2'), {
    type: 'line',
    data: {
      labels: farmData.chartCO2.labels,
      datasets: [{
        label: 'CO₂ 절감 누적',
        data: farmData.chartCO2.data,
        borderColor: COLORS.primary,
        backgroundColor: 'rgba(27,94,32,0.1)',
        fill: true,
        tension: 0.4,
        pointBackgroundColor: COLORS.primary,
        pointRadius: 5,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 900 },
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, grid: { color: '#f0f0f0' } },
        x: { grid: { display: false } },
      },
    },
  });
}

// ===== 탭 전환 =====

const tabRenderers = {
  dashboard: renderDashboard,
  imminent: renderImminent,
  ugly: renderUgly,
  notify: renderNotify,
  farm: renderFarm,
};

function switchTab(tabId) {
  document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
  const activeNav = document.querySelector(`.nav-item[data-tab="${tabId}"]`);
  if (activeNav) activeNav.classList.add('active');

  const contentArea = document.getElementById('content-area');
  contentArea.classList.add('fade-out');

  setTimeout(() => {
    tabRenderers[tabId]();
    contentArea.classList.remove('fade-out');
    contentArea.classList.add('fade-in');
    setTimeout(() => contentArea.classList.remove('fade-in'), 300);
  }, 150);
}

// ===== 모달 =====

function showModal() {
  document.getElementById('ugly-modal').classList.remove('hidden');
}

function closeModal(e) {
  if (!e || e.target.id === 'ugly-modal' || e.currentTarget.tagName === 'BUTTON') {
    const m = document.getElementById('ugly-modal');
    if (m) m.classList.add('hidden');
  }
}

// ===== 초기화 =====

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('today-date').textContent = getTodayString();
  switchTab('dashboard');
});
