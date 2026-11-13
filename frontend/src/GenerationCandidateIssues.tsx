import { useRef, useState } from 'react';
import { CaseDialog } from './CaseDialog';
import { Form } from './Form';
import { generationFailure } from './generationApi';
import type { GenerationCandidateIssue } from './generationPage';

export function GenerationCandidateIssues({
  issues,
  onEdit,
}: {
  issues: GenerationCandidateIssue[];
  onEdit: (issue: GenerationCandidateIssue) => void;
}) {
  if (!issues.length) return null;
  return (
    <section aria-label="候选格式与校验问题">
      <h3 className="panel-pad">候选格式与校验问题</h3>
      <p className="hint panel-pad">
        这些原始候选已保留，尚未进入可应用建议；其他有效建议可继续审核入库。修正或忽略不会调用AI。
      </p>
      {issues.map((issue) => (
        <article className="code-finding" key={issue.key}>
          <span
            className={`badge ${issue.status === 'PENDING' ? 'orange' : issue.status === 'RESOLVED' ? 'green' : ''}`}
          >
            {{ PENDING: '待处理', RESOLVED: '已修正', IGNORED: '已忽略' }[issue.status]}
          </span>
          <h3>
            {issue.kind === 'response'
              ? '返回结果无法完整解析'
              : `第${issue.ordinal}条${issue.kind === 'case' ? '用例候选' : '返回说明'}`}
          </h3>
          <p>
            {issue.duplicates.length
              ? '同一字段存在重复值，需要人工确认。'
              : generationFailure(issue.reason)}
          </p>
          {issue.duplicates.map((duplicate, index) => (
            <p className="hint" key={index}>
              重复字段 {duplicate.path}：{duplicate.values.join(' / ')}
            </p>
          ))}
          {issue.rawJson ? (
            <details className="evidence">
              <summary>查看原候选内容（保留重复字段）</summary>
              <pre className="code">{issue.rawJson}</pre>
            </details>
          ) : (
            <p className="hint">原候选内容仅发起人可查看和修正。</p>
          )}
          {issue.note && <p className="hint">处理说明：{issue.note}</p>}
          {issue.canEdit && (
            <button className="small mt" onClick={() => onEdit(issue)}>
              修正或忽略（不调用AI）
            </button>
          )}
        </article>
      ))}
    </section>
  );
}

type Resolution = {
  request_id: string;
  corrected_json: string;
  ignored: boolean;
  reason: string;
  confirmed: true;
};
export function CandidateIssueDialog({
  issue,
  busy,
  error,
  onClose,
  onSave,
}: {
  issue: GenerationCandidateIssue;
  busy: boolean;
  error: string;
  onClose: () => void;
  onSave: (value: Resolution) => Promise<boolean>;
}) {
  const [body, setBody] = useState(issue.correctedJson || issue.rawJson);
  const [reason, setReason] = useState('');
  const [discard, setDiscard] = useState(false);
  const requestId = useRef(crypto.randomUUID());
  const dirty = body !== (issue.correctedJson || issue.rawJson) || !!reason;
  const close = () => {
    if (!busy) {
      if (dirty) setDiscard(true);
      else onClose();
    }
  };
  async function save(ignored: boolean) {
    if (busy) return;
    await onSave({
      request_id: requestId.current,
      corrected_json: ignored ? '' : body,
      ignored,
      reason,
      confirmed: true,
    });
  }
  return (
    <CaseDialog title="处理问题候选" wide busy={busy} onClose={close}>
      {discard ? (
        <>
          <p>放弃尚未保存的候选修正？</p>
          <div className="row mt">
            <button onClick={() => setDiscard(false)}>继续编辑</button>
            <button className="primary" onClick={onClose}>
              放弃修改
            </button>
          </div>
        </>
      ) : (
        <Form
          onSubmit={(event) => {
            event.preventDefault();
            const button = (event.nativeEvent as SubmitEvent).submitter;
            void save(button instanceof HTMLButtonElement && button.value === 'ignore');
          }}
        >
          <p className="hint">
            原始响应保持不变。修正后的候选需通过全部格式、来源及业务校验，再进入用例建议；不会直接写入用例库。
          </p>
          <label className="form-field mt">
            候选JSON
            <textarea
              className="mono"
              rows={16}
              value={body}
              disabled={busy}
              maxLength={1048576}
              onChange={(event) => setBody(event.target.value)}
            />
          </label>
          <label className="form-field mt">
            处理说明
            <textarea
              required
              rows={3}
              maxLength={10000}
              value={reason}
              disabled={busy}
              onChange={(event) => setReason(event.target.value)}
              placeholder="说明保留哪个值或忽略原因"
            />
          </label>
          {error && (
            <p className="form-error mt" role="alert">
              {error}
            </p>
          )}
          <div className="row mt">
            <button type="button" disabled={busy} onClick={close}>
              取消
            </button>
            <button type="submit" value="ignore" disabled={busy}>
              忽略此项
            </button>
            <button type="submit" value="save" className="primary" disabled={busy}>
              保存修正并校验
            </button>
          </div>
        </Form>
      )}
    </CaseDialog>
  );
}
