import { Select } from './FormSelect';
import { useState } from 'react';
import type { DocumentPreview, WorkbookSheet } from './documentApi';

export function excelColumn(index: number): string {
  let label = '';
  for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26))
    label = String.fromCharCode(65 + ((n - 1) % 26)) + label;
  return label;
}

export function OfficePreview({
  preview,
}: {
  preview: Extract<DocumentPreview, { kind: 'word' | 'workbook' }>;
}) {
  const [sheetIndex, setSheetIndex] = useState(0);
  if (preview.kind === 'word')
    return (
      <article className="office-word">
        <p className="doc-note">正文与表格内容预览；图片、批注和复杂排版请查看原件。</p>
        {preview.blocks.map((block, index) =>
          block.kind === 'table' ? (
            <div className="office-table-scroll" key={index}>
              <table className="office-word-table">
                <tbody>
                  {block.rows.map((row, r) => (
                    <tr key={r}>
                      {row.map((cell, c) => (
                        <td key={c} colSpan={cell.colspan} rowSpan={cell.rowspan}>
                          {cell.text}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : block.kind === 'heading' ? (
            <h2 key={index} className={`office-heading-${block.level}`}>
              {block.text}
            </h2>
          ) : (
            <p key={index} className="office-paragraph">
              {block.text || '\u00a0'}
            </p>
          ),
        )}
        {!preview.blocks.length && <p className="muted">未读取到可显示的正文，请下载原件查看。</p>}
        {preview.truncated && <p className="doc-note">文档仅展示部分内容，原件完整保留。</p>}
      </article>
    );
  const sheet = preview.sheets[sheetIndex] || preview.sheets[0];
  return (
    <section className="office-workbook">
      <div className="office-workbook-toolbar">
        <label className="form-field">
          工作表
          <Select value={sheetIndex} onChange={(e) => setSheetIndex(Number(e))}>
            {preview.sheets.map((s, i) => (
              <option key={i} value={i}>
                {s.name}
              </option>
            ))}
          </Select>
        </label>
        {sheet && (
          <span className="hint">
            {sheet.total_rows} 行 × {sheet.total_columns} 列
          </span>
        )}
      </div>
      <p className="doc-note">
        展示保存时的单元格值，保留行列位置及合并区域；公式不重新计算，图表和复杂格式请查看原件。
      </p>
      {sheet ? <SheetTable sheet={sheet} /> : <p className="panel-pad muted">未找到工作表。</p>}
      {(preview.truncated || sheet?.truncated) && (
        <p className="doc-note">
          仅展示部分内容：最多20个工作表，每表200行、50列，超长内容截取。原件完整保留。
        </p>
      )}
    </section>
  );
}

function SheetTable({ sheet }: { sheet: WorkbookSheet }) {
  const columns = Math.max(0, ...sheet.rows.map((row) => row.length));
  const hidden = new Set<string>(),
    anchors = new Map<string, { rowspan: number; colspan: number }>();
  for (const [r, c, rs, cs] of sheet.merges) {
    anchors.set(`${r}:${c}`, { rowspan: rs, colspan: cs });
    for (let ri = r; ri < r + rs; ri++)
      for (let ci = c; ci < c + cs; ci++) if (ri !== r || ci !== c) hidden.add(`${ri}:${ci}`);
  }
  if (!sheet.rows.length || !columns) return <p className="panel-pad muted">此工作表为空。</p>;
  return (
    <div className="office-table-scroll" tabIndex={0} aria-label={`${sheet.name}，可滚动查看表格`}>
      <table className="office-sheet">
        <thead>
          <tr>
            <th aria-label="行号" />
            {Array.from({ length: columns }, (_, c) => (
              <th scope="col" key={c}>
                {excelColumn(c)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sheet.rows.map((row, r) => (
            <tr key={r}>
              <th scope="row">{r + 1}</th>
              {Array.from({ length: columns }, (_, c) => {
                const key = `${r}:${c}`;
                if (hidden.has(key)) return null;
                const span = anchors.get(key);
                return (
                  <td
                    key={c}
                    rowSpan={span?.rowspan}
                    colSpan={span?.colspan}
                    title={`${excelColumn(c)}${r + 1}`}
                  >
                    {row[c] || ''}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
