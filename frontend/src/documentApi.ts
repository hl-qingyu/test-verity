import { isRecord } from './api/guards';
import { apiErrorMessage, apiRequest } from './api/http';

export type DocumentGroup = { id: number; name: string };
export type DocumentVersion = {
  deleted?: boolean;
  id: number;
  document_id: number;
  number: number;
  filename: string;
  extension: string;
  size: number;
  sha256: string;
  created_at: string;
  created_by: string;
};
export type SourceDocument = {
  id: number;
  group_id: number | null;
  position: number;
  current: DocumentVersion;
};
export type DocumentLibrary = {
  revision: number;
  groups: DocumentGroup[];
  documents: SourceDocument[];
};
export type WordBlock =
  | { kind: 'paragraph' | 'heading'; text: string; level: number }
  | { kind: 'table'; rows: { text: string; colspan: number; rowspan: number }[][] };
export type WorkbookSheet = {
  name: string;
  rows: string[][];
  merges: number[][];
  total_rows: number;
  total_columns: number;
  truncated: boolean;
};
export type DocumentPreview = { text: string; truncated?: boolean; deleted?: boolean } & (
  | { kind: 'text' | 'image' | 'pdf' | 'unsupported' }
  | { kind: 'word'; blocks: WordBlock[] }
  | { kind: 'workbook'; sheets: WorkbookSheet[] }
);
export function parsePreview(value: unknown): DocumentPreview {
  const invalid = () => {
    throw new Error('document_response_invalid');
  };
  if (
    !object(value) ||
    (value.deleted !== undefined && typeof value.deleted !== 'boolean') ||
    typeof value.kind !== 'string' ||
    typeof value.text !== 'string' ||
    (value.truncated !== undefined && typeof value.truncated !== 'boolean')
  )
    return invalid();
  if (value.kind === 'word') {
    if (!Array.isArray(value.blocks) || value.blocks.length > 500) return invalid();
    for (const block of value.blocks) {
      if (!object(block)) return invalid();
      if (block.kind === 'table') {
        if (!Array.isArray(block.rows) || block.rows.length > 200) return invalid();
        for (const row of block.rows) {
          if (!Array.isArray(row) || row.length > 50) return invalid();
          for (const c of row) {
            if (
              !object(c) ||
              typeof c.text !== 'string' ||
              !positive(c.colspan) ||
              c.colspan > 50 ||
              !positive(c.rowspan) ||
              c.rowspan > 200
            )
              return invalid();
          }
        }
      } else if (
        !['paragraph', 'heading'].includes(String(block.kind)) ||
        typeof block.text !== 'string' ||
        typeof block.level !== 'number' ||
        !Number.isInteger(block.level) ||
        block.level < 0 ||
        block.level > 6
      )
        return invalid();
    }
  } else if (value.kind === 'workbook') {
    if (!Array.isArray(value.sheets) || value.sheets.length > 20) return invalid();
    for (const sheet of value.sheets) {
      if (
        !object(sheet) ||
        typeof sheet.name !== 'string' ||
        typeof sheet.truncated !== 'boolean' ||
        !Array.isArray(sheet.rows) ||
        sheet.rows.length > 200 ||
        !Array.isArray(sheet.merges)
      )
        return invalid();
      if (
        !['total_rows', 'total_columns'].every(
          (key) =>
            typeof sheet[key] === 'number' &&
            Number.isSafeInteger(sheet[key]) &&
            Number(sheet[key]) >= 0,
        )
      )
        return invalid();
      if (
        sheet.rows.some(
          (row) => !Array.isArray(row) || row.length > 50 || row.some((c) => typeof c !== 'string'),
        )
      )
        return invalid();
      if (
        sheet.merges.some(
          (m) =>
            !Array.isArray(m) ||
            m.length !== 4 ||
            m.some((n) => typeof n !== 'number' || !Number.isInteger(n)) ||
            m[0] < 0 ||
            m[1] < 0 ||
            m[2] < 1 ||
            m[3] < 1 ||
            m[0] + m[2] > 200 ||
            m[1] + m[3] > 50,
        )
      )
        return invalid();
    }
  } else if (!['text', 'image', 'pdf', 'unsupported'].includes(value.kind)) return invalid();
  return value as DocumentPreview;
}

export type DocumentLink = {
  href: string;
  label: string;
  binding: null | {
    id: number;
    revision: number;
    target: DocumentVersion;
    latest_number: number;
    inherited: boolean;
  };
};
export type DocumentLinks = {
  revision: number;
  source_version_id: number;
  editable: boolean;
  truncated: boolean;
  links: DocumentLink[];
};
export function linkKey(href: string): string {
  try {
    return decodeURIComponent(href);
  } catch {
    return href;
  }
}
export function parseLinks(value: unknown): DocumentLinks {
  if (
    !object(value) ||
    !positive(value.source_version_id) ||
    typeof value.revision !== 'number' ||
    !Number.isSafeInteger(value.revision) ||
    value.revision < 0 ||
    typeof value.editable !== 'boolean' ||
    typeof value.truncated !== 'boolean' ||
    !Array.isArray(value.links)
  )
    throw new Error('document_response_invalid');
  const links = value.links.map((entry: unknown): DocumentLink => {
    if (!object(entry) || typeof entry.href !== 'string' || typeof entry.label !== 'string')
      throw new Error('document_response_invalid');
    let binding: DocumentLink['binding'] = null;
    if (entry.binding !== null) {
      const b = entry.binding;
      if (
        !object(b) ||
        !positive(b.id) ||
        !positive(b.revision) ||
        !positive(b.latest_number) ||
        typeof b.inherited !== 'boolean'
      )
        throw new Error('document_response_invalid');
      const target = parseVersion(b.target);
      if (b.latest_number < target.number) throw new Error('document_response_invalid');
      binding = {
        id: b.id,
        revision: b.revision,
        latest_number: b.latest_number,
        inherited: b.inherited,
        target,
      };
    }
    return { href: entry.href, label: entry.label, binding };
  });
  return {
    revision: value.revision,
    source_version_id: value.source_version_id,
    editable: value.editable,
    truncated: value.truncated,
    links,
  };
}
const object = (v: unknown): v is Record<string, unknown> => isRecord(v, true);
const positive = (v: unknown): v is number =>
  typeof v === 'number' && Number.isSafeInteger(v) && v > 0;
export function parseVersion(v: unknown): DocumentVersion {
  if (
    !object(v) ||
    (v.deleted !== undefined && typeof v.deleted !== 'boolean') ||
    !positive(v.id) ||
    !positive(v.document_id) ||
    !positive(v.number) ||
    !positive(v.size) ||
    !['filename', 'extension', 'sha256', 'created_at', 'created_by'].every(
      (k) => typeof v[k] === 'string',
    )
  )
    throw new Error('document_response_invalid');
  return v as DocumentVersion;
}
export function parseLibrary(value: unknown): DocumentLibrary {
  if (
    !object(value) ||
    typeof value.revision !== 'number' ||
    !Number.isSafeInteger(value.revision) ||
    value.revision < 0 ||
    !Array.isArray(value.groups) ||
    !Array.isArray(value.documents)
  )
    throw new Error('document_response_invalid');
  const groups = value.groups.map((g: unknown) => {
    if (!object(g) || !positive(g.id) || typeof g.name !== 'string')
      throw new Error('document_response_invalid');
    return { id: g.id, name: g.name };
  });
  const documents = value.documents.map((d: unknown) => {
    if (
      !object(d) ||
      !positive(d.id) ||
      (d.group_id !== null && !groups.some((g) => g.id === d.group_id)) ||
      typeof d.position !== 'number' ||
      !Number.isSafeInteger(d.position)
    )
      throw new Error('document_response_invalid');
    const current = parseVersion(d.current);
    if (current.document_id !== d.id) throw new Error('document_response_invalid');
    return { id: d.id, group_id: d.group_id as number | null, position: d.position, current };
  });
  return { revision: value.revision, groups, documents };
}
export async function libraryRequest(path: string, options?: RequestInit & { timeoutMs?: number }) {
  return parseLibrary(await apiRequest<unknown>(path, options));
}
export function documentError(error: unknown, onSessionEnd: () => void) {
  return apiErrorMessage(error, onSessionEnd, {
    invalid_request: '请检查名称、文件或表单内容。',
    documents_changed: '资料已被其他操作更新，请重新加载后再操作。',
    document_group_duplicate: '分组名称已存在，请换一个名称。',
    document_group_not_found: '分组不存在，请重新加载。',
    document_deleted: '资料已删除，不能新增引用或修改；原有依据仍可查看。',
    document_not_found: '资料不存在或当前账号无权访问。',
    project_not_found: '项目不存在或你已不在该项目中。',
    document_format: '不支持此文件格式。',
    document_format_mismatch: '文件内容与格式不符，或文件已损坏。',
    document_empty: '不能上传空文件。',
    document_text_encoding: '文本编码无法识别，请另存为UTF-8后上传。',
    document_expansion_limit: '文件解压内容过大，无法安全处理。',
    document_storage_unavailable: '文件存储暂不可用，请稍后重试。',
    document_upload_conflict: '重复请求对应的文件不同，请重新选择文件。',
    document_order_boundary: '文件已在分组边界，请重新加载。',
    document_response_invalid: '资料响应异常，请重新加载。',
    document_links_require_markdown: '仅Markdown文档支持附件链接关联。',
    document_link_history_readonly: '该文档已成为历史版本，关联只读。请在当前版本中修改。',
    document_link_not_found: '原文中未找到此链接，请刷新预览后重试。',
    document_link_self: '不能关联到当前正在查看的同一文档版本。',
    document_links_inheritance_unverified:
      '新版超出链接解析范围，无法确认部分原有关联是否仍存在；本次未生成新版本，请先整理文档。',
  });
}

export type MaterialDeletion = {
  id: number;
  revision: number;
  name: string;
  kind: 'FILE' | 'DIRECTORY' | 'LINK' | 'GITHUB';
  versions: number;
  requirement_references: number;
  risk_report_references?: number;
  link_references: number;
};
export function parseMaterialDeletion(value: unknown): MaterialDeletion {
  if (
    !object(value) ||
    !positive(value.id) ||
    typeof value.name !== 'string' ||
    !['FILE', 'DIRECTORY', 'LINK', 'GITHUB'].includes(String(value.kind)) ||
    (value.risk_report_references !== undefined &&
      (typeof value.risk_report_references !== 'number' ||
        !Number.isSafeInteger(value.risk_report_references) ||
        value.risk_report_references < 0)) ||
    !['revision', 'versions', 'requirement_references', 'link_references'].every(
      (k) =>
        typeof value[k] === 'number' && Number.isSafeInteger(value[k]) && Number(value[k]) >= 0,
    )
  )
    throw new Error('document_response_invalid');
  return value as MaterialDeletion;
}
export function parseMaterialDeleted(value: unknown, id: number) {
  if (
    !object(value) ||
    value.id !== id ||
    typeof value.revision !== 'number' ||
    !Number.isSafeInteger(value.revision) ||
    value.revision < 0
  )
    throw new Error('document_response_invalid');
  return value;
}
