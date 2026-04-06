// /infra/* 차단 — 인프라 코드는 publish 금지.

export const onRequest = () => new Response('Not Found', {
  status: 404,
  headers: { 'Content-Type': 'text/plain; charset=utf-8' },
});
