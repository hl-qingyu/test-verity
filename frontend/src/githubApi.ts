import { apiErrorMessage } from './api/http';

export const connectionErrors: Record<string, string> = {
  invalid_request:
    '请检查字段格式。支持 ghp_ 开头的 Classic、github_pat_ 开头的 Fine-grained，以及旧版40位 Token。',
  invalid_password_envelope: '安全校验已失效，请重新提交。',
  github_token_required: '首次连接需要填写 Token。',
  github_new_owner_requires_token:
    '所属个人或组织已改变，请重新填写有访问权限的 Token，可以复用同一枚 Classic Token。',
  github_token_type_mismatch: 'Token 与所选访问方式不匹配，请选择对应方式或重新填写 Token。',
  github_token_invalid: 'Token 无效或已过期，请在 GitHub 核对。',
  github_owner_mismatch: '个人账号名称与 Token 对应的 GitHub 身份不一致。',
  github_access_denied: 'GitHub 拒绝访问。请核对仓库权限、组织审批、SSO授权和访问策略。',
  github_repository_unavailable:
    '仓库或分支不可访问。可能已改名、删除、未授权，或组织审批尚未完成。',
  github_empty_repository: '仓库尚无可读取的分支，请先在 GitHub 初始化仓库。',
  github_request_rejected: 'GitHub 不接受当前请求，请核对仓库和分支。',
  github_rate_limited: 'GitHub 请求受到限流，请稍后重试。',
  github_timeout: '等待 GitHub 响应超时，请稍后重试。',
  github_connection_failed: '无法连接 GitHub，请检查后端网络。',
  github_invalid_response: 'GitHub 返回的数据格式异常，本次操作未完成。',
  github_upstream_error: 'GitHub 返回异常，本次操作未完成。',
  github_operation_not_allowed: '该 GitHub 操作不在平台只读白名单中。',
  github_connection_not_found: '连接不存在或不属于当前账号。',
  github_connection_changed: '连接已被修改，请重新加载、测试并选择仓库。',
  github_retest_required: '测试结果已过期或连接信息已改变，请重新测试。',
  github_repository_not_allowed: '仓库不在当前账号连接的授权选择中。',
  github_key_storage_unavailable: '凭据存储不可用，请联系管理员。',
  admin_required: '仅平台管理员可执行此操作。',
  too_many_attempts: '操作过于频繁，请稍后重试。',
  service_unavailable: '服务暂不可用，请稍后重试。',
  origin_not_allowed: '当前访问地址未获允许。',
};

export function requestError(error: unknown, onSessionEnd: () => void): string {
  return apiErrorMessage(error, onSessionEnd, connectionErrors);
}

export type GitHubRepository = {
  github_id: number;
  full_name: string;
  default_branch: string;
  private: boolean;
  owner_type: 'User' | 'Organization';
};
export type GitHubConnection = {
  id: number;
  name: string;
  kind: 'personal' | 'organization' | 'automatic';
  token_type: 'classic' | 'fine_grained';
  resource_owner: string;
  github_login: string;
  version: number;
  has_token: boolean;
  repositories: GitHubRepository[];
};

export type ProbeResult = {
  github_login: string;
  repositories: GitHubRepository[];
  receipt: string;
  has_more: boolean;
  page: number;
};
export function parseProbeResult(value: unknown): ProbeResult {
  if (
    !value ||
    typeof value !== 'object' ||
    !('github_login' in value) ||
    typeof value.github_login !== 'string' ||
    !('receipt' in value) ||
    typeof value.receipt !== 'string' ||
    !('has_more' in value) ||
    typeof value.has_more !== 'boolean' ||
    !('page' in value) ||
    !Number.isInteger(value.page) ||
    !('repositories' in value) ||
    !Array.isArray(value.repositories) ||
    !value.repositories.every((repo: unknown) => {
      if (!repo || typeof repo !== 'object') return false;
      return (
        'github_id' in repo &&
        Number.isInteger(repo.github_id) &&
        Number(repo.github_id) > 0 &&
        'full_name' in repo &&
        typeof repo.full_name === 'string' &&
        /^[A-Za-z0-9][A-Za-z0-9-]*\/[A-Za-z0-9_.-]+$/.test(repo.full_name) &&
        'default_branch' in repo &&
        typeof repo.default_branch === 'string' &&
        'private' in repo &&
        typeof repo.private === 'boolean' &&
        'owner_type' in repo &&
        (repo.owner_type === 'User' || repo.owner_type === 'Organization')
      );
    })
  )
    throw new Error('github_invalid_response');
  return value as ProbeResult;
}
export function groupRepositories(repos: GitHubRepository[]): [string, GitHubRepository[]][] {
  const groups = new Map<string, GitHubRepository[]>();
  for (const repo of repos) {
    const key = `${repo.owner_type === 'Organization' ? '组织' : '个人'} · ${repo.full_name.split('/')[0]}`;
    groups.set(key, [...(groups.get(key) || []), repo]);
  }
  return [...groups];
}
