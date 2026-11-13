import { useEffect, useId, useRef, useState } from 'react';
import { CaseDialog } from './CaseDialog';
import { Form } from './Form';
import { FormSelect } from './FormSelect';
import { defaultDecision, reviewProblem } from './GenerationReview';
import type { ReviewItem } from './GenerationReview';
import type { GenerationPreviewItem } from './generationPage';

export function batchReviewProblem(item: GenerationPreviewItem, choice?: ReviewItem) {
  const decision = choice
    ? { action: choice.action, targetId: choice.target_id, reason: choice.reason }
    : defaultDecision(item);
  const problem = reviewProblem(item, decision);
  if (problem) return problem;
  const target = item.matches.find((c) => c.id === decision.targetId) || item.target;
  if (
    choice &&
    (choice.draft_revision !== item.revision || choice.target_version !== (target?.version || null))
  )
    return '处理依据已变化，请重新核对重复项。';
  return '';
}
export function batchReviewItem(item: GenerationPreviewItem, choice?: ReviewItem): ReviewItem {
  if (choice) return choice;
  const d = defaultDecision(item),
    target = item.matches.find((c) => c.id === d.targetId) || item.target;
  return {
    key: item.key,
    draft_revision: item.revision,
    action: d.action,
    target_id: d.targetId || item.target?.id || null,
    target_version: target?.version || null,
    reason: d.reason,
    category_mode: 'KEEP',
    category_id: null,
  };
}
export function GenerationBatchReview({
  items,
  choices,
  busy,
  error,
  onClose,
  onSubmit,
  single = false,
}: {
  items: GenerationPreviewItem[];
  choices: Record<string, ReviewItem>;
  busy: boolean;
  error: string;
  onClose: () => void;
  onSubmit: (items: ReviewItem[]) => void;
  single?: boolean;
}) {
  const submitted = useRef(false);
  useEffect(() => {
    if (!busy) submitted.current = false;
  }, [busy, error, items]);
  const problems = items.filter((i) => batchReviewProblem(i, choices[i.key])),
    ignored = items.filter((i) => batchReviewItem(i, choices[i.key]).action === 'ignore').length,
    reused = items.filter(
      (i) =>
        !batchReviewProblem(i, choices[i.key]) &&
        ['reuse', 'restore'].includes(batchReviewItem(i, choices[i.key]).action),
    ).length;
  return (
    <CaseDialog
      title={
        ignored === items.length && ignored > 0
          ? '确认忽略建议'
          : single
            ? '确认入库'
            : '确认批量入库'
      }
      busy={busy}
      onClose={onClose}
      className={single ? 'generation-single-confirm' : 'generation-batch-confirm'}
      footer={
        <footer className="change-dialog-footer">
          <button disabled={busy} onClick={onClose}>
            取消
          </button>
          <button
            className="primary"
            disabled={busy || !items.length || !!problems.length}
            onClick={() => {
              if (busy || submitted.current || !items.length || problems.length) return;
              submitted.current = true;
              onSubmit(items.map((i) => batchReviewItem(i, choices[i.key])));
            }}
          >
            {busy ? '正在入库…' : '确认'}
          </button>
        </footer>
      }
    >
      <p>
        {ignored === items.length && ignored > 0 ? (
          <>
            确认忽略所选的 <strong>{ignored}</strong> 条用例建议？
          </>
        ) : ignored > 0 ? (
          <>
            确认将 <strong>{items.length - ignored}</strong> 条用例审核入库，并忽略{' '}
            <strong>{ignored}</strong> 条建议？
          </>
        ) : (
          <>
            确认将所选的 <strong>{items.length}</strong> 条用例审核入库？
          </>
        )}
      </p>
      {!!reused && (
        <p className="hint mt">其中 {reused} 条关联复用已有用例，保留原设计和测试记录。</p>
      )}
      {!!problems.length && (
        <p className="form-error" role="alert">
          {problems.length} 条需处理：{batchReviewProblem(problems[0], choices[problems[0].key])}
          请返回表格修订或调整勾选后重试。
        </p>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </CaseDialog>
  );
}

export function GenerationDuplicateResolution({
  item,
  choice,
  busy,
  onClose,
  onSave,
}: {
  item: GenerationPreviewItem;
  choice?: ReviewItem;
  busy: boolean;
  onClose: () => void;
  onSave: (choice: ReviewItem) => void;
}) {
  const initial = choice
      ? { action: choice.action, targetId: choice.target_id, reason: choice.reason }
      : defaultDecision(item),
    [action, setAction] = useState(initial.action),
    [targetId, setTargetId] = useState(String(initial.targetId || '')),
    [reason, setReason] = useState(initial.reason),
    [error, setError] = useState(''),
    id = useId();
  const target = item.matches.find((c) => c.id === Number(targetId)),
    problem = reviewProblem(item, { action, targetId: target?.id || null, reason }),
    needsReason = ['restore', 'include', 'ignore'].includes(action);
  return (
    <CaseDialog
      title="处理重复建议"
      busy={busy}
      onClose={onClose}
      className="generation-duplicate-resolution"
      footer={
        <footer className="change-dialog-footer">
          <button disabled={busy} onClick={onClose}>
            取消
          </button>
          <button className="primary" type="submit" form={id} disabled={busy}>
            保存处理方式
          </button>
        </footer>
      }
    >
      <p>{item.design.title}</p>
      <p className="hint">这里只保存本次处理选择，返回主表格确认后才入库。</p>
      <Form
        id={id}
        onSubmit={(e) => {
          e.preventDefault();
          if (busy) return;
          if (problem) {
            setError(problem);
            return;
          }
          onSave({
            key: item.key,
            draft_revision: item.revision,
            action,
            target_id: target?.id || null,
            target_version: target?.version || null,
            reason,
            category_mode: 'KEEP',
            category_id: null,
          });
        }}
      >
        <FormSelect
          label="如何处理"
          value={action}
          disabled={busy}
          options={[
            { value: 'reuse', label: '复用已有用例' },
            { value: 'restore', label: '恢复停用用例并复用' },
            { value: 'include', label: '仍然新增' },
            { value: 'ignore', label: '忽略本条' },
          ]}
          onChange={(value) => {
            setAction(value as ReviewItem['action']);
            setError('');
          }}
        />
        {['reuse', 'restore'].includes(action) && (
          <FormSelect
            label="选择已有用例"
            value={targetId}
            disabled={busy}
            options={[
              { value: '', label: '请选择' },
              ...item.matches.map((c) => ({
                value: String(c.id),
                label: `${c.number} / v${c.version}${c.lifecycle === 'RETIRED' ? ' · 停用' : ''}`,
              })),
            ]}
            onChange={(value) => {
              setTargetId(value);
              setError('');
            }}
          />
        )}
        {needsReason && (
          <label className="form-field">
            原因
            <textarea
              value={reason}
              required
              maxLength={10000}
              disabled={busy}
              onChange={(e) => {
                setReason(e.target.value);
                setError('');
              }}
            />
          </label>
        )}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </Form>
    </CaseDialog>
  );
}
