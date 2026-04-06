// Cloudflare Pages middleware — server-side 파일 노출 차단
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
