import { AnalysisChat } from './AnalysisChat';
import type { PageChangeRecord } from './changeAnalysisPage';
import { changeError, changeErrors } from './changeAnalysisApi';

export function ChangeAnalysisChat({
  record,
  ...props
}: {
  record: PageChangeRecord;
  findingKey: string;
  onClearFinding: () => void;
  onSessionEnd: () => void;
}) {
  return (
    <AnalysisChat
      {...props}
      base={`/api/projects/${record.projectId}/change-analysis/${record.id}/chat`}
      allowed={record.status === 'COMPLETED' && !!record.structured}
      title={record.title}
      moduleName="变更分析"
      questionLabel="继续询问变更问题"
      unavailableText="需先完成或导入变更分析报告。"
      errorMessage={changeError}
      errors={changeErrors}
    />
  );
}
