import { AnalysisChat } from './AnalysisChat';
import type { CodeDetail } from './codeAnalysisApi';
import { codeError } from './codeAnalysisApi';

export function CodeAnalysisChat({
  record,
  ...props
}: {
  record: CodeDetail;
  findingKey: string;
  onClearFinding: () => void;
  onSessionEnd: () => void;
}) {
  return (
    <AnalysisChat
      {...props}
      base={`/api/projects/${record.project_id}/code-analysis/${record.id}/chat`}
      allowed={record.status === 'COMPLETED' && !!record.report}
      title={record.title}
      moduleName="代码分析"
      questionLabel="继续询问代码问题"
      unavailableText="需先完成或导入代码分析报告。"
      errorMessage={codeError}
    />
  );
}
