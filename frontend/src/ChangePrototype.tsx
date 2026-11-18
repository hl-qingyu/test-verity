import { useEffect, useRef, useState } from 'react';
import { apiRequest } from './api/http';
import { FormSelect } from './FormSelect';
import { CodeFileTree } from './CodeAnalysisNew';
import { PrototypeLinkPages } from './PrototypeLinkPages';
import type { LinkSelection } from './PrototypeLinkPages';
import {
  parsePrototypeLibrary,
  parsePrototypeOptions,
  parsePrototypeScope,
  prototypeError,
} from './prototypeApi';
import type { PrototypeConnection, PrototypeSource } from './prototypeApi';
import { riskDetailRequest, riskListing } from './riskApi';
import type { RiskDetail, ReportItem } from './riskApi';
import type { ChangePair } from './changeAnalysisPage';
import { GitVersionPicker } from './GitVersionPicker';
import { directoryCatalog } from './prototypeDirectory';
import { parseVersion } from './documentApi';
import type { DocumentVersion } from './documentApi';

function DirectoryPrototypePair({
  source,
  projectId,
  onChange,
  onSessionEnd,
}: {
  source: PrototypeSource;
  projectId: number;
  onChange: (pair: ChangePair) => void;
  onSessionEnd: () => void;
}) {
  const [versions, setVersions] = useState<DocumentVersion[]>([]),
    [before, setBefore] = useState(''),
    [after, setAfter] = useState(''),
    [paths, setPaths] = useState<string[]>([]),
    [chosen, setChosen] = useState<string[]>([]),
    [error, setError] = useState(''),
    [loading, setLoading] = useState(false);
  useEffect(() => {
    const c = new AbortController();
    apiRequest<unknown>(`/api/projects/${projectId}/documents/${source.id}/versions`, {
      signal: c.signal,
    })
      .then((value) => {
        if (!Array.isArray(value)) throw Error('prototype_response_invalid');
        const items = value.map(parseVersion);
        if (items.some((v) => v.document_id !== source.id || v.extension !== 'directory'))
          throw Error('prototype_response_invalid');
        if (!c.signal.aborted) setVersions(items);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(prototypeError(e, onSessionEnd));
      });
    return () => c.abort();
  }, [projectId, source.id, onSessionEnd]);
  useEffect(() => {
    if (!before || !after) {
      setLoading(false);
      return;
    }
    const c = new AbortController();
    setLoading(true);
    setError('');
    Promise.all([
      directoryCatalog(projectId, source.id, Number(before), c.signal),
      directoryCatalog(projectId, source.id, Number(after), c.signal),
    ])
      .then(([a, b]) => {
        if (!c.signal.aborted) setPaths([...new Set([...a, ...b].map((f) => f.path))].sort());
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(prototypeError(e, onSessionEnd));
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [before, after, projectId, source.id, onSessionEnd]);
  function emit(selected: string[], a = before, b = after) {
    onChange({
      name: source.name,
      before: a ? `version-${a}` : '',
      after: b ? `version-${b}` : '',
      scope: selected,
      update: '本地目录 · 完整版本比较',
      selection: {
        kind: 'DIRECTORY_PROTOTYPE',
        source_id: source.id,
        before_version_id: Number(a) || undefined,
        after_version_id: Number(b) || undefined,
        paths: selected,
        update_mode: 'FULL_REPLACEMENT',
      },
    });
  }
  return (
    <section className="prototype-directory-files">
      <div className="form-grid">
        {(['before', 'after'] as const).map((side) => (
          <FormSelect
            key={side}
            label={side === 'before' ? '旧基准版本' : '新目标版本'}
            value={side === 'before' ? before : after}
            options={[
              { value: '', label: '请选择固定目录版本' },
              ...versions.map((v) => ({
                value: String(v.id),
                label: `v${v.number} · ${v.filename}`,
              })),
            ]}
            onChange={(v) => {
              setPaths([]);
              setChosen([]);
              if (side === 'before') {
                setBefore(v);
                emit([], v, after);
              } else {
                setAfter(v);
                emit([], before, v);
              }
            }}
          />
        ))}
      </div>
      {before && before === after && (
        <p className="form-error" role="alert">
          旧、新目录版本须不同。
        </p>
      )}
      {loading && <p className="hint">正在读取双侧完整文件清单…</p>}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {!!paths.length && (
        <CodeFileTree
          paths={paths}
          selected={chosen}
          onChange={(v) => {
            setChosen(v);
            emit(v);
          }}
        />
      )}
      <p className="hint">仅发送所选文件，依赖需另行勾选。</p>
    </section>
  );
}

export function linkBaseline(report: RiskDetail, source: PrototypeSource) {
  const binding = report.bindings.find(
    (b) =>
      b.document_id === source.id &&
      b.kind === 'LINK' &&
      b.purpose === 'PROTOTYPE' &&
      !b.deleted &&
      b.url === source.url,
  );
  const material = report.input.materials.find(
    (m) => m.source_id === binding?.source_id && m.origin === 'PROTOTYPE' && m.kind === 'LINK',
  );
  if (
    !binding ||
    !material?.snapshot_ref ||
    ['URL', 'NOT_LOADED'].includes(material.snapshot_ref.toUpperCase()) ||
    /^https?:\/\//.test(material.snapshot_ref) ||
    !['READABLE', 'PARTIAL'].includes(material.read_state) ||
    !material.segments.some((s) => s.text.trim() && s.text.trim() !== source.url)
  )
    throw new Error('所选报告没有该链接实际保存的旧页面内容，不能作为旧基准。');
  return material;
}
function GithubPrototypePair({
  source,
  connections,
  projectId,
  onChange,
  onSessionEnd,
}: {
  source: PrototypeSource;
  connections: PrototypeConnection[];
  projectId: number;
  onChange: (pair: ChangePair) => void;
  onSessionEnd: () => void;
}) {
  const [connection, setConnection] = useState(connections[0]?.id || 0),
    [before, setBefore] = useState(''),
    [after, setAfter] = useState(''),
    [fixed, setFixed] = useState<{ before: string; after: string } | null>(null),
    [paths, setPaths] = useState<string[]>([]),
    [chosen, setChosen] = useState<string[]>([]),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  const controller = useRef(new AbortController());
  useEffect(() => {
    const c = new AbortController();
    controller.current = c;
    return () => c.abort();
  }, []);
  function emit(selected: string[], value = fixed) {
    onChange({
      name: source.name,
      before: value?.before || '',
      after: value?.after || '',
      update: 'GitHub原型 · 固定提交文件范围',
      scope: selected,
      selection: {
        kind: 'GITHUB_PROTOTYPE',
        source_id: source.id,
        connection_id: connection,
        before_ref: value?.before || '',
        after_ref: value?.after || '',
        paths: selected,
        update_mode: 'FULL_REPLACEMENT',
      },
    });
  }
  function clear() {
    setFixed(null);
    setPaths([]);
    setChosen([]);
    emit([], null);
  }
  async function read() {
    setBusy(true);
    setError('');
    clear();
    try {
      const results = await Promise.all(
        [before, after].map((branch) =>
          apiRequest<unknown>(`/api/projects/${projectId}/prototypes/scope`, {
            method: 'POST',
            signal: controller.current.signal,
            body: JSON.stringify({
              connection_id: connection,
              repository_id: source.repository_id,
              branch,
              path: source.path || '',
              comparison: true,
            }),
          }).then(parsePrototypeScope),
        ),
      );
      if (controller.current.signal.aborted) return;
      if (results[0].commit === results[1].commit)
        throw new Error('两側解析到相同提交，请更换比较版本。');
      if (results.some((s) => s.full_name !== source.repository_name))
        throw new Error('原型仓库与登记来源不一致。');
      setFixed({ before: results[0].commit, after: results[1].commit });
      setPaths([...new Set(results.flatMap((s) => s.files.map((f) => f.path)))].sort());
    } catch (e) {
      if (!controller.current.signal.aborted)
        setError(
          e instanceof Error && /相同提交|不一致/.test(e.message)
            ? e.message
            : prototypeError(e, onSessionEnd),
        );
    } finally {
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  return (
    <section className="evidence">
      <p className="hint mono">
        {source.repository_name} / {source.path || '仓库根目录'}
      </p>
      <FormSelect
        label="本人GitHub连接"
        value={String(connection || '')}
        options={[
          { value: '', label: '请选择连接' },
          ...connections.map((c) => ({ value: String(c.id), label: c.name })),
        ]}
        disabled={busy}
        onChange={(v) => {
          setConnection(Number(v));
          setBefore('');
          setAfter('');
          clear();
        }}
      />
      <div className="form-grid mt">
        {(['before', 'after'] as const).map((side) => (
          <GitVersionPicker
            key={`${side}:${connection}`}
            label={side === 'before' ? '旧基准' : '新目标'}
            projectId={projectId}
            repositoryId={source.repository_id || 0}
            connectionId={connection}
            defaultBranch={source.branch || 'main'}
            value={side === 'before' ? before : after}
            disabled={busy}
            onChange={(v) => {
              if (side === 'before') setBefore(v);
              else setAfter(v);
              clear();
            }}
            onSessionEnd={onSessionEnd}
          />
        ))}
      </div>
      <button
        type="button"
        className="small mt"
        disabled={busy || !connection || !before || !after}
        onClick={() => void read()}
      >
        {busy ? '读取中…' : '读取两侧原型文件树'}
      </button>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {fixed && (
        <>
          <p className="hint mono mt">
            旧基准：{fixed.before}
            <br />
            新目标：{fixed.after}
          </p>
          <CodeFileTree
            paths={paths}
            selected={chosen}
            onChange={(files) => {
              setChosen(files);
              emit(files);
            }}
          />
        </>
      )}
      <p className="hint mt">分析时读取所选固定提交。</p>
    </section>
  );
}
function LinkPrototypePair({
  source,
  projectId,
  onChange,
  onSessionEnd,
}: {
  source: PrototypeSource;
  projectId: number;
  onChange: (pair: ChangePair) => void;
  onSessionEnd: () => void;
}) {
  const [reports, setReports] = useState<ReportItem[]>([]),
    [page, setPage] = useState(0),
    [more, setMore] = useState(false),
    [reportId, setReportId] = useState(''),
    [baseline, setBaseline] = useState<{ ref: string; scope: string[]; reportId: number } | null>(
      null,
    ),
    [pages, setPages] = useState<LinkSelection>({ paths: [], snapshot: '' }),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  const controller = useRef(new AbortController());
  useEffect(() => {
    const c = new AbortController();
    controller.current = c;
    return () => c.abort();
  }, []);
  function emit(old = baseline, next = pages) {
    onChange({
      name: source.name,
      before: old?.ref || '',
      after: next.snapshot ? `当前页面目录 ${next.snapshot}（正文未固定）` : '',
      update: '原型链接 · 旧固定正文对新页面范围',
      scope:
        old && next.paths.length
          ? [...old.scope.map((s) => `旧：${s}`), ...next.paths.map((s) => `新：${s}`)]
          : [],
      selection: {
        kind: 'LINK_PROTOTYPE',
        source_id: source.id,
        baseline_report_id: old?.reportId,
        paths: next.paths,
        snapshot: next.snapshot,
        url: source.url || '',
        update_mode: 'FULL_REPLACEMENT',
      },
    });
  }
  async function readReports() {
    setBusy(true);
    setError('');
    try {
      const next = await riskListing(
        `/api/projects/${projectId}/requirements/risk-reports?page=${page + 1}`,
        controller.current.signal,
      );
      if (controller.current.signal.aborted) return;
      setReports((old) => [...old, ...next.items]);
      setPage((p) => p + 1);
      setMore(next.has_more);
    } catch (e) {
      if (!controller.current.signal.aborted) setError(prototypeError(e, onSessionEnd));
    } finally {
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  async function choose(id: string) {
    setReportId(id);
    setBaseline(null);
    emit(null);
    if (!id) return;
    setBusy(true);
    setError('');
    try {
      const report = await riskDetailRequest(
        `/api/projects/${projectId}/requirements/risk-reports/${id}`,
        projectId,
        { signal: controller.current.signal },
      );
      const material = linkBaseline(report, source);
      if (controller.current.signal.aborted) return;
      const value = {
        ref: `报告 #${report.id} · ${material.snapshot_ref}`,
        reportId: report.id,
        scope: material.segments.filter((s) => s.text.trim()).map((s) => s.location),
      };
      setBaseline(value);
      emit(value);
    } catch (e) {
      if (!controller.current.signal.aborted)
        setError(
          e instanceof Error && e.message.includes('旧基准')
            ? e.message
            : prototypeError(e, onSessionEnd),
        );
    } finally {
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  return (
    <section className="evidence">
      <p className="hint mono">{source.url}</p>
      <h3>旧基准 · 已保存页面快照</h3>
      <button
        type="button"
        className="small mt"
        disabled={busy || (page > 0 && !more)}
        onClick={() => void readReports()}
      >
        {busy ? '加载中…' : page ? '更多报告' : '读取已有报告'}
      </button>
      <FormSelect
        label="选择含该链接旧正文的报告"
        value={reportId}
        disabled={busy}
        options={[
          { value: '', label: '请选择已有报告' },
          ...reports.map((r) => ({
            value: String(r.id),
            label: `#${r.id} · ${r.title} · ${new Date(r.created_at).toLocaleString()}`,
          })),
        ]}
        onChange={(v) => void choose(v)}
      />
      {baseline ? (
        <>
          <p className="hint mono">{baseline.ref}</p>
          <details>
            <summary>旧页面正文位置 · {baseline.scope.length}项</summary>
            {baseline.scope.map((s, i) => (
              <p className="hint" key={i}>
                {s}
              </p>
            ))}
          </details>
        </>
      ) : (
        <p className="hint">没有实际保存的旧正文不能比较；相同URL或目录哈希不能充当旧页面快照。</p>
      )}
      <h3 className="mt">新目标 · 当前页面</h3>
      <PrototypeLinkPages
        projectId={projectId}
        documentId={source.id}
        value={pages}
        disabled={busy}
        onSessionEnd={onSessionEnd}
        onChange={(next) => {
          setPages(next);
          emit(baseline, next);
        }}
      />
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <p className="hint mt">页面正文固定与差异比较待接入；当前仅可选择页面目录。</p>
    </section>
  );
}
export function ChangePrototypeSources({
  projectId,
  onChange,
  onSessionEnd,
}: {
  projectId: number;
  onChange: (pairs: ChangePair[]) => void;
  onSessionEnd: () => void;
}) {
  const [sources, setSources] = useState<PrototypeSource[]>([]),
    [connections, setConnections] = useState<PrototypeConnection[]>([]),
    [mode, setMode] = useState<'GITHUB' | 'LINK' | 'DIRECTORY'>('GITHUB'),
    [chosen, setChosen] = useState<Record<number, ChangePair>>({}),
    [busy, setBusy] = useState(true),
    [error, setError] = useState('');
  useEffect(() => {
    const c = new AbortController();
    Promise.all([
      apiRequest<unknown>(`/api/projects/${projectId}/prototypes`, { signal: c.signal }).then(
        parsePrototypeLibrary,
      ),
      apiRequest<unknown>(`/api/projects/${projectId}/prototypes/options`, {
        signal: c.signal,
      }).then(parsePrototypeOptions),
    ])
      .then(([library, options]) => {
        if (!c.signal.aborted) {
          setSources(library.sources);
          setConnections(options);
        }
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(prototypeError(e, onSessionEnd));
      })
      .finally(() => {
        if (!c.signal.aborted) setBusy(false);
      });
    return () => c.abort();
  }, [projectId, onSessionEnd]);
  function update(id: number, pair: ChangePair | null) {
    const next = { ...chosen };
    if (pair) next[id] = pair;
    else delete next[id];
    setChosen(next);
    onChange(Object.values(next));
  }
  return (
    <section>
      <h3>原型变更来源</h3>
      <div className="row mt">
        {(['GITHUB', 'LINK', 'DIRECTORY'] as const).map((key) => (
          <button
            type="button"
            className={mode === key ? 'primary' : 'ghost'}
            aria-pressed={mode === key}
            key={key}
            onClick={() => {
              setMode(key);
              setChosen({});
              onChange([]);
            }}
          >
            {key === 'DIRECTORY' ? '本地目录' : key === 'GITHUB' ? 'GitHub 原型' : '原型链接'}
          </button>
        ))}
      </div>
      <p className="hint mt">
        {mode === 'DIRECTORY'
          ? '比较本地目录资料的两个固定版本和所选文件。'
          : mode === 'GITHUB'
            ? '比较固定旧、新提交的原型文件。'
            : '比较旧报告实际保存的页面正文与本次选择的新页面范围。'}
      </p>
      {busy && <p className="hint">加载已登记原型来源…</p>}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {sources
        .filter((s) => s.kind === mode)
        .map((source) => (
          <section className="change-version-row mt" key={source.id}>
            <label className="check-label">
              <input
                type="checkbox"
                checked={Object.hasOwn(chosen, source.id)}
                onChange={(e) =>
                  update(
                    source.id,
                    e.target.checked
                      ? {
                          name: source.name,
                          before: '',
                          after: '',
                          update: mode === 'GITHUB' ? 'GitHub原型' : '原型链接',
                          scope: [],
                        }
                      : null,
                  )
                }
              />
              <strong>{source.name}</strong>
            </label>
            {Object.hasOwn(chosen, source.id) &&
              (mode === 'DIRECTORY' ? (
                <DirectoryPrototypePair
                  source={source}
                  projectId={projectId}
                  onChange={(pair) => update(source.id, pair)}
                  onSessionEnd={onSessionEnd}
                />
              ) : mode === 'GITHUB' ? (
                <GithubPrototypePair
                  source={source}
                  connections={connections.filter((c) =>
                    c.repositories.some((r) => r.id === source.repository_id),
                  )}
                  projectId={projectId}
                  onChange={(pair) => update(source.id, pair)}
                  onSessionEnd={onSessionEnd}
                />
              ) : (
                <LinkPrototypePair
                  source={source}
                  projectId={projectId}
                  onChange={(pair) => update(source.id, pair)}
                  onSessionEnd={onSessionEnd}
                />
              ))}
          </section>
        ))}
      {!busy && !sources.some((s) => s.kind === mode) && (
        <p className="hint mt">暂无此类原型来源，请先在原型资料登记。</p>
      )}
    </section>
  );
}
