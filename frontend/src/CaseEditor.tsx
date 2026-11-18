import { Form } from './Form';
import { Select, FormSelect } from './FormSelect';
import { useEffect, useRef, useState } from 'react';
import { apiRequest } from './api/http';
import { CaseDialog } from './CaseDialog';
import {
  blankDesign,
  CASE_COLUMNS,
  CASE_RESULTS,
  CASE_TYPES,
  PRIORITIES,
  DESIGN_FIELDS,
  caseError,
  parseCaseDetail,
} from './caseApi';
import type { CaseDetail, CaseMetadata, Design } from './caseApi';

export function CaseEditor({
  base,
  id,
  metadata,
  categoryId,
  onClose,
  onSaved,
  onSessionEnd,
}: {
  base: string;
  id: number | null;
  metadata: CaseMetadata;
  categoryId: number | null;
  onClose: () => void;
  onSaved: () => void;
  onSessionEnd: () => void;
}) {
  const [detail, setDetail] = useState<CaseDetail | null>(null),
    [loading, setLoading] = useState(id !== null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [version, setVersion] = useState(0);
  const [values, setValues] = useState<
    Design & { result: string; tester: string; review_status: string; category_id: number | null }
  >({
    ...blankDesign(),
    case_type: '功能需求',
    priority: 'P1',
    result: '未测',
    tester: '',
    review_status: '待审核',
    category_id: categoryId,
  });
  const requestId = useRef(crypto.randomUUID()),
    pending = useRef(false),
    alive = useRef(true);
  const [refresh, setRefresh] = useState(0);
  const [lifecycleReason, setLifecycleReason] = useState(''),
    [lifecycleConfirmed, setLifecycleConfirmed] = useState(false);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (id === null) return;
    const c = new AbortController();
    setLoading(true);
    setError('');
    apiRequest<unknown>(`${base}/${id}`, { signal: c.signal })
      .then(parseCaseDetail)
      .then((d) => {
        if (c.signal.aborted) return;
        setDetail(d);
        setVersion(0);
        const v = d.versions[0],
          test = v.records.find((r) => r.kind === 'TEST'),
          review = v.records.find((r) => r.kind === 'REVIEW');
        setValues({
          ...(Object.fromEntries(DESIGN_FIELDS.map((f) => [f, v[f]])) as Design),
          result: test?.result || '',
          tester: test?.tester || '',
          review_status: review?.review_status || '待审核',
          category_id: d.category_id,
        });
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(caseError(e, onSessionEnd));
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [base, id, refresh, onSessionEnd]);
  const current = detail?.versions[0],
    view = detail?.versions[version];
  const changed = !!current && DESIGN_FIELDS.some((f) => values[f] !== current[f]);
  const historic = version > 0;
  const displayed =
    historic && view
      ? {
          ...view,
          result: view.records.find((r) => r.kind === 'TEST')?.result || '',
          tester: view.records.find((r) => r.kind === 'TEST')?.tester || '',
        }
      : values;
  async function save() {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError('');
    try {
      parseCaseDetail(
        await apiRequest<unknown>(id === null ? base : `${base}/${id}`, {
          method: id === null ? 'POST' : 'PATCH',
          body: JSON.stringify({
            ...values,
            revision: detail?.revision ?? metadata.revision,
            request_id: requestId.current,
          }),
        }),
      );
      if (alive.current) onSaved();
    } catch (e) {
      if (alive.current) setError(caseError(e, onSessionEnd));
    } finally {
      pending.current = false;
      if (alive.current) setBusy(false);
    }
  }
  const categories = detail?.categories || metadata.categories;
  return (
    <CaseDialog
      title={id === null ? '新建用例' : `用例 ${detail?.number || '…'}`}
      busy={busy}
      onClose={onClose}
      wide
    >
      {loading ? (
        <p role="status">正在加载用例…</p>
      ) : (
        <>
          {detail && (
            <section className="evidence">
              <strong>生命周期：{detail.lifecycle === 'RETIRED' ? '停用' : '活动'}</strong>
              <p className="hint">停用后不能新增测试记录，编辑设计不会自动恢复。</p>
              <label className="form-field">
                启停理由
                <input
                  maxLength={10000}
                  value={lifecycleReason}
                  onChange={(e) => setLifecycleReason(e.target.value)}
                />
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={lifecycleConfirmed}
                  onChange={(e) => setLifecycleConfirmed(e.target.checked)}
                />
                已核对启停影响，明确确认本次操作
              </label>
              <button
                type="button"
                disabled={busy || !lifecycleConfirmed || !lifecycleReason.trim()}
                onClick={() => {
                  if (pending.current) return;
                  pending.current = true;
                  setBusy(true);
                  setError('');
                  void apiRequest<unknown>(`${base}/${id}/lifecycle`, {
                    method: 'POST',
                    body: JSON.stringify({
                      revision: detail.revision,
                      lifecycle: detail.lifecycle === 'RETIRED' ? 'ACTIVE' : 'RETIRED',
                      reason: lifecycleReason,
                      confirmed: true,
                    }),
                  })
                    .then(parseCaseDetail)
                    .then(() => {
                      if (alive.current) onSaved();
                    })
                    .catch((e) => {
                      if (alive.current) setError(caseError(e, onSessionEnd));
                    })
                    .finally(() => {
                      pending.current = false;
                      if (alive.current) setBusy(false);
                    });
                }}
              >
                {detail.lifecycle === 'RETIRED' ? '确认恢复' : '确认停用'}
              </button>
              <details>
                <summary>启停历史</summary>
                {detail.lifecycle_history?.map((h, n) => (
                  <p className="hint" key={n}>
                    {h.at} · {h.lifecycle} · {h.reason}
                  </p>
                ))}
              </details>
            </section>
          )}
          <div className="case-editor-top">
            <label className="form-field">
              用例分类
              <Select
                disabled={busy || historic}
                value={values.category_id ?? ''}
                onChange={(e) =>
                  setValues((v) => ({
                    ...v,
                    category_id: e ? Number(e) : null,
                  }))
                }
              >
                <option value="">未分类</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </label>
            {detail && (
              <label className="form-field">
                设计版本
                <Select disabled={busy} value={version} onChange={(e) => setVersion(Number(e))}>
                  {detail.versions.map((v, i) => (
                    <option key={v.id} value={i}>
                      v{v.number}
                      {i === 0 ? ' · 当前版本' : ' · 历史只读'}
                    </option>
                  ))}
                </Select>
              </label>
            )}
          </div>
          <Form
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            <div className="case-form-grid">
              <label className="form-field">
                用例编号
                <input readOnly value={detail?.number ?? metadata.next_number} />
              </label>
              <p className="hint">新建用例自动分配编号。</p>
              {CASE_COLUMNS.filter(([key]) => key !== 'serial' && key !== 'number').map(
                ([key, name]) => {
                  if (key === 'serial' || key === 'number') return null;
                  const choices =
                    key === 'priority' ? PRIORITIES : key === 'result' ? CASE_RESULTS : null;
                  const long = ['preconditions', 'steps', 'expected', 'remark'].includes(key);
                  const resets = changed && (key === 'result' || key === 'tester');
                  const retiredTest =
                    detail?.lifecycle === 'RETIRED' && (key === 'result' || key === 'tester');
                  const value = resets ? (key === 'result' ? '未测' : '') : displayed[key];
                  return (
                    <label key={key} className={`form-field${long ? ' span2' : ''}`}>
                      {name}
                      {choices ? (
                        <Select
                          disabled={busy || historic || resets || retiredTest}
                          value={value}
                          onChange={(e) => setValues((v) => ({ ...v, [key]: e }))}
                        >
                          {choices.map((c) => (
                            <option key={c} value={c}>
                              {c || '留空'}
                            </option>
                          ))}
                        </Select>
                      ) : long ? (
                        <textarea
                          rows={key === 'steps' || key === 'expected' ? 5 : 3}
                          disabled={busy || historic}
                          value={value}
                          onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
                        />
                      ) : key === 'case_type' ? (
                        <FormSelect
                          editable
                          hideLabel
                          label="用例类型"
                          value={value}
                          options={CASE_TYPES.filter(Boolean).map((type) => ({
                            value: type,
                            label: type,
                          }))}
                          disabled={busy || historic}
                          maxLength={200}
                          placeholder="可自定义，例如：业务流程"
                          onChange={(value) => setValues((v) => ({ ...v, case_type: value }))}
                        />
                      ) : (
                        <input
                          disabled={busy || historic || resets || retiredTest}
                          value={value}
                          onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
                        />
                      )}
                    </label>
                  );
                },
              )}
            </div>
            <p className="hint">步骤与预期不要求逐行对应。</p>
            {changed && (
              <p className="doc-note">
                设计内容已修改，保存将生成新版，并重置为“未测、待审核”，测试人员留空；旧版记录保留。
              </p>
            )}
            <details className="evidence">
              <summary>关联与审核信息（不占默认列）</summary>
              <div className="case-form-grid">
                <label className="form-field">
                  审核状态
                  <Select
                    disabled={busy || historic || changed}
                    value={
                      historic
                        ? view?.records.find((r) => r.kind === 'REVIEW')?.review_status || '待审核'
                        : changed
                          ? '待审核'
                          : values.review_status
                    }
                    onChange={(e) => setValues((v) => ({ ...v, review_status: e }))}
                  >
                    <option>待审核</option>
                    <option>已审核</option>
                  </Select>
                </label>
                <p className="hint">需求验收点与Skill关联待接入。</p>
                {(['data_requirements', 'cleanup'] as const).map((f, i) => (
                  <label className="form-field" key={f}>
                    {i ? '清理要求' : '测试数据要求'}
                    <textarea
                      disabled={busy || historic}
                      value={displayed[f]}
                      onChange={(e) => setValues((v) => ({ ...v, [f]: e.target.value }))}
                    />
                  </label>
                ))}
              </div>
            </details>
            {!historic && (
              <button className="primary" disabled={busy || (id !== null && !detail)}>
                {busy ? '正在保存…' : '保存用例'}
              </button>
            )}
          </Form>
          {view && (
            <details className="evidence">
              <summary>来源与测试 / 审核记录</summary>
              <p className="hint">
                v{view.number} · {view.created_by} · {new Date(view.created_at).toLocaleString()}
              </p>
              {view.import_id && (
                <>
                  <a href={`${base}/imports/${view.import_id}/source`}>下载导入原件</a>
                  <p className="hint">
                    工作表：{view.source.sheet} · 行号：{view.source.row} · 原编号：
                    {view.source.original_number} · 原结果：{view.source.original_result}
                  </p>
                </>
              )}
              <div className="case-records">
                {view.records.map((r) => (
                  <div key={r.id}>
                    <strong>
                      {r.kind === 'TEST'
                        ? `测试结果：${r.result || '空'} · 测试人员：${r.tester || '未填写'}`
                        : `审核：${r.review_status}`}
                    </strong>
                    <p className="hint">
                      {r.source_kind === 'IMPORT' ? '导入记录' : '人工记录'} · 录入：{r.recorded_by}{' '}
                      · {new Date(r.recorded_at).toLocaleString()}
                    </p>
                  </div>
                ))}
              </div>
            </details>
          )}
        </>
      )}
      {error && (
        <p role="alert" className="form-error">
          {error}
          {id !== null && (
            <button disabled={busy} onClick={() => setRefresh((n) => n + 1)}>
              重新加载用例（放弃未保存修改）
            </button>
          )}
        </p>
      )}
    </CaseDialog>
  );
}
