import type { GenerationRecord, GenerationSuggestion } from './generationPage';

const brief = (text: string, limit = 300) =>
  text.length > limit ? text.slice(0, limit) + '…' : text;
export function GenerationEvidence({
  record,
  suggestion,
}: {
  record: Pick<GenerationRecord, 'materials'>;
  suggestion: Pick<GenerationSuggestion, 'evidence'>;
}) {
  return (
    <>
      {!suggestion.evidence.length && <p className="hint">本条没有保存来源引用。</p>}
      {suggestion.evidence.map((e, index) => {
        const matches = record.materials.filter(
            (m) => m.sourceId === e.source && (!m.side || m.side === e.side),
          ),
          material = matches.length === 1 ? matches[0] : undefined,
          segment = material?.segments.find((s) => s.id === e.segment),
          hasQuote =
            !!e.quote &&
            (e.verifiedQuote === true ||
              (e.verifiedQuote === undefined && !!segment?.text.includes(e.quote)));
        return (
          <section className="evidence generation-fixed-evidence" key={index}>
            <strong>{material?.name || e.source}</strong>
            <p className="hint">
              {e.side} · {material?.versionName || material?.version || '未保存资料版本'} ·{' '}
              {segment?.location || '资料级来源'}
            </p>
            {e.quoteWarning ? (
              <>
                <p className="generation-evidence-quote">AI摘录（待核对）：{brief(e.quote)}</p>
                <p className="hint">{e.quoteWarning}</p>
              </>
            ) : hasQuote ? (
              <p className="generation-evidence-quote">需求 / 原型证据摘要：{brief(e.quote)}</p>
            ) : (
              <p className="hint">此报告仅保存资料级引用，未保存支持本条用例的需求 / 原型摘录。</p>
            )}
            {!material && <p className="hint">此引用没有可唯一匹配的已保存资料快照。</p>}
          </section>
        );
      })}
    </>
  );
}
