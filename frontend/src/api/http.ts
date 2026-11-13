import { postEncrypted } from '../passwordTransport';

type RequestOptions = RequestInit & { timeoutMs?: number };

async function responseJSON<T>(response: Response): Promise<T> {
  if (response.status === 401) throw new Error('not_authenticated');
  const body: unknown = await response.json();
  if (!response.ok) {
    const detail =
      body !== null && typeof body === 'object' && 'detail' in body ? body.detail : undefined;
    throw new Error(typeof detail === 'string' ? detail : 'invalid_request');
  }
  // T documents the endpoint contract; business-specific validation belongs to its API module.
  return body as T;
}

async function apiFetch(path: string, options: RequestOptions = {}): Promise<Response> {
  const { timeoutMs = 130000, signal, ...request } = options;
  const timeoutSignal = AbortSignal.timeout(timeoutMs);
  const headers = new Headers(request.headers);
  if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  return fetch(path, {
    ...request,
    headers,
    cache: 'no-store',
    signal: signal ? AbortSignal.any([signal, timeoutSignal]) : timeoutSignal,
  });
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return responseJSON<T>(await apiFetch(path, options));
}

export async function apiDownload(path: string, options: RequestOptions = {}): Promise<Blob> {
  const response = await apiFetch(path, options);
  if (!response.ok) await responseJSON(response);
  return response.blob();
}

export async function encryptedRequest<T>(
  path: string,
  payload: Record<string, unknown>,
  timeoutMs = 190000,
): Promise<T> {
  return responseJSON<T>(await postEncrypted(path, payload, timeoutMs));
}

export function apiErrorMessage(
  error: unknown,
  onSessionEnd: () => void,
  messages: Record<string, string>,
): string {
  if (error instanceof Error && error.message === 'not_authenticated') {
    onSessionEnd();
    return '登录状态已失效。';
  }
  return error instanceof Error && messages[error.message]
    ? messages[error.message]
    : '连接中断或响应异常，操作结果尚未确认。请重新加载核对。';
}
