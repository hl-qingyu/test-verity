import { callModeName } from './aiConfiguration';
import { PrototypeDirectoryFiles } from './PrototypeDirectoryFiles';
import { CodeFileTree } from './CodeFileTree';
export { CodeFileTree } from './CodeFileTree';
import { useEffect, useRef, useState } from 'react';
import type { User } from './Auth';
import { CaseDialog } from './CaseDialog';
import { Form } from './Form';
import { FormSelect } from './FormSelect';
import { PrototypeLinkPages } from './PrototypeLinkPages';
import {
  authorizeDirectory,
  chooseDirectory,
  readSelection,
  scanDirectory,
} from './localCodeFiles';
import type { DirectoryTree } from './localCodeFiles';
import { bindDirectory, loadBinding } from './localCodeStore';
import { bindingKey, localError } from './localCodeApi';
import {
  codeError,
  codeKinds,
  codePreflight,
  codeRequest,
  codeTargets,
  parseCodeDetail,
  parseCodePreview,
  parseCodeScope,
} from './codeAnalysisApi';
import type {
  CodeDetail,
  CodeKind,
  CodeOptions,
  CodeTarget,
  MaterialSelection,
  SourceSelection,
} from './codeAnalysisApi';

export type ReadySource = {
  selection: SourceSelection;
  name: string;
  repositoryKind: CodeKind;
  tree?: DirectoryTree;
};
type Repo = {
  id: number;
  kind: CodeKind;
  version: number;
  name: string;
  directory_name?: string;
  client_id?: string;
  default_branch?: string;
};

export function SourcePicker({
  repo,
  mode,
  base,
  projectId,
  user,
  connections,
  onChange,
  disabled,
  onSessionEnd,
}: {
  repo: Repo;
  mode: 'GITHUB' | 'LOCAL';
  base: string;
  projectId: number;
  user: User;
  connections: CodeOptions['connections'];
  onChange: (value: ReadySource | null) => void;
  disabled: boolean;
  onSessionEnd: () => void;
}) {
  const [enabled, setEnabled] = useState(false),
    [connection, setConnection] = useState(connections[0]?.id || 0),
    [ref, setRef] = useState(repo.default_branch || 'main'),
    [commit, setCommit] = useState(''),
    [paths, setPaths] = useState<string[]>([]),
    [selected, setSelected] = useState<string[]>([]),
    [preview, setPreview] = useState<{ path: string; content: string } | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const tree = useRef<DirectoryTree | undefined>(undefined),
    controller = useRef(new AbortController()),
    generation = useRef(0);
  useEffect(() => {
    const current = new AbortController();
    controller.current = current;
    return () => current.abort();
  }, []);
  function emit(next: string[], nextCommit = commit, nextTree = tree.current) {
    setSelected(next);
    onChange(
      next.length
        ? {
            name: repo.name,
            repositoryKind: repo.kind,
            tree: nextTree,
            selection: {
              kind: mode,
              source_id: repo.id,
              source_version: repo.version,
              commit: nextCommit,
              ...(mode === 'GITHUB' ? { connection_id: connection } : {}),
              files: next.map((path) => ({ path })),
            },
          }
        : null,
    );
  }
  function clear() {
    generation.current++;
    setPaths([]);
    setCommit('');
    setPreview(null);
    tree.current = undefined;
    emit([]);
  }
  async function load() {
    if (busy || disabled) return;
    const current = ++generation.current;
    setBusy(true);
    setError('');
    emit([]);
    try {
      if (mode === 'GITHUB') {
        const query = new URLSearchParams({
          repository_id: String(repo.id),
          connection_id: String(connection),
          branch: ref,
        });
        const scope = await codeRequest(`${base}/github-scope?${query}`, parseCodeScope, {
          signal: controller.current.signal,
        });
        if (controller.current.signal.aborted || current !== generation.current) return;
        if (scope.source_version !== repo.version || scope.repository_kind !== repo.kind)
          throw new Error('code_source_changed');
        setPaths(scope.files.map((file) => file.path));
        setCommit(scope.commit);
      } else {
        if (!repo.client_id) throw new Error('code_source_unavailable');
        const key = bindingKey(user.id, projectId, repo.client_id),
          binding = await loadBinding(key);
        const handle = binding
          ? await authorizeDirectory(binding.handle).then(() => binding.handle)
          : await chooseDirectory();
        if (handle.name !== repo.directory_name) throw new Error('directory_mismatch');
        await bindDirectory(key, handle, binding?.scope || []);
        const loaded = await scanDirectory(handle, controller.current.signal);
        if (controller.current.signal.aborted || current !== generation.current) return;
        tree.current = loaded;
        setPaths(loaded.files.map((file) => file.path));
        setCommit('本次提交时固定内容快照');
      }
    } catch (reason) {
      if (!controller.current.signal.aborted)
        setError(
          mode === 'LOCAL' ? localError(reason, onSessionEnd) : codeError(reason, onSessionEnd),
        );
    } finally {
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  async function showPreview(path: string) {
    if (busy || disabled) return;
    const current = generation.current;
    setBusy(true);
    setError('');
    try {
      let value: { path: string; content: string };
      if (mode === 'GITHUB') {
        const query = new URLSearchParams({
          repository_id: String(repo.id),
          connection_id: String(connection),
          commit,
          path,
        });
        value = await codeRequest(`${base}/github-file?${query}`, parseCodePreview, {
          signal: controller.current.signal,
        });
      } else {
        if (!tree.current) throw new Error('code_source_unavailable');
        const read = await readSelection(tree.current, [path], controller.current.signal);
        if (!read.files[path]) throw new Error('code_text_required');
        value = { path, content: read.files[path].content };
      }
      if (!controller.current.signal.aborted && current === generation.current) setPreview(value);
    } catch (reason) {
      if (!controller.current.signal.aborted) setError(codeError(reason, onSessionEnd));
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
          disabled={disabled || busy}
          onChange={(event) => {
            setEnabled(event.target.checked);
            if (!event.target.checked) clear();
          }}
        />
        <strong>{repo.name}</strong>
        <span className="hint">
          {codeKinds[repo.kind]} · {mode === 'LOCAL' ? '本地' : 'GitHub'} · 已选{selected.length}
          个文件
        </span>
      </label>
      {enabled && (
        <>
          <div className="form-grid mt">
            {mode === 'GITHUB' ? (
              <>
                <FormSelect
                  label="本人GitHub连接"
                  value={String(connection)}
                  options={connections.map((item) => ({
                    value: String(item.id),
                    label: item.name,
                  }))}
                  disabled={disabled || busy}
                  onChange={(value) => {
                    setConnection(Number(value));
                    clear();
                  }}
                />
                <label className="form-field">
                  分支或完整提交SHA
                  <input
                    value={ref}
                    disabled={disabled || busy}
                    onChange={(event) => {
                      setRef(event.target.value);
                      clear();
                    }}
                  />
                </label>
              </>
            ) : (
              <p className="hint">
                授权目录：{repo.directory_name}。仅所选文件在提交时读取并发送。
              </p>
            )}
          </div>
          <button
            type="button"
            className="mt"
            disabled={disabled || busy || (mode === 'GITHUB' && !connection)}
            onClick={() => void load()}
          >
            {busy ? '读取中…' : mode === 'LOCAL' ? '读取本地代码树' : '读取代码树'}
          </button>
          {commit && <p className="hint mono">固定版本：{commit}</p>}
          {!!paths.length && (
            <div className="code-selection-layout">
              <CodeFileTree
                paths={paths}
                selected={selected}
                disabled={disabled || busy}
                onChange={emit}
                onPreview={(path) => void showPreview(path)}
              />
              <section className="code-source-preview">
                <h4>代码预览 · 只读</h4>
                {preview ? (
                  <>
                    <p className="hint mono">{preview.path}</p>
                    <pre className="code">{preview.content}</pre>
                  </>
                ) : (
                  <p className="hint">点击文件名预览，勾选文件用于分析。</p>
                )}
              </section>
            </div>
          )}
          {!busy && commit && !paths.length && <p className="hint">没有可分析的文本文件。</p>}
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
        </>
      )}
    </section>
  );
}

export function NewCodeAnalysis({
  projectId,
  user,
  options,
  onClose,
  onCreated,
  onSessionEnd,
}: {
  projectId: number;
  user: User;
  options: CodeOptions;
  onClose: () => void;
  onCreated: (record: CodeDetail) => void;
  onSessionEnd: () => void;
}) {
  const [title, setTitle] = useState(''),
    [focus, setFocus] = useState(''),
    [mode, setMode] = useState<'GITHUB' | 'LOCAL'>('GITHUB'),
    [targets, setTargets] = useState<CodeTarget[]>([
      'BUG',
      'REQUIREMENT_DEVIATION',
      'FRONTEND_BACKEND_MISMATCH',
    ]),
    [selectedSources, setSelectedSources] = useState<Record<string, ReadySource>>({}),
    [materials, setMaterials] = useState<MaterialSelection[]>([]),
    [tab, setTab] = useState('REQUIREMENT'),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const pending = useRef(false),
    controller = useRef(new AbortController()),
    requestId = useRef(crypto.randomUUID());
  const base = `/api/projects/${projectId}/code-analysis`;
  useEffect(() => {
    const current = new AbortController();
    controller.current = current;
    return () => current.abort();
  }, []);
  const repositories: Repo[] =
    mode === 'GITHUB'
      ? options.repositories.map((repo) => ({ ...repo, name: repo.full_name }))
      : options.local_sources;
  const chosen = Object.values(selectedSources),
    readyMaterials = materials.filter(
      (material) =>
        (material.version_id !== null &&
          (options.materials.find((m) => m.id === material.document_id)?.kind !== 'DIRECTORY' ||
            material.paths.length > 0)) ||
        (material.paths.length > 0 && (material.commit !== '' || material.snapshot !== '')),
    );
  const preflight = codePreflight(
    targets,
    chosen.map((source) => ({ kind: source.repositoryKind, count: source.selection.files.length })),
    readyMaterials.length,
  );
  const setMaterial = (id: number, patch: Partial<MaterialSelection>) =>
    setMaterials((old) =>
      old.map((item) => (item.document_id === id ? { ...item, ...patch } : item)),
    );
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    if (preflight.blocking) {
      setError(preflight.blocking);
      return;
    }
    if (materials.some((m) => !readyMaterials.includes(m))) {
      setError('请为已选原型链接或GitHub资料选择具体页面／文件，或取消该资料。');
      return;
    }
    pending.current = true;
    setBusy(true);
    setError('');
    try {
      const sources: SourceSelection[] = [];
      for (const item of chosen) {
        if (item.selection.kind === 'LOCAL') {
          if (!item.tree) throw new Error('code_source_unavailable');
          const result = await readSelection(
            item.tree,
            item.selection.files.map((file) => file.path),
            controller.current.signal,
          );
          if (Object.keys(result.skipped).length) throw new Error('code_text_required');
          const files = [];
          for (const [path, file] of Object.entries(result.files)) {
            const bytes = new TextEncoder().encode(file.content),
              hash = await crypto.subtle.digest('SHA-256', bytes);
            files.push({
              path,
              content: file.content,
              sha256: Array.from(new Uint8Array(hash), (value) =>
                value.toString(16).padStart(2, '0'),
              ).join(''),
            });
          }
          sources.push({ ...item.selection, commit: '', files });
        } else sources.push(item.selection);
      }
      const body = JSON.stringify({
        request_id: requestId.current,
        ai_version: options.ai.version,
        ai_call_mode: options.ai.call_mode,
        ai_preference_version: options.ai.preference_version,
        title: title.trim(),
        focus,
        targets,
        sources,
        materials,
      });
      const result = await codeRequest(base, parseCodeDetail, {
        method: 'POST',
        signal: controller.current.signal,
        body,
      });
      if (!controller.current.signal.aborted) onCreated(result);
    } catch (reason) {
      if (!controller.current.signal.aborted) setError(codeError(reason, onSessionEnd));
    } finally {
      pending.current = false;
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  return (
    <CaseDialog
      title="新建代码分析"
      busy={busy}
      onClose={onClose}
      wide
      className="code-analysis-dialog requirement-ui"
    >
      <Form onSubmit={(event) => void submit(event)}>
        <label className="form-field">
          分析名称
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            required
            maxLength={200}
            disabled={busy}
          />
        </label>
        <fieldset className="code-analysis-targets">
          <legend>检查目标</legend>
          {(Object.entries(codeTargets) as [CodeTarget, string][]).map(([key, name]) => (
            <label className={`check-label ${targets.includes(key) ? 'selected' : ''}`} key={key}>
              <input
                type="checkbox"
                checked={targets.includes(key)}
                disabled={busy}
                onChange={() =>
                  setTargets((old) =>
                    old.includes(key) ? old.filter((t) => t !== key) : [...old, key],
                  )
                }
              />
              {name}
            </label>
          ))}
        </fieldset>
        <section>
          <h3>代码来源与文件范围</h3>
          <FormSelect
            label="代码来源方式"
            className="code-source-mode"
            value={mode}
            options={[
              { value: 'GITHUB', label: 'GitHub 仓库代码' },
              { value: 'LOCAL', label: '本地代码工作区' },
            ]}
            disabled={busy}
            onChange={(value) => {
              setMode(value === 'LOCAL' ? 'LOCAL' : 'GITHUB');
              setSelectedSources({});
            }}
          />
          <p className="hint">可选择多个来源；切换来源方式会清空代码选择。</p>
          {repositories
            .filter((repo) => repo.kind !== 'PROTOTYPE')
            .map((repo) => (
              <SourcePicker
                key={`${mode}:${repo.id}`}
                repo={repo}
                mode={mode}
                projectId={projectId}
                user={user}
                base={base}
                connections={options.connections}
                disabled={busy}
                onSessionEnd={onSessionEnd}
                onChange={(value) =>
                  setSelectedSources((old) => {
                    const next = { ...old };
                    if (value) next[String(repo.id)] = value;
                    else delete next[String(repo.id)];
                    return next;
                  })
                }
              />
            ))}
          {!repositories.filter((repo) => repo.kind !== 'PROTOTYPE').length && (
            <p className="hint">暂无可用来源，请先在项目设置关联仓库或本地目录。</p>
          )}
        </section>
        <section className="code-material-picker">
          <h3>需求与原型依据</h3>
          <p className="hint">
            {targets.includes('REQUIREMENT_DEVIATION')
              ? '需求符合性需要至少一份固定版本依据；原型链接需先读取并选择页面。'
              : '可选补充依据，不会自动开启未勾选目标。'}
          </p>
          <div className="tabs">
            {[
              ['REQUIREMENT', '需求资料'],
              ['PROTOTYPE', '原型资料'],
            ].map(([key, name]) => (
              <button
                type="button"
                key={key}
                className={tab === key ? 'selected' : ''}
                onClick={() => setTab(key)}
              >
                {name}
              </button>
            ))}
          </div>
          {options.materials
            .filter((m) => m.purpose === tab)
            .map((material) => {
              const picked = materials.find((m) => m.document_id === material.id),
                displayName =
                  material.kind === 'FILE'
                    ? material.versions.find(
                        (version) =>
                          version.id === (picked?.version_id ?? material.versions[0]?.id),
                      )?.filename || material.name
                    : material.name,
                available = ['FILE', 'DIRECTORY'].includes(material.kind)
                  ? material.versions.length > 0
                  : material.kind === 'LINK' ||
                    (material.kind === 'GITHUB' && !!material.commit && material.files.length > 0);
              return (
                <div className="evidence" key={material.id}>
                  <label className="check-label">
                    <input
                      type="checkbox"
                      disabled={busy || !available}
                      checked={!!picked}
                      onChange={(event) =>
                        setMaterials((old) =>
                          event.target.checked
                            ? [
                                ...old,
                                {
                                  document_id: material.id,
                                  version_id: material.versions[0]?.id || null,
                                  commit: material.commit,
                                  paths: [],
                                  snapshot: '',
                                  url: material.url,
                                },
                              ]
                            : old.filter((m) => m.document_id !== material.id),
                        )
                      }
                    />
                    {displayName}
                    <span className="hint">
                      {material.kind === 'LINK'
                        ? '读取页面后选择范围'
                        : material.kind === 'GITHUB'
                          ? 'GitHub固定资料'
                          : '固定文件版本'}
                    </span>
                  </label>
                  {picked && ['FILE', 'DIRECTORY'].includes(material.kind) && (
                    <FormSelect
                      label="资料版本"
                      value={String(picked.version_id || '')}
                      disabled={busy}
                      options={material.versions.map((v) => ({
                        value: String(v.id),
                        label: `v${v.number} · ${v.filename}`,
                      }))}
                      onChange={(value) =>
                        setMaterial(material.id, {
                          version_id: Number(value),
                          ...(material.kind === 'DIRECTORY' ? { paths: [] } : {}),
                        })
                      }
                    />
                  )}
                  {picked && material.kind === 'DIRECTORY' && picked.version_id && (
                    <PrototypeDirectoryFiles
                      key={`${material.id}:${picked.version_id}`}
                      projectId={projectId}
                      documentId={material.id}
                      versionId={picked.version_id}
                      value={picked.paths}
                      onChange={(paths) => setMaterial(material.id, { paths })}
                      onSessionEnd={onSessionEnd}
                      disabled={busy}
                    />
                  )}
                  {picked && material.kind === 'GITHUB' && (
                    <>
                      <p className="hint mono">{material.commit}</p>
                      <CodeFileTree
                        paths={material.files.map((f) => f.path)}
                        selected={picked.paths}
                        disabled={busy}
                        onChange={(paths) => setMaterial(material.id, { paths })}
                      />
                    </>
                  )}
                  {picked && material.kind === 'LINK' && (
                    <PrototypeLinkPages
                      projectId={projectId}
                      documentId={material.id}
                      value={{ paths: picked.paths, snapshot: picked.snapshot }}
                      onChange={(value) => setMaterial(material.id, value)}
                      onSessionEnd={onSessionEnd}
                      disabled={busy}
                    />
                  )}
                </div>
              );
            })}
          {!options.materials.some((m) => m.purpose === tab) && <p className="hint">暂无资料。</p>}
        </section>
        <section className="evidence">
          <h3>本次检查范围确认</h3>
          {preflight.goals.map((goal) => (
            <div className="code-goal-row" key={goal.target}>
              <strong>{codeTargets[goal.target]}</strong>
              <span className={`badge ${goal.ready ? 'green' : 'orange'}`}>
                {goal.ready ? '输入条件已满足' : '依据不足'}
              </span>
              <p className="hint">{goal.reason}</p>
            </div>
          ))}
          <p className="hint">
            实际发送：{chosen.length}个代码来源、
            {chosen.reduce((sum, s) => sum + s.selection.files.length, 0)}个文件、{materials.length}
            份资料。切换目标保留选择。
          </p>
          {preflight.blocking && (
            <p className="form-error" role="alert">
              {preflight.blocking}
            </p>
          )}
        </section>
        <label className="form-field">
          补充关注点
          <textarea
            value={focus}
            onChange={(event) => setFocus(event.target.value)}
            maxLength={10000}
            disabled={busy}
            placeholder="例如：重点检查重复提交、门店归属或状态字段"
          />
        </label>
        <section className="evidence">
          <strong>执行配置</strong>
          <p className="hint">
            {callModeName(options.ai.call_mode)} · {options.ai.name} · {options.ai.model}
          </p>
          <p className="hint">
            所选代码和资料将发送至你的AI服务，并在项目内共享。任务可在后台继续。
          </p>
          {options.ai.error_code && <p className="form-error">请先在平台设置配置自己的AI服务。</p>}
        </section>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <footer className="prototype-editor-footer">
          <button type="button" disabled={busy} onClick={onClose}>
            取消
          </button>
          <button
            className="primary"
            disabled={busy || !!preflight.blocking || !!options.ai.error_code}
          >
            {busy ? '正在提交…' : '开始分析'}
          </button>
        </footer>
      </Form>
    </CaseDialog>
  );
}
