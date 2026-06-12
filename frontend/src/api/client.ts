import type { ApiEnvelope } from '../types/api';

export async function apiGet<T>(path: string): Promise<ApiEnvelope<T>> {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  });
  if (response.status === 401 || response.redirected) {
    window.location.assign('/login');
    throw new Error('登录状态已失效');
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `请求失败（${response.status}）`);
  }
  return response.json() as Promise<ApiEnvelope<T>>;
}
