import { apiErrorMessage, apiRequest } from './api/http';
import { connectionErrors } from './githubApi';
import { parseVersion } from './documentApi';
import type { DocumentGroup, DocumentVersion } from './documentApi';

export type PrototypeFile = { path: string; sha: string; size: number };
export type PrototypeSource = {
  id: number;
  kind: 'FILE' | 'DIRECTORY' | 'LINK' | 'GITHUB';
  name: string;
  description: string;
  group_id: number | null;
  position: number;
  url: string | null;
  repository_id: number | null;
  repository_name: string | null;
  github_id: number | null;
  branch: string | null;
  path: string | null;
  selected_paths: string[];
  latest_commit: string | null;
  checked_at: string | null;
  files: PrototypeFile[];
  current: DocumentVersion | null;
};
export type PrototypeLibrary = {
  revision: number;
  groups: DocumentGroup[];
  sources: PrototypeSource[];
};
export type PrototypeConnection = {
  id: number;
  name: string;
  repositories: { id: number; name: string; branch: string }[];
};
export type PrototypeScope = { commit: string; full_name: string; files: PrototypeFile[] };
export type PrototypeCheck = {
  changed: boolean;
  previous_commit: string | null;
  source: PrototypeSource;
};
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object';
const positive = (v: unknown): v is number =>
  typeof v === 'number' && Number.isSafeInteger(v) && v > 0;
const sha = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{40}$/.test(v);
function invalid(): never {
  throw new Error('prototype_response_invalid');
}
export function prototypeUrl(value: string): string {
  try {
    const u = new URL(value);
    return ['http:', 'https:'].includes(u.protocol) &&
      !u.username &&
      !u.password &&
      !/[\s\\]/.test(value)
      ? u.href
      : '';
  } catch {
    return '';
  }
}
function files(value: unknown): PrototypeFile[] {
  if (!Array.isArray(value)) return invalid();
  return value.map((v: unknown) => {
    if (
      !object(v) ||
      typeof v.path !== 'string' ||
      !sha(v.sha) ||
      typeof v.size !== 'number' ||
      !Number.isSafeInteger(v.size) ||
      v.size < 0
    )
      return invalid();
    return { path: v.path, sha: v.sha, size: v.size };
  });
}
export function parsePrototype(v: unknown): PrototypeSource {
  if (
    !object(v) ||
    !positive(v.id) ||
    !['FILE', 'DIRECTORY', 'LINK', 'GITHUB'].includes(String(v.kind)) ||
    typeof v.name !== 'string' ||
    typeof v.description !== 'string' ||
    (v.group_id !== null && !positive(v.group_id)) ||
    typeof v.position !== 'number' ||
    !Number.isSafeInteger(v.position)
  )
    return invalid();
  for (const k of ['url', 'repository_name', 'branch', 'path', 'checked_at'])
    if (v[k] !== null && typeof v[k] !== 'string') return invalid();
  for (const k of ['repository_id', 'github_id'])
    if (v[k] !== null && !positive(v[k])) return invalid();
  if (v.latest_commit !== null && !sha(v.latest_commit)) return invalid();
  if (!Array.isArray(v.selected_paths) || v.selected_paths.some((p) => typeof p !== 'string'))
    return invalid();
  const manifest = files(v.files),
    current = v.current === null ? null : parseVersion(v.current);
  if (['FILE', 'DIRECTORY'].includes(String(v.kind)) && (!current || current.document_id !== v.id))
    return invalid();
  if (v.kind === 'DIRECTORY' && current?.extension !== 'directory') return invalid();
  if (v.kind === 'LINK' && (typeof v.url !== 'string' || !prototypeUrl(v.url))) return invalid();
  if (
    v.kind === 'GITHUB' &&
    (!positive(v.repository_id) ||
      !positive(v.github_id) ||
      !v.branch ||
      typeof v.path !== 'string' ||
      !sha(v.latest_commit))
  )
    return invalid();
  return { ...v, files: manifest, current } as PrototypeSource;
}
export function parsePrototypeLibrary(v: unknown): PrototypeLibrary {
  if (
    !object(v) ||
    typeof v.revision !== 'number' ||
    !Number.isSafeInteger(v.revision) ||
    v.revision < 0 ||
    !Array.isArray(v.groups) ||
    !Array.isArray(v.sources)
  )
    return invalid();
  const groups = v.groups.map((g: unknown) => {
    if (!object(g) || !positive(g.id) || typeof g.name !== 'string') return invalid();
    return { id: g.id, name: g.name };
  });
  const sources = v.sources.map(parsePrototype);
  if (sources.some((s) => s.group_id !== null && !groups.some((g) => g.id === s.group_id)))
    return invalid();
  return { revision: v.revision, groups, sources };
}
export function parsePrototypeOptions(v: unknown): PrototypeConnection[] {
  if (!Array.isArray(v)) return invalid();
  return v.map((c: unknown) => {
    if (
      !object(c) ||
      !positive(c.id) ||
      typeof c.name !== 'string' ||
      !Array.isArray(c.repositories)
    )
      return invalid();
    const repositories = c.repositories.map((r: unknown) => {
      if (
        !object(r) ||
        !positive(r.id) ||
        typeof r.name !== 'string' ||
        typeof r.branch !== 'string'
      )
        return invalid();
      return { id: r.id, name: r.name, branch: r.branch };
    });
    return { id: c.id, name: c.name, repositories };
  });
}
export function parsePrototypeScope(v: unknown): PrototypeScope {
  if (!object(v) || !sha(v.commit) || typeof v.full_name !== 'string') return invalid();
  return { commit: v.commit, full_name: v.full_name, files: files(v.files) };
}
export function parsePrototypeCheck(v: unknown): PrototypeCheck {
  if (
    !object(v) ||
    typeof v.changed !== 'boolean' ||
    (v.previous_commit !== null && !sha(v.previous_commit))
  )
    return invalid();
  return {
    changed: v.changed,
    previous_commit: v.previous_commit,
    source: parsePrototype(v.source),
  };
}
export async function prototypeRequest(
  url: string,
  options?: RequestInit & { timeoutMs?: number },
) {
  return parsePrototypeLibrary(await apiRequest<unknown>(url, options));
}
export function prototypeError(error: unknown, onSessionEnd: () => void) {
  return apiErrorMessage(error, onSessionEnd, {
    ...connectionErrors,
    invalid_request: '请检查名称、链接、分支、目录和文件选择。',
    project_repository_not_found: '仓库不属于当前项目，请重新选择。',
    project_not_found: '项目不存在或当前账号无权访问。',
    prototype_not_found: '原型资料不存在或当前账号无权访问。',
    prototype_response_invalid: '原型资料响应异常，请重新加载。',
    prototype_kind_changed: '来源类型不匹配，请重新打开资料。',
    prototype_commit_changed: '分支已有新提交，请重新读取文件清单后保存。',
    prototype_files_changed: '所选文件已删除或超出目录，请编辑来源重新选择。',
    prototype_scope_invalid: '请填写有效分支及仓库内相对目录或文件路径。',
    prototype_scope_empty: '所选范围内没有可读取的原型代码文件。',
    prototype_tree_incomplete: 'GitHub未返回完整目录，本次读取未完成；请稍后重试或检查仓库。',
    documents_changed: '资料已被其他操作更新，请重新加载后操作。',
    document_group_duplicate: '分组名称已存在。',
    document_group_not_found: '分组不存在或不属于原型资料。',
    document_not_found: '图片不存在或不属于当前资料类别。',
    document_format: '原型文件支持 HTML、HTM、PNG、JPG、JPEG、WEBP，请使用对应上传入口。',
    document_format_mismatch: '文件内容与格式不符或文件已损坏。',
    document_empty: '不能上传空图片。',
    document_upload_conflict: '重复上传标识对应不同文件，请重新选择。',
    document_storage_unavailable: '文件存储暂不可用，请稍后重试。',
    document_order_boundary: '资料已在分组边界，请重新加载。',
    prototype_directory_unsupported: '当前浏览器未提供目录文件路径，请使用支持文件夹上传的浏览器。',
    prototype_directory_invalid: '目录清单、路径或文件内容不完整，请重新选择目录。',
    prototype_directory_selection_invalid: '请至少选择一个该固定版本内的文件。',
    prototype_directory_version_invalid: '目录版本不属于当前资料，请重新选择。',
    prototype_directory_file_changed: '固定目录文件完整性校验失败，本次未读取。',
    document_text_encoding: '目录中的文本编码无法识别，请另存为 UTF-8 后上传。',
    code_private_key_content: '所选文件包含私钥内容，请移除后重新上传。',
  });
}
