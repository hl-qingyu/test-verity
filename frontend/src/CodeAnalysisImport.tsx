import { useEffect, useRef, useState } from 'react';
import { CaseDialog } from './CaseDialog';
import { FilePicker } from './FilePicker';
import { Form } from './Form';
import { FormSelect } from './FormSelect';
import {
  codeError,
  codeKinds,
  codeRequest,
  codeTargets,
  parseCodeDetail,
  parseCodeInput,
  parseCodeReport,
  readCodeJSON,
} from './codeAnalysisApi';
import type {
  CodeDetail,
  CodeInput,
  CodeOptions,
  CodeReport,
  MaterialBinding,
} from './codeAnalysisApi';

type Loaded<T> = { filename: string; text: string; parsed: T };

export function ImportCodeAnalysis({
  projectId,
  options,
  onClose,
  onImported,
  onSessionEnd,
}: {
  projectId: number;
  options: CodeOptions;
  onClose: () => void;
  onImported: (record: CodeDetail) => void;
  onSessionEnd: () => void;
}) {
  const [input, setInput] = useState<Loaded<CodeInput> | null>(null),
    [report, setReport] = useState<Loaded<CodeReport> | null>(null),
    [title, setTitle] = useState(''),
    [bindings, setBindings] = useState<MaterialBinding[]>([]),
    [busy, setBusy] = useState(false),
    [reading, setReading] = useState({ input: false, report: false }),
    [error, setError] = useState('');
  const controller = useRef(new AbortController()),
    pending = useRef(false),
    generations = useRef({ input: 0, report: 0 });
  useEffect(() => {
    const c = new AbortController();
    controller.current = c;
    return () => c.abort();
  }, []);
  async function pick(kind: 'input' | 'report', files: File[]) {
    const file = files[0];
    if (!file || pending.current) return;
    const generation = ++generations.current[kind];
    setReading((old) => ({ ...old, [kind]: true }));
    setError('');
    if (kind === 'input') {
      setInput(null);
      setBindings([]);
    } else setReport(null);
    try {
      const loaded = await readCodeJSON(file);
      if (controller.current.signal.aborted || generation !== generations.current[kind]) return;
      if (kind === 'input') setInput({ ...loaded, parsed: parseCodeInput(loaded.data) });
      else {
        setReport({ ...loaded, parsed: parseCodeReport(loaded.data) });
        setTitle((old) => old || file.name.replace(/\.json$/i, ''));
      }
    } catch (reason) {
      if (!controller.current.signal.aborted) setError(codeError(reason, onSessionEnd));
    } finally {
      if (!controller.current.signal.aborted && generation === generations.current[kind])
        setReading((old) => ({ ...old, [kind]: false }));
    }
  }
  const matched = !!input && !!report && input.parsed.request_id === report.parsed.request_id;
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current || !input || !report) return;
    if (!matched) {
      setError('两份JSON的request_id不一致，请选择同一次分析的输入与结果。');
      return;
    }
    if (
      input.parsed.materials.some((material) => {
        const binding = bindings.find((b) => b.source_id === material.source_id),
          option = options.materials.find((m) => m.id === binding?.document_id);
        return !option || (['FILE', 'DIRECTORY'].includes(option.kind) && !binding?.version_id);
      })
    ) {
      setError('请关联每份资料的系统来源，文件资料须选择固定版本。');
      return;
    }
    pending.current = true;
    setBusy(true);
    setError('');
    try {
      const result = await codeRequest(
        `/api/projects/${projectId}/code-analysis/import`,
        parseCodeDetail,
        {
          method: 'POST',
          signal: controller.current.signal,
          body: JSON.stringify({
            title: title.trim(),
            input_filename: input.filename,
            report_filename: report.filename,
            input_json: input.text,
            report_json: report.text,
            bindings,
          }),
        },
      );
      if (!controller.current.signal.aborted) onImported(result);
    } catch (reason) {
      if (!controller.current.signal.aborted) setError(codeError(reason, onSessionEnd));
    } finally {
      pending.current = false;
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  return (
    <CaseDialog
      title="导入代码分析结果"
      busy={busy}
      onClose={onClose}
      wide
      className="code-analysis-dialog requirement-ui"
    >
      <Form onSubmit={(event) => void submit(event)}>
        <p className="doc-note">选择 v2 的 input.json 与 report.json，每份最大16MB。</p>
        <div className="risk-import-files">
          {(['input', 'report'] as const).map((kind) => (
            <section className="evidence" key={kind}>
              <h3>{kind === 'input' ? '分析输入 · input.json' : '分析结果 · report.json'}</h3>
              <FilePicker
                accept=".json"
                disabled={busy}
                onChange={(files) => void pick(kind, files)}
              />
              <p className="hint">
                {reading[kind]
                  ? '读取中…'
                  : (kind === 'input' ? input?.filename : report?.filename) || '尚未选择'}
              </p>
            </section>
          ))}
        </div>
        <label className="form-field">
          报告名称
          <input
            required
            maxLength={200}
            value={title}
            disabled={busy}
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        {input && (
          <section className="evidence">
            <h3>固定代码范围</h3>
            <p className="hint">{input.parsed.targets.map((t) => codeTargets[t]).join(' · ')}</p>
            {input.parsed.sources.map((source) => (
              <div className="code-import-source" key={source.source_id}>
                <strong>{source.name}</strong>
                <p className="hint">
                  {source.source_kind === 'LOCAL' ? '本地' : 'GitHub'} ·{' '}
                  {codeKinds[source.repository_kind]} · {source.files.length}个文件
                </p>
                <p className="mono hint">{source.snapshot_ref}</p>
              </div>
            ))}
            <p className="hint">导入快照将保存在本项目，尚未与真实仓库比对。</p>
          </section>
        )}
        {report && (
          <section className="evidence">
            <strong>待校验：{report.parsed.findings.length}条发现</strong>
            <p>{report.parsed.summary.conclusion}</p>
          </section>
        )}
        {input && report && !matched && (
          <p className="form-error" role="alert">
            输入与结果的调用标识不一致。
          </p>
        )}
        {input && input.parsed.materials.length > 0 && (
          <section>
            <h3>关联系统已有资料</h3>
            <p className="hint">关联项目中已有原件，无需重复上传。</p>
            {input.parsed.materials.map((material) => {
              const binding = bindings.find((b) => b.source_id === material.source_id),
                option = options.materials.find((m) => m.id === binding?.document_id);
              return (
                <div className="evidence" key={material.source_id}>
                  <strong>
                    {material.source_id} · {material.name}
                  </strong>
                  <p className="hint">
                    {material.origin} · {material.read_state}
                  </p>
                  <FormSelect
                    label="系统资料"
                    value={String(binding?.document_id || '')}
                    disabled={busy}
                    required
                    options={[
                      { value: '', label: '请选择对应资料，不按文件名自动匹配' },
                      ...options.materials
                        .filter(
                          (m) =>
                            !['REQUIREMENT', 'PROTOTYPE'].includes(material.origin) ||
                            m.purpose === material.origin,
                        )
                        .map((m) => ({ value: String(m.id), label: `${m.name} · ${m.kind}` })),
                    ]}
                    onChange={(value) =>
                      setBindings((old) => [
                        ...old.filter((b) => b.source_id !== material.source_id),
                        ...(value
                          ? [
                              {
                                source_id: material.source_id,
                                document_id: Number(value),
                                version_id: null,
                              },
                            ]
                          : []),
                      ])
                    }
                  />
                  {option && ['FILE', 'DIRECTORY'].includes(option.kind) && (
                    <FormSelect
                      label="固定版本"
                      value={String(binding?.version_id || '')}
                      disabled={busy}
                      required
                      options={[
                        { value: '', label: '请选择固定版本' },
                        ...option.versions.map((v) => ({
                          value: String(v.id),
                          label: `v${v.number} · ${v.filename}`,
                        })),
                      ]}
                      onChange={(value) =>
                        setBindings((old) =>
                          old.map((b) =>
                            b.source_id === material.source_id
                              ? { ...b, version_id: Number(value) || null }
                              : b,
                          ),
                        )
                      }
                    />
                  )}
                </div>
              );
            })}
          </section>
        )}
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
            disabled={busy || reading.input || reading.report || !matched}
          >
            {busy ? '校验并导入中…' : '校验并导入'}
          </button>
        </footer>
      </Form>
    </CaseDialog>
  );
}
