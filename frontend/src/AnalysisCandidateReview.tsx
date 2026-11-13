import { PageJump } from './PageJump';
import { useEffect, useRef, useState } from 'react';
import { apiErrorMessage } from './api/http';
import { candidateReviewRequest } from './analysisCandidateApi';
import type { AnalysisCandidate } from './analysisCandidateApi';
import { CaseDialog } from './CaseDialog';
import { Form } from './Form';
import { aiErrors } from './aiErrors';

const groupNames: Record<string, string> = {
  findings: '分析发现',
  risks: '风险候选',
  changes: '变化项',
  impacts: '影响项',
  regressions: '回归建议',
  notes: '说明与待澄清',
  functions: '功能项',
  requirements: '需求项',
  coverage: '覆盖记录',
  target_results: '目标结论',
};

const messages: Record<string, string> = {
  ...aiErrors,
  risk_json_invalid: 'JSON格式无效或包含重复字段，请根据下方原始候选修正。',
  candidate_review_unavailable: '候选修订存储暂不可用，请稍后重试。',
  candidate_review_changed: '候选已被其他窗口修改，请关闭后重新打开。',
  candidate_review_owner_only: '只有发起人可以查看和修正原始候选。',
  candidate_review_not_ready: '此任务没有可处理的候选，或已经完成。',
};
export function AnalysisCandidateReview({
  endpoint,
  onSessionEnd,
  onUpdated,
}: {
  endpoint: string;
  onSessionEnd: () => void;
  onUpdated?: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className="small" type="button" onClick={() => setOpen(true)}>
        候选与待处理问题
      </button>
      {open && (
        <CandidateWorkspace
          endpoint={endpoint}
          onSessionEnd={onSessionEnd}
          onUpdated={onUpdated}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}
function CandidateWorkspace({
  endpoint,
  onSessionEnd,
  onUpdated,
  onClose,
}: {
  endpoint: string;
  onSessionEnd: () => void;
  onUpdated?: () => void;
  onClose: () => void;
}) {
  const [data, setData] = useState<AnalysisCandidate | null>(null),
    [body, setBody] = useState(''),
    [reason, setReason] = useState(''),
    [busy, setBusy] = useState(true),
    [error, setError] = useState(''),
    [discard, setDiscard] = useState(false),
    [page, setPage] = useState(0);
  const request = useRef<{ body: string; reason: string; id: string } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void candidateReviewRequest(endpoint, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) {
          setData(value);
          setBody(value.candidateJson);
          setBusy(false);
        }
      })
      .catch((failure) => {
        if (!controller.signal.aborted) {
          setError(apiErrorMessage(failure, onSessionEnd, messages));
          setBusy(false);
        }
      });
    return () => controller.abort();
  }, [endpoint, onSessionEnd]);
  const dirty = !!data && (body !== data.candidateJson || !!reason);
  function close() {
    if (!busy) {
      if (dirty) setDiscard(true);
      else onClose();
    }
  }
  async function save() {
    if (!data || busy) return;
    setBusy(true);
    setError('');
    if (request.current?.body !== body || request.current.reason !== reason)
      request.current = { body, reason, id: crypto.randomUUID() };
    try {
      const value = await candidateReviewRequest(endpoint, {
        method: 'POST',
        body: JSON.stringify({
          request_id: request.current.id,
          base_sha256: data.sha256,
          candidate_json: body,
          reason,
          confirmed: true,
        }),
      });
      setData(value);
      setBody(value.candidateJson);
      setReason('');
      setPage(0);
      request.current = null;
      if (value.published) onUpdated?.();
    } catch (failure) {
      setError(apiErrorMessage(failure, onSessionEnd, messages));
    } finally {
      setBusy(false);
    }
  }
  return (
    <CaseDialog title="候选与待处理问题" wide busy={busy} onClose={close}>
      {discard ? (
        <>
          <p>放弃尚未保存的候选修改？</p>
          <div className="row mt">
            <button onClick={() => setDiscard(false)}>继续编辑</button>
            <button onClick={onClose}>放弃修改</button>
          </div>
        </>
      ) : (
        <>
          <p className="hint">
            原始响应和每次人工修订均保留。此处可查看所有可解析候选及重复字段；候选尚未通过完整校验，引用关系和业务结论仍需核对。保存、校验不会调用AI。
          </p>
          {busy && <p role="status">正在读取或校验候选…</p>}
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          {data && (
            <>
              <p className="notice" role="status">
                {data.published
                  ? '修正已通过全部校验，结果已保存。'
                  : `候选待处理：${data.parseError ? 'JSON无法完整解析' : `可解析${data.items.length}项，重复字段${data.conflicts.length}处`}。${data.history.length ? '人工草稿已保存。' : ''}`}
              </p>
              {data.errorCode && (
                <p className="hint">校验原因：{messages[data.errorCode] || data.errorCode}</p>
              )}
              {!!data.conflicts.length && (
                <details className="evidence">
                  <summary>重复字段与全部冲突值</summary>
                  {data.conflicts.map((c, i) => (
                    <p key={i}>
                      {c.path}：{c.values.join(' / ')}
                    </p>
                  ))}
                </details>
              )}
              {data.items.slice(page * 20, (page + 1) * 20).map((item, index) => (
                <article className="code-finding" key={index}>
                  <span className={`badge ${data.published ? 'green' : 'orange'}`}>
                    {data.published ? '已校验候选' : '待校验候选'}
                  </span>
                  <h3>
                    {groupNames[item.group] || item.group} · 第{item.ordinal}项 {item.title}
                  </h3>
                  <details className="evidence">
                    <summary>查看候选内容</summary>
                    <pre className="code">{item.rawJson}</pre>
                  </details>
                </article>
              ))}
              {data.items.length > 20 && (
                <div className="row mt">
                  <button disabled={page === 0} onClick={() => setPage(page - 1)}>
                    上一页
                  </button>
                  <span>
                    {page + 1} / {Math.ceil(data.items.length / 20)}
                  </span>
                  <button
                    disabled={(page + 1) * 20 >= data.items.length}
                    onClick={() => setPage(page + 1)}
                  >
                    下一页
                  </button>
                  <PageJump
                    page={page + 1}
                    pages={Math.ceil(data.items.length / 20)}
                    disabled={busy}
                    onChange={(value) => setPage(value - 1)}
                  />
                </div>
              )}
              <Form
                onSubmit={(event) => {
                  event.preventDefault();
                  void save();
                }}
              >
                <label className="form-field mt">
                  完整候选JSON
                  <textarea
                    className="mono"
                    rows={16}
                    value={body}
                    disabled={busy || !data.canEdit}
                    onChange={(event) => setBody(event.target.value)}
                  />
                </label>
                {data.canEdit && (
                  <>
                    <label className="form-field mt">
                      处理说明
                      <textarea
                        required
                        maxLength={10000}
                        rows={3}
                        value={reason}
                        disabled={busy}
                        onChange={(event) => setReason(event.target.value)}
                        placeholder="说明字段取值、删除或澄清的依据"
                      />
                    </label>
                    <button className="primary mt" type="submit" disabled={busy || !reason.trim()}>
                      保存修订并校验（不调用AI）
                    </button>
                  </>
                )}
              </Form>
              {!!data.history.length && (
                <details className="evidence mt">
                  <summary>人工处理记录（{data.history.length}次）</summary>
                  {data.history.map((entry, i) => (
                    <p key={i}>
                      {new Date(entry.at).toLocaleString()} ·{' '}
                      {entry.validation_passed ? '校验通过' : '仍待处理'} · {entry.reason}
                    </p>
                  ))}
                </details>
              )}
              {data.published && (
                <button
                  className="mt"
                  onClick={() => {
                    onClose();
                    if (!onUpdated) window.location.reload();
                  }}
                >
                  查看已保存结果
                </button>
              )}
            </>
          )}
        </>
      )}
    </CaseDialog>
  );
}
