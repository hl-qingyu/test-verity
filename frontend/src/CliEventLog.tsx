import { useEffect, useRef, useState } from 'react';
import { cliEvents } from './cliEventsApi';
import type { CliEvent, CliEvents } from './cliEventsApi';
import { generationError } from './generationApi';
import { FormSelect } from './FormSelect';
import './cli-workspace.css';

const names: Record<string, string> = {
  'thread.started': '会话开始',
  'turn.started': '本轮开始',
  'item.started': '操作开始',
  'item.updated': '操作更新',
  'item.completed': '操作结束',
  error: '错误 / 重连',
  'turn.failed': '本轮失败',
  'turn.completed': '本轮结束（结果仍需校验）',
};

export function CliEventLog({ url, onSessionEnd }: { url: string; onSessionEnd: () => void }) {
  const [events, setEvents] = useState<CliEvent[]>([]);
  const [meta, setMeta] = useState<CliEvents | null>(null);
  const [attempt, setAttempt] = useState<number>();
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [follow, setFollow] = useState(true);
  const output = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const controller = new AbortController();
    let cursor = 0,
      timer: number | undefined,
      resolvedAttempt = attempt;
    setEvents([]);
    setMeta(null);
    setError('');
    async function read() {
      try {
        const result = await cliEvents(url, cursor, controller.signal, resolvedAttempt);
        if (controller.signal.aborted) return;
        if (result.attempt_index >= 0) resolvedAttempt = result.attempt_index;
        cursor = result.next_cursor;
        setMeta(result);
        setError('');
        if (result.items.length) setEvents((old) => [...old, ...result.items].slice(-200));
        if (result.has_more || ['QUEUED', 'RUNNING'].includes(result.status)) {
          timer = window.setTimeout(() => void read(), result.has_more ? 50 : 1500);
        }
      } catch (e) {
        if (!controller.signal.aborted) setError(generationError(e, onSessionEnd));
      }
    }
    void read();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [url, attempt, reload, onSessionEnd]);
  useEffect(() => {
    if (follow && output.current) output.current.scrollTop = output.current.scrollHeight;
  }, [events, follow]);
  return (
    <section className="cli-event-panel" aria-label="CLI执行记录">
      <div className="row cli-event-toolbar">
        <strong>CLI 执行记录</strong>
        {meta && (
          <span className="hint">
            {meta.status} · 已读取 {meta.next_cursor} 条事件
          </span>
        )}
        <button
          type="button"
          className="small"
          aria-pressed={follow}
          onClick={() => setFollow(!follow)}
        >
          {follow ? '跟随最新：开' : '跟随最新：关'}
        </button>
        <button type="button" className="small" onClick={() => setReload((v) => v + 1)}>
          重新读取
        </button>
      </div>
      {meta && meta.attempts.length > 1 && (
        <FormSelect
          label="执行历史"
          value={String(attempt ?? meta.attempt_index)}
          onChange={(value) => setAttempt(Number(value))}
          options={meta.attempts.map((a) => ({
            value: String(a.index),
            label: `第 ${a.index + 1} 次 · ${a.status}${a.started_at ? ` · ${new Date(a.started_at).toLocaleString()}` : ''}`,
          }))}
        />
      )}
      <div
        ref={output}
        className="cli-event-output"
        tabIndex={0}
        role="region"
        aria-label="CLI事件时间线"
      >
        {!meta && !error && <p>正在读取执行记录…</p>}
        {meta && !events.length && (
          <p>
            {meta.available
              ? '本次没有可展示事件。'
              : ['QUEUED', 'RUNNING'].includes(meta.status)
                ? '等待执行事件…'
                : '暂无可读取的 CLI 事件。'}
          </p>
        )}
        {events.map((e) => (
          <article
            key={e.sequence}
            className={['error', 'turn.failed'].includes(e.type) ? 'cli-event-error' : ''}
          >
            <span className="cli-event-heading">
              #{e.sequence} · {e.at ? new Date(e.at).toLocaleTimeString() : '历史事件（无时间戳）'}{' '}
              · {names[e.type] || e.type}
            </span>
            {e.text && <pre>{e.text}</pre>}
            {e.truncated && <p>本条仅展开前 16000 字符，完整候选或原始记录仍保留。</p>}
          </article>
        ))}
      </div>
      {meta && ['QUEUED', 'RUNNING'].includes(meta.status) && (
        <p className="hint">自动读取新事件；没有新事件不代表模型正在处理。关闭窗口不停止任务。</p>
      )}
      {meta && meta.next_cursor > 200 && (
        <p className="hint">当前显示最近 200 条，完整记录保留在后端。</p>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
