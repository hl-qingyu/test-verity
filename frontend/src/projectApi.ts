import { apiErrorMessage } from './api/http';
import { connectionErrors } from './githubApi';

const projectErrors: Record<string, string> = {
  project_delete_active: '项目仍有排队或执行中的任务，请等待结束或在对应模块取消后再删除。',
  ...connectionErrors,
  invalid_request: '项目信息不符合要求，请检查项目名称和负责人。',
  project_not_found: '项目不存在或当前账号无权访问。',
  project_manager_required: '仅项目负责人或平台管理员可以修改项目配置。',
  project_account_unavailable: '所选账号不存在或已停用。',
  project_changed: '项目配置已被修改，请刷新后再操作。',
  project_duplicate: '项目标识或当前项目的仓库关联已存在，请检查后重试。',
  project_owner_required: '不能移除项目负责人，请由管理员先变更负责人。',
  project_repository_not_found: '当前项目中没有这个仓库关联。',
  project_repository_in_use:
    '该仓库关联仍被原型资料或历史来源引用，不能删除。请先处理相关资料引用。',
};

export function requestError(error: unknown, onSessionEnd: () => void): string {
  return apiErrorMessage(error, onSessionEnd, projectErrors);
}
