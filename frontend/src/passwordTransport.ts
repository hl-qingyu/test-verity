type Challenge = { challenge_id: string; public_key: string; expires_in: number };

function base64(bytes: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)));
}

export async function postEncrypted(
  path: string,
  payload: Record<string, unknown>,
  timeout = 15000,
): Promise<Response> {
  if (!globalThis.crypto?.subtle) {
    throw new Error('当前环境无法安全提交密码，请使用HTTPS或本机地址。');
  }
  const challengeResponse = await fetch('/api/auth/password-challenge', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
    cache: 'no-store',
    signal: AbortSignal.timeout(10000),
  });
  if (!challengeResponse.ok) return challengeResponse;
  const challenge: Challenge = await challengeResponse.json();
  const publicKey = await crypto.subtle.importKey(
    'spki',
    Uint8Array.from(atob(challenge.public_key), (character) => character.charCodeAt(0)),
    { name: 'RSA-OAEP', hash: 'SHA-256' },
    false,
    ['encrypt'],
  );
  const key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt']);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const aad = new TextEncoder().encode(
    `verity-password-v1\nPOST\n${path}\n${challenge.challenge_id}`,
  );
  const ciphertext = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv, additionalData: aad, tagLength: 128 },
    key,
    new TextEncoder().encode(JSON.stringify(payload)),
  );
  const wrappedKey = await crypto.subtle.encrypt(
    { name: 'RSA-OAEP', label: aad },
    publicKey,
    await crypto.subtle.exportKey('raw', key),
  );
  return fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      challenge_id: challenge.challenge_id,
      wrapped_key: base64(wrappedKey),
      iv: base64(iv.buffer),
      ciphertext: base64(ciphertext),
    }),
    signal: AbortSignal.timeout(timeout),
  });
}
