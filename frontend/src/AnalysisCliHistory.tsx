import { useEffect, useRef, useState } from 'react';
import { apiRequest } from './api/http';
import { FormSelect } from './FormSelect';
import { CachedNativeCliWorkspace } from './NativeCliWorkspace';

type Kind = 'requirements' | 'code' | 'changes' | 'coverage';
const names: Record<Kind, string> = {
  requirements: '需求分析',
  code: '代码分析',
  changes: '变更分析',
  coverage: '用例分析',
};
const errors: Record<string, string> = {
  analysis_terminal_not_found: '此记录的 CLI 会话已不可用。',
  analysis_terminal_owner_only: '只有分析发起人可以查看此 CLI 会话。',
  analysis_terminal_history_unavailable: 'CLI 尚未建立可续接的对话。',
  analysis_terminal_stopping: '上一个 CLI 进程正在结束，请稍后重试。',
  analysis_terminal_interrupted: '后台进程已中断，可以继续原 CLI 对话。',
  analysis_terminal_candidate_not_found: '候选轮次已不可用。',
  generation_terminal_permission_required: '当前账号未启用 CLI 对话。',
  generation_terminal_failed: 'CLI 进程运行失败，请查看终端记录。',
  generation_terminal_turn_failed: 'CLI 本轮分析失败，请查看终端记录。',
  generation_terminal_turn_interrupted: 'CLI 本轮分析已中断。',
  generation_terminal_response_incomplete: 'CLI 未返回完整报告。',
  generation_terminal_command_blocked: 'CLI 已阻止未经授权的命令。',
  generation_native_results_unavailable: '暂时无法读取 CLI 候选轮次。',
  generation_response_invalid: 'CLI 会话响应格式无效。',
};

export function useHistoryButton(open: boolean) {
  const trigger = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);
  useEffect(() => {
    if (!open && wasOpen.current) trigger.current?.focus();
    wasOpen.current = open;
  }, [open]);
  return trigger;
}

export function AnalysisCliHistory({
  projectId,
  recordId,
  kind,
  cancelUrl,
  open,
  reference,
  onClose,
  onInitialFinished,
  errorMessage,
}: {
  projectId: number;
  recordId: number | string;
  kind: Kind;
  cancelUrl: string;
  open: boolean;
  reference?: string;
  onClose: () => void;
  onInitialFinished?: () => void;
  errorMessage: (error: unknown) => string;
}) {
  const base = `/api/projects/${projectId}/analysis-terminal/${kind}/${recordId}`;
  const explain = (error: unknown) =>
    (error instanceof Error && errors[error.message]) || errorMessage(error);
  return (
    <CachedNativeCliWorkspace
      key={base}
      base={base}
      cancelInitial={cancelUrl}
      initialCancelLabel="取消分析"
      workspaceTitle={`${names[kind]}历史对话`}
      label={names[kind]}
      errorMessage={explain}
      onInitialFinished={onInitialFinished}
      onClose={onClose}
      open={open}
      reference={reference}
      renderResults={<CandidateRounds base={base} visible={open} errorMessage={explain} />}
    />
  );
}

type Round = { id: string; timestamp: string };
type Preview = {
  raw: string;
  counts: Record<string, number>;
  warnings: number;
  error_code: string;
};
function obj(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw Error('generation_response_invalid');
  return value as Record<string, unknown>;
}
function validCount(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}
function parseRounds(value: unknown): Round[] {
  const items = obj(value).items;
  if (!Array.isArray(items)) throw Error('generation_response_invalid');
  return items.map((item: unknown) => {
    const { id, timestamp } = obj(item);
    if (
      typeof id !== 'string' ||
      !/^[a-f0-9]{64}$/.test(id) ||
      typeof timestamp !== 'string' ||
      !Number.isFinite(Date.parse(timestamp))
    )
      throw Error('generation_response_invalid');
    return { id, timestamp };
  });
}
function parsePreview(value: unknown, id: string): Preview {
  const { id: returnedId, raw, counts, warnings, error_code } = obj(value);
  const entries = Object.entries(obj(counts));
  if (
    returnedId !== id ||
    typeof raw !== 'string' ||
    typeof error_code !== 'string' ||
    !validCount(warnings) ||
    entries.some(([, count]) => !validCount(count))
  )
    throw Error('generation_response_invalid');
  return {
    raw,
    counts: Object.fromEntries(entries) as Record<string, number>,
    warnings,
    error_code,
  };
}

function CandidateRounds({
  base,
  visible,
  errorMessage,
}: {
  base: string;
  visible: boolean;
  errorMessage: (error: unknown) => string;
}) {
  const [rounds, setRounds] = useState<Round[] | null>(null),
    [selected, setSelected] = useState(''),
    [preview, setPreview] = useState<Preview | null>(null),
    [error, setError] = useState('');
  const explain = useRef(errorMessage);
  explain.current = errorMessage;
  useEffect(() => {
    if (!visible) return;
    const c = new AbortController();
    let timer: number;
    async function load() {
      try {
        const values = parseRounds(await apiRequest(`${base}/results`, { signal: c.signal }));
        if (!c.signal.aborted) {
          setRounds(values);
          setSelected((old) => (values.some((item) => item.id === old) ? old : ''));
        }
      } catch (e) {
        if (!c.signal.aborted) setError(explain.current(e));
      } finally {
        if (!c.signal.aborted) timer = window.setTimeout(load, 4000);
      }
    }
    void load();
    return () => {
      c.abort();
      window.clearTimeout(timer);
    };
  }, [base, visible]);
  useEffect(() => {
    if (!selected || !visible) return;
    const c = new AbortController();
    setError('');
    setPreview(null);
    void apiRequest(`${base}/results/${selected}`, { signal: c.signal })
      .then((value) => {
        if (!c.signal.aborted) setPreview(parsePreview(value, selected));
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(explain.current(e));
      });
    return () => c.abort();
  }, [base, selected, visible]);
  return (
    <section className="evidence cli-event-panel">
      <h3>CLI 候选轮次</h3>
      {rounds?.length ? (
        <FormSelect
          label="CLI 返回轮次"
          value={selected}
          options={[
            { value: '', label: '请选择轮次' },
            ...rounds.map((round, index) => ({
              value: round.id,
              label: `第 ${rounds.length - index} 轮 · ${new Date(round.timestamp).toLocaleString()}`,
            })),
          ]}
          onChange={setSelected}
        />
      ) : (
        <p className="hint" role="status">
          {rounds ? '暂无续聊候选。' : '正在读取候选轮次…'}
        </p>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {selected && !preview && !error && <p role="status">正在校验候选…</p>}
      {selected && preview && (
        <>
          {preview.error_code ? (
            <p className="form-error" role="alert">
              校验未通过 · {explain.current(new Error(preview.error_code))}
            </p>
          ) : (
            <p className="hint">
              {Object.entries(preview.counts)
                .map(([label, count]) => `${label} ${count}`)
                .join(' · ')}
              {preview.warnings > 0 && ` · ${preview.warnings} 项待核对`}
            </p>
          )}
          <details>
            <summary>原始报告 JSON</summary>
            <pre className="native-result-json">{preview.raw}</pre>
          </details>
        </>
      )}
    </section>
  );
}
