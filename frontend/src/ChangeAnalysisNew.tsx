import { callModeName } from './aiConfiguration';
import { useEffect, useId, useRef, useState } from 'react';
import type { User } from './Auth';
import { CaseDialog } from './CaseDialog';
import { Form } from './Form';
import { FormSelect } from './FormSelect';
import { PrototypeDirectoryFiles } from './PrototypeDirectoryFiles';
import { CodeFileTree, SourcePicker } from './CodeAnalysisNew';
import type { ReadySource } from './CodeAnalysisNew';
import { readSelection } from './localCodeFiles';
import { changeDetail, changeError, changeTargets } from './changeAnalysisApi';
import { ChangeContext } from './ChangeContext';
import { ChangePrototypeSources } from './ChangePrototype';
import { GitVersionPicker } from './GitVersionPicker';
import { codeError, codeKinds, codeRequest, parseCodeScope } from './codeAnalysisApi';
import type { CodeOptions, CodeKind } from './codeAnalysisApi';
import { bindingKey, localError } from './localCodeApi';
import { loadSnapshot, readHistory, snapshotName } from './localCodeStore';
import type { Snapshot, SnapshotSummary } from './localCodeStore';
import { changeModes, changeScopeError } from './changeAnalysisPage';
import type { ChangeMode, ChangePair, PageChangeRecord } from './changeAnalysisPage';

type Repo = {
  id: number;
  name: string;
  kind: CodeKind;
  version: number;
  default_branch?: string;
  client_id?: string;
};
function CodeComparison({
  repo,
  source,
  options,
  projectId,
  user,
  onChange,
  onSessionEnd,
}: {
  repo: Repo;
  source: 'GITHUB' | 'LOCAL';
  options: CodeOptions;
  projectId: number;
  user: User;
  onChange: (pair: ChangePair | null) => void;
  onSessionEnd: () => void;
}) {
  const [enabled, setEnabled] = useState(false),
    [connection, setConnection] = useState(options.connections[0]?.id || 0),
    [before, setBefore] = useState(''),
    [after, setAfter] = useState(''),
    [history, setHistory] = useState<SnapshotSummary[]>([]),
    [moreHistory, setMoreHistory] = useState(false),
    [files, setFiles] = useState<string[]>([]),
    [selected, setSelected] = useState<string[]>([]),
    [fixed, setFixed] = useState<{ before: string; after: string; target: string[] } | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const controller = useRef(new AbortController()),
    generation = useRef(0),
    localSnapshots = useRef<[Snapshot, Snapshot] | null>(null);
  useEffect(() => {
    const c = new AbortController();
    controller.current = c;
    return () => c.abort();
  }, []);
  function clear() {
    generation.current++;
    setFiles([]);
    setSelected([]);
    setFixed(null);
    localSnapshots.current = null;
    setError('');
    onChange(null);
  }
  function choose(paths: string[]) {
    setSelected(paths);
    onChange(
      fixed && paths.length
        ? {
            name: repo.name,
            before: fixed.before,
            after: fixed.after,
            update:
              source === 'GITHUB'
                ? 'GitHub · 双固定提交'
                : '本地 · 双读取快照（范围变化不等于文件增删）',
            scope: paths,
            kind: repo.kind,
            targetFiles: paths.filter((p) => fixed.target.includes(p)).length,
            selection: {
              kind: source === 'GITHUB' ? 'GITHUB_CODE' : 'LOCAL_CODE',
              source_id: repo.id,
              source_version: repo.version,
              connection_id: source === 'GITHUB' ? connection : undefined,
              before_ref: fixed.before,
              after_ref: fixed.after,
              paths,
              update_mode: 'CODE_SNAPSHOT',
              ...(localSnapshots.current
                ? {
                    before_local: localSide(localSnapshots.current[0], paths),
                    after_local: localSide(localSnapshots.current[1], paths),
                  }
                : {}),
            },
          }
        : null,
    );
  }
  async function getHistory(append = false) {
    if (!repo.client_id || busy) return;
    const g = ++generation.current;
    setBusy(true);
    setError('');
    try {
      const rows = await readHistory(
        bindingKey(user.id, projectId, repo.client_id),
        append ? history.at(-1)?.sequence : undefined,
      );
      if (controller.current.signal.aborted || g !== generation.current) return;
      setHistory((old) => (append ? [...old, ...rows] : rows));
      setMoreHistory(rows.length === 20);
    } catch (e) {
      if (!controller.current.signal.aborted) setError(localError(e, onSessionEnd));
    } finally {
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  async function load() {
    const g = ++generation.current;
    setBusy(true);
    setError('');
    setSelected([]);
    setFixed(null);
    setFiles([]);
    onChange(null);
    try {
      let oldRef: string, newRef: string, oldFiles: string[], newFiles: string[];
      if (source === 'GITHUB') {
        const scopes = await Promise.all(
          [before, after].map((branch) => {
            const query = new URLSearchParams({
              repository_id: String(repo.id),
              connection_id: String(connection),
              branch,
            });
            return codeRequest(
              `/api/projects/${projectId}/code-analysis/github-scope?${query}`,
              parseCodeScope,
              { signal: controller.current.signal },
            );
          }),
        );
        if (
          scopes.some((x) => x.source_version !== repo.version || x.repository_kind !== repo.kind)
        )
          throw new Error('code_source_changed');
        oldRef = scopes[0].commit;
        newRef = scopes[1].commit;
        oldFiles = scopes[0].files.map((x) => x.path);
        newFiles = scopes[1].files.map((x) => x.path);
      } else {
        if (!repo.client_id) throw new Error('code_source_unavailable');
        const key = bindingKey(user.id, projectId, repo.client_id),
          snapshots = await Promise.all([before, after].map((x) => loadSnapshot(key, Number(x))));
        const old = snapshots[0],
          next = snapshots[1];
        if (!old || !next) throw new Error('local_history_missing');
        localSnapshots.current = [old, next];
        oldRef = `${snapshotName(old)} · #${old.sequence}`;
        newRef = `${snapshotName(next)} · #${next.sequence}`;
        oldFiles = Object.keys(old.files);
        newFiles = Object.keys(next.files);
      }
      if (controller.current.signal.aborted || g !== generation.current) return;
      if (oldRef === newRef) throw new Error('两侧解析到同一版本，请选择不同基准。');
      setFixed({ before: oldRef, after: newRef, target: newFiles });
      setFiles([...new Set([...oldFiles, ...newFiles])].sort());
    } catch (e) {
      if (!controller.current.signal.aborted && g === generation.current)
        setError(
          e instanceof Error && e.message.startsWith('两侧')
            ? e.message
            : source === 'LOCAL'
              ? localError(e, onSessionEnd)
              : codeError(e, onSessionEnd),
        );
    } finally {
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  return (
    <section className="code-source-card">
      <label className="check-label">
        <input
          type="checkbox"
          checked={enabled}
          disabled={busy}
          onChange={(e) => {
            setEnabled(e.target.checked);
            clear();
          }}
        />
        <strong>{repo.name}</strong>
        <span className="hint">
          {codeKinds[repo.kind]} · 已选{selected.length}个文件
        </span>
      </label>
      {enabled && (
        <>
          {source === 'GITHUB' ? (
            <FormSelect
              label="本人GitHub连接"
              value={String(connection)}
              options={options.connections.map((x) => ({ value: String(x.id), label: x.name }))}
              disabled={busy}
              onChange={(v) => {
                setConnection(Number(v));
                setBefore('');
                setAfter('');
                clear();
              }}
            />
          ) : (
            <div className="row mt">
              <button type="button" disabled={busy} onClick={() => void getHistory()}>
                读取已有快照记录
              </button>
              {moreHistory && (
                <button type="button" disabled={busy} onClick={() => void getHistory(true)}>
                  更多快照
                </button>
              )}
            </div>
          )}
          <div className="form-grid mt">
            {(['before', 'after'] as const).map((side) =>
              source === 'GITHUB' ? (
                <GitVersionPicker
                  key={`${side}:${connection}`}
                  label={side === 'before' ? '旧基准' : '新目标'}
                  projectId={projectId}
                  repositoryId={repo.id}
                  connectionId={connection}
                  defaultBranch={repo.default_branch || 'main'}
                  value={side === 'before' ? before : after}
                  disabled={busy}
                  onSessionEnd={onSessionEnd}
                  onChange={(v) => {
                    if (side === 'before') setBefore(v);
                    else setAfter(v);
                    clear();
                  }}
                />
              ) : (
                <FormSelect
                  key={side}
                  label={side === 'before' ? '旧基准' : '新目标'}
                  value={side === 'before' ? before : after}
                  options={[
                    { value: '', label: '请选择快照' },
                    ...history.map((x) => ({
                      value: String(x.sequence),
                      label: `${snapshotName(x)} · #${x.sequence}`,
                    })),
                  ]}
                  disabled={busy}
                  onChange={(v) => {
                    if (side === 'before') setBefore(v);
                    else setAfter(v);
                    clear();
                  }}
                />
              ),
            )}
          </div>
          <button
            type="button"
            disabled={busy || !before || !after || (source === 'GITHUB' && !connection)}
            onClick={() => void load()}
          >
            {busy ? '读取中…' : '读取两侧文件树'}
          </button>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          {fixed && (
            <>
              <p className="hint mono">
                旧：{fixed.before}
                <br />
                新：{fixed.after}
              </p>
              <CodeFileTree paths={files} selected={selected} onChange={choose} disabled={busy} />
              <p className="hint">
                仅选择文件范围，尚未计算代码差异或读取正文用于分析。未变文件可作为关联上下文补选。
              </p>
            </>
          )}
          {source === 'LOCAL' && (
            <p className="hint">
              仅使用当前账号本浏览器已有快照。不上传源码，不新建读取历史；缺基准时请先到项目设置读取。
            </p>
          )}
        </>
      )}
    </section>
  );
}
type Material = CodeOptions['materials'][number];
function materialName(material: Material, versionId?: number) {
  return (
    material.versions.find((v) => v.id === versionId)?.filename ||
    material.versions[0]?.filename ||
    material.name
  );
}
function versionOptions(material: Material | undefined) {
  return [
    { value: '', label: '请选择固定版本' },
    ...(material?.versions || []).map((x) => ({
      value: String(x.id),
      label: `${x.filename} · v${x.number}`,
    })),
  ];
}
type MaterialGroup = {
  key: string;
  comparison: 'VERSION' | 'SUPPLEMENT';
  beforeDoc: number;
  beforeVersion: number;
  afterDoc: number;
  afterVersion: number;
  update: string;
};
function localSide(snapshot: Snapshot, paths: string[]) {
  return {
    ref: `read-${snapshot.sequence}`,
    captured_at: snapshot.foundAt,
    scope: snapshot.scope,
    files: paths.flatMap((path) =>
      snapshot.files[path]
        ? [{ path, content: snapshot.files[path].content, sha256: snapshot.files[path].hash }]
        : [],
    ),
    skipped: Object.fromEntries(
      Object.entries(snapshot.skipped).filter(([p]) =>
        paths.some((path) => path === p || path.startsWith(p.replace(/\/$/, '') + '/')),
      ),
    ),
  };
}
export function ChangeAnalysisNew({
  projectId,
  user,
  options,
  onClose,
  onCreate,
  onSessionEnd,
}: {
  projectId: number;
  user: User;
  options: CodeOptions;
  onClose: () => void;
  onCreate: (record: PageChangeRecord) => void;
  onSessionEnd: () => void;
}) {
  const [title, setTitle] = useState(''),
    [mode, setMode] = useState<ChangeMode>('REQUIREMENT_CHANGE'),
    [source, setSource] = useState<'GITHUB' | 'LOCAL'>('GITHUB'),
    [targets, setTargets] = useState(['业务变化与功能影响']),
    [groups, setGroups] = useState<MaterialGroup[]>([]),
    [codePairs, setCodePairs] = useState<Record<number, ChangePair>>({}),
    [context, setContext] = useState<string[]>([]),
    [confirmed, setConfirmed] = useState(false),
    [focus, setFocus] = useState(''),
    [error, setError] = useState('');
  const [prototypePairs, setPrototypePairs] = useState<ChangePair[]>([]);
  const [contextPaths, setContextPaths] = useState<Record<number, string[]>>({});
  const [busy, setBusy] = useState(false),
    [caseIds, setCaseIds] = useState<number[]>([]),
    [caseVersions, setCaseVersions] = useState<Record<string, number>>({}),
    [historyItems, setHistoryItems] = useState<
      { module: 'REQUIREMENT_ANALYSIS' | 'CODE_REVIEW'; report_id: number; item_key: string }[]
    >([]),
    [contextMode, setContextMode] = useState<'GITHUB' | 'LOCAL'>('GITHUB'),
    [contextSources, setContextSources] = useState<Record<string, ReadySource>>({});
  const submitController = useRef(new AbortController()),
    requestId = useRef(crypto.randomUUID()),
    submitting = useRef(false);
  useEffect(() => {
    const c = new AbortController();
    submitController.current = c;
    return () => c.abort();
  }, []);
  const materials = options.materials
    .filter((x) => x.kind === 'FILE' && x.versions.length)
    .map((m) => ({ ...m, versions: [...m.versions].sort((a, b) => b.number - a.number) }));
  const contextMaterials = options.materials
    .filter((m) => ['FILE', 'DIRECTORY'].includes(m.kind) && m.versions.length)
    .map((m) => ({ ...m, versions: [...m.versions].sort((a, b) => b.number - a.number) }));
  const materialPairs: ChangePair[] = groups.map((g) => {
    const old = materials.find((x) => x.id === g.beforeDoc),
      next = materials.find((x) => x.id === g.afterDoc),
      a = old?.versions.find((x) => x.id === g.beforeVersion),
      b = next?.versions.find((x) => x.id === g.afterVersion);
    return {
      name: `${old ? materialName(old, g.beforeVersion) : '旧资料'} → ${next ? materialName(next, g.afterVersion) : '新资料'}`,
      before: a ? `${old?.id}:${a.id} · ${a.filename} @ v${a.number}` : '',
      after: b ? `${next?.id}:${b.id} · ${b.filename} @ v${b.number}` : '',
      update: g.update,
      scope: a && b ? [a.filename, b.filename] : [],
      selection: {
        kind: 'FILE',
        source_id: g.beforeDoc,
        after_document_id: g.afterDoc,
        before_version_id: g.beforeVersion,
        after_version_id: g.afterVersion,
        update_mode: g.update.includes('增量') ? 'INCREMENTAL_SUPPLEMENT' : 'FULL_REPLACEMENT',
      },
    };
  });
  const pairs =
      mode === 'REQUIREMENT_CHANGE'
        ? materialPairs
        : mode === 'PROTOTYPE_CHANGE'
          ? prototypePairs
          : Object.values(codePairs),
    problem = contextMaterials.some(
      (m) =>
        m.kind === 'DIRECTORY' &&
        context.some((x) => x.startsWith(`${m.id}:`)) &&
        !contextPaths[m.id]?.length,
    )
      ? '请为补充目录资料选择至少一个固定版本文件。'
      : mode === 'REQUIREMENT_CHANGE' &&
          groups.some(
            (g) => g.comparison === 'SUPPLEMENT' && g.beforeDoc && g.beforeDoc === g.afterDoc,
          )
        ? '两份文件配对需选择不同文件；同一资料请使用旧、新版本对比。'
        : changeScopeError(
            mode,
            pairs,
            targets,
            confirmed,
            context.length > 0,
            Object.values(contextSources).map((s) => ({
              kind: s.repositoryKind,
              targetFiles: s.selection.files.length,
            })),
          );
  function updateGroup(key: string, patch: Partial<MaterialGroup>) {
    setConfirmed(false);
    setGroups((rows) => rows.map((g) => (g.key === key ? { ...g, ...patch } : g)));
  }
  const repos: Repo[] =
    source === 'GITHUB'
      ? options.repositories.map((r) => ({ ...r, name: r.full_name }))
      : options.local_sources;
  const goalNames =
    mode === 'REQUIREMENT_CHANGE'
      ? ['业务变化与功能影响', '代码实现跟进', '用例维护与回归建议']
      : mode === 'PROTOTYPE_CHANGE'
        ? ['原型行为变化与功能影响', '代码实现跟进', '用例维护与回归建议']
        : ['代码Bug', '需求符合性', '前后端一致性'];
  const formId = useId();
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || problem) {
      setError(problem);
      return;
    }
    submitting.current = true;
    setBusy(true);
    setError('');
    try {
      const sources = [];
      for (const ready of Object.values(contextSources)) {
        if (ready.selection.kind === 'LOCAL') {
          if (!ready.tree) throw Error('code_source_unavailable');
          const result = await readSelection(
            ready.tree,
            ready.selection.files.map((f) => f.path),
            submitController.current.signal,
          );
          if (Object.keys(result.skipped).length) throw Error('code_text_required');
          sources.push({
            ...ready.selection,
            files: Object.entries(result.files).map(([path, file]) => ({
              path,
              content: file.content,
              sha256: file.hash,
            })),
          });
        } else sources.push(ready.selection);
      }
      const selectedTargets = targets.map((name) =>
        name === '原型行为变化与功能影响'
          ? 'BUSINESS_IMPACT'
          : Object.keys(changeTargets).find((key) => changeTargets[key] === name),
      );
      if (selectedTargets.some((t) => !t) || pairs.some((p) => !p.selection))
        throw Error('请选择完整固定范围。');
      const result = await changeDetail(`/api/projects/${projectId}/change-analysis`, projectId, {
        method: 'POST',
        signal: submitController.current.signal,
        body: JSON.stringify({
          request_id: requestId.current,
          ai_version: options.ai.version,
          ai_call_mode: options.ai.call_mode,
          ai_preference_version: options.ai.preference_version,
          title: title.trim(),
          mode,
          targets: selectedTargets,
          focus,
          pairs: pairs.map((p) => p.selection),
          confirmed,
          materials: context.map((value) => {
            const ids = value.split(' · ')[0].split(':').map(Number);
            return { document_id: ids[0], version_id: ids[1], paths: contextPaths[ids[0]] || [] };
          }),
          sources,
          case_ids: caseIds,
          case_versions: caseVersions,
          historical_items: historyItems,
        }),
      });
      if (!submitController.current.signal.aborted) onCreate(result);
    } catch (e) {
      if (!submitController.current.signal.aborted) setError(changeError(e, onSessionEnd));
    } finally {
      submitting.current = false;
      if (!submitController.current.signal.aborted) setBusy(false);
    }
  }
  return (
    <CaseDialog
      title="新建变更分析"
      busy={busy}
      onClose={onClose}
      wide
      className="code-analysis-dialog change-analysis-dialog"
      footer={
        <footer className="change-dialog-footer">
          <button type="button" disabled={busy} onClick={onClose}>
            取消
          </button>
          <button
            type="submit"
            form={formId}
            className="primary"
            disabled={busy || !!problem || !title.trim() || !!options.ai?.error_code}
          >
            {busy ? '提交中…' : '开始分析'}
          </button>
        </footer>
      }
    >
      <Form id={formId} onSubmit={(e) => void submit(e)}>
        <p className="notice">
          使用你的个人AI配置在后台分析；固定选定双侧内容和补充依据，离开页面后继续。结果在当前项目共享。
        </p>
        <label className="form-field">
          分析名称
          <input
            required
            maxLength={200}
            placeholder="例如：核销门店规则补充"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
        <section>
          <h3>变更方式</h3>
          <div className="row mt">
            {Object.entries(changeModes).map(([key, name]) => (
              <button
                type="button"
                key={key}
                className={mode === key ? 'primary' : 'ghost'}
                aria-pressed={mode === key}
                onClick={() => {
                  setMode(key as ChangeMode);
                  setTargets(
                    key === 'REQUIREMENT_CHANGE'
                      ? ['业务变化与功能影响']
                      : key === 'PROTOTYPE_CHANGE'
                        ? ['原型行为变化与功能影响']
                        : ['代码Bug'],
                  );
                  setConfirmed(false);
                  setCodePairs({});
                  setPrototypePairs([]);
                }}
              >
                {name}
              </button>
            ))}
          </div>
        </section>
        <fieldset className="change-analysis-targets">
          <legend>分析目标</legend>
          {goalNames.map((name) => (
            <label className="check-label" key={name}>
              <input
                type="checkbox"
                checked={targets.includes(name)}
                onChange={(e) =>
                  setTargets((old) =>
                    e.target.checked ? [...old, name] : old.filter((x) => x !== name),
                  )
                }
              />
              {name}
            </label>
          ))}
        </fieldset>
        {mode === 'REQUIREMENT_CHANGE' ? (
          <section>
            <div className="between">
              <h3>资料配对 · 固定版本</h3>
              <button
                type="button"
                className="small"
                onClick={() => {
                  setConfirmed(false);
                  setGroups((old) => [
                    ...old,
                    {
                      key: crypto.randomUUID(),
                      comparison: 'SUPPLEMENT',
                      beforeDoc: 0,
                      beforeVersion: 0,
                      afterDoc: 0,
                      afterVersion: 0,
                      update: '增量补充',
                    },
                  ]);
                }}
              >
                添加补充文件配对
              </button>
            </div>
            <p className="hint mt">
              勾选资料后，在同一项选择旧基准和新目标；默认上一版对最新版。只有一个版本时，旧基准留空，不伪造历史版本。
            </p>
            <div className="change-version-list mt">
              {materials
                .filter((m) => m.purpose === 'REQUIREMENT')
                .map((m) => {
                  const g = groups.find(
                    (row) => row.comparison === 'VERSION' && row.beforeDoc === m.id,
                  );
                  return (
                    <section className="change-version-row" key={m.id}>
                      <label className="check-label">
                        <input
                          type="checkbox"
                          checked={!!g}
                          onChange={(e) => {
                            setConfirmed(false);
                            setGroups((old) =>
                              e.target.checked
                                ? [
                                    ...old,
                                    {
                                      key: crypto.randomUUID(),
                                      comparison: 'VERSION',
                                      beforeDoc: m.id,
                                      beforeVersion: m.versions[1]?.id || 0,
                                      afterDoc: m.id,
                                      afterVersion: m.versions[0].id,
                                      update: '完整替换',
                                    },
                                  ]
                                : old.filter(
                                    (row) => row.comparison !== 'VERSION' || row.beforeDoc !== m.id,
                                  ),
                            );
                          }}
                        />
                        <span>{materialName(m)}</span>
                      </label>
                      {g && (
                        <div className="change-version-pair">
                          <div className="form-grid">
                            <FormSelect
                              label="旧基准"
                              value={String(g.beforeVersion || '')}
                              options={versionOptions(m)}
                              onChange={(v) => updateGroup(g.key, { beforeVersion: Number(v) })}
                            />
                            <FormSelect
                              label="新目标"
                              value={String(g.afterVersion || '')}
                              options={versionOptions(m)}
                              onChange={(v) => updateGroup(g.key, { afterVersion: Number(v) })}
                            />
                          </div>
                          <FormSelect
                            label="本组更新方式"
                            value={g.update}
                            options={['完整替换', '增量补充'].map((x) => ({ value: x, label: x }))}
                            onChange={(v) => updateGroup(g.key, { update: v })}
                          />
                          {m.versions.length < 2 && (
                            <p className="hint">尚无旧版本；请先登记旧资料，或使用两份文件配对。</p>
                          )}
                          {g.beforeVersion && g.beforeVersion === g.afterVersion ? (
                            <p className="form-error" role="alert">
                              旧基准与新目标不能是同一个版本。
                            </p>
                          ) : null}
                          {g.update === '增量补充' && (
                            <p className="hint">未提及的旧规则继续适用，不单列为变化项。</p>
                          )}
                        </div>
                      )}
                    </section>
                  );
                })}
            </div>
            {groups
              .filter((g) => g.comparison === 'SUPPLEMENT')
              .map((g, i) => (
                <section className="evidence change-supplement-pair" key={g.key}>
                  <div className="between">
                    <strong>两份文件配对 {i + 1}</strong>
                    <button
                      type="button"
                      className="ghost small"
                      onClick={() => {
                        setConfirmed(false);
                        setGroups((old) => old.filter((row) => row.key !== g.key));
                      }}
                    >
                      移除配对
                    </button>
                  </div>
                  <p className="hint">
                    旧基准文件＋新版补充文件，分别固定版本；补充未提及的旧规则继续适用。
                  </p>
                  <div className="form-grid mt">
                    {(['before', 'after'] as const).map((side) => (
                      <div className="stack" key={side}>
                        <strong>{side === 'before' ? '旧基准文件' : '新版补充文件'}</strong>
                        <div className="change-material-list">
                          {materials
                            .filter((m) => m.purpose === 'REQUIREMENT')
                            .map((m) => {
                              const checked =
                                g[side === 'before' ? 'beforeDoc' : 'afterDoc'] === m.id;
                              return (
                                <label className="check-label" key={m.id}>
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={(e) =>
                                      updateGroup(
                                        g.key,
                                        side === 'before'
                                          ? {
                                              beforeDoc: e.target.checked ? m.id : 0,
                                              beforeVersion: e.target.checked
                                                ? m.versions[0].id
                                                : 0,
                                            }
                                          : {
                                              afterDoc: e.target.checked ? m.id : 0,
                                              afterVersion: e.target.checked ? m.versions[0].id : 0,
                                            },
                                      )
                                    }
                                  />
                                  <span>{materialName(m)}</span>
                                </label>
                              );
                            })}
                        </div>
                        {!!g[side === 'before' ? 'beforeDoc' : 'afterDoc'] && (
                          <FormSelect
                            label={side === 'before' ? '旧基准版本' : '补充文件版本'}
                            value={String(
                              g[side === 'before' ? 'beforeVersion' : 'afterVersion'] || '',
                            )}
                            options={versionOptions(
                              materials.find(
                                (m) => m.id === g[side === 'before' ? 'beforeDoc' : 'afterDoc'],
                              ),
                            )}
                            onChange={(v) =>
                              updateGroup(
                                g.key,
                                side === 'before'
                                  ? { beforeVersion: Number(v) }
                                  : { afterVersion: Number(v) },
                              )
                            }
                          />
                        )}
                      </div>
                    ))}
                  </div>
                  {g.beforeDoc && g.beforeDoc === g.afterDoc ? (
                    <p className="form-error" role="alert">
                      请选择不同文件；同一资料使用旧、新版本对比。
                    </p>
                  ) : null}
                </section>
              ))}
            {!materials.length && (
              <p className="hint">暂无已有文件版本，请先登记需求或原型资料。</p>
            )}
            <p className="hint mt">
              需求按已有固定文件版本对比；GitHub和链接原型请选择“原型变更”。
            </p>
          </section>
        ) : mode === 'PROTOTYPE_CHANGE' ? (
          <ChangePrototypeSources
            projectId={projectId}
            onSessionEnd={onSessionEnd}
            onChange={(pairs) => {
              setPrototypePairs(pairs);
              setConfirmed(false);
            }}
          />
        ) : (
          <section>
            <h3>代码来源与新旧范围</h3>
            <FormSelect
              label="来源方式"
              value={source}
              options={[
                { value: 'GITHUB', label: 'GitHub 仓库代码' },
                { value: 'LOCAL', label: '本地双快照' },
              ]}
              onChange={(v) => {
                setSource(v === 'LOCAL' ? 'LOCAL' : 'GITHUB');
                setCodePairs({});
                setConfirmed(false);
              }}
            />
            {repos
              .filter((r) => r.kind !== 'PROTOTYPE')
              .map((repo) => (
                <CodeComparison
                  key={`${source}:${repo.id}`}
                  repo={repo}
                  source={source}
                  options={options}
                  projectId={projectId}
                  user={user}
                  onSessionEnd={onSessionEnd}
                  onChange={(pair) => {
                    setConfirmed(false);
                    setCodePairs((old) => {
                      const next = { ...old };
                      if (pair) next[repo.id] = pair;
                      else delete next[repo.id];
                      return next;
                    });
                  }}
                />
              ))}
            {!repos.length && (
              <p className="hint">暂无可用来源，请先到项目设置关联仓库或本地目录。</p>
            )}
          </section>
        )}
        <section>
          <h3>补充依据与固定引用</h3>
          <div className="stack mt">
            <details className="evidence">
              <summary>指定当前代码快照</summary>
              <FormSelect
                label="代码来源方式"
                value={contextMode}
                disabled={busy}
                options={[
                  { value: 'GITHUB', label: 'GitHub' },
                  { value: 'LOCAL', label: '本地目录' },
                ]}
                onChange={(v) => {
                  setContextMode(v as 'GITHUB' | 'LOCAL');
                  setContextSources({});
                }}
              />
              {(contextMode === 'GITHUB'
                ? options.repositories.map((r) => ({ ...r, name: r.full_name }))
                : options.local_sources
              ).map((repo) => (
                <SourcePicker
                  key={`${contextMode}:${repo.id}`}
                  repo={repo}
                  mode={contextMode}
                  base={`/api/projects/${projectId}/code-analysis`}
                  projectId={projectId}
                  user={user}
                  connections={options.connections}
                  disabled={busy}
                  onSessionEnd={onSessionEnd}
                  onChange={(value) =>
                    setContextSources((old) => {
                      const next = { ...old };
                      if (value) next[String(repo.id)] = value;
                      else delete next[String(repo.id)];
                      return next;
                    })
                  }
                />
              ))}
            </details>
            <div className="change-material-versions">
              {contextMaterials.map((m) => {
                const picked = context.find((x) => x.startsWith(`${m.id}:`));
                const version = m.versions.find((v) => picked?.startsWith(`${m.id}:${v.id} · `));
                const reference = (v: Material['versions'][number]) =>
                  `${m.id}:${v.id} · ${v.filename} @ v${v.number}`;
                return (
                  <div className="change-material-row" key={m.id}>
                    <label className="check-label">
                      <input
                        type="checkbox"
                        checked={!!picked}
                        onChange={(e) => {
                          setContextPaths((old) => ({ ...old, [m.id]: [] }));
                          setConfirmed(false);
                          setContext((old) => [
                            ...old.filter((x) => !x.startsWith(`${m.id}:`)),
                            ...(e.target.checked ? [reference(m.versions[0])] : []),
                          ]);
                        }}
                      />
                      <span>{materialName(m, version?.id)}</span>
                    </label>
                    {picked && (
                      <FormSelect
                        label="固定版本"
                        value={picked}
                        options={m.versions.map((v) => ({
                          value: reference(v),
                          label: `${v.filename} @ v${v.number}`,
                        }))}
                        onChange={(v) => {
                          setContext((old) => [...old.filter((x) => !x.startsWith(`${m.id}:`)), v]);
                          setContextPaths((old) => ({ ...old, [m.id]: [] }));
                          setConfirmed(false);
                        }}
                      />
                    )}
                    {picked && m.kind === 'DIRECTORY' && version && (
                      <PrototypeDirectoryFiles
                        key={`${m.id}:${version.id}`}
                        projectId={projectId}
                        documentId={m.id}
                        versionId={version.id}
                        value={contextPaths[m.id] || []}
                        onChange={(paths) => {
                          setContextPaths((old) => ({ ...old, [m.id]: paths }));
                          setConfirmed(false);
                        }}
                        onSessionEnd={onSessionEnd}
                        disabled={busy}
                      />
                    )}
                  </div>
                );
              })}
              {!contextMaterials.length && <p className="hint">暂无可选需求／原型文件。</p>}
            </div>
            <ChangeContext
              projectId={projectId}
              onCases={(ids, versions) => {
                setCaseIds(ids);
                setCaseVersions(versions);
              }}
              onHistory={setHistoryItems}
              onSessionEnd={onSessionEnd}
            />
          </div>
        </section>
        <label className="check-label">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          已核对新旧范围对应关系
        </label>
        <div className="evidence" role="status">
          {problem || '范围选择条件满足，开始后固定正文并进行后台分析。'}
          {targets.includes('代码实现跟进') && (
            <p className="hint">只核对指定当前实现；缺实现依据时该目标标明不足，其他目标继续。</p>
          )}
          {targets.includes('用例维护与回归建议') && (
            <p className="hint">未带入用例不能判断用例无影响。</p>
          )}
        </div>
        <label className="form-field">
          补充关注点
          <textarea
            rows={3}
            maxLength={4000}
            placeholder="例如：重点核对门店权限和重复提交"
            value={focus}
            onChange={(e) => setFocus(e.target.value)}
          />
        </label>
        <section className="evidence">
          <strong>本人AI配置</strong>
          <p className="hint">
            完整固定所选双侧正文、补充上下文、用例、历史与附件，一次请求交给你的AI分析。
            平台不按语义筛减内容，不自动分批或重试；实际容量由本人模型服务判断。
          </p>
          <p className="hint">
            {options.ai?.error_code
              ? codeError(new Error(options.ai.error_code), onSessionEnd)
              : `${callModeName(options.ai?.call_mode)} · ${options.ai?.name || '本人AI'} · ${options.ai?.model || ''}；仅使用你的配置，不回退平台密钥。`}
          </p>
        </section>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </Form>
    </CaseDialog>
  );
}
