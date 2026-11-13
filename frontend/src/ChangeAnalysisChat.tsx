import { callModeName } from './aiConfiguration';
import { useEffect, useRef, useState } from 'react';
import { Form } from './Form';
import { codeErrors, codeRequest, codeStates, codeTurns, parseCodeTurn } from './codeAnalysisApi';
import type { CodeTurn } from './codeAnalysisApi';
import type { PageChangeRecord } from './changeAnalysisPage';
import { changeError, changeErrors } from './changeAnalysisApi';

export function ChangeAnalysisChat({
  record,
  findingKey,
  onClearFinding,
  onSessionEnd,
}: {
  record: PageChangeRecord;
  findingKey: string;
  onClearFinding: () => void;
  onSessionEnd: () => void;
}) {
  const [turns, setTurns] = useState<CodeTurn[]>([]),
    [question, setQuestion] = useState(''),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true),
    [hasMore, setHasMore] = useState(false),
    [loadingMore, setLoadingMore] = useState(false),
    [reload, setReload] = useState(0);
  const controller = useRef(new AbortController()),
    loadedEarlier = useRef(false),
    pending = useRef(false),
    request = useRef({ id: crypto.randomUUID(), signature: '' });
  const base = `/api/projects/${record.projectId}/change-analysis/${record.id}/chat`;
  useEffect(() => {
    const c = new AbortController();
    controller.current = c;
    return () => c.abort();
  }, []);
  useEffect(() => {
    const c = new AbortController();
    let polling = false;
    async function refresh() {
      if (polling) return;
      polling = true;
      try {
        const result = await codeTurns(base, c.signal);
        if (!c.signal.aborted) {
          setTurns((old) =>
            [...new Map([...old, ...result.items].map((turn) => [turn.id, turn])).values()].sort(
              (a, b) => a.id - b.id,
            ),
          );
          if (!loadedEarlier.current) setHasMore(result.has_more);
          setError('');
        }
      } catch (reason) {
        if (!c.signal.aborted) setError(changeError(reason, onSessionEnd));
      } finally {
        polling = false;
        if (!c.signal.aborted) setLoading(false);
      }
    }
    void refresh();
    const timer = setInterval(() => void refresh(), 3500);
    return () => {
      clearInterval(timer);
      c.abort();
    };
  }, [base, onSessionEnd, reload]);
  async function earlier() {
    if (loadingMore || !turns.length) return;
    setLoadingMore(true);
    try {
      const result = await codeTurns(`${base}?before=${turns[0].id}`, controller.current.signal);
      if (!controller.current.signal.aborted) {
        setTurns((old) =>
          [...new Map([...result.items, ...old].map((turn) => [turn.id, turn])).values()].sort(
            (a, b) => a.id - b.id,
          ),
        );
        loadedEarlier.current = true;
        setHasMore(result.has_more);
      }
    } catch (reason) {
      if (!controller.current.signal.aborted) setError(changeError(reason, onSessionEnd));
    } finally {
      if (!controller.current.signal.aborted) setLoadingMore(false);
    }
  }
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current || !question.trim()) return;
    pending.current = true;
    setBusy(true);
    setError('');
    const signature = question + '\n' + findingKey;
    if (request.current.signature !== signature)
      request.current = { id: crypto.randomUUID(), signature };
    try {
      const turn = await codeRequest(base, parseCodeTurn, {
        method: 'POST',
        signal: controller.current.signal,
        body: JSON.stringify({
          request_id: request.current.id,
          question: question.trim(),
          finding_key: findingKey,
        }),
      });
      if (!controller.current.signal.aborted) {
        setTurns((old) => [...old.filter((v) => v.id !== turn.id), turn]);
        setQuestion('');
        request.current = { id: crypto.randomUUID(), signature: '' };
        onClearFinding();
        setReload((v) => v + 1);
      }
    } catch (reason) {
      if (!controller.current.signal.aborted) setError(changeError(reason, onSessionEnd));
    } finally {
      pending.current = false;
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  async function cancel(turn: CodeTurn) {
    if (busy) return;
    setBusy(true);
    try {
      const updated = await codeRequest(`${base}/${turn.id}/cancel`, parseCodeTurn, {
        method: 'POST',
        signal: controller.current.signal,
      });
      if (!controller.current.signal.aborted)
        setTurns((old) => old.map((item) => (item.id === updated.id ? updated : item)));
    } catch (reason) {
      if (!controller.current.signal.aborted) setError(changeError(reason, onSessionEnd));
    } finally {
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  const active = turns.some((turn) => turn.status === 'QUEUED' || turn.status === 'RUNNING'),
    allowed = record.status === 'COMPLETED' && !!record.structured;
  return (
    <section className="panel code-chat-main">
      <div className="panel-head">
        <div>
          <h2>{record.title} · 对话</h2>
          <p className="hint">固定双侧内容和选定范围 · 仅本记录上下文</p>
        </div>
      </div>
      <div className="code-chat-messages">
        {hasMore && (
          <button className="ghost small" disabled={loadingMore} onClick={() => void earlier()}>
            {loadingMore ? '加载中…' : '更早的对话'}
          </button>
        )}
        {loading && <p role="status">正在加载对话…</p>}
        {!loading && !turns.length && (
          <p className="hint">暂无历史对话。可以询问调用链、字段映射或证据缺口。</p>
        )}
        {turns.map((turn) => (
          <div className="code-chat-turn" key={turn.id}>
            <article className="code-chat-message mine">
              <strong>用户提问</strong>
              {turn.finding_key && <span className="badge">引用 {turn.finding_key}</span>}
              <p>{turn.question}</p>
              <small className="hint">{new Date(turn.created_at).toLocaleString()}</small>
            </article>
            <article className="code-chat-message">
              <strong>AI · 变更分析</strong>
              <span className="hint">
                {' '}
                · {callModeName(turn.ai.call_mode)} · {turn.ai.name} · {turn.ai.model} ·{' '}
                {codeStates[turn.status]}
              </span>
              {turn.answer ? (
                <p>{turn.answer}</p>
              ) : (
                <p className="hint">
                  {turn.error_code
                    ? changeErrors[turn.error_code] ||
                      codeErrors[turn.error_code] ||
                      '本轮未完成，可核对原因后重新提问。'
                    : turn.status === 'CANCELLED'
                      ? '已取消，未保存完整回答。'
                      : '等待完整回复…'}
                </p>
              )}
              {turn.can_cancel && (
                <button className="ghost small" disabled={busy} onClick={() => void cancel(turn)}>
                  取消本轮
                </button>
              )}
            </article>
          </div>
        ))}
      </div>
      <Form className="code-chat-compose" onSubmit={(event) => void submit(event)}>
        {findingKey && (
          <div className="row">
            <span className="badge">引用发现：{findingKey}</span>
            <button type="button" className="link" onClick={onClearFinding}>
              取消引用
            </button>
          </div>
        )}
        <label className="form-field">
          继续询问变更问题
          <textarea
            required
            maxLength={10000}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            disabled={!allowed || busy || active}
            placeholder="例如：请核对这条调用链还缺少哪些证据"
          />
        </label>
        <p className="hint">
          使用你的个人AI配置；仅携带当前分析的固定输入、报告、处理和本对话历史。回答不会自动修改发现。
        </p>
        {!allowed && <p className="hint">需先完成或导入变更分析报告。</p>}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <button className="primary" disabled={!allowed || busy || active}>
          {active ? '本记录有对话处理中…' : busy ? '提交中…' : '发送'}
        </button>
      </Form>
    </section>
  );
}
