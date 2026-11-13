import { PrototypeDirectoryFiles } from './PrototypeDirectoryFiles';
import { PageJump } from './PageJump';
import { useEffect, useId, useRef, useState } from 'react';
import { CaseDialog } from './CaseDialog';
import { Form } from './Form';
import { FormSelect } from './FormSelect';
import { CodeFileTree } from './CodeAnalysisNew';
import { PrototypeLinkPages } from './PrototypeLinkPages';
import { GitVersionPicker } from './GitVersionPicker';
import { apiRequest } from './api/http';
import { codeError } from './codeAnalysisApi';
import type { CodeOptions } from './codeAnalysisApi';
import type { PrototypeSource } from './prototypeApi';
import { parsePrototypeScope } from './prototypeApi';
import type { CaseList } from './caseApi';
import type { User } from './Auth';
import type { GenerationMaterial, GenerationRecord, GenerationSummary } from './generationPage';
import { generationDetail, generationError } from './generationApi';

export function GithubMaterial({
  projectId,
  source,
  connections,
  picked,
  onChange,
  onSessionEnd,
}: {
  projectId: number;
  source: PrototypeSource;
  connections: CodeOptions['connections'];
  picked: GenerationMaterial;
  onChange: (value: GenerationMaterial) => void;
  onSessionEnd: () => void;
}) {
  const [connection, setConnection] = useState(connections[0]?.id || 0),
    [sha, setSha] = useState(picked.version),
    [files, setFiles] = useState(source.files.map((f) => f.path)),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  function clear(value: string, selectedConnection = connection) {
    controller.current?.abort();
    setBusy(false);
    setSha(value);
    setFiles([]);
    onChange({ ...picked, version: value, paths: [], connectionId: selectedConnection });
  }
  async function read() {
    controller.current?.abort();
    const c = new AbortController();
    controller.current = c;
    setBusy(true);
    setError('');
    try {
      const scope = parsePrototypeScope(
        await apiRequest<unknown>(`/api/projects/${projectId}/prototypes/scope`, {
          method: 'POST',
          signal: c.signal,
          body: JSON.stringify({
            connection_id: connection,
            repository_id: source.repository_id,
            branch: sha,
            path: source.path || '',
          }),
        }),
      );
      if (c.signal.aborted) return;
      if (scope.full_name !== source.repository_name || scope.commit !== sha)
        throw Error('code_source_changed');
      setFiles(scope.files.map((f) => f.path));
      onChange({ ...picked, version: scope.commit, paths: [], connectionId: connection });
    } catch (e) {
      if (!c.signal.aborted) setError(codeError(e, onSessionEnd));
    } finally {
      if (!c.signal.aborted) setBusy(false);
    }
  }
  return (
    <>
      <FormSelect
        label="本人GitHub连接"
        value={String(connection || '')}
        options={[
          { value: '', label: '请选择连接' },
          ...connections.map((c) => ({ value: String(c.id), label: c.name })),
        ]}
        onChange={(v) => {
          setConnection(Number(v));
          clear('', Number(v));
        }}
        disabled={busy}
      />
      <GitVersionPicker
        label="固定提交版本"
        projectId={projectId}
        repositoryId={source.repository_id || 0}
        connectionId={connection}
        defaultBranch={source.branch || 'main'}
        value={sha}
        onChange={clear}
        onSessionEnd={onSessionEnd}
        disabled={busy}
      />
      <button
        type="button"
        className="small"
        disabled={busy || !sha || !connection}
        onClick={() => void read()}
      >
        {busy ? '读取中…' : '读取原型文件树'}
      </button>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <p className="hint mono">{picked.version}</p>
      <CodeFileTree
        paths={files}
        selected={picked.paths}
        disabled={busy}
        onChange={(paths) => onChange({ ...picked, paths, connectionId: connection })}
      />
    </>
  );
}
export function CaseGenerationNew({
  projectId,
  user,
  options,
  prototypes,
  snapshot,
  records,
  busy = false,
  serverError = '',
  onClose,
  onCreate,
  onSessionEnd,
}: {
  projectId: number;
  user: User;
  options: CodeOptions;
  prototypes: PrototypeSource[];
  snapshot: CaseList;
  records: (GenerationRecord | GenerationSummary)[];
  busy?: boolean;
  serverError?: string;
  onClose: () => void;
  onCreate: (record: GenerationRecord) => Promise<boolean>;
  onSessionEnd: () => void;
}) {
  const [title, setTitle] = useState(''),
    [mode, setMode] = useState<'INITIAL' | 'UPDATE'>('INITIAL'),
    [baselineId, setBaseline] = useState(''),
    [picked, setPicked] = useState<GenerationMaterial[]>([]),
    [scope, setScope] = useState('完整所选资料'),
    [scopeText, setScopeText] = useState(''),
    [caseScope, setCaseScope] = useState('不对照已有用例'),
    [category, setCategory] = useState(''),
    [caseIds, setIds] = useState<number[]>([]),
    [caseQuery, setCaseQuery] = useState(''),
    [casePage, setCasePage] = useState(1),
    [reference, setReference] = useState(false),
    [focus, setFocus] = useState(''),
    [error, setError] = useState('');
  const [preparing, setPreparing] = useState(false),
    submitting = useRef(false),
    request = useRef<{ signature: string; id: string } | null>(null),
    inFlight = busy || preparing;
  const [loadedBase, setBase] = useState<GenerationRecord | null>(null),
    [baselineBusy, setBaselineBusy] = useState(false);
  useEffect(() => {
    setBase(null);
    if (!baselineId) {
      setBaselineBusy(false);
      return;
    }
    const c = new AbortController();
    setBaselineBusy(true);
    setError('');
    generationDetail(projectId, baselineId, c.signal)
      .then((row) => {
        if (!c.signal.aborted) setBase(row);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(generationError(e, onSessionEnd));
      })
      .finally(() => {
        if (!c.signal.aborted) setBaselineBusy(false);
      });
    return () => c.abort();
  }, [baselineId, projectId, onSessionEnd]);
  const [riskReports, setRiskReports] = useState<{ id: number; title: string }[]>([]),
    [riskId, setRiskId] = useState(''),
    [riskMore, setRiskMore] = useState(false),
    [riskPage, setRiskPage] = useState(1);
  useEffect(() => {
    if (!reference) return;
    const c = new AbortController();
    apiRequest<unknown>(`/api/projects/${projectId}/requirements/risk-reports?page=${riskPage}`, {
      signal: c.signal,
    })
      .then((value) => {
        if (
          !value ||
          typeof value !== 'object' ||
          !('items' in value) ||
          !Array.isArray(value.items) ||
          !('has_more' in value) ||
          typeof value.has_more !== 'boolean'
        )
          throw Error('risk_response_invalid');
        const items = value.items.map((r: unknown) => {
          if (
            !r ||
            typeof r !== 'object' ||
            !('id' in r) ||
            typeof r.id !== 'number' ||
            !Number.isSafeInteger(r.id) ||
            !('title' in r) ||
            typeof r.title !== 'string'
          )
            throw Error('risk_response_invalid');
          return { id: r.id, title: r.title };
        });
        if (!c.signal.aborted) {
          setRiskReports((old) => (riskPage === 1 ? items : [...old, ...items]));
          setRiskMore(value.has_more);
        }
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(codeError(e, onSessionEnd));
      });
    return () => c.abort();
  }, [reference, projectId, riskPage, onSessionEnd]);
  const formId = useId(),
    base = loadedBase?.id === baselineId ? loadedBase : null;
  const selectedCases = snapshot.items.filter(
    (c) =>
      caseScope !== '不对照已有用例' &&
      (caseScope === '整个项目' ||
        (caseScope === '所选分类'
          ? c.category_id === (category ? Number(category) : null)
          : caseIds.includes(c.id))),
  );
  const caseRows = snapshot.items.filter((c) =>
      (c.number + c.title + c.module).toLowerCase().includes(caseQuery.toLowerCase()),
    ),
    pages = Math.max(1, Math.ceil(caseRows.length / 20)),
    page = Math.min(casePage, pages);
  function changeMaterial(documentId: number, patch: Partial<GenerationMaterial>) {
    setPicked((old) => old.map((m) => (m.documentId === documentId ? { ...m, ...patch } : m)));
  }
  const materialReady =
    picked.length > 0 &&
    picked.every(
      (m) =>
        m.version &&
        (m.kind === 'FILE' || m.paths.length > 0) &&
        (m.kind !== 'DIRECTORY' || !m.before || !!m.beforePaths?.length),
    );
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (submitting.current || inFlight) return;
    if (baselineId && (!base || base.id !== baselineId || baselineBusy)) {
      setError('请等待所选历史基准读取完成；读取失败时可重新选择。');
      return;
    }
    if (!materialReady) {
      setError('请勾选资料、固定版本，并完成每份已选GitHub/链接的文件或页面范围。');
      return;
    }
    if (reference && !riskId) {
      setError('请选择要固定带入的需求风险报告。');
      return;
    }
    if (scope === '指定功能' && !scopeText.trim()) {
      setError('请填写功能范围。');
      return;
    }
    if (caseScope === '手动勾选' && !selectedCases.length) {
      setError('请勾选用例。');
      return;
    }
    if (picked.some((m) => m.before && m.before === m.version)) {
      setError('同一资料旧新版本相同，请重新选择。');
      return;
    }
    const signature = JSON.stringify([
      title.trim(),
      mode,
      scope,
      scopeText,
      focus,
      picked,
      caseScope,
      selectedCases.map((c) => [c.id, c.version]),
      snapshot.revision,
      baselineId,
      reference ? riskId : '',
    ]);
    if (request.current?.signature !== signature)
      request.current = { signature, id: crypto.randomUUID() };
    submitting.current = true;
    setPreparing(true);
    setError('');
    try {
      await onCreate({
        riskReportIds: reference ? [Number(riskId)] : [],
        id: request.current.id,
        projectId,
        ownerId: user.id,
        title: title.trim(),
        createdAt: new Date().toISOString(),
        mode,
        origin: 'DRAFT',
        cancelled: false,
        scope: scope === '指定功能' ? scopeText.trim() : scope,
        focus,
        materials: structuredClone(
          picked.map((m) => {
            const source = options.materials.find((s) => s.id === m.documentId),
              current = source?.versions.find((v) => String(v.id) === m.version),
              previous = source?.versions.find((v) => String(v.id) === m.before);
            return {
              ...m,
              versionName: current ? `v${current.number} · ${current.filename}` : m.version,
              beforeName: previous ? `v${previous.number} · ${previous.filename}` : m.before,
            };
          }),
        ),
        cases: structuredClone(selectedCases),
        caseScope: `${caseScope} · ${selectedCases.length}条固定用例`,
        libraryRevision: snapshot.revision,
        baselineId,
        suggestions: [],
        questions: [],
        handling: {},
        decisions: [],
        failures: [],
        chatDrafts: {},
        batches: [],
        limitations: [
          reference ? '已记录参考需求风险的意向，精确分析记录引用待接入。' : '未选择额外分析引用。',
          '读取完整正文并保存固定输入；查看输入估算后开始本人AI生成。',
        ],
        outcome: '',
      });
    } catch (e) {
      setError(generationError(e, onSessionEnd));
    } finally {
      submitting.current = false;
      setPreparing(false);
    }
  }
  return (
    <CaseDialog
      title="新建用例生成"
      busy={inFlight}
      onClose={onClose}
      wide
      className="code-analysis-dialog change-analysis-dialog generation-dialog"
      footer={
        <footer className="change-dialog-footer">
          <button type="button" disabled={inFlight} onClick={onClose}>
            取消
          </button>
          <button
            type="submit"
            form={formId}
            className="primary"
            disabled={inFlight || baselineBusy}
          >
            {inFlight ? '正在读取资料并准备…' : '读取资料并准备生成'}
          </button>
        </footer>
      }
    >
      <Form id={formId} onSubmit={submit} aria-busy={inFlight}>
        {inFlight && (
          <p className="notice" role="status">
            <span className="generation-spinner" aria-hidden="true" />
            正在读取所选资料并保存固定输入，请稍候。此时尚未调用AI，准备完成后再确认开始生成。
          </p>
        )}
        <fieldset disabled={inFlight} className="generation-prepare-fields">
          <p className="notice">
            准备实际资料与用例快照，查看输入估算后开始本人AI生成；维护无需历史生成记录。
          </p>
          <label className="form-field">
            名称
            <input
              required
              maxLength={200}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <FormSelect
            label="生成模式"
            value={mode}
            options={[
              { value: 'INITIAL', label: '首次生成' },
              { value: 'UPDATE', label: '维护已有用例' },
            ]}
            onChange={(v) => {
              setMode(v === 'UPDATE' ? 'UPDATE' : 'INITIAL');
              setBaseline('');
              setPicked((old) => old.map((m) => ({ ...m, before: '', update: '' })));
            }}
          />
          {mode === 'UPDATE' && (
            <>
              <FormSelect
                label="可选旧资料/历史基准"
                value={baselineId}
                options={[
                  { value: '', label: '无历史基准，按当前需求核对' },
                  ...records
                    .filter((r) => ('hasMaterials' in r ? r.hasMaterials : r.materials.length))
                    .map((r) => ({ value: r.id, label: r.title })),
                ]}
                onChange={(v) => {
                  setBaseline(v);
                  setPicked((old) => old.map((m) => ({ ...m, before: '', update: '' })));
                }}
              />
              <div className="evidence">
                {baselineBusy
                  ? '正在读取所选历史基准…'
                  : base
                    ? '已选固定历史范围，可配对相同资料旧版本。'
                    : '保留原编号及当前人工内容；没有旧需求时不推断历史变化，不因未提及而停用。'}
              </div>
            </>
          )}
          <section>
            <h3>需求与原型资料 · 直接勾选固定版本</h3>
            {options.materials.map((m) => {
              const p = picked.find((p) => p.documentId === m.id),
                versions = [...m.versions].sort((a, b) => b.number - a.number),
                name =
                  m.kind === 'FILE'
                    ? (versions.find((v) => String(v.id) === p?.version) || versions[0])
                        ?.filename || m.name
                    : m.name,
                old = base?.materials.find(
                  (b) => b.documentId === m.id && b.kind === m.kind && b.side !== 'BEFORE',
                ),
                source = prototypes.find((s) => s.id === m.id);
              return (
                <section className="evidence generation-source" key={m.id}>
                  <label className="check-label">
                    <input
                      type="checkbox"
                      checked={!!p}
                      disabled={['FILE', 'DIRECTORY'].includes(m.kind) && !versions.length}
                      onChange={(e) => {
                        setPicked((rows) =>
                          e.target.checked
                            ? [
                                ...rows,
                                {
                                  documentId: m.id,
                                  sourceId: String(m.id),
                                  name,
                                  purpose: m.purpose,
                                  kind: m.kind,
                                  version: ['FILE', 'DIRECTORY'].includes(m.kind)
                                    ? String(versions[0]?.id || '')
                                    : m.kind === 'GITHUB'
                                      ? m.commit
                                      : '',
                                  before: mode === 'UPDATE' ? old?.version || '' : '',
                                  update: old ? '完整替换' : '',
                                  paths: [],
                                  readState: 'NOT_LOADED',
                                  segments: [],
                                },
                              ]
                            : rows.filter((x) => x.documentId !== m.id),
                        );
                      }}
                    />
                    <strong>{name}</strong>
                    <span className="hint">
                      {m.purpose === 'PROTOTYPE' ? '原型资料' : '需求资料'} ·{' '}
                      {m.kind === 'LINK'
                        ? '选择页面目录；正文未固定'
                        : m.kind === 'GITHUB'
                          ? '固定提交及文件范围'
                          : '固定文件版本'}
                    </span>
                  </label>
                  {p && (
                    <>
                      {mode === 'UPDATE' && (
                        <div className="form-grid mt">
                          {m.kind === 'GITHUB' && source ? (
                            <GitVersionPicker
                              label="此资料旧基准（可选）"
                              defaultBranch={source.branch || 'main'}
                              projectId={projectId}
                              repositoryId={source.repository_id || 0}
                              connectionId={p.connectionId || options.connections[0]?.id || 0}
                              value={p.before}
                              disabled={false}
                              onChange={(before) =>
                                changeMaterial(m.id, {
                                  before,
                                  update: before ? '完整替换' : '',
                                  paths: [],
                                })
                              }
                              onSessionEnd={onSessionEnd}
                            />
                          ) : (
                            <FormSelect
                              label="此资料旧基准（可选）"
                              value={p.before}
                              options={[
                                { value: '', label: '无对应旧正文，按现状核对' },
                                ...versions.map((v) => ({
                                  value: String(v.id),
                                  label: `v${v.number} · ${v.filename}`,
                                })),
                                ...(old && !versions.some((v) => String(v.id) === old.version)
                                  ? [{ value: old.version, label: `固定历史 ${old.version}` }]
                                  : []),
                              ]}
                              onChange={(before) =>
                                changeMaterial(m.id, {
                                  before,
                                  update: before ? '完整替换' : '',
                                  beforePaths: [],
                                })
                              }
                            />
                          )}
                          {m.kind === 'DIRECTORY' && p.before && (
                            <PrototypeDirectoryFiles
                              key={`${m.id}:before:${p.before}`}
                              projectId={projectId}
                              documentId={m.id}
                              versionId={Number(p.before)}
                              value={p.beforePaths || []}
                              onChange={(beforePaths) => changeMaterial(m.id, { beforePaths })}
                              onSessionEnd={onSessionEnd}
                              disabled={inFlight}
                            />
                          )}
                          {p.before && (
                            <FormSelect
                              label="此资料更新方式"
                              value={p.update || '完整替换'}
                              options={['完整替换', '增量补充'].map((v) => ({
                                value: v,
                                label: v,
                              }))}
                              onChange={(update) => changeMaterial(m.id, { update })}
                            />
                          )}
                        </div>
                      )}
                      {['FILE', 'DIRECTORY'].includes(m.kind) && (
                        <FormSelect
                          label="当前需求版本"
                          value={p.version}
                          options={versions.map((v) => ({
                            value: String(v.id),
                            label: `v${v.number} · ${v.filename}`,
                          }))}
                          onChange={(version) =>
                            changeMaterial(m.id, {
                              version,
                              ...(m.kind === 'DIRECTORY' ? { paths: [] } : {}),
                              name:
                                m.kind === 'DIRECTORY'
                                  ? m.name
                                  : versions.find((v) => String(v.id) === version)?.filename ||
                                    m.name,
                            })
                          }
                        />
                      )}{' '}
                      {m.kind === 'DIRECTORY' && p.version && (
                        <PrototypeDirectoryFiles
                          key={`${m.id}:${p.version}`}
                          projectId={projectId}
                          documentId={m.id}
                          versionId={Number(p.version)}
                          value={p.paths}
                          onChange={(paths) => changeMaterial(m.id, { paths })}
                          onSessionEnd={onSessionEnd}
                          disabled={inFlight}
                        />
                      )}
                      {m.kind === 'GITHUB' &&
                        (source ? (
                          <GithubMaterial
                            key={`${m.id}`}
                            projectId={projectId}
                            source={source}
                            connections={options.connections}
                            picked={p}
                            onChange={(value) => {
                              setPicked((rows) =>
                                rows.map((x) => (x.documentId === m.id ? value : x)),
                              );
                            }}
                            onSessionEnd={onSessionEnd}
                          />
                        ) : (
                          <>
                            <p className="hint mono">{m.commit}</p>
                            <CodeFileTree
                              paths={m.files.map((f) => f.path)}
                              selected={p.paths}
                              disabled={false}
                              onChange={(paths) => changeMaterial(m.id, { paths })}
                            />
                          </>
                        ))}
                      {m.kind === 'LINK' && (
                        <PrototypeLinkPages
                          projectId={projectId}
                          documentId={m.id}
                          value={{ paths: p.paths, snapshot: p.version }}
                          onChange={(v) =>
                            changeMaterial(m.id, { paths: v.paths, version: v.snapshot })
                          }
                          onSessionEnd={onSessionEnd}
                        />
                      )}
                    </>
                  )}
                </section>
              );
            })}
            {!options.materials.length && (
              <p className="hint">暂无资料，请先添加需求或原型资料。</p>
            )}
          </section>
          <div className="form-grid">
            <FormSelect
              label="功能范围"
              value={scope}
              options={['完整所选资料', '指定功能'].map((v) => ({ value: v, label: v }))}
              onChange={(v) => {
                setScope(v);
              }}
            />
            <FormSelect
              label="现有用例范围"
              value={caseScope}
              options={['不对照已有用例', '整个项目', '所选分类', '手动勾选'].map((v) => ({
                value: v,
                label: v,
              }))}
              onChange={(v) => {
                setCaseScope(v);
              }}
            />
          </div>
          {scope === '指定功能' && (
            <label className="form-field">
              功能及范围说明
              <textarea
                required
                maxLength={2000}
                value={scopeText}
                onChange={(e) => {
                  setScopeText(e.target.value);
                }}
              />
            </label>
          )}
          {caseScope === '所选分类' && (
            <FormSelect
              label="选择用例分类"
              value={category}
              options={[
                { value: '', label: '未分类' },
                ...snapshot.categories.map((c) => ({ value: String(c.id), label: c.name })),
              ]}
              onChange={(v) => {
                setCategory(v);
              }}
            />
          )}
          {caseScope === '手动勾选' && (
            <section className="generation-case-picker">
              <label className="form-field">
                搜索用例
                <input
                  value={caseQuery}
                  onChange={(e) => {
                    setCaseQuery(e.target.value);
                    setCasePage(1);
                  }}
                />
              </label>
              {caseRows.slice((page - 1) * 20, page * 20).map((c) => (
                <label className="check-label mt" key={c.id}>
                  <input
                    type="checkbox"
                    checked={caseIds.includes(c.id)}
                    onChange={(e) => {
                      setIds((ids) =>
                        e.target.checked ? [...ids, c.id] : ids.filter((id) => id !== c.id),
                      );
                    }}
                  />
                  {c.number} · {c.title} / v{c.version}
                </label>
              ))}
              <div className="between mt">
                <span className="hint">
                  {caseRows.length}条 · 第{page}/{pages}页 · 已选{caseIds.length}条（跨页）
                </span>
                <div className="row">
                  <button
                    type="button"
                    className="small"
                    disabled={page === 1}
                    onClick={() => setCasePage(page - 1)}
                  >
                    上一页
                  </button>
                  <button
                    type="button"
                    className="small"
                    disabled={page === pages}
                    onClick={() => setCasePage(page + 1)}
                  >
                    下一页
                  </button>
                  <PageJump page={page} onChange={setCasePage} pages={pages} disabled={busy} />
                </div>
              </div>
            </section>
          )}
          <p className="hint">
            将冻结{selectedCases.length}条完整设计及版本，不以显示编号定位；开始生成后才发送本人AI。
          </p>
          <label className="check-label">
            <input
              type="checkbox"
              checked={reference}
              onChange={(e) => {
                setReference(e.target.checked);
              }}
            />
            参考需求风险（固定报告及处理快照，完整资料仍是依据）
          </label>
          {reference && (
            <section className="evidence">
              <FormSelect
                label="固定需求风险报告"
                value={riskId}
                options={[
                  { value: '', label: '请选择已有报告' },
                  ...riskReports.map((r) => ({ value: String(r.id), label: r.title })),
                ]}
                onChange={(v) => {
                  setRiskId(v);
                }}
              />
              {riskMore && (
                <button type="button" className="small" onClick={() => setRiskPage((p) => p + 1)}>
                  加载更多报告
                </button>
              )}
            </section>
          )}
          <label className="form-field">
            补充关注点
            <textarea maxLength={4000} value={focus} onChange={(e) => setFocus(e.target.value)} />
          </label>
          <p className="hint">
            完整所选资料一次交给本人AI。准备后显示文本输入估算，资料较大时可继续生成或缩小范围；不会自动拆分或重试。
          </p>
        </fieldset>
        {(error || serverError) && (
          <p className="form-error" role="alert">
            {error || serverError}
          </p>
        )}
      </Form>
    </CaseDialog>
  );
}
