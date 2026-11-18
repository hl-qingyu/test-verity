import { useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { CaseDialog } from './CaseDialog';
import { Form } from './Form';
import { FormSelect } from './FormSelect';
import { overviewModules } from './overviewApi';
import type { OverviewModule } from './overviewApi';
import {
  acceptanceError,
  acceptanceValues,
  readAcceptance,
  readAcceptanceSummary,
  saveAcceptance,
} from './acceptanceApi';
import type {
  AcceptanceDetail,
  AcceptanceGroup,
  AcceptanceMetrics,
  AcceptanceState,
  Criterion,
} from './acceptanceApi';
import './analysis-acceptance.css';

export function AcceptanceEditor({
  data,
  onClose,
  onSaved,
  onSessionEnd,
}: {
  data: AcceptanceDetail;
  onClose: () => void;
  onSaved: (d: AcceptanceDetail) => void;
  onSessionEnd: () => void;
}) {
  const [value, setValue] = useState<AcceptanceState>(() => structuredClone(data.state)),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [exit, setExit] = useState(false);
  const formId = useId(),
    abort = useRef(new AbortController()),
    pending = useRef(false);
  const dirty = JSON.stringify(value) !== JSON.stringify(data.state);
  useEffect(() => {
    const c = new AbortController();
    abort.current = c;
    return () => c.abort();
  }, []);
  useEffect(() => {
    const protect = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', protect);
    return () => window.removeEventListener('beforeunload', protect);
  }, [dirty]);
  function criterion(id: string, patch: Partial<Criterion>) {
    setValue((s) => ({
      ...s,
      criteria: s.criteria.map((c) => (c.id === id ? { ...c, ...patch } : c)),
    }));
    setError('');
  }
  async function submit() {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError('');
    try {
      const result = await saveAcceptance(data, value, abort.current.signal);
      if (!abort.current.signal.aborted) onSaved(result);
    } catch (e) {
      if (!abort.current.signal.aborted) setError(acceptanceError(e, onSessionEnd));
    } finally {
      pending.current = false;
      if (!abort.current.signal.aborted) setBusy(false);
    }
  }
  function close() {
    if (dirty) setExit(true);
    else onClose();
  }
  return (
    <CaseDialog
      title="遗漏与基准（按需补充）"
      wide
      busy={busy}
      onClose={close}
      className="aa-dialog"
      footer={
        <footer className="aa-footer">
          <span className="hint">详情处理自动统计；这里仅补充人工清单</span>
          <div className="row">
            <button type="button" disabled={busy} onClick={close}>
              取消
            </button>
            <button className="primary" type="submit" form={formId} disabled={busy || !dirty}>
              {busy ? '保存中…' : '保存清单'}
            </button>
          </div>
        </footer>
      }
    >
      <p className="hint">{data.title}</p>
      <Form
        id={formId}
        className="aa-scope"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <p className="notice">仅登记原范围内的遗漏及人工基准。</p>
        <button
          type="button"
          disabled={busy}
          onClick={() =>
            setValue((s) => ({
              ...s,
              criteria: [
                ...s.criteria,
                {
                  id: crypto.randomUUID(),
                  title: '',
                  basis: '',
                  critical: true,
                  baseline: false,
                  result: 'UNREVIEWED',
                  matched_key: '',
                  scope_confirmed: true,
                },
              ],
            }))
          }
        >
          添加遗漏或基准项
        </button>
        {value.criteria.map((c) => (
          <section className="aa-criterion" key={c.id}>
            <label>
              验收项标题
              <input
                disabled={busy}
                value={c.title}
                maxLength={500}
                onChange={(e) => criterion(c.id, { title: e.target.value })}
              />
            </label>
            <label>
              原固定范围依据／位置
              <textarea
                rows={2}
                disabled={busy}
                value={c.basis}
                maxLength={3000}
                onChange={(e) => criterion(c.id, { basis: e.target.value })}
              />
            </label>
            <div className="row">
              <label className="check-label">
                <input
                  type="checkbox"
                  disabled={busy}
                  checked={c.critical}
                  onChange={(e) => criterion(c.id, { critical: e.target.checked })}
                />
                关键项
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  disabled={busy}
                  checked={c.baseline}
                  onChange={(e) => criterion(c.id, { baseline: e.target.checked })}
                />
                纳入人工基准分母
              </label>
            </div>
            <FormSelect
              label="AI是否覆盖本项"
              value={c.result}
              disabled={busy}
              options={[
                { value: 'UNREVIEWED', label: '尚未核对' },
                { value: 'COVERED', label: '正确覆盖' },
                { value: 'MISSING', label: '确认遗漏' },
              ]}
              onChange={(v) =>
                criterion(c.id, { result: v as Criterion['result'], matched_key: '' })
              }
            />
            {c.result === 'COVERED' && (
              <FormSelect
                label="关联详情中已确认的条目"
                value={c.matched_key}
                disabled={busy}
                options={[
                  { value: '', label: '请选择已确认条目' },
                  ...data.items
                    .filter((i) => value.items[i.key]?.verdict === 'VALID')
                    .map((i) => ({ value: i.key, label: i.title })),
                ]}
                onChange={(v) => criterion(c.id, { matched_key: v })}
              />
            )}
            <p className="hint">保存即确认属于本记录原固定范围。</p>
            <button
              type="button"
              className="danger ghost small"
              disabled={busy}
              onClick={() =>
                setValue((s) => ({ ...s, criteria: s.criteria.filter((x) => x.id !== c.id) }))
              }
            >
              移除此项
            </button>
          </section>
        ))}
        <label className="check-label">
          <input
            type="checkbox"
            disabled={busy}
            checked={value.scope_reviewed}
            onChange={(e) => setValue((s) => ({ ...s, scope_reviewed: e.target.checked }))}
          />
          已核对原固定范围（可选）
        </label>
        <label>
          范围核对说明
          <textarea
            rows={3}
            maxLength={3000}
            disabled={busy}
            value={value.note}
            onChange={(e) => setValue((s) => ({ ...s, note: e.target.value }))}
          />
        </label>
      </Form>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <details className="aa-history">
        <summary>清单／历史验收审计（{data.history.length}）</summary>
        {data.history.map((h) => (
          <p key={h.revision}>
            v{h.revision} · {h.actor} · {new Date(h.time).toLocaleString('zh-CN')}
          </p>
        ))}
      </details>
      {exit && (
        <CaseDialog title="放弃未保存的清单修改？" busy={false} onClose={() => setExit(false)}>
          <p>当前清单修改尚未保存。</p>
          <div className="row">
            <button type="button" onClick={() => setExit(false)}>
              继续编辑
            </button>
            <button type="button" className="danger" onClick={onClose}>
              放弃修改
            </button>
          </div>
        </CaseDialog>
      )}
    </CaseDialog>
  );
}

function Rules() {
  return (
    <details className="aa-footnote">
      <summary>指标定义与计算口径</summary>
      <p>
        处理进度＝（已认可＋误报＋忽略／不适用）÷原始条目总数；认可率＝已认可÷已明确处理条目。数据自动来自详情处理和实际入库，修改后采纳不代表AI原稿正确。
      </p>
      <p>
        关键遗漏按人工确认的原固定范围重要遗漏项计数；范围未核对且未登记遗漏时显示“—”。基准覆盖率＝关联详情中已认可条目的已覆盖基准项÷人工基准总项数，没有清单时显示“—”。回归建议可用率＝详情已采纳÷（已采纳＋不采纳）回归建议；修订建议采纳率＝实际新增或修改成功÷原始明确修订建议数。
      </p>
      <p>
        生成新增／修改候选、需求风险、代码发现、变更影响、用例分析问题分别统计。回归建议按详情采纳／不采纳统计，暂缓不进入分母；人工补写不进入AI分母。未记录依据核对或重复原因时保持未知，不要求补做一遍评价。
      </p>
    </details>
  );
}
function Values({
  metrics,
  module,
  part,
}: {
  metrics: AcceptanceMetrics;
  module: OverviewModule;
  part?: 'core' | 'special';
}) {
  const values = acceptanceValues(metrics, module);
  return (
    <dl className="aa-values">
      {(part === 'core' ? values.slice(0, 5) : part === 'special' ? values.slice(5) : values).map(
        ([label, value, detail]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
            <small>{detail}</small>
          </div>
        ),
      )}
    </dl>
  );
}

export function AcceptanceSummary({
  projectId,
  onSelectProject,
  onSessionEnd,
}: {
  projectId: number | null;
  onSelectProject?: (id: number) => void;
  onSessionEnd: () => void;
}) {
  const [groups, setGroups] = useState<AcceptanceGroup[] | null>(null),
    [error, setError] = useState(''),
    [reload, setReload] = useState(0),
    [loading, setLoading] = useState(true);
  useEffect(() => {
    const c = new AbortController();
    setGroups(null);
    setLoading(true);
    setError('');
    let fetching = false;
    const read = () => {
      if (fetching || c.signal.aborted) return;
      fetching = true;
      void readAcceptanceSummary(projectId, c.signal)
        .then((v) => {
          if (!c.signal.aborted) {
            setGroups(v);
            setError('');
          }
        })
        .catch((e) => {
          if (!c.signal.aborted) {
            if (
              e instanceof Error &&
              ['not_authenticated', 'project_not_found', 'admin_required'].includes(e.message)
            )
              setGroups(null);
            setError(acceptanceError(e, onSessionEnd));
          }
        })
        .finally(() => {
          fetching = false;
          if (!c.signal.aborted) setLoading(false);
        });
    };
    read();
    window.addEventListener('focus', read);
    return () => {
      c.abort();
      window.removeEventListener('focus', read);
    };
  }, [projectId, reload, onSessionEnd]);
  const available = groups?.filter((g) => g.available && g.metrics) || [];
  const sum = (key: keyof AcceptanceMetrics) => available.reduce((n, g) => n + g.metrics![key], 0);
  const processed = sum('valid') + sum('invalid') + sum('dismissed');
  return (
    <section className="aa-summary" aria-label="AI结果汇总">
      <div className="panel-head">
        <div>
          <h2>结果总览</h2>
        </div>
        <button className="ghost small" disabled={loading} onClick={() => setReload((v) => v + 1)}>
          {loading ? '读取中…' : '刷新指标'}
        </button>
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {groups && (
        <>
          {available.length < groups.length && (
            <p className="notice" role="status">
              已读取 {available.length}/5 类分析。以下总量仅包含已读取模块，暂不可用项请刷新重试。
            </p>
          )}
          <dl className="aa-totals">
            {[
              ['有结果记录', sum('records')],
              ['AI原始条目', sum('total')],
              ['已明确处理', processed],
              ['待人工处理', sum('needs_review') + sum('unreviewed')],
            ].map(([label, value]) => (
              <div className="panel" key={label}>
                <dt>{label}</dt>
                <dd>{available.length ? value : '—'}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
      {!groups && loading ? (
        <p className="panel-pad" role="status">
          正在汇总验收指标…
        </p>
      ) : (
        groups?.map((g, index) => (
          <article className="panel aa-module" key={g.module}>
            <div className="aa-module-head">
              <div className="aa-module-title">
                <span className="aa-module-number" aria-hidden="true">
                  0{index + 1}
                </span>
                <div>
                  <h3>{overviewModules[g.module][0]}</h3>
                  {g.metrics && (
                    <p className="hint">
                      {g.metrics.records} 次有结果记录 · {g.metrics.total} 条AI原始条目
                    </p>
                  )}
                </div>
              </div>
              {projectId !== null && (
                <Link
                  className="action ghost small"
                  to={overviewModules[g.module][1]}
                  onClick={() => onSelectProject?.(projectId)}
                >
                  进入分析
                </Link>
              )}
            </div>
            {g.available && g.metrics ? (
              <>
                {g.metrics.records === 0 && <p className="hint aa-empty">暂无有结果的分析记录。</p>}
                <Values metrics={g.metrics} module={g.module} part="core" />
                <div className="aa-special">
                  <h4>模块专属指标</h4>
                  <Values metrics={g.metrics} module={g.module} part="special" />
                </div>
              </>
            ) : (
              <p className="hint">暂不可用</p>
            )}
          </article>
        ))
      )}
      <p className="aa-footnote">“—”表示暂无评价样本；覆盖率仅针对人工基准清单。</p>
      <Rules />
    </section>
  );
}

export function AcceptancePanel({
  projectId,
  module,
  recordId,
  onSessionEnd,
  refreshKey,
}: {
  projectId: number;
  module: OverviewModule;
  recordId: number | null;
  onSessionEnd: () => void;
  refreshKey?: string | number;
}) {
  return recordId && Number.isSafeInteger(recordId) && recordId > 0 ? (
    <RecordPanel
      key={`${projectId}:${module}:${recordId}`}
      projectId={projectId}
      module={module}
      recordId={recordId}
      onSessionEnd={onSessionEnd}
      refreshKey={refreshKey}
    />
  ) : null;
}
function RecordPanel({
  projectId,
  module,
  recordId,
  onSessionEnd,
  refreshKey,
}: {
  projectId: number;
  module: OverviewModule;
  recordId: number;
  onSessionEnd: () => void;
  refreshKey?: string | number;
}) {
  const [data, setData] = useState<AcceptanceDetail | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(''),
    [reload, setReload] = useState(0),
    [scopeOpen, setScopeOpen] = useState(false);
  useEffect(() => {
    const c = new AbortController();
    setLoading(true);
    void readAcceptance(projectId, module, recordId, c.signal)
      .then((d) => {
        if (!c.signal.aborted) {
          setData(d);
          setError('');
        }
      })
      .catch((e) => {
        if (!c.signal.aborted) {
          setData(null);
          setError(acceptanceError(e, onSessionEnd));
        }
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [projectId, module, recordId, reload, refreshKey, onSessionEnd]);
  return (
    <section className="panel aa-record">
      <div className="panel-head">
        <div>
          <h2>本记录AI结果指标</h2>
          <p className="hint">
            {data ? `${data.title} · #${recordId}` : '统计自动来自现有详情处理，无需再次确认'}
          </p>
        </div>
        <div className="row">
          <button
            className="ghost small"
            disabled={loading}
            onClick={() => setReload((v) => v + 1)}
          >
            刷新指标
          </button>
          <button className="small" disabled={!data || loading} onClick={() => setScopeOpen(true)}>
            遗漏与基准
          </button>
        </div>
      </div>
      {error && (
        <p
          className={
            error === '本记录尚无可统计的正式报告。' ? 'aa-footnote' : 'form-error aa-footnote'
          }
          role={error === '本记录尚无可统计的正式报告。' ? 'status' : 'alert'}
        >
          {error}
        </p>
      )}
      {loading && !data && (
        <p className="aa-footnote" role="status">
          正在读取本记录指标…
        </p>
      )}
      {data && (
        <>
          <Values metrics={data.metrics} module={module} />

          <Rules />
          {data.stale && (
            <p className="notice">原报告已变化，旧清单保留审计；当前处理结果仍按原详情统计。</p>
          )}
        </>
      )}
      {data && scopeOpen && (
        <AcceptanceEditor
          key={data.revision}
          data={data}
          onClose={() => setScopeOpen(false)}
          onSaved={(d) => {
            setData(d);
            setScopeOpen(false);
          }}
          onSessionEnd={onSessionEnd}
        />
      )}
    </section>
  );
}
