import { Form } from './Form';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { postEncrypted } from './passwordTransport';
import type { PlatformRole } from './accountRoles';

export type User = {
  id: number;
  login_name: string;
  display_name: string;
  platform_role: PlatformRole;
};

export const authMessages: Record<number, string> = {
  400: '安全校验已失效，请重新点击登录。',
  401: '账号或密码错误，请重新输入',
  403: '当前访问地址未获允许，请联系管理员。',
  422: '账号或密码错误，请重新输入',
  429: '尝试次数过多，请稍后再试。连续输错5次后需等待15分钟。',
  503: '服务暂不可用，请稍后重试。',
};

export function useAuth(pathname: string) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const generation = useRef(0);
  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  const updateUser = useCallback((value: User | null) => {
    generation.current += 1;
    setUser(value);
    setError('');
    setLoading(false);
  }, []);

  useEffect(() => {
    const current = ++generation.current;
    const controller = new AbortController();
    async function check() {
      try {
        const response = await fetch('/api/auth/me', {
          cache: 'no-store',
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10000)]),
        });
        if (!response.ok && response.status !== 401) throw new Error('unavailable');
        const nextUser: User | null = response.ok ? await response.json() : null;
        if (current === generation.current) {
          setUser(nextUser);
          setError('');
        }
      } catch {
        if (current === generation.current && !controller.signal.aborted) {
          setError('暂时无法连接服务，请重试。');
        }
      } finally {
        if (current === generation.current) setLoading(false);
      }
    }
    void check();
    return () => controller.abort();
  }, [pathname, revision]);

  useEffect(() => {
    function checkVisible() {
      if (document.visibilityState === 'visible') refresh();
    }
    window.addEventListener('focus', checkVisible);
    document.addEventListener('visibilitychange', checkVisible);
    const timer = window.setInterval(checkVisible, 60000);
    return () => {
      window.removeEventListener('focus', checkVisible);
      document.removeEventListener('visibilitychange', checkVisible);
      window.clearInterval(timer);
    };
  }, [refresh]);

  return { user, loading, error, refresh, updateUser };
}

export function AuthStatus({ error, onRetry }: { error: string; onRetry: () => void }) {
  return (
    <main className="login-page">
      <section className="panel login-card" aria-live="polite">
        <h1>质序</h1>
        <p className="muted mt">{error || '正在确认登录状态…'}</p>
        {error && (
          <button className="primary mt" onClick={onRetry}>
            重新连接
          </button>
        )}
      </section>
    </main>
  );
}

export function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    setError('');
    try {
      const response = await postEncrypted('/api/auth/login', {
        login_name: String(data.get('login_name')).trim(),
        password: String(data.get('password')),
      });
      if (!response.ok) {
        setError(authMessages[response.status] || '登录失败，请稍后重试。');
        return;
      }
      const user: User = await response.json();
      form.reset();
      onLogin(user);
    } catch {
      setError(
        !globalThis.crypto?.subtle
          ? '当前浏览器无法安全提交密码，请使用HTTPS、本机地址，或启用此地址的局域网试用设置后重启浏览器。'
          : '连接失败，请检查网络后重试。',
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-page">
      <section className="panel login-card" aria-labelledby="login-heading">
        <div className="brand login-brand">
          <div className="brand-mark">v</div>
          <div>
            <strong>质序</strong>
            <small>VERITY / AI QUALITY</small>
          </div>
        </div>
        <h1 id="login-heading">欢迎登录</h1>
        <p className="muted smalltext mt">从需求到实现，让质量判断有据可依。</p>
        <Form
          className="stack mt"
          validationMessage={authMessages[401]}
          onSubmitCapture={() => setError('')}
          onSubmit={submit}
        >
          <label className="form-field">
            账号
            <input
              name="login_name"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              minLength={3}
              maxLength={64}
              placeholder="请输入账号"
              required
              disabled={busy}
            />
          </label>
          <label className="form-field" htmlFor="login-password">
            密码
          </label>
          <div className="password-field">
            <input
              id="login-password"
              name="password"
              type={showPassword ? 'text' : 'password'}
              autoComplete="current-password"
              maxLength={128}
              placeholder="请输入密码"
              required
              disabled={busy}
            />
            <button
              type="button"
              className="ghost small"
              aria-pressed={showPassword}
              aria-controls="login-password"
              onClick={() => setShowPassword(!showPassword)}
            >
              {showPassword ? '隐藏密码' : '显示密码'}
            </button>
          </div>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button className="primary full" type="submit" disabled={busy}>
            {busy ? '正在登录…' : '登录'}
          </button>
        </Form>
        <p className="hint mt">账号由平台管理员创建。</p>
      </section>
      <p className="login-footer">VERITY · 让每一个质量判断都有依据</p>
    </main>
  );
}
