import { CASE_COLUMNS } from './caseApi';
import { currentHandling } from './generationPage';
import type { GenerationRecord } from './generationPage';

export function downloadGeneration(name: string, content: string | Blob, json = false) {
  const blob =
    typeof content === 'string'
      ? new Blob([content], {
          type: json ? 'application/json;charset=utf-8' : 'text/markdown;charset=utf-8',
        })
      : content;
  const url = URL.createObjectURL(blob),
    a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
const xml = (s: string) =>
  s
    .split('')
    .filter((c) => c.charCodeAt(0) >= 32 || ['\t', '\n', '\r'].includes(c))
    .join('')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
// Small dependency-free, uncompressed ZIP: candidates are literal XML strings, never Excel formulas.
export function generationXlsx(record: GenerationRecord): Blob {
  return caseDesignXlsx(
    record.suggestions
      .filter((s) => s.kind !== 'RETIRE')
      .map((s) => currentHandling(record, s)?.draft || s.design),
  );
}
export function caseDesignXlsx(designs: import('./caseApi').Design[]): Blob {
  const rows = [
    CASE_COLUMNS.map((c) => String(c[1])),
    ...designs.map((d, i) =>
      CASE_COLUMNS.map(([f]) =>
        f === 'serial'
          ? String(i + 1)
          : f === 'number' || f === 'tester'
            ? ''
            : f === 'result'
              ? '未测'
              : d[f],
      ),
    ),
  ];
  const sheet = `<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>${rows.map((r, i) => `<row r="${i + 1}">${r.map((c, j) => `<c r="${String.fromCharCode(65 + j)}${i + 1}" t="inlineStr"><is><t xml:space="preserve">${xml(c)}</t></is></c>`).join('')}</row>`).join('')}</sheetData></worksheet>`;
  const files: [string, string][] = [
    [
      '[Content_Types].xml',
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
    ],
    [
      '_rels/.rels',
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
    ],
    [
      'xl/workbook.xml',
      '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="候选用例" sheetId="1" r:id="rId1"/></sheets></workbook>',
    ],
    [
      'xl/_rels/workbook.xml.rels',
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
    ],
    ['xl/worksheets/sheet1.xml', sheet],
  ];
  const parts: Uint8Array<ArrayBuffer>[] = [],
    central: Uint8Array<ArrayBuffer>[] = [];
  let offset = 0;
  for (const [path, content] of files) {
    const name = new TextEncoder().encode(path),
      data = new TextEncoder().encode(content);
    let crc = 0xffffffff;
    for (const b of data) {
      crc ^= b;
      for (let i = 0; i < 8; i++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
    }
    crc = (crc ^ 0xffffffff) >>> 0;
    const local = new Uint8Array(30 + name.length),
      lv = new DataView(local.buffer);
    lv.setUint32(0, 0x04034b50, true);
    lv.setUint16(4, 20, true);
    lv.setUint32(14, crc, true);
    lv.setUint32(18, data.length, true);
    lv.setUint32(22, data.length, true);
    lv.setUint16(26, name.length, true);
    local.set(name, 30);
    const directory = new Uint8Array(46 + name.length),
      dv = new DataView(directory.buffer);
    dv.setUint32(0, 0x02014b50, true);
    dv.setUint16(4, 20, true);
    dv.setUint16(6, 20, true);
    dv.setUint32(16, crc, true);
    dv.setUint32(20, data.length, true);
    dv.setUint32(24, data.length, true);
    dv.setUint16(28, name.length, true);
    dv.setUint32(42, offset, true);
    directory.set(name, 46);
    parts.push(local, data);
    central.push(directory);
    offset += local.length + data.length;
  }
  const end = new Uint8Array(22),
    ev = new DataView(end.buffer);
  ev.setUint32(0, 0x06054b50, true);
  ev.setUint16(8, files.length, true);
  ev.setUint16(10, files.length, true);
  ev.setUint32(
    12,
    central.reduce((n, p) => n + p.length, 0),
    true,
  );
  ev.setUint32(16, offset, true);
  return new Blob([...parts, ...central, end], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
}
