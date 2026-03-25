// 카카오 본인인증 OAuth 토큰 교환 + 사용자 정보 조회
// Cloudflare Pages Function
// 환경변수: KAKAO_REST_KEY, KAKAO_SECRET

export async function onRequestPost(context) {
  const corsHeaders = {
    'Access-Control-Allow-Origin': 'https://poomasi.org',
    'Content-Type': 'application/json',
  };

  try {
    const { code, redirect_uri } = await context.request.json();
    const KAKAO_REST_KEY = context.env.KAKAO_REST_KEY || 'd312e73c18347168e7fd2d2c56fde2b6';
    const KAKAO_SECRET = context.env.KAKAO_SECRET || '';

    if (!code) {
      return new Response(JSON.stringify({ success: false, error: '인증 코드가 없습니다' }), {
        status: 400, headers: corsHeaders
      });
    }

    // 1. 인증 코드 → 액세스 토큰 교환
    const tokenRes = await fetch('https://kauth.kakao.com/oauth/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'authorization_code',
        client_id: KAKAO_REST_KEY,
        client_secret: KAKAO_SECRET || '',
        redirect_uri: redirect_uri || 'https://poomasi.org/join.html',
        code
      })
    });

    const tokens = await tokenRes.json();
    if (tokens.error) {
      return new Response(JSON.stringify({ success: false, error: tokens.error_description || tokens.error }), {
        status: 400, headers: corsHeaders
      });
    }

    // 2. 사용자 정보 조회 (CI 포함)
    const userRes = await fetch('https://kapi.kakao.com/v2/user/me', {
      headers: { 'Authorization': `Bearer ${tokens.access_token}` }
    });

    const user = await userRes.json();
    const account = user.kakao_account || {};

    // 3. 결과 반환 (CI + 본인확인 정보)
    return new Response(JSON.stringify({
      success: true,
      kakao_id: user.id,
      name: account.name || null,
      phone: account.phone_number || null,
      birthyear: account.birthyear || null,
      birthday: account.birthday || null,
      ci: account.ci || null,
      ci_authenticated_at: account.ci_authenticated_at || null,
    }), { headers: corsHeaders });

  } catch (err) {
    return new Response(JSON.stringify({ success: false, error: err.message }), {
      status: 500, headers: corsHeaders
    });
  }
}

export async function onRequestOptions() {
  return new Response(null, {
    headers: {
      'Access-Control-Allow-Origin': 'https://poomasi.org',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    }
  });
}
