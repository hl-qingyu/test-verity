export type DeletionInfo = {
  id: number;
  project_id: number;
  title: string;
  revision: number | null;
  can_delete: boolean;
  active: boolean;
};
export const deletionErrors: Record<string, string> = {
  analysis_delete_forbidden:
    '仅记录发起人、项目负责人或管理员可以删除；共享报告还需拥有其关联记录的删除权限。',
  analysis_delete_active: '还有排队或执行中的分析、对话或入库任务，请先取消或等待结束。',
  analysis_delete_changed: '记录已变化，请重新核对后再删除。',
  analysis_record_deleted: '分析记录已删除，请刷新列表。',
  analysis_record_not_found: '分析记录不存在或当前无权访问。',
  project_not_found: '项目不存在或当前已无访问权限。',
};

export function parseDeletion(value: unknown, id: number, projectId: number): DeletionInfo {
  const o = value as DeletionInfo | null;
  if (
    !o ||
    o.id !== id ||
    o.project_id !== projectId ||
    typeof o.title !== 'string' ||
    typeof o.can_delete !== 'boolean' ||
    typeof o.active !== 'boolean' ||
    !(o.revision === null || (Number.isSafeInteger(o.revision) && o.revision > 0))
  )
    throw Error('analysis_delete_response_invalid');
  return o;
}
