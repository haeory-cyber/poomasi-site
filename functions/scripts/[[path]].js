// /scripts/* 차단 — server-side admin 스크립트는 publish 금지.
// CF Pages는 정적 파일이 Function보다 우선이지만, 명시적 path Function이
// 있으면 정적을 override한다.

export const onRequest = () => new Response('Not Found', {
  status: 404,
  headers: { 'Content-Type': 'text/plain; charset=utf-8' },
});
