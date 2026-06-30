// 연대지능 랜딩 — poomasi.org standalone (poomasi-notes SolidarityLanding 이식)
//  1) 풀스크린 3D 지식그래프 (컬렉션별 색 / external 포털 노드)
//  2) 휠 = 그래프 전체 크기 줌(OrbitControls), 가만두면 자동회전. 아래 섹션은 히어로의 '아래로' 버튼/스크롤 화살표로 이동
//  3) IntersectionObserver 스크롤 리빌 (prefers-reduced-motion 존중)
//  4) 우하단 품아이 위챗 버블
// ForceGraph3D 는 index.html 의 UMD <script> 가 전역으로 제공.

const COLLECTION_COLORS = {
  생태계: "#ff8c42",
  동지본: "#c4803a",
  사상가: "#9b6dff",
  개념: "#2dd4bf",
  한국SSE: "#52b788",
  운동조직: "#4a90d9",
  법률정책: "#e07a5f",
  학술본: "#b07ddb",
  대정부본: "#d98ba0",
  원본자료: "#7aa0c4",
  저작: "#c9a227",
  품아이: "#e89bb0",
  품에: "#5ec8c0",
  시민재생에너지: "#5ec8c0",
  사회운동: "#6fae5a",
  교육훈련: "#8fb96a",
  활동: "#88b04b",
}
const MUTED = "#8a8a80"

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
    .nodeOpacity(0.92)
    .linkColor(() => "rgba(196,128,58,0.18)")
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

  // 맨 처음 방식: 그래프 위에서 맨 휠 = 전체 크기 줌(페이지 스크롤 막음). 아래 섹션 위에서는 정상 스크롤.
  const cam = fg.camera()
  const zoom = (dir) => {
    const p = cam.position
    const cur = Math.hypot(p.x, p.y, p.z) || 1
    const target = Math.max(40, Math.min(4000, cur * (dir > 0 ? 1.18 : 0.85)))
    const s = target / cur
    p.set(p.x * s, p.y * s, p.z * s)
  }
  container.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault()
      zoom(e.deltaY)
    },
    { passive: false },
  )

  // PC용 +/- 줌 버튼 (모바일은 CSS @media(pointer:coarse)에서 숨김)
  const ctrls = document.createElement("div")
  ctrls.className = "si-graph-controls"
  ctrls.innerHTML =
    '<button type="button" data-zoom="in" aria-label="그래프 확대" title="그래프 확대 (마우스 휠도 가능)">+</button>' +
    '<button type="button" data-zoom="out" aria-label="그래프 축소" title="그래프 축소">−</button>'
  ctrls.addEventListener("click", (e) => {
    const t = e.target.closest("button[data-zoom]")
    if (!t) return
    zoom(t.dataset.zoom === "in" ? -1 : 1)
  })
  document.body.appendChild(ctrls)

  const onResize = () => fg.width(window.innerWidth).height(window.innerHeight)
  window.addEventListener("resize", onResize)
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
  // 히어로 '아래로' 버튼도 부드럽게 스크롤 (휠 줌으로 페이지가 안 내려가므로)
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
  const container = document.querySelector(".si-graph[data-si-graph]")
  if (container && typeof ForceGraph3D !== "undefined") renderGraph(container)
  setupReveal()
  setupScrollCue()
  injectPoomaiWidget()
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init)
else init()
