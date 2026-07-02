// 연대지능 랜딩 — 한지·낮 리디자인 (landing.js 기반, 2026-07-02)
//  1) 풀스크린 3D 지식그래프 = 한지 위 수묵 성좌 (먹·감·쑥·단청 4계열 팔레트)
//  2) PC: 휠 = 그래프 줌(검증된 커스텀 dolly) / 모바일: 두손가락 핀치 = 그래프 줌 [신규]
//     핀치 방식: 그래프(z0)와 본문(z10) 사이 투명 터치막(z5, touch-action:pan-y).
//     한손가락 세로 스크롤은 브라우저 네이티브(pan-y), 두손가락은 JS가 가로채 카메라 dolly.
//     본문 섹션은 터치막 위 레이어라 링크 탭·텍스트 확대 영향 없음.
//  3) ?debug=1 : 터치 손가락 수·카메라 거리 실측 오버레이 (레슨 20260701)
// ForceGraph3D 는 index.html 의 UMD <script> 가 전역으로 제공.

// 수묵 팔레트 — 먹(지식)·감(생태계/포털)·쑥(운동/교육)·단청적갈(사상)·청먹(개념)
const COLLECTION_COLORS = {
  생태계: "#b3641f",       // 감
  동지본: "#9c4a3a",       // 단청 적갈
  사상가: "#6b5a72",       // 자먹
  개념: "#46586b",         // 청먹
  한국SSE: "#55683f",      // 쑥 진
  운동조직: "#46586b",
  법률정책: "#8a6b3a",     // 황먹
  학술본: "#6b5a72",
  대정부본: "#9c4a3a",
  원본자료: "#7d7464",     // 옅은 먹
  저작: "#8a6b3a",
  품아이: "#b3641f",
  품에: "#4e7a6a",         // 옥빛
  시민재생에너지: "#4e7a6a",
  사회운동: "#55683f",
  교육훈련: "#6f7f4a",
  활동: "#6f7f4a",
}
const MUTED = "#a89e8a"

const ZOOM_MIN = 40
const ZOOM_MAX = 4000

function collectionOf(id) {
  const segs = id.split("/")
  for (let i = segs.length - 2; i >= 0; i--) {
    if (COLLECTION_COLORS[segs[i]]) return segs[i]
  }
  return segs.length > 1 ? segs[0] : null
}
function colorOf(n) {
  const c = collectionOf(n.id)
  return (c && COLLECTION_COLORS[c]) || MUTED
}
function nodeValOf(n, degree) {
  const d = degree.get(n.id) || 0
  const base = 2 + Math.sqrt(d)
  const r = n.external ? base + 4 : base
  return r * r
}

// ---------- 디버그 오버레이 (?debug=1) ----------
const DEBUG = new URLSearchParams(location.search).get("debug") === "1"
let debugEl = null
const debugState = { fingers: 0, cam: 0, last: "-" }
function debugInit() {
  if (!DEBUG || debugEl) return
  debugEl = document.createElement("div")
  debugEl.className = "si-debug"
  document.body.appendChild(debugEl)
}
function debugUpdate(patch) {
  if (!DEBUG) return
  Object.assign(debugState, patch)
  if (debugEl)
    debugEl.textContent =
      "fingers: " + debugState.fingers +
      "\ncamDist: " + Math.round(debugState.cam) +
      "\nlast: " + debugState.last
}

async function renderGraph(container) {
  let raw
  try {
    raw = await (await fetch("/landing-graph.json", { cache: "no-cache" })).json()
  } catch (e) {
    return // 그래프 데이터 실패 시 히어로는 그대로(배경만)
  }
  const valid = new Set(Object.keys(raw))
  const links = []
  for (const [source, v] of Object.entries(raw)) {
    for (const dest of v.links || []) if (valid.has(dest)) links.push({ source, target: dest })
  }
  const nodes = Object.keys(raw).map((id) => ({ id, text: raw[id].title || id, external: raw[id].external }))

  const degree = new Map()
  for (const l of links) {
    degree.set(l.source, (degree.get(l.source) || 0) + 1)
    degree.set(l.target, (degree.get(l.target) || 0) + 1)
  }

  // 모바일 경량화: 차수 상위 + 포털만
  const isMobile = window.matchMedia("(max-width: 768px)").matches
  let useNodes = nodes
  let useLinks = links
  if (isMobile && nodes.length > 120) {
    const top = new Set(
      [...nodes].sort((a, b) => (degree.get(b.id) || 0) - (degree.get(a.id) || 0)).slice(0, 120).map((n) => n.id),
    )
    useNodes = nodes.filter((n) => n.external || top.has(n.id))
    const keep = new Set(useNodes.map((n) => n.id))
    useLinks = links.filter((l) => keep.has(l.source) && keep.has(l.target))
  }

  const navigateNode = (n) => {
    if (n.external) window.open(n.external, "_blank", "noopener")
    else window.open("https://wiki.poomasi.org/" + encodeURI(n.id), "_blank", "noopener")
  }

  const fg = new ForceGraph3D(container, {
    rendererConfig: { antialias: true, alpha: true },
    controlType: "orbit",
  })
    .width(window.innerWidth)
    .height(window.innerHeight)
    .backgroundColor("rgba(0,0,0,0)")
    .showNavInfo(false)
    .enableNodeDrag(false)
    .graphData({ nodes: useNodes, links: useLinks.map((l) => ({ source: l.source, target: l.target })) })
    .nodeLabel((n) => n.text)
    .nodeColor((n) => colorOf(n))
    .nodeVal((n) => nodeValOf(n, degree))
    .nodeOpacity(0.85)
    .linkColor(() => "rgba(38,34,27,0.16)")   // 옅은 먹선
    .linkWidth(0.5)
    .onNodeClick((n) => navigateNode(n))

  if (isMobile) fg.cooldownTicks(60).warmupTicks(20)

  // 컨트롤: OrbitControls 휠 줌은 끄고(페이지 스크롤 막지 못함) 아래 커스텀 휠로 처리 + 자동회전 + 드래그회전
  try {
    const c = fg.controls()
    if (c) {
      c.enableZoom = false
      c.enablePan = false
      c.autoRotate = true
      c.autoRotateSpeed = 0.55
    }
  } catch (_) {}

  // 카메라 거리 dolly — 휠/버튼/핀치 공용
  const cam = fg.camera()
  const camDist = () => {
    const p = cam.position
    return Math.hypot(p.x, p.y, p.z) || 1
  }
  const dollyTo = (target) => {
    const cur = camDist()
    const t = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, target))
    const s = t / cur
    cam.position.set(cam.position.x * s, cam.position.y * s, cam.position.z * s)
    debugUpdate({ cam: t })
  }
  const zoom = (dir) => dollyTo(camDist() * (dir > 0 ? 1.18 : 0.85))
  debugUpdate({ cam: camDist() })

  // PC: 그래프 위 맨 휠 = 줌 (검증된 현행 방식 유지)
  container.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault()
      zoom(e.deltaY)
    },
    { passive: false },
  )

  // ---------- 모바일 핀치 줌 [신규] ----------
  // 그래프(pointer-events:none)와 본문 사이 z5 투명 터치막.
  // touch-action:pan-y → 한손가락 세로 스크롤은 네이티브, 두손가락 touchmove는
  // 브라우저 몫이 아니므로 cancelable하게 JS 도착 → preventDefault + 카메라 dolly.
  if (window.matchMedia("(pointer: coarse)").matches) {
    const layer = document.createElement("div")
    layer.className = "si-touch-layer"
    layer.setAttribute("aria-hidden", "true")
    // 본문(.si-sections, z10)보다 아래라 히어로/그래프 영역 터치만 받는다
    document.querySelector(".solidarity-landing").insertBefore(
      layer,
      document.querySelector(".solidarity-landing .si-hero"),
    )

    let pinchDist = 0
    const dist2 = (t) => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY)

    layer.addEventListener(
      "touchstart",
      (e) => {
        debugUpdate({ fingers: e.touches.length, last: "touchstart" })
        if (e.touches.length === 2) pinchDist = dist2(e.touches)
      },
      { passive: true },
    )
    layer.addEventListener(
      "touchmove",
      (e) => {
        debugUpdate({ fingers: e.touches.length, last: "touchmove c=" + e.cancelable })
        if (e.touches.length !== 2) return
        e.preventDefault() // 브라우저 페이지줌 차단 (pan-y 덕에 cancelable)
        const d = dist2(e.touches)
        if (pinchDist > 0 && d > 0) {
          dollyTo(camDist() * (pinchDist / d)) // 손가락 벌림 = 확대(거리 감소)
          debugUpdate({ last: "pinch " + (d > pinchDist ? "in(확대)" : "out(축소)") })
        }
        pinchDist = d
      },
      { passive: false },
    )
    const reset = (e) => {
      if (e.touches.length < 2) pinchDist = 0
      debugUpdate({ fingers: e.touches.length, last: e.type })
    }
    layer.addEventListener("touchend", reset, { passive: true })
    layer.addEventListener("touchcancel", reset, { passive: true })

    // iOS 구형 사파리 보루: 터치막 위 제스처 기본동작 차단
    layer.addEventListener("gesturestart", (e) => e.preventDefault())
  }

  // 줌 버튼 — 한지판에서는 모바일에도 노출(핀치 백업)
  const ctrls = document.createElement("div")
  ctrls.className = "si-graph-controls"
  ctrls.innerHTML =
    '<button type="button" data-zoom="in" aria-label="그래프 확대" title="그래프 확대 (마우스 휠·두손가락도 가능)">+</button>' +
    '<button type="button" data-zoom="out" aria-label="그래프 축소" title="그래프 축소">−</button>'
  ctrls.addEventListener("click", (e) => {
    const t = e.target.closest("button[data-zoom]")
    if (!t) return
    zoom(t.dataset.zoom === "in" ? -1 : 1)
  })
  document.body.appendChild(ctrls)

  const onResize = () => fg.width(window.innerWidth).height(window.innerHeight)
  window.addEventListener("resize", onResize)

  // 디버그/검증용 훅 — 카메라 거리 외부 조회
  window.__siCamDist = camDist
}

function setupScrollCue() {
  const cue = document.querySelector(".solidarity-landing .si-scroll-cue")
  const main = document.getElementById("si-main")
  if (!cue || !main) return
  cue.setAttribute("role", "button")
  cue.setAttribute("tabindex", "0")
  cue.setAttribute("aria-label", "다음 섹션으로 이동")
  const go = () => main.scrollIntoView({ behavior: "smooth", block: "start" })
  cue.addEventListener("click", go)
  cue.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault()
      go()
    }
  })
  const down = document.querySelector(".solidarity-landing .si-hero-join[data-scroll-down]")
  if (down) down.addEventListener("click", (e) => { e.preventDefault(); go() })
}

function setupReveal() {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches
  const els = Array.from(document.querySelectorAll(".solidarity-landing .si-reveal"))
  if (reduce || !("IntersectionObserver" in window)) {
    els.forEach((el) => el.classList.add("is-visible"))
    return
  }
  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry, i) => {
        if (entry.isIntersecting) {
          const el = entry.target
          window.setTimeout(() => el.classList.add("is-visible"), i * 40)
          io.unobserve(el)
        }
      })
    },
    { threshold: 0.15, rootMargin: "0px 0px -8% 0px" },
  )
  els.forEach((el) => io.observe(el))
}

function injectPoomaiWidget() {
  if (document.getElementById("si-poomai-widget-script")) return
  const s = document.createElement("script")
  s.id = "si-poomai-widget-script"
  s.src = "https://seed.poomasi.org/poomai-widget.js"
  s.async = true
  document.body.appendChild(s)
}

function init() {
  debugInit()
  const container = document.querySelector(".si-graph[data-si-graph]")
  if (container && typeof ForceGraph3D !== "undefined") renderGraph(container)
  setupReveal()
  setupScrollCue()
  injectPoomaiWidget()
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init)
else init()
