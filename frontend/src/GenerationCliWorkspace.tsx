import { useEffect, useRef, useState } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { apiRequest } from './api/http';
import { generationBase, generationError } from './generationApi';
import {
  parseTerminalFrame,
  sessionResponse,
  terminalSocket,
  terminalEnabled,
  nativeSessionUrl,
  nativeSessionLabel,
  nativeTurnFailure,
} from './nativeTerminalApi';
import type { NativeSession } from './nativeTerminalApi';
import './cli-workspace.css';
import { NativeResultReview } from './NativeResultReview';

export function GenerationCliWorkspace({
  projectId,
  runId,
  onSessionEnd,
  onClose,
  open = true,
  label = '整体',
  reference = '',
  resultRevision,
  onSaveResult,
  onReviewResult,
}: {
  projectId: number;
  runId: string;
  onSessionEnd: () => void;
  onClose: () => void;
  open?: boolean;
  label?: string;
  reference?: string;
  resultRevision?: number;
  onSaveResult?: (id: string, requestId: string) => Promise<boolean>;
  onReviewResult?: (id: string) => void;
}) {
  const [session, setSession] = useState<NativeSession | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [bound, setBound] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [replaying, setReplaying] = useState(true);
  const [reviewResult, setReviewResult] = useState(false);
  const restoring = useRef(true);
  const allowed = useRef(false);
  const attached = useRef(false);
  const visible = useRef(open);
  visible.current = open;
  const received = useRef(0);
  const sessionEndHandler = useRef(onSessionEnd);
  sessionEndHandler.current = onSessionEnd;
  const closeHandler = useRef(onClose);
  closeHandler.current = onClose;
  const host = useRef<HTMLDivElement>(null);
  const terminal = useRef<Terminal | null>(null);
  const fit = useRef<FitAddon | null>(null);
  const controller = useRef<AbortController | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const selected = useRef<NativeSession | null>(null);
  selected.current = session;
  const sessionId = session?.id;
  const base = `${generationBase(projectId)}/${runId}/terminal`;
  const streamUrl = session ? nativeSessionUrl(base, session) : '';
  const epoch = session?.epoch;

  useEffect(() => {
    const c = new AbortController();
    controller.current = c;
    const term = new Terminal({
      cursorBlink: true,
      disableStdin: true,
      fontSize: 14,
      fontFamily: 'Consolas, monospace',
      scrollback: 5000,
      allowProposedApi: false,
      theme: { background: '#122d29', foreground: '#e2eee9' },
    });
    const addon = new FitAddon();
    term.attachCustomKeyEventHandler((event) => {
      if (event.key !== 'Escape') return true;
      if (event.type === 'keydown') {
        event.preventDefault();
        event.stopPropagation();
        closeHandler.current();
      }
      return false;
    });
    term.loadAddon(addon);
    terminal.current = term;
    fit.current = addon;
    if (host.current) {
      term.open(host.current);
      addon.fit();
    }
    function send(command: unknown) {
      const s = selected.current;
      if (
        !visible.current ||
        !attached.current ||
        !allowed.current ||
        !s ||
        !['QUEUED', 'RUNNING'].includes(s.status)
      )
        return;
      if (socket.current?.readyState === WebSocket.OPEN)
        socket.current.send(JSON.stringify(command));
    }
    const data = term.onData((raw) => {
      for (let i = 0; i < raw.length; i += 4096)
        send({ type: 'input', data: raw.slice(i, i + 4096) });
    });
    const observer = new ResizeObserver(() => {
      if (!visible.current || restoring.current) return;
      addon.fit();
      send({ type: 'resize', rows: Math.max(8, term.rows), cols: Math.max(20, term.cols) });
    });
    if (host.current) observer.observe(host.current);
    return () => {
      c.abort();
      attached.current = false;
      data.dispose();
      observer.disconnect();
      term.dispose();
      terminal.current = null;
    };
  }, [base]);

  useEffect(() => {
    const term = terminal.current;
    if (!term) return;
    term.options.disableStdin =
      !open ||
      !allowed.current ||
      !attached.current ||
      !selected.current ||
      !['QUEUED', 'RUNNING'].includes(selected.current.status);
    if (!open) return;
    if (!restoring.current) fit.current?.fit();
    term.scrollToBottom();
    const c = new AbortController();
    // Recheck access and the current attempt, while retaining the existing screen/socket.
    void apiRequest<unknown>(base, { signal: c.signal })
      .then((r) => {
        if (!c.signal.aborted) {
          const saved = sessionResponse(r);
          setSession(saved);
          if (!saved) setReplaying(false);
          setBound(
            !!r && typeof r === 'object' && 'generation_bound' in r && r.generation_bound === true,
          );
          setLoaded(true);
          allowed.current = terminalEnabled(r);
          setEnabled(allowed.current);
          term.options.disableStdin = !visible.current || !allowed.current || !attached.current;
        }
      })
      .catch((e) => {
        if (!c.signal.aborted) {
          setError(generationError(e, sessionEndHandler.current));
          setReplaying(false);
        }
      });
    return () => c.abort();
  }, [base, open]);

  useEffect(() => {
    if (!sessionId) return;
    let disposed = false,
      timer: number | undefined;
    received.current = 0;
    attached.current = false;
    if (terminal.current) terminal.current.options.disableStdin = true;
    terminal.current?.reset();
    restoring.current = true;
    terminal.current?.resize(
      selected.current?.replay_cols || 110,
      selected.current?.replay_rows || 30,
    );
    setReplaying(true);
    function connect() {
      if (disposed) return;
      const ws = terminalSocket(streamUrl, received.current);
      let replayDelivered = false;
      socket.current = ws;
      ws.onopen = () => {
        if (disposed || socket.current !== ws) return;
        attached.current = false;
        if (!received.current) setReplaying(true);
        if (terminal.current) terminal.current.options.disableStdin = true;
        setError('');
      };
      ws.onmessage = (event) => {
        if (disposed || socket.current !== ws) return;
        try {
          const frame = parseTerminalFrame(String(event.data));
          if (frame.type === 'output') {
            const term = terminal.current;
            let offset = 0;
            for (const size of frame.resizes) {
              term?.write(frame.chunks.slice(offset, size.index).join(''), () => {
                if (!disposed) term.resize(size.cols, size.rows);
              });
              offset = size.index;
            }
            term?.write(frame.chunks.slice(offset).join(''));
            received.current += frame.chunks.length;
          } else if (frame.type === 'ready') {
            replayDelivered = true;
            const term = terminal.current;
            // xterm parses writes asynchronously. Enable input only after every
            // recorded query has been rendered with disableStdin still set.
            term?.write('', () => {
              if (disposed || socket.current !== ws) return;
              restoring.current = false;
              if (visible.current) fit.current?.fit();
              // Restore the screen offscreen, then reveal only its latest viewport.
              // Completed sessions may close their socket before this callback runs.
              term.scrollToBottom();
              setReplaying(false);
              if (ws.readyState !== WebSocket.OPEN) return;
              attached.current = true;
              term.options.disableStdin =
                !visible.current ||
                !allowed.current ||
                !selected.current ||
                !['QUEUED', 'RUNNING'].includes(selected.current.status);
              if (visible.current && allowed.current)
                ws.send(
                  JSON.stringify({
                    type: 'resize',
                    rows: Math.min(120, Math.max(8, term.rows)),
                    cols: Math.min(300, Math.max(20, term.cols)),
                  }),
                );
            });
          } else if (frame.session) {
            selected.current = frame.session;
            setSession(frame.session);
            if (terminal.current && attached.current)
              terminal.current.options.disableStdin =
                !visible.current ||
                !allowed.current ||
                !['QUEUED', 'RUNNING'].includes(frame.session.status);
            if (frame.session.error_code)
              setError(
                generationError(new Error(frame.session.error_code), sessionEndHandler.current),
              );
          }
        } catch (e) {
          setError(generationError(e, sessionEndHandler.current));
        }
      };
      ws.onclose = () => {
        if (disposed || socket.current !== ws) return;
        attached.current = false;
        if (terminal.current) terminal.current.options.disableStdin = true;
        if (selected.current && ['QUEUED', 'RUNNING'].includes(selected.current.status)) {
          setError('终端连接中断，正在重新连接同一进程…');
          timer = window.setTimeout(connect, 1500);
        } else if (!replayDelivered) {
          setError('终端画面恢复中断，请关闭后重新打开。');
        }
      };
    }
    connect();
    return () => {
      disposed = true;
      attached.current = false;
      window.clearTimeout(timer);
      socket.current?.close();
      socket.current = null;
    };
  }, [streamUrl, sessionId, epoch]);

  async function start(resume: boolean) {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const term = terminal.current;
      const response = await apiRequest<unknown>(base, {
        method: 'POST',
        signal: controller.current?.signal,
        body: JSON.stringify({
          request_id: crypto.randomUUID(),
          resume,
          rows: Math.max(8, term?.rows || 30),
          cols: Math.max(20, term?.cols || 110),
        }),
      });
      setSession(sessionResponse(response));
      term?.focus();
    } catch (e) {
      setError(generationError(e, sessionEndHandler.current));
    } finally {
      setBusy(false);
    }
  }
  async function stop() {
    if (!session || busy) return;
    setBusy(true);
    try {
      await apiRequest(
        session.kind === 'generation'
          ? `${generationBase(projectId)}/${runId}/cancel`
          : `${generationBase(projectId)}/${runId}/chat/${session.id}/cancel`,
        {
          method: 'POST',
          signal: controller.current?.signal,
        },
      );
      setSession({ ...session, status: 'CANCELLED' });
    } catch (e) {
      setError(generationError(e, sessionEndHandler.current));
    } finally {
      setBusy(false);
    }
  }
  const active = !!session && ['QUEUED', 'RUNNING'].includes(session.status);
  const failure = error || nativeTurnFailure(session);
  return (
    <section
      className="panel generation-chat-main native-cli-workspace"
      hidden={!open}
      aria-label="用例生成历史对话"
    >
      <div className="panel-head">
        <h2>{label}对话</h2>
        <span className="badge">Codex CLI</span>
      </div>
      <div className="panel-pad">
        {reference && <p className="hint">当前引用：{reference}</p>}
        <div className="row cli-event-toolbar">
          {bound && (
            <button
              className="primary small"
              disabled={busy || active || !enabled}
              onClick={() => void start(true)}
            >
              继续同一 CLI 对话（可能计费）
            </button>
          )}
          {active && (
            <button className="small danger" disabled={busy} onClick={() => void stop()}>
              {session?.kind === 'generation' ? '取消生成' : '结束对话进程'}
            </button>
          )}
          <span className="hint">{nativeSessionLabel(session)}</span>
          {bound && onSaveResult && (
            <button
              className="small"
              onClick={() => setReviewResult((value) => !value)}
              aria-expanded={reviewResult}
            >
              {reviewResult ? '收起结果' : '查看或手动保存 CLI 结果'}
            </button>
          )}
        </div>
        {reviewResult && onSaveResult && (
          <NativeResultReview
            base={base}
            resultRevision={resultRevision}
            onSessionEnd={onSessionEnd}
            onSave={onSaveResult}
            onReview={onReviewResult}
          />
        )}
        <div
          className={`native-cli-container${replaying ? ' is-restoring' : ''}`}
          aria-busy={replaying}
        >
          <div ref={host} className="native-cli-surface" aria-label="Codex CLI 原生终端" />
          {replaying && (
            <p className="native-cli-restoring" role="status">
              <span className="native-cli-restoring-label">
                {!error && <span className="generation-spinner" aria-hidden="true" />}
                <span>{error ? '终端画面尚未恢复完成。' : '正在恢复终端最新画面…'}</span>
              </span>
            </p>
          )}
        </div>
        {!enabled && (
          <p className="notice">
            {!loaded
              ? '正在关联生成会话…'
              : !bound
                ? '此记录未关联 CLI 生成会话，仅可查看历史。'
                : '当前账号未启用 CLI，可查看历史画面。'}
          </p>
        )}
        {failure && (
          <p className="form-error" role="alert">
            {failure}
          </p>
        )}
      </div>
    </section>
  );
}
