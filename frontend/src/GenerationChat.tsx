import { usePolling } from './usePolling';
import { useEffect, useRef, useState } from 'react';
import { MarkdownPreview } from './MarkdownPreview';
import { apiRequest } from './api/http';
import { generationBase, generationError } from './generationApi';
import { Form } from './Form';
import { CliEventLog } from './CliEventLog';

type Turn = {
  id: number;
  question: string;
  answer: string;
  status: string;
  can_cancel: boolean;
  error_code: string;
  call_mode?: string;
};
function parse(value: unknown, functionKey: string): { items: Turn[]; hasMore: boolean } {
  if (
    !value ||
    typeof value !== 'object' ||
    !('items' in value) ||
    !Array.isArray(value.items) ||
    !('has_more' in value) ||
    typeof value.has_more !== 'boolean'
  )
    throw Error('generation_response_invalid');
  return {
    items: value.items.map((v: unknown) => {
      if (
        !v ||
        typeof v !== 'object' ||
        !('id' in v) ||
        typeof v.id !== 'number' ||
        !Number.isSafeInteger(v.id) ||
        v.id <= 0 ||
        !('function_key' in v) ||
        v.function_key !== functionKey ||
        !('question' in v) ||
        typeof v.question !== 'string' ||
        !('answer' in v) ||
        typeof v.answer !== 'string' ||
        !('status' in v) ||
        typeof v.status !== 'string' ||
        !('can_cancel' in v) ||
        typeof v.can_cancel !== 'boolean' ||
        !('error_code' in v) ||
        typeof v.error_code !== 'string'
      )
        throw Error('generation_response_invalid');
      return {
        id: v.id,
        question: v.question,
        answer: v.answer,
        status: v.status,
        can_cancel: v.can_cancel,
        error_code: v.error_code,
        call_mode: 'call_mode' in v && typeof v.call_mode === 'string' ? v.call_mode : undefined,
      };
    }),
    hasMore: value.has_more,
  };
}
export function GenerationChat({
  projectId,
  runId,
  functionKey,
  label,
  reference,
  onSessionEnd,
  onDraft,
  terminal = false,
}: {
  projectId: number;
  runId: string;
  functionKey: string;
  label: string;
  reference: string;
  onSessionEnd: () => void;
  onDraft: (turnId: number) => void;
  terminal?: boolean;
}) {
  const [turns, setTurns] = useState<Turn[]>([]),
    [question, setQuestion] = useState(''),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false),
    [hasMore, setHasMore] = useState(false);
  const controller = useRef<AbortController | null>(null),
    alive = useRef(true),
    requestId = useRef('');
  const base = `${generationBase(projectId)}/${runId}/chat`;
  const [reload, setReload] = useState(0);
  const active = turns.some((t) => ['QUEUED', 'RUNNING'].includes(t.status));
  useEffect(() => {
    alive.current = true;
    const c = new AbortController();
    controller.current = c;
    return () => {
      alive.current = false;
      c.abort();
    };
  }, [base, functionKey]);
  usePolling({
    active,
    interval: 2500,
    refreshKey: base + ':' + functionKey + ':' + reload,
    load: async (signal) => {
      try {
        const result = parse(
          await apiRequest<unknown>(`${base}?function_key=${encodeURIComponent(functionKey)}`, {
            signal: signal,
          }),
          functionKey,
        );
        if (!signal.aborted) {
          setTurns((old) =>
            [...old.filter((t) => !result.items.some((n) => n.id === t.id)), ...result.items].sort(
              (a, b) => a.id - b.id,
            ),
          );
          setHasMore(result.hasMore);
        }
      } catch (e) {
        if (!signal.aborted) setError(generationError(e, onSessionEnd));
      }
    },
  });
  async function send(path: string, body?: unknown) {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await apiRequest<unknown>(base + path, {
        method: 'POST',
        signal: controller.current?.signal,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (alive.current) setReload((value) => value + 1);
      if (alive.current && path === '') {
        setQuestion('');
        requestId.current = '';
      }
    } catch (e) {
      if (alive.current) setError(generationError(e, onSessionEnd));
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  return (
    <section className={`panel generation-chat-main${terminal ? ' cli-terminal-chat' : ''}`}>
      <div className="panel-head">
        <h2>
          {terminal ? 'CLI 对话 · ' : ''}
          {label}对话
        </h2>
      </div>
      <div className="code-chat-messages">
        {hasMore && (
          <button
            className="small"
            disabled={busy}
            onClick={() => {
              void (async () => {
                try {
                  const r = parse(
                    await apiRequest<unknown>(
                      `${base}?function_key=${encodeURIComponent(functionKey)}&before=${turns[0].id}`,
                      { signal: controller.current?.signal },
                    ),
                    functionKey,
                  );
                  if (alive.current) {
                    setTurns((old) => [...r.items, ...old]);
                    setHasMore(r.hasMore);
                  }
                } catch (e) {
                  if (alive.current) setError(generationError(e, onSessionEnd));
                }
              })();
            }}
          >
            加载更早对话
          </button>
        )}
        {!turns.length && <div className="empty">本记录/功能暂无对话。</div>}
        {turns.map((t) => (
          <article className="evidence" key={t.id}>
            <strong>提问</strong>
            <p>{t.question}</p>
            {terminal && t.call_mode === 'CODEX_EXEC' && (
              <CliEventLog url={`${base}/${t.id}/cli-events`} onSessionEnd={onSessionEnd} />
            )}
            <MarkdownPreview
              text={t.answer || `${t.status}${t.error_code ? ` · ${t.error_code}` : ''}`}
            />
            {t.can_cancel && (
              <button
                className="small"
                disabled={busy}
                onClick={() => void send(`/${t.id}/cancel`)}
              >
                取消本轮
              </button>
            )}
            {t.status === 'COMPLETED' && !terminal && (
              <button className="small" onClick={() => onDraft(t.id)}>
                人工添加为草案
              </button>
            )}
          </article>
        ))}
      </div>
      <Form
        className="generation-chat-compose"
        onSubmit={(e) => {
          e.preventDefault();
          if (!question.trim() || active) return;
          requestId.current ||= crypto.randomUUID();
          void send('', {
            request_id: requestId.current,
            function_key: functionKey,
            finding_key: reference,
            question,
            ...(terminal ? { cli_only: true } : {}),
          });
        }}
      >
        {reference && <p className="hint">当前引用：{reference}</p>}
        <label className="form-field">
          提问
          <textarea
            value={question}
            maxLength={10000}
            disabled={busy || active}
            onChange={(e) => {
              setQuestion(e.target.value);
              requestId.current = '';
            }}
          />
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <button className="primary" disabled={busy || active || !question.trim()}>
          {busy ? '提交中…' : active ? '回答处理中…' : '发送'}
        </button>
      </Form>
    </section>
  );
}
