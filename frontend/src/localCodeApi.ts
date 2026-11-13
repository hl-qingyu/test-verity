import { apiRequest, apiErrorMessage } from './api/http';

export type LocalSource = {
  id: number;
  project_id: number;
  owner_id: number;
  client_id: string;
  name: string;
  directory_name: string;
  kind: string;
  version: number;
  created_at: string;
  updated_at: string;
};
export type SourceInput = Pick<
  LocalSource,
  'client_id' | 'name' | 'directory_name' | 'kind' | 'version'
>;
export const localKinds = [
  ['BACKEND', '后端'],
  ['WEB', '前端'],
  ['FLUTTER', '移动端'],
  ['PROTOTYPE', '原型'],
  ['OTHER', '其他'],
];

function parseSource(value: unknown): LocalSource {
  if (!value || typeof value !== 'object') throw new Error('invalid_response');
  const record = value as Record<string, unknown>;
  for (const key of ['id', 'project_id', 'owner_id', 'version']) {
    if (!Number.isSafeInteger(record[key]) || Number(record[key]) <= 0)
      throw new Error('invalid_response');
  }
  for (const key of ['client_id', 'name', 'directory_name', 'kind', 'created_at', 'updated_at']) {
    if (typeof record[key] !== 'string') throw new Error('invalid_response');
  }
  if (
    !localKinds.some(([kind]) => kind === record.kind) ||
    !/^[0-9a-f-]{36}$/i.test(String(record.client_id))
  )
    throw new Error('invalid_response');
  return record as LocalSource;
}

export async function listLocalSources(
  projectId: number,
  signal?: AbortSignal,
): Promise<LocalSource[]> {
  const result = await apiRequest<unknown>(`/api/projects/${projectId}/local-code`, { signal });
  if (!Array.isArray(result)) throw new Error('invalid_response');
  const sources = result.map(parseSource);
  if (sources.some((source) => source.project_id !== projectId))
    throw new Error('invalid_response');
  return sources;
}
export async function saveLocalSource(projectId: number, input: SourceInput): Promise<LocalSource> {
  const source = parseSource(
    await apiRequest(`/api/projects/${projectId}/local-code`, {
      method: 'POST',
      body: JSON.stringify({
        client_id: input.client_id,
        name: input.name,
        directory_name: input.directory_name,
        kind: input.kind,
        version: input.version,
      }),
    }),
  );
  if (source.project_id !== projectId || source.client_id !== input.client_id)
    throw new Error('invalid_response');
  return source;
}
export function bindingKey(userId: number, projectId: number, clientId: string): string {
  return `${userId}:${projectId}:${clientId}`;
}
export function localError(error: unknown, onSessionEnd: () => void): string {
  if (error instanceof DOMException) {
    if (error.name === 'AbortError') return '已取消，未保存新的读取记录。';
    if (error.name === 'NotAllowedError' || error.name === 'SecurityError')
      return '目录权限不可用，请在支持的浏览器中重新授权。';
    if (error.name === 'NotFoundError' || error.name === 'NotReadableError')
      return '文件在读取期间变化或无法读取，本次未保存。请刷新重试。';
  }
  return apiErrorMessage(error, onSessionEnd, {
    directory_unsupported:
      '当前浏览器不支持目录授权，请使用支持此功能的Chrome或Edge，通过HTTPS或本机地址访问。',
    directory_denied: '目录读取权限已失效，请点击“重新授权”后再读取。',
    directory_mismatch: '所选目录与原授权目录不同，请为新目录添加独立来源。',
    directory_too_large: '目录超过32层深度或路径长度上限，请选择更浅的目录。',
    directory_invalid_entry: '目录存在不安全的文件路径，本次未读取。',
    local_storage_unavailable: '浏览器本地存储不可用，请检查浏览器设置；尚未保存本次记录。',
    local_storage_full: '本地存储失败或空间不足，旧记录已保留，本次未保存。',
    local_read_conflict: '其他标签页已保存新记录，请重新读取后再保存。',
    local_file_changed: '文件在读取期间已修改，本次未保存，请重新读取。',
    local_history_missing: '本地历史数据缺失，无法覆盖旧记录，请重新关联目录。',
    local_code_changed: '目录配置已变化，请重新加载后编辑。',
    local_directory_duplicate: '当前项目中已关联此目录，请使用已有来源读取最新内容。',
    local_code_directory_changed: '不能把既有来源改为另一个目录，请新增目录来源。',
    project_not_found: '项目不存在或你已无权访问。',
    project_manager_required: '仅项目负责人或平台管理员可维护目录关联。',
    invalid_request: '请检查名称、目录名称和类型。',
  });
}
