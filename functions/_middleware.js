// ⚠️ DEAD CODE — 이 파일은 poomasi.org에서 실행되지 않는다.
//   poomasi.org origin = GitHub Pages이며, Cloudflare Pages Functions는
//   CF Pages 배포에서만 동작한다(GitHub Pages에는 Functions 런타임이 없음).
//   → 실제 server-side 파일 노출 차단은 루트 _config.yml(Jekyll exclude)로 한다.
//   이 파일은 수정해도 라이브에 아무 효과 없으며, 오해 방지용으로만 남겨둔다.
//   (검증 2026-06-30: 이 미들웨어에도 불구하고 /infra/·/scripts/ 가 HTTP 200으로 노출됐음)
//
// (이하 원본) Cloudflare Pages middleware — server-side 파일 노출 차단 [CF Pages 배포 전용]
// Functions는 static asset보다 먼저 실행되므로 _redirects의 404 규칙이
// 작동하지 않는 실존 파일도 여기서 차단 가능.

const BLOCKED_PATTERNS = [
  /^\/scripts\//,         // server-side admin scripts
  /^\/infra\//,           // 인프라 코드
  /\.bak$/,               // 백업 파일
  /\.bak_\d/,             // 날짜 백업
  /\.bak2_\d/,            // 백업2 패턴
];

export const onRequest = async ({ request, next }) => {
  const url = new URL(request.url);
  if (BLOCKED_PATTERNS.some((re) => re.test(url.pathname))) {
    return new Response('Not Found', {
      status: 404,
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    });
  }
  return next();
};
