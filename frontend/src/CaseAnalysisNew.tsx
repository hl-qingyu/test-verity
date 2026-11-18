import { PrototypeDirectoryFiles } from './PrototypeDirectoryFiles';
import { PageJump } from './PageJump';
import { useRef, useState } from 'react';
import { CaseDialog } from './CaseDialog';
import { Form } from './Form';
import { FormSelect } from './FormSelect';
import { GithubMaterial } from './CaseGenerationNew';
import { PrototypeLinkPages } from './PrototypeLinkPages';
import type { CodeOptions } from './codeAnalysisApi';
import type { PrototypeSource } from './prototypeApi';
import type { CaseList } from './caseApi';
import type { GenerationMaterial } from './generationPage';

export function CaseAnalysisNew({
  options,
  prototypes,
  snapshot,
  projectId,
  parentId,
  busy,
  error,
  onClose,
  onPrepare,
  onSessionEnd,
}: {
  options: CodeOptions;
  prototypes: PrototypeSource[];
  snapshot: CaseList;
  projectId: number;
  parentId?: number;
  busy: boolean;
  error: string;
  onClose: () => void;
  onPrepare: (v: unknown) => Promise<void>;
  onSessionEnd: () => void;
}) {
  const [mode, setMode] = useState('COMPARE'),
    [title, setTitle] = useState('现有用例 · 分析'),
    [scope, setScope] = useState('all'),
    [category, setCategory] = useState('*'),
    [query, setQuery] = useState(''),
    [ids, setIds] = useState<number[]>([]),
    [page, setPage] = useState(1),
    [materials, setMaterials] = useState<GenerationMaterial[]>([]),
    [focus, setFocus] = useState(''),
    [zero, setZero] = useState(false);
  const request = useRef<{ signature: string; id: string } | null>(null),
    lock = useRef(false);
  const candidates = snapshot.items.filter(
    (c) =>
      (category === '*' || String(c.category_id || 0) === category) &&
      (!query || [c.title, c.module, c.expected].some((s) => s.includes(query))),
  );
  const selected =
    scope === 'all'
      ? snapshot.items
      : scope === 'filtered'
        ? candidates
        : snapshot.items.filter((c) => ids.includes(c.id));
  function pick(v: GenerationMaterial) {
    setMaterials((rows) => rows.map((m) => (m.documentId === v.documentId ? v : m)));
  }
  async function submit() {
    if (lock.current || busy) return;
    const body = {
      title,
      mode,
      materials:
        mode === 'QUALITY'
          ? []
          : materials.map((m) => ({
              document_id: m.documentId,
              version: m.version,
              paths: m.paths,
              connection_id: m.connectionId || null,
            })),
      search: { lifecycle: 'ACTIVE', page: 1, page_size: 100, category_id: null, conditions: [] },
      case_ids: selected.map((c) => c.id),
      case_versions: Object.fromEntries(selected.map((c) => [String(c.id), c.version])),
      library_revision: snapshot.revision,
      zero_confirmed: zero,
      focus,
      parent_id: parentId || null,
    };
    const signature = JSON.stringify(body);
    if (request.current?.signature !== signature)
      request.current = { signature, id: crypto.randomUUID() };
    lock.current = true;
    try {
      await onPrepare({ ...body, request_id: request.current.id });
    } finally {
      lock.current = false;
    }
  }
  return (
    <CaseDialog
      title={parentId ? '关联复核 · 新建分析' : '新建用例分析'}
      busy={busy}
      onClose={onClose}
      wide
      className="case-review-dialog case-review-new"
      footer={
        <footer className="change-dialog-footer review-dialog-footer">
          <button disabled={busy} onClick={onClose}>
            取消
          </button>
          <button className="primary" disabled={busy} form="caseReviewNew">
            {busy ? '正在读取并固定输入…' : '读取资料并准备分析'}
          </button>
        </footer>
      }
    >
      <Form
        id="caseReviewNew"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <fieldset disabled={busy} className="review-prepare-fields">
          <div className="form-grid">
            <label className="field-label">
              分析名称
              <input
                required
                maxLength={200}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </label>
            <FormSelect
              label="审查方式"
              value={mode}
              options={[
                { value: 'COMPARE', label: '对照需求分析' },
                { value: 'QUALITY', label: '仅检查用例质量' },
              ]}
              onChange={setMode}
            />
          </div>
          {mode === 'COMPARE' && (
            <section className="review-form-section">
              <h3>需求与原型 · 固定完整正文及页面批注</h3>
              {options.materials.map((m) => {
                const p = materials.find((x) => x.documentId === m.id),
                  versions = [...m.versions].sort((a, b) => b.number - a.number),
                  name =
                    m.kind === 'FILE'
                      ? (versions.find((v) => String(v.id) === p?.version) || versions[0])
                          ?.filename || m.name
                      : m.name,
                  source = prototypes.find((s) => s.id === m.id);
                return (
                  <section className="evidence review-source-card" key={m.id}>
                    <label className="check-label">
                      <input
                        type="checkbox"
                        checked={!!p}
                        disabled={['FILE', 'DIRECTORY'].includes(m.kind) && !m.versions.length}
                        onChange={(e) =>
                          setMaterials((rows) =>
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
                                    before: '',
                                    update: '',
                                    paths: [],
                                    readState: 'NOT_LOADED',
                                    segments: [],
                                  },
                                ]
                              : rows.filter((x) => x.documentId !== m.id),
                          )
                        }
                      />
                      <span className="review-source-name">{name}</span>
                    </label>
                    {p && ['FILE', 'DIRECTORY'].includes(m.kind) && (
                      <FormSelect
                        label="固定版本"
                        value={p.version}
                        options={m.versions.map((v) => ({
                          value: String(v.id),
                          label: `v${v.number} · ${v.filename}`,
                        }))}
                        onChange={(v) =>
                          pick({
                            ...p,
                            version: v,
                            ...(m.kind === 'DIRECTORY' ? { paths: [] } : {}),
                            name:
                              m.kind === 'DIRECTORY'
                                ? m.name
                                : versions.find((item) => String(item.id) === v)?.filename ||
                                  m.name,
                          })
                        }
                      />
                    )}{' '}
                    {p && m.kind === 'DIRECTORY' && p.version && (
                      <PrototypeDirectoryFiles
                        key={`${m.id}:${p.version}`}
                        projectId={projectId}
                        documentId={m.id}
                        versionId={Number(p.version)}
                        value={p.paths}
                        onChange={(paths) => pick({ ...p, paths })}
                        onSessionEnd={onSessionEnd}
                        disabled={busy}
                      />
                    )}
                    {p && m.kind === 'GITHUB' && source && (
                      <GithubMaterial
                        projectId={projectId}
                        source={source}
                        connections={options.connections}
                        picked={p}
                        onChange={pick}
                        onSessionEnd={onSessionEnd}
                      />
                    )}{' '}
                    {p && m.kind === 'LINK' && source && (
                      <PrototypeLinkPages
                        projectId={projectId}
                        documentId={m.id}
                        value={{ paths: p.paths, snapshot: p.version }}
                        onChange={(v) => pick({ ...p, paths: v.paths, version: v.snapshot })}
                        onSessionEnd={onSessionEnd}
                      />
                    )}
                  </section>
                );
              })}
            </section>
          )}
          <div className="form-grid">
            <FormSelect
              label="用例范围"
              value={scope}
              options={[
                { value: 'all', label: '全部活动用例' },
                { value: 'filtered', label: '分类 / 搜索结果' },
                { value: 'selected', label: '已勾选用例（跨页）' },
              ]}
              onChange={(v) => {
                setScope(v);
                setPage(1);
              }}
            />

            <FormSelect
              disabled={scope === 'all'}
              label="分类"
              value={category}
              options={[
                { value: '*', label: '全部分类' },
                { value: '0', label: '未分类' },
                ...snapshot.categories.map((c) => ({ value: String(c.id), label: c.name })),
              ]}
              onChange={(v) => {
                setCategory(v);
                setPage(1);
              }}
            />
            <label className="field-label span2">
              搜索标题 / 模块 / 预期
              <input
                disabled={scope === 'all'}
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setPage(1);
                }}
              />
            </label>
          </div>
          <p className="hint">已选{selected.length}条（含其他分页）；准备不调用AI。</p>
          {scope === 'selected' && (
            <>
              <div className="row">
                <button
                  type="button"
                  onClick={() => setIds([...new Set([...ids, ...candidates.map((c) => c.id)])])}
                >
                  全选候选（跨页）
                </button>
                <button type="button" onClick={() => setIds([])}>
                  清空
                </button>
              </div>
              {candidates.slice((page - 1) * 10, page * 10).map((c) => (
                <label className="check-label" key={c.id}>
                  <input
                    type="checkbox"
                    checked={ids.includes(c.id)}
                    onChange={(e) =>
                      setIds((old) =>
                        e.target.checked ? [...old, c.id] : old.filter((id) => id !== c.id),
                      )
                    }
                  />
                  {c.number} · {c.title} / v{c.version}
                </label>
              ))}
              <div className="row">
                <button type="button" disabled={page === 1} onClick={() => setPage((p) => p - 1)}>
                  上一页
                </button>
                <span>
                  {page}/{Math.max(1, Math.ceil(candidates.length / 10))}
                </span>
                <button
                  type="button"
                  disabled={page * 10 >= candidates.length}
                  onClick={() => setPage((p) => p + 1)}
                >
                  下一页
                </button>
                <PageJump
                  page={page}
                  onChange={setPage}
                  pages={Math.max(1, Math.ceil(candidates.length / 10))}
                  disabled={busy}
                />
              </div>
            </>
          )}
          <label className="field-label">
            关注点
            <textarea value={focus} maxLength={10000} onChange={(e) => setFocus(e.target.value)} />
          </label>
          <label className="check-label">
            <input type="checkbox" checked={zero} onChange={(e) => setZero(e.target.checked)} />
            0条时确认仅识别所选需求缺失场景
          </label>
        </fieldset>
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
      </Form>
    </CaseDialog>
  );
}
