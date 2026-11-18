import { useEffect, useRef, useState } from 'react';
import { CaseDialog } from './CaseDialog';
import { Form } from './Form';
import { FormSelect } from './FormSelect';
import {
  codeError,
  codeEvidenceStates,
  codeHandlingStates,
  codeKinds,
  codeLevels,
  codeRequest,
  codeTargets,
  parseCodeDetail,
} from './codeAnalysisApi';
import type { CodeDetail, CodeEvidence, CodeFinding, CodeHandlingState } from './codeAnalysisApi';

export function EvidenceCard({
  evidence,
  record,
  open = false,
}: {
  evidence: CodeEvidence;
  record: CodeDetail;
  open?: boolean;
}) {
  const source = record.input?.sources.find((s) => s.source_id === evidence.source_id),
    file = source?.files.find((f) => f.file_id === evidence.file_id),
    material = record.input?.materials.find((m) => m.source_id === evidence.source_id),
    segment = material?.segments.find((s) => s.segment_id === evidence.segment_id);
  return (
    <details className="code-node-source" open={open}>
      <summary>
        {evidence.key} · {file?.path || material?.name || evidence.source_id}
        {evidence.kind === 'CODE'
          ? ` · L${evidence.start_line}–L${evidence.end_line}`
          : ` · ${segment?.location || evidence.segment_id}`}
      </summary>
      <p className="hint mono">
        {source
          ? `${source.source_kind === 'LOCAL' ? '本地' : 'GitHub'} · ${codeKinds[source.repository_kind]} · ${source.snapshot_ref}`
          : material?.snapshot_ref}
      </p>
      <p>{evidence.observation}</p>
      {evidence.excerpt && <pre className="code">{evidence.excerpt}</pre>}
      {segment?.image_ref && <p className="hint">本次固定附件的报告观察。</p>}
    </details>
  );
}

export function CodeFindingDetail({
  record,
  finding,
  onClose,
  onSaved,
  onAsk,
  onSessionEnd,
}: {
  record: CodeDetail;
  finding: CodeFinding;
  onClose: () => void;
  onSaved: (record: CodeDetail) => void;
  onAsk: (key: string) => void;
  onSessionEnd: () => void;
}) {
  const current = record.handling[finding.key],
    [status, setStatus] = useState<CodeHandlingState>(current?.status || 'PENDING'),
    [note, setNote] = useState(current?.note || ''),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const controller = useRef(new AbortController()),
    pending = useRef(false);
  useEffect(() => {
    const c = new AbortController();
    controller.current = c;
    return () => c.abort();
  }, []);
  const evidence = record.report?.evidence || [],
    chains = record.report?.chains.filter((c) => finding.chain_refs.includes(c.key)) || [];
  function refs(keys: string[]) {
    return keys.map((key) => {
      const item = evidence.find((e) => e.key === key);
      return item ? <EvidenceCard key={key} evidence={item} record={record} /> : null;
    });
  }
  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    if (status !== 'PENDING' && !note.trim()) {
      setError('请填写处理说明。');
      return;
    }
    pending.current = true;
    setBusy(true);
    setError('');
    try {
      const result = await codeRequest(
        `/api/projects/${record.project_id}/code-analysis/${record.id}/handling`,
        parseCodeDetail,
        {
          method: 'POST',
          signal: controller.current.signal,
          body: JSON.stringify({
            revision: record.revision,
            finding_key: finding.key,
            status,
            note: note.trim(),
          }),
        },
      );
      if (!controller.current.signal.aborted) onSaved(result);
    } catch (reason) {
      if (!controller.current.signal.aborted) setError(codeError(reason, onSessionEnd));
    } finally {
      pending.current = false;
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  return (
    <CaseDialog
      title={`${finding.key} · 代码分析内容`}
      busy={busy}
      onClose={onClose}
      wide
      className="code-analysis-dialog requirement-ui"
    >
      <div className="code-finding-detail">
        <div className="row code-finding-badges">
          <span className="badge">{finding.category}</span>
          <span className={`badge ${finding.severity === 'HIGH' ? 'red' : 'orange'}`}>
            严重程度：{codeLevels[finding.severity]}
          </span>
          <span className="badge">{codeEvidenceStates[finding.evidence_state]}</span>
          <span className="badge">{codeHandlingStates[current?.status || 'PENDING']}</span>
        </div>
        <h2 className="mt">{finding.title}</h2>
        <p className="hint">固定版本静态分析 · 未运行验证</p>
        <p className="hint">严重程度依据：{finding.severity_reason}</p>
        <section className="evidence">
          <strong>触发条件</strong>
          <p>{finding.trigger}</p>
        </section>
        {finding.target_views.map((view) => (
          <section className="code-detail-section code-target-detail" key={view.target}>
            <h3>
              {view.target === 'BUG'
                ? '代码Bug · 执行路径与错误原因'
                : view.target === 'REQUIREMENT_DEVIATION'
                  ? '需求符合性 · 需求与实现对照'
                  : '前后端一致性 · 接口与字段对照'}
            </h3>
            <span className="badge">{codeEvidenceStates[view.evidence_state]}</span>
            {view.target === 'BUG' ? (
              <div className="form-grid mt">
                <section>
                  <h4>代码预期与依据</h4>
                  <p>{view.expected}</p>
                  <p className="hint">{view.basis}</p>
                </section>
                <section>
                  <h4>实际执行与错误原因</h4>
                  <p>{finding.actual}</p>
                </section>
              </div>
            ) : (
              <>
                <section className="evidence">
                  <strong>
                    {view.target === 'REQUIREMENT_DEVIATION'
                      ? '需求／原型原文及版本'
                      : '接口关联依据'}
                  </strong>
                  <p>{view.basis}</p>
                  {refs(view.basis_refs)}
                </section>
                <p>预期行为：{view.expected}</p>
                <div className="table-wrap mt">
                  <table>
                    <thead>
                      <tr>
                        <th>对照项</th>
                        <th>
                          {view.target === 'REQUIREMENT_DEVIATION' ? '需求或原型依据' : '后端代码'}
                        </th>
                        <th>
                          {view.target === 'REQUIREMENT_DEVIATION' ? '代码实现' : '客户端代码'}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {view.comparison_rows.map((row, index) => (
                        <tr key={index}>
                          <td>{row.label}</td>
                          <td>
                            {row.left.statement}
                            {refs(row.left.evidence_refs)}
                          </td>
                          <td>
                            {row.right.statement}
                            {refs(row.right.evidence_refs)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
            <p className="mt">
              <strong>结论与反证核查边界：</strong>
              {view.explanation}
            </p>
          </section>
        ))}
        <section className="code-detail-section">
          <h3>调用链与证据</h3>

          {chains.map((chain) => (
            <div key={chain.key}>
              <ol className="code-evidence-chain">
                {chain.nodes.map((node, index) => (
                  <li key={node.key}>
                    <span className="code-node-number">{index + 1}</span>
                    <div className="code-node-content">
                      <h4>{node.label}</h4>
                      <p>{node.observation}</p>
                      {(node.inputs || node.outputs) && (
                        <p className="hint">
                          输入：{node.inputs || '未说明'} → 输出：{node.outputs || '未说明'}
                        </p>
                      )}
                      {refs(node.evidence_refs)}
                    </div>
                  </li>
                ))}
              </ol>
              {chain.edges.map((edge, index) => (
                <p
                  className={`code-chain-edge ${edge.relation === 'UNKNOWN' ? 'unknown' : ''}`}
                  key={index}
                >
                  {chain.nodes.find((n) => n.key === edge.from)?.label} →{' '}
                  {chain.nodes.find((n) => n.key === edge.to)?.label} ·{' '}
                  {{
                    CALL: '调用',
                    RETURN: '返回',
                    FIELD_MAPPING: '字段映射',
                    STATE_ASSIGNMENT: '状态赋值',
                    UNKNOWN: '关联待核实',
                  }[edge.relation] || edge.relation}
                  <br />
                  <span className="hint">{edge.note}</span>
                </p>
              ))}
            </div>
          ))}
          {!chains.length && <p className="hint">暂无独立调用链，可查看固定证据。</p>}
          <details className="evidence">
            <summary>本条全部证据 · {finding.evidence_refs.length}项</summary>
            {refs(finding.evidence_refs)}
          </details>
        </section>
        <section className="code-detail-section">
          <h3>影响与建议</h3>
          <div className="evidence">
            <strong>影响范围</strong>
            <p>{finding.impact}</p>
          </div>
          <div className="form-grid mt">
            <section>
              <h4>修复建议</h4>
              <p>{finding.fix_suggestion}</p>
            </section>
            <section>
              <h4>验证建议</h4>
              <p>{finding.verification_suggestion}</p>
            </section>
          </div>
          {!!finding.missing_evidence.length && (
            <section className="code-missing-evidence mt">
              <h4>待补充证据</h4>
              <ul>
                {finding.missing_evidence.map((item, index) => (
                  <li key={index}>
                    {item.needed}
                    <p className="hint">
                      {item.reason}；{item.effect}
                    </p>
                  </li>
                ))}
              </ul>
              <p className="hint">范围外文件需另行选择。</p>
            </section>
          )}
        </section>
        <section className="code-detail-section">
          <h3>人工处理</h3>
          <Form onSubmit={(event) => void save(event)}>
            <div className="form-grid">
              <FormSelect
                label="处理状态"
                value={status}
                disabled={busy}
                options={Object.entries(codeHandlingStates).map(([value, label]) => ({
                  value,
                  label,
                }))}
                onChange={(value) => setStatus(value as CodeHandlingState)}
              />
              <label className="form-field">
                处理说明
                <textarea
                  value={note}
                  maxLength={10000}
                  required={status !== 'PENDING'}
                  disabled={busy}
                  onChange={(event) => setNote(event.target.value)}
                />
              </label>
            </div>

            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
            <footer className="prototype-editor-footer">
              <button type="button" disabled={busy} onClick={() => onAsk(finding.key)}>
                引用此发现追问
              </button>
              <button type="button" disabled={busy} onClick={onClose}>
                关闭
              </button>
              <button className="primary" disabled={busy}>
                {busy ? '保存中…' : '保存处理记录'}
              </button>
            </footer>
          </Form>
          {!!current?.history.length && (
            <details className="mt">
              <summary>处理历史 · {current.history.length}条</summary>
              {current.history.map((item, index) => (
                <div className="evidence" key={index}>
                  <strong>{codeHandlingStates[item.status]}</strong>
                  <p>{item.note}</p>
                  <p className="hint">
                    {item.actor_name} · {new Date(item.at).toLocaleString()}
                  </p>
                </div>
              ))}
            </details>
          )}
        </section>
        <p className="hint">
          所属目标：{finding.target_refs.map((t) => codeTargets[t]).join(' · ')}
        </p>
      </div>
    </CaseDialog>
  );
}
