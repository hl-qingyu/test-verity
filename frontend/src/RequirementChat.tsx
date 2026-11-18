import { callModeName, readSelectedAI } from './aiConfiguration';
import { PageJump } from './PageJump';
import { useEffect, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { CaseDialog } from './CaseDialog';
import { Form } from './Form';
import { FormSelect } from './FormSelect';
import { apiRequest } from './api/http';
import {
  chatError,
  chatFailure,
  chatHistory,
  chatSend,
  chatStates,
  parseChatTurn,
} from './chatApi';
import type { ChatTurn } from './chatApi';
import {
  parseManualRisk,
  riskDetailRequest,
  riskError,
  riskLevels,
  riskListing,
  riskTypes,
} from './riskApi';
import type { RiskDetail, ReportItem } from './riskApi';
import type { Project } from './Projects';
import './requirement-chat.css';
import './requirement-ui.css';

function merge(rows: ChatTurn[], incoming: ChatTurn[]) {
  const map = new Map(rows.map((row) => [row.id, row]));
  for (const row of incoming) map.set(row.id, row);
  return [...map.values()].sort((a, b) => a.id - b.id);
}

export function RequirementChat({
  project,
  onSessionEnd,
}: {
  project: Project | null;
  onSessionEnd: () => void;
}) {
  const { reportId: raw } = useParams();
  const [search] = useSearchParams();
  const reportId = Number(raw);
  const functionKey = search.get('function') || '';
  const riskKey = search.get('risk') || '';
  // A keyed child prevents response, draft or request identity leaking to another conversation.
  if (!project || !Number.isSafeInteger(reportId) || reportId < 1)
    return <p>请选择有效的需求分析记录。</p>;
  return (
    <Chat
      key={`${project.id}:${reportId}:${functionKey}`}
      project={project}
      reportId={reportId}
      functionKey={functionKey}
      riskKey={riskKey}
      onSessionEnd={onSessionEnd}
    />
  );
}

function Chat({
  project,
  reportId,
  functionKey,
  riskKey,
  onSessionEnd,
}: {
  project: Project;
  reportId: number;
  functionKey: string;
  riskKey: string;
  onSessionEnd: () => void;
}) {
  const base = `/api/projects/${project.id}/requirements/risk-reports`;
  const endpoint = `${base}/${reportId}/chat`;
  const [detail, setDetail] = useState<RiskDetail | null>(null),
    [turns, setTurns] = useState<ChatTurn[]>([]);
  const [records, setRecords] = useState<ReportItem[]>([]),
    [recordPage, setRecordPage] = useState(1),
    [recordMore, setRecordMore] = useState(false),
    [recordLoading, setRecordLoading] = useState(true);
  const [hasMore, setHasMore] = useState(false),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState(''),
    [error, setError] = useState(''),
    [config, setConfig] = useState('正在读取个人AI配置…');
  const [notice, setNotice] = useState('');
  const [adding, setAdding] = useState<ChatTurn | null>(null);
  const [recordQuery, setRecordQuery] = useState('');
  const controller = useRef(new AbortController()),
    pending = useRef(false),
    latest = useRef(0);
  const request = useRef<{
    request_id: string;
    question: string;
    last_turn_id: number;
    risk_key?: string;
  } | null>(null);

  useEffect(() => {
    const c = new AbortController();
    controller.current = c;
    let firstLoad = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const data = await chatHistory(endpoint, reportId, c.signal, undefined, functionKey);
        if (c.signal.aborted) return;
        latest.current = data.items.at(-1)?.id || 0;
        setTurns((old) => merge(old, data.items));
        if (firstLoad) {
          setHasMore(data.has_more);
          firstLoad = false;
        }
        setLoading(false);
      } catch (reason) {
        if (!c.signal.aborted) {
          setError(chatError(reason, onSessionEnd));
          setLoading(false);
          if (
            reason instanceof Error &&
            [
              'not_authenticated',
              'project_not_found',
              'project_access_denied',
              'risk_report_not_found',
            ].includes(reason.message)
          ) {
            setDetail(null);
            setTurns([]);
            setRecords([]);
            c.abort();
          }
        }
      } finally {
        if (!c.signal.aborted) timer = setTimeout(poll, 2500);
      }
    }
    void poll();
    riskDetailRequest(`${base}/${reportId}`, project.id, { signal: c.signal })
      .then((v) => {
        if (!c.signal.aborted) setDetail(v);
      })
      .catch((reason) => {
        if (!c.signal.aborted) setError(chatError(reason, onSessionEnd));
      });
    readSelectedAI(c.signal)
      .then((v) => {
        if (!c.signal.aborted)
          setConfig(
            v.personal
              ? `${callModeName(v.personal.call_mode)} · ${v.personal.name} · ${v.personal.model}`
              : '尚未配置个人AI服务',
          );
      })
      .catch((reason) => {
        if (!c.signal.aborted) setError(chatError(reason, onSessionEnd));
      });
    return () => {
      c.abort();
      clearTimeout(timer);
    };
  }, [base, endpoint, reportId, project.id, functionKey, onSessionEnd]);

  useEffect(() => {
    const c = new AbortController();
    setRecordLoading(true);
    riskListing(`${base}?page=${recordPage}`, c.signal)
      .then((v) => {
        if (!c.signal.aborted) {
          setRecords(v.items);
          setRecordMore(v.has_more);
        }
      })
      .catch((reason) => {
        if (!c.signal.aborted) setError(chatError(reason, onSessionEnd));
      })
      .finally(() => {
        if (!c.signal.aborted) setRecordLoading(false);
      });
    return () => c.abort();
  }, [base, recordPage, onSessionEnd]);

  async function send() {
    if (pending.current) return;
    const question = draft.trim();
    if (!question) return;
    pending.current = true;
    setBusy(true);
    setError('');
    if (!request.current || request.current.question !== question)
      request.current = {
        request_id: crypto.randomUUID(),
        question,
        last_turn_id: latest.current,
        risk_key: riskKey,
      };
    try {
      const row = await chatSend(
        endpoint,
        reportId,
        request.current,
        controller.current.signal,
        functionKey,
      );
      if (!controller.current.signal.aborted) {
        setTurns((old) => merge(old, [row]));
        latest.current = row.id;
        setDraft('');
        request.current = null;
        setNotice('问题已保存，由后台继续处理；你可以离开页面后再回来。');
      }
    } catch (reason) {
      if (!controller.current.signal.aborted) {
        setError(chatError(reason, onSessionEnd));
        if (
          reason instanceof Error &&
          ['chat_history_changed', 'chat_busy'].includes(reason.message)
        )
          request.current = null;
      }
    } finally {
      pending.current = false;
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }

  async function older() {
    setBusy(true);
    try {
      const data = await chatHistory(
        endpoint,
        reportId,
        controller.current.signal,
        turns[0]?.id,
        functionKey,
      );
      if (!controller.current.signal.aborted) {
        setTurns((old) => merge(old, data.items));
        setHasMore(data.has_more);
      }
    } catch (reason) {
      if (!controller.current.signal.aborted) setError(chatError(reason, onSessionEnd));
    } finally {
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  async function cancel(row: ChatTurn) {
    setBusy(true);
    setError('');
    try {
      const value = await apiRequest(`${endpoint}/${row.id}/cancel`, {
        method: 'POST',
        signal: controller.current.signal,
      });
      const result = parseChatTurn(value, reportId);
      if (!controller.current.signal.aborted) {
        setTurns((old) => merge(old, [result]));
        setNotice('已停止本轮结果保存；上游请求结束时间和计费以AI服务为准。');
      }
    } catch (reason) {
      if (!controller.current.signal.aborted) setError(chatError(reason, onSessionEnd));
    } finally {
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  const active = turns.some((row) => row.status === 'RUNNING' || row.status === 'QUEUED');
  return (
    <div className="requirement-chat-page requirement-ui">
      <header className="page-head">
        <div>
          <h1>分析对话</h1>
          <p>{detail?.title || '正在加载分析记录…'}</p>
        </div>
        <Link className="action" to="/requirements">
          返回需求分析
        </Link>
      </header>

      <div className="requirement-chat-layout">
        <aside className="panel chat-sidebar">
          <div className="panel-pad chat-side-scroll">
            <h3>当前分析的对话</h3>
            <p className="hint">{detail?.title || '正在加载分析记录…'}</p>
            {detail && (
              <>
                <Link
                  className={`action full ${!functionKey ? 'primary' : 'ghost'}`}
                  to={`/requirements/chat/${reportId}`}
                >
                  需求分析对话
                </Link>
                <h4 className="mt">功能独立对话</h4>
                {detail.report.functions.map((item) => (
                  <Link
                    className={`action full ${functionKey === item.key ? 'primary' : 'ghost'}`}
                    key={item.key}
                    to={`/requirements/chat/${reportId}?function=${encodeURIComponent(item.key)}`}
                  >
                    {item.name}
                  </Link>
                ))}
              </>
            )}
            <div className="divider" />
            <h3>历史会话</h3>
            <label className="field-label">
              搜索历史
              <input
                type="search"
                value={recordQuery}
                onChange={(event) => setRecordQuery(event.target.value)}
                placeholder="查找会话名称"
              />
            </label>
            <div className="chat-history">
              {records
                .filter((row) => row.title.toLowerCase().includes(recordQuery.toLowerCase()))
                .map((row) => (
                  <Link
                    className="evidence chat-history-item"
                    key={row.id}
                    aria-current={row.id === reportId ? 'page' : undefined}
                    to={`/requirements/chat/${row.id}`}
                  >
                    <span className="chat-history-title">{row.title}</span>
                    <span className="hint">{new Date(row.created_at).toLocaleString()}</span>
                    {row.id === reportId && <span className="badge">当前记录</span>}
                  </Link>
                ))}
              {!records.filter((row) => row.title.toLowerCase().includes(recordQuery.toLowerCase()))
                .length && (
                <p className="hint">{recordQuery ? '没有匹配的历史会话。' : '暂无历史会话。'}</p>
              )}
            </div>
            <div className="row chat-history-pages">
              <span className="hint">第{recordPage}页</span>
              <button
                className="small"
                disabled={recordLoading || recordPage === 1}
                onClick={() => setRecordPage((p) => p - 1)}
              >
                上一页
              </button>
              <button
                className="small"
                disabled={recordLoading || !recordMore}
                onClick={() => setRecordPage((p) => p + 1)}
              >
                下一页
              </button>
              <PageJump page={recordPage} onChange={setRecordPage} disabled={recordLoading} />
            </div>
            <Link className="action primary small full" to="/requirements">
              新建分析会话
            </Link>
          </div>
        </aside>
        <section className="panel chat-main">
          <div className="panel-head">
            <h2>
              {functionKey
                ? `${detail?.report.functions.find((item) => item.key === functionKey)?.name || '功能'} · 独立对话`
                : '需求分析对话'}
            </h2>
            <Link className="action ghost small" to="/requirements">
              返回需求分析
            </Link>
          </div>
          <div className="panel-pad">
            <p className="hint">
              {functionKey
                ? '仅使用本功能聊天历史、相关依据和必要公共规则。'
                : '检查整体遗漏与跨功能影响；各功能聊天历史独立保存。'}
            </p>
            <p className="hint">
              本人AI：{config} · <Link to="/platform">配置AI服务</Link>
            </p>
            {functionKey && (
              <Link className="action ghost small" to={`/requirements/chat/${reportId}`}>
                切换需求分析对话
              </Link>
            )}
            {riskKey && <p className="doc-note">本轮追问引用风险：{riskKey}</p>}
          </div>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          {notice && (
            <p className="doc-note" role="status">
              {notice}
            </p>
          )}
          <div className="chat-messages" aria-live="polite">
            {hasMore && (
              <button disabled={busy} onClick={() => void older()}>
                加载更早消息
              </button>
            )}
            {loading && <p role="status">正在读取聊天历史…</p>}
            {!loading && !turns.length && <p className="hint">暂无对话，可直接提问。</p>}
            {turns.map((row) => (
              <div className="chat-turn" key={row.id}>
                <article className="chat-message mine">
                  <strong>{row.actor}</strong>
                  {row.risk_key && <p className="hint">引用风险：{row.risk_key}</p>}
                  <p>{row.question}</p>
                  <span className="hint">{new Date(row.created_at).toLocaleString()}</span>
                </article>
                <article className="chat-message">
                  <strong>
                    AI · {callModeName(row.ai.call_mode)} · {row.ai.name} · {row.ai.model}
                  </strong>
                  <p>{row.answer || chatStates[row.status]}</p>
                  {row.status === 'QUEUED' && <p className="hint">排队中，等待处理。</p>}
                  {row.status === 'RUNNING' && (
                    <p className="hint">接收AI回复中，完整结束后显示回答。</p>
                  )}
                  {row.status === 'FAILED' && (
                    <p className="form-error">{chatFailure(row.error_code)}</p>
                  )}
                  {row.can_cancel && (
                    <div className="row">
                      <button disabled={busy} onClick={() => void cancel(row)}>
                        停止回答
                      </button>
                    </div>
                  )}
                  {['FAILED', 'CANCELLED'].includes(row.status) && (
                    <div className="row">
                      <button
                        disabled={busy || active}
                        onClick={() => {
                          setDraft(row.question);
                          request.current = null;
                          setNotice(
                            '已填回原问题；点击发送将使用你当前的AI配置重新调用，可能产生费用。',
                          );
                        }}
                      >
                        填回问题重试
                      </button>
                    </div>
                  )}
                  {row.status === 'COMPLETED' && (
                    <div className="row">
                      <button className="ghost small" type="button" onClick={() => setAdding(row)}>
                        添加为风险点
                      </button>
                    </div>
                  )}
                </article>
              </div>
            ))}
          </div>
          <Form
            className="panel-pad chat-compose"
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
          >
            <label className="field-label">
              继续提问
              <textarea
                name="question"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={3}
                required
                maxLength={8000}
                disabled={busy}
                placeholder="例如：这个功能还遗漏了哪些异常情况？"
              />
            </label>
            <div className="row">
              <span className="hint">仅发送给本人配置的AI服务</span>
              <button className="primary" disabled={busy || loading || !detail || active}>
                发送
              </button>
            </div>
          </Form>
        </section>
        <aside className="panel chat-context">
          <div className="panel-pad chat-side-scroll">
            <h3>本次上下文</h3>
            <p className="hint">分析 #{reportId}</p>
            <p className="hint">
              当前讨论：
              {detail?.report.functions.find((item) => item.key === functionKey)?.name ||
                '整个需求'}
            </p>
            <p>使用本次分析的资料、结果及人工结论。</p>
            <p className="hint">仅使用已保存文字和观察，不重新读取原件或链接。</p>
            {detail?.input.materials.map((m) => {
              const binding = detail.bindings.find((b) => b.source_id === m.source_id);
              return (
                <div className="evidence" key={m.source_id}>
                  {binding && !binding.deleted ? (
                    <Link
                      to={`${binding.purpose === 'PROTOTYPE' ? '/prototypes' : '/documents'}?document=${binding.document_id}`}
                    >
                      {m.source_id} · {m.name} →
                    </Link>
                  ) : (
                    <span>
                      {m.source_id} · {m.name}（资料已不可用）
                    </span>
                  )}
                </div>
              );
            })}
            <h3 className="mt">关联风险引用</h3>
            {detail?.report.risks
              .filter((item) => !functionKey || item.function_keys.includes(functionKey))
              .map((item) => (
                <div className="evidence" key={item.key}>
                  <strong>
                    {item.key} · {item.title}
                  </strong>
                  <div className="row">
                    <Link
                      className="action link"
                      to={`/requirements/chat/${reportId}?function=${encodeURIComponent(item.function_keys[0] || '')}&risk=${encodeURIComponent(item.key)}`}
                    >
                      引用提问
                    </Link>
                    <Link className="action link" to="/requirements">
                      返回风险详情
                    </Link>
                  </div>
                </div>
              ))}
          </div>
        </aside>
      </div>
      {adding && detail && (
        <ManualRiskDialog
          base={base}
          detail={detail}
          turn={adding}
          functionKey={functionKey}
          onClose={() => setAdding(null)}
          onSaved={() => {
            setAdding(null);
            setNotice('风险点已人工确认入库，并进入累计风险清单。');
          }}
          onSessionEnd={onSessionEnd}
        />
      )}
    </div>
  );
}

function ManualRiskDialog({
  base,
  detail,
  turn,
  functionKey,
  onClose,
  onSaved,
  onSessionEnd,
}: {
  base: string;
  detail: RiskDetail;
  turn: ChatTurn;
  functionKey: string;
  onClose: () => void;
  onSaved: () => void;
  onSessionEnd: () => void;
}) {
  const initialFunction = functionKey || detail.report.functions[0]?.key || '';
  const [feature, setFeature] = useState(initialFunction);
  const [source, setSource] = useState(detail.input.materials[0]?.source_id || '');
  const material = detail.input.materials.find((item) => item.source_id === source);
  const [segment, setSegment] = useState(material?.segments[0]?.segment_id || '');
  const selected = material?.segments.find((item) => item.segment_id === segment);
  const [severity, setSeverity] = useState<keyof typeof riskLevels>('MEDIUM');
  const [type, setType] = useState<keyof typeof riskTypes>('RULE_GAP');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || busy) return;
    const data = new FormData(event.currentTarget);
    if (
      !String(data.get('excerpt') || '').trim() &&
      !String(data.get('observation') || '').trim()
    ) {
      setError('原文摘录和依据说明至少填写一项。');
      return;
    }
    setBusy(true);
    setError('');
    try {
      parseManualRisk(
        await apiRequest(`${base}/${detail.id}/manual-risks`, {
          method: 'POST',
          body: JSON.stringify({
            request_id: crypto.randomUUID(),
            message_turn_id: turn.id,
            function_key: feature,
            title: String(data.get('title') || ''),
            severity,
            risk_type: type,
            description: String(data.get('description') || ''),
            evidence: [
              {
                source_id: source,
                segment_id: segment,
                location: selected.location,
                excerpt: String(data.get('excerpt') || ''),
                observation: String(data.get('observation') || ''),
              },
            ],
            impact: String(data.get('impact') || ''),
            questions: [String(data.get('question') || '')],
            improvement: {
              proposal: String(data.get('proposal') || ''),
              rationale: String(data.get('rationale') || ''),
              tradeoffs: String(data.get('tradeoffs') || ''),
              requires_confirmation: true,
            },
          }),
        }),
      );
      onSaved();
    } catch (reason) {
      setError(riskError(reason, onSessionEnd));
    } finally {
      setBusy(false);
    }
  }
  return (
    <CaseDialog title="添加为风险点" busy={busy} onClose={onClose} wide>
      <Form onSubmit={(event) => void submit(event)}>
        <p className="hint">核对依据后再入库。</p>
        <FormSelect
          label="所属功能"
          value={feature}
          onChange={setFeature}
          disabled={busy || !!functionKey}
          options={detail.report.functions.map((item) => ({ value: item.key, label: item.name }))}
        />
        <label className="form-field">
          风险标题
          <input name="title" required maxLength={500} disabled={busy} />
        </label>
        <div className="form-grid">
          <FormSelect
            label="风险等级"
            value={severity}
            onChange={(v) => setSeverity(v as keyof typeof riskLevels)}
            disabled={busy}
            options={Object.entries(riskLevels).map(([value, label]) => ({ value, label }))}
          />
          <FormSelect
            label="风险类型"
            value={type}
            onChange={(v) => setType(v as keyof typeof riskTypes)}
            disabled={busy}
            options={Object.entries(riskTypes).map(([value, label]) => ({ value, label }))}
          />
        </div>
        <label className="form-field">
          问题描述
          <textarea name="description" required maxLength={10000} rows={3} disabled={busy} />
        </label>
        <div className="form-grid">
          <FormSelect
            label="原文资料"
            value={source}
            onChange={(value) => {
              setSource(value);
              setSegment(
                detail.input.materials.find((item) => item.source_id === value)?.segments[0]
                  ?.segment_id || '',
              );
            }}
            disabled={busy}
            options={detail.input.materials
              .filter((item) => item.segments.length)
              .map((item) => ({ value: item.source_id, label: item.name }))}
          />
          <FormSelect
            label="原文位置"
            value={segment}
            onChange={setSegment}
            disabled={busy}
            options={(material?.segments || []).map((item) => ({
              value: item.segment_id,
              label: item.location,
            }))}
          />
        </div>
        <label className="form-field">
          原文摘录
          <textarea name="excerpt" maxLength={10000} rows={2} disabled={busy} />
        </label>
        <label className="form-field">
          依据说明
          <textarea name="observation" maxLength={10000} rows={2} disabled={busy} />
        </label>
        <label className="form-field">
          可能影响
          <textarea name="impact" required maxLength={10000} rows={2} disabled={busy} />
        </label>
        <label className="form-field">
          待确认问题
          <textarea name="question" required maxLength={10000} rows={2} disabled={busy} />
        </label>
        <label className="form-field">
          完善建议
          <textarea name="proposal" required maxLength={10000} rows={2} disabled={busy} />
        </label>
        <label className="form-field">
          建议理由
          <textarea name="rationale" required maxLength={10000} rows={2} disabled={busy} />
        </label>
        <label className="form-field">
          方案取舍
          <textarea name="tradeoffs" maxLength={10000} rows={2} disabled={busy} />
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <div className="row prototype-editor-footer">
          <button type="button" onClick={onClose} disabled={busy}>
            取消
          </button>
          <button className="primary" disabled={busy || !selected}>
            确认入库
          </button>
        </div>
      </Form>
    </CaseDialog>
  );
}
