import { CachedNativeCliWorkspace } from './NativeCliWorkspace';
import { NativeResultReview } from './NativeResultReview';
import { generationBase, generationError } from './generationApi';

export function GenerationCliWorkspace({
  projectId,
  runId,
  onSessionEnd,
  onClose,
  open = true,
  label,
  reference,
  resultRevision,
  onSaveResult,
  onReviewResult,
}: {
  projectId: number;
  runId: string;
  onSessionEnd: () => void;
  onClose: () => void;
  open?: boolean;
  label?: string;
  reference?: string;
  resultRevision?: number;
  onSaveResult?: (id: string, requestId: string) => Promise<boolean>;
  onReviewResult?: (id: string) => void;
}) {
  const record = `${generationBase(projectId)}/${runId}`;
  const terminal = `/api/projects/${projectId}/analysis-terminal/generation/${runId}`;
  return (
    <CachedNativeCliWorkspace
      open={open}
      base={terminal}
      cancelInitial={`${record}/cancel`}
      cancelResume={(id) => `${terminal}/${id}/cancel`}
      initialCancelLabel="取消生成"
      workspaceTitle="用例生成历史对话"
      errorMessage={(error) => generationError(error, onSessionEnd)}
      onClose={onClose}
      label={label}
      reference={reference}
      reviewLabel="查看或手动保存 CLI 结果"
      renderResults={
        onSaveResult ? (
          <NativeResultReview
            base={terminal}
            resultRevision={resultRevision}
            onSessionEnd={onSessionEnd}
            onSave={onSaveResult}
            onReview={onReviewResult}
          />
        ) : undefined
      }
    />
  );
}
