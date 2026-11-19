import { useEffect, useRef, useState } from 'react';
import { Form } from './Form';
import { FormSelect } from './FormSelect';
import { generationError } from './generationApi';
import { nativeResults, nativeResultPreview } from './nativeResultApi';
import type { NativeResult, NativeResultPreview } from './nativeResultApi';

export function NativeResultReview({
  base,
  resultRevision,
  onSessionEnd,
  onSave,
  onReview,
}: {
  base: string;
  resultRevision?: number;
  onSessionEnd: () => void;
  onSave: (id: string, requestId: string) => Promise<boolean>;
  onReview?: (id: string) => void;
}) {
  const [items, setItems] = useState<NativeResult[]>([]),
    [selected, setSelected] = useState(''),
    [preview, setPreview] = useState<NativeResultPreview | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [loaded, setLoaded] = useState(false);
  const request = useRef(''),
    sessionEnd = useRef(onSessionEnd);
  sessionEnd.current = onSessionEnd;
  const saved = preview?.saved || items.find((item) => item.id === selected)?.saved;
  useEffect(() => {
    const c = new AbortController();
    setBusy(true);
    void nativeResults(base, c.signal)
      .then((value) => {
        if (!c.signal.aborted) {
          setItems(value);
          setLoaded(true);
        }
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(generationError(e, sessionEnd.current));
      })
      .finally(() => {
        if (!c.signal.aborted) setBusy(false);
      });
    return () => c.abort();
  }, [base, resultRevision]);
  useEffect(() => {
    setPreview(null);
    if (!selected) return;
    const c = new AbortController();
    setBusy(true);
    setError('');
    void nativeResultPreview(base, selected, c.signal)
      .then((value) => {
        if (!c.signal.aborted) setPreview(value);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(generationError(e, sessionEnd.current));
      })
      .finally(() => {
        if (!c.signal.aborted) setBusy(false);
      });
    return () => c.abort();
  }, [base, selected, resultRevision]);
  async function save() {
    if (busy || saved || !preview?.can_save || preview.id !== selected) return;
    request.current ||= crypto.randomUUID();
    setBusy(true);
    setError('');
    try {
      if (await onSave(selected, request.current)) {
        setItems((old) =>
          old.map((item) => (item.id === selected ? { ...item, saved: true } : item)),
        );
        setPreview((old) => (old ? { ...old, saved: true } : old));
      } else setError('尚未确认保存成功，请查看页面提示后重试。');
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="evidence mt" aria-label="从CLI结果保存待审阅候选">
      <h3>CLI 候选结果</h3>
      <Form
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <FormSelect
          label="CLI返回轮次"
          value={selected}
          disabled={busy}
          required
          options={[
            { value: '', label: '请选择轮次' },
            ...items.map((item) => ({
              value: item.id,
              label: `${new Date(item.timestamp).toLocaleString()} · ${item.saved ? '已保存 · ' : ''}${item.complete === null ? '结构待校验（条数待确认）' : `${item.case_count}条候选 · ${item.complete === true ? '声明完整' : '部分结果/待澄清'}`}`,
            })),
          ]}
          onChange={(value) => {
            request.current = '';
            setSelected(value);
          }}
        />
        {busy && (
          <p className="hint mt" role="status">
            <span className="generation-spinner" aria-hidden="true" /> 正在读取、校验或保存…
          </p>
        )}
        {loaded && !items.length && <p className="hint">暂无可保存的生成结果。</p>}
        {preview && (
          <>
            <p className="hint">有效候选 {preview.valid_cases} 条</p>
            {preview.issues > 0 && (
              <p className="notice">{preview.issues} 项问题待处理，可在“冲突与待澄清”中查看。</p>
            )}
            <details className="evidence">
              <summary>原始 JSON</summary>
              <pre className="native-result-json">{preview.raw_json}</pre>
            </details>
            {!preview.can_save && <p className="hint">生成结束后可保存候选。</p>}
          </>
        )}
        {error && (
          <p className="form-error mt" role="alert">
            {error}
          </p>
        )}
        <div className="row mt">
          <button
            className={saved ? undefined : 'primary'}
            disabled={busy || saved || !preview?.can_save}
            type="submit"
          >
            {saved ? '本轮已保存' : '手动保存到当前对话'}
          </button>
          {saved && onReview && (
            <button className="primary" type="button" onClick={() => onReview(selected)}>
              审核本轮候选
            </button>
          )}
        </div>
      </Form>
    </section>
  );
}
