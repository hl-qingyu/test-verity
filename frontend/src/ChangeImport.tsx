import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { CaseDialog } from './CaseDialog';
import { Form } from './Form';
import { FormSelect } from './FormSelect';
import { FilePicker } from './FilePicker';
import { codeRequest, parseCodeOptions } from './codeAnalysisApi';
import type { CodeOptions } from './codeAnalysisApi';
import {
  array,
  object,
  string,
  changeDetail,
  changeError,
  parseChangeDetail,
} from './changeAnalysisApi';
import type { PageChangeRecord } from './changeAnalysisPage';

type Binding = {
  snapshot_ref: string;
  document_id?: number;
  version_id?: number;
  source_id?: number;
  source_version?: number;
  connection_id?: number;
  kind?: 'GITHUB' | 'LOCAL';
};
export function ChangeImport({
  projectId,
  onClose,
  onImported,
  onSessionEnd,
}: {
  projectId: number;
  onClose: () => void;
  onImported: (record: PageChangeRecord) => void;
  onSessionEnd: () => void;
}) {
  const [input, setInput] = useState<{ name: string; text: string } | null>(null),
    [report, setReport] = useState<{ name: string; text: string } | null>(null),
    [title, setTitle] = useState(''),
    [options, setOptions] = useState<CodeOptions | null>(null),
    [bindings, setBindings] = useState<Record<string, Binding>>({}),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const controller = useRef(new AbortController()),
    formId = useId();
  useEffect(() => {
    const c = new AbortController();
    controller.current = c;
    void codeRequest(`/api/projects/${projectId}/code-analysis/options`, parseCodeOptions, {
      signal: c.signal,
    })
      .then((o) => {
        if (!c.signal.aborted) setOptions(o);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(changeError(e, onSessionEnd));
      });
    return () => c.abort();
  }, [projectId, onSessionEnd]);
  async function pick(kind: 'input' | 'report', files: File[]) {
    const f = files[0];
    if (!f || busy) return;
    setBusy(true);
    setError('');
    setBindings({});
    if (kind === 'input') setInput(null);
    else setReport(null);
    try {
      if (!f.name.toLowerCase().endsWith('.json')) throw Error('请选择JSON文件。');
      const value = { name: f.name, text: await f.text() };
      if (controller.current.signal.aborted) return;
      if (kind === 'input') setInput(value);
      else setReport(value);
    } catch (e) {
      if (!controller.current.signal.aborted)
        setError(e instanceof Error ? e.message : '读取文件失败。');
    } finally {
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  const { preview, snapshots, validation } = useMemo(() => {
    if (!input || !report) return { preview: null, snapshots: [], validation: '' };
    try {
      const a = object(JSON.parse(input.text.replace(/^\uFEFF/, ''))),
        b = object(JSON.parse(report.text.replace(/^\uFEFF/, '')));
      if (
        a.contract_version !== 2 ||
        (b.contract_version !== 2 && b.contract_version !== 3) ||
        a.analysis_type !== 'CHANGE_IMPACT' ||
        a.project_id !== projectId ||
        a.request_id !== b.request_id
      )
        throw Error('需要当前项目的 CHANGE_IMPACT 配对文件，支持契约 v2 和 v3。');
      const value = parseChangeDetail(
        {
          id: 1,
          project_id: projectId,
          title: '导入预览',
          mode: a.mode,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          origin: 'IMPORT',
          status: 'COMPLETED',
          input: a,
          report: b,
          handling: {},
          revision: 1,
          error_code: '',
          targets: a.targets,
          focus: a.focus,
          selections: {},
        },
        projectId,
      );
      return { preview: value, snapshots: array(a.snapshots).map(object), validation: '' };
    } catch (e) {
      return {
        preview: null,
        snapshots: [],
        validation: e instanceof Error ? e.message : '双JSON格式无效。',
      };
    }
  }, [input, report, projectId]);
  function bind(ref: string, value: Binding) {
    setBindings((old) => ({ ...old, [ref]: value }));
  }
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!preview || !input || !report || busy) return;
    setBusy(true);
    setError('');
    try {
      const value = await changeDetail(
        `/api/projects/${projectId}/change-analysis/import`,
        projectId,
        {
          method: 'POST',
          signal: controller.current.signal,
          body: JSON.stringify({
            title: title.trim(),
            input_filename: input.name,
            report_filename: report.name,
            input_json: input.text,
            report_json: report.text,
            bindings: Object.values(bindings),
          }),
        },
      );
      if (!controller.current.signal.aborted) onImported(value);
    } catch (e) {
      if (!controller.current.signal.aborted) setError(changeError(e, onSessionEnd));
    } finally {
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  return (
    <CaseDialog
      title="导入变更分析结果"
      busy={busy}
      wide
      onClose={onClose}
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
            disabled={
              busy ||
              !preview ||
              !title.trim() ||
              snapshots.some((s) => !bindings[string(s.snapshot_ref)])
            }
          >
            校验并导入
          </button>
        </footer>
      }
    >
      <Form id={formId} onSubmit={(e) => void submit(e)}>
        <p className="notice">导入快照尚未与真实仓库比对。</p>
        <div className="form-grid">
          {(['input', 'report'] as const).map((kind) => (
            <section className="evidence" key={kind}>
              <h3>{kind}.json</h3>
              <FilePicker
                accept=".json"
                disabled={busy}
                onChange={(files) => void pick(kind, files)}
              />
              <p className="hint">{(kind === 'input' ? input : report)?.name || '尚未选择'}</p>
            </section>
          ))}
        </div>
        <label className="form-field">
          记录名称
          <input
            required
            maxLength={200}
            disabled={busy}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
        {preview && (
          <section className="evidence">
            <p>
              {preview.changes.length}项变化 / {preview.impacts.length}项影响与风险 /{' '}
              {preview.regressions.length}项回归 · 待服务端校验
            </p>
          </section>
        )}
        {snapshots.map((s) => {
          const ref = string(s.snapshot_ref),
            b = bindings[ref],
            isCode = s.kind === 'CODE',
            origin = object(s.provenance).source_kind;
          const candidates = isCode
            ? [
                ...(origin !== 'LOCAL'
                  ? (options?.repositories || [])
                      .filter((r) => r.kind === s.repository_kind)
                      .map((r) => ({
                        value: `GITHUB:${r.id}`,
                        label: r.full_name,
                        kind: 'GITHUB' as const,
                        id: r.id,
                        version: r.version,
                      }))
                  : []),
                ...(origin !== 'GITHUB'
                  ? (options?.local_sources || [])
                      .filter((r) => r.kind === s.repository_kind)
                      .map((r) => ({
                        value: `LOCAL:${r.id}`,
                        label: r.name,
                        kind: 'LOCAL' as const,
                        id: r.id,
                        version: r.version,
                      }))
                  : []),
              ]
            : [];
          return (
            <section className="evidence" key={ref}>
              <strong>
                {string(s.name)} · {ref}
              </strong>
              {isCode ? (
                <>
                  <FormSelect
                    label="项目代码来源"
                    disabled={busy}
                    value={b?.source_id ? `${b.kind}:${b.source_id}` : ''}
                    options={[{ value: '', label: '选择登记角色一致的来源' }, ...candidates]}
                    onChange={(v) => {
                      const row = candidates.find((r) => r.value === v);
                      if (row)
                        bind(ref, {
                          snapshot_ref: ref,
                          kind: row.kind,
                          source_id: row.id,
                          source_version: row.version,
                          connection_id:
                            row.kind === 'GITHUB' ? options?.connections[0]?.id : undefined,
                        });
                      else
                        setBindings((old) => {
                          const next = { ...old };
                          delete next[ref];
                          return next;
                        });
                    }}
                  />
                  {b?.kind === 'GITHUB' && (
                    <FormSelect
                      label="本人GitHub连接"
                      disabled={busy}
                      value={String(b.connection_id || '')}
                      options={[
                        { value: '', label: '请选择连接' },
                        ...(options?.connections || []).map((c) => ({
                          value: String(c.id),
                          label: c.name,
                        })),
                      ]}
                      onChange={(v) => bind(ref, { ...b, connection_id: Number(v) || undefined })}
                    />
                  )}
                </>
              ) : (
                <>
                  <FormSelect
                    label="已有原件"
                    disabled={busy}
                    value={String(b?.document_id || '')}
                    options={[
                      { value: '', label: '请选择本项目对应资料' },
                      ...(options?.materials || [])
                        .filter((m) => m.purpose === s.kind)
                        .map((m) => ({
                          value: String(m.id),
                          label: m.versions[0]?.filename || m.name,
                        })),
                    ]}
                    onChange={(v) => {
                      const m = options?.materials.find((m) => m.id === Number(v));
                      if (m)
                        bind(ref, {
                          snapshot_ref: ref,
                          document_id: m.id,
                          version_id: ['FILE', 'DIRECTORY'].includes(m.kind)
                            ? m.versions[0]?.id
                            : undefined,
                        });
                      else
                        setBindings((old) => {
                          const next = { ...old };
                          delete next[ref];
                          return next;
                        });
                    }}
                  />
                  {b?.document_id &&
                    ['FILE', 'DIRECTORY'].includes(
                      options?.materials.find((m) => m.id === b.document_id)?.kind || '',
                    ) && (
                      <FormSelect
                        label="原件固定版本"
                        disabled={busy}
                        value={String(b.version_id || '')}
                        options={[
                          { value: '', label: '请选择版本' },
                          ...(
                            options?.materials.find((m) => m.id === b.document_id)?.versions || []
                          ).map((v) => ({
                            value: String(v.id),
                            label: `${v.filename} · v${v.number}`,
                          })),
                        ]}
                        onChange={(v) => bind(ref, { ...b, version_id: Number(v) || undefined })}
                      />
                    )}
                </>
              )}
            </section>
          );
        })}
        {(error || validation) && (
          <p className="form-error" role="alert">
            {error || validation}
          </p>
        )}
      </Form>
    </CaseDialog>
  );
}
