import { useState } from 'react';
import type { User } from './Auth';
import type { Project } from './Projects';
import { AcceptanceSummary } from './AnalysisAcceptance';
import { FormSelect } from './FormSelect';

export function AIResultsAcceptance({
  user,
  projects,
  projectsLoading,
  onSelectProject,
  onSessionEnd,
}: {
  user: User;
  projects: Project[];
  projectsLoading: boolean;
  onSelectProject: (id: number) => void;
  onSessionEnd: () => void;
}) {
  const [projectId, setProjectId] = useState<number | null>(null);
  const project = projects.find((p) => p.id === projectId);
  if (user.platform_role !== 'ADMIN')
    return (
      <section className="panel panel-pad">
        <h1>无权访问</h1>
        <p>AI结果验收仅平台管理员可查看。</p>
      </section>
    );
  return (
    <div className="aa-page">
      <div className="page-head">
        <div>
          <h1>AI结果验收</h1>
        </div>
        <span className="badge">仅管理员</span>
      </div>
      <section className="panel aa-range" aria-label="汇总范围">
        <FormSelect
          label="汇总范围"
          value={projectId === null ? 'all' : String(projectId)}
          disabled={projectsLoading}
          options={[
            { value: 'all', label: '全部项目' },
            ...(!project && projectId !== null
              ? [{ value: String(projectId), label: '项目不可用', disabled: true }]
              : []),
            ...projects.map((p) => ({ value: String(p.id), label: p.name })),
          ]}
          onChange={(v) => setProjectId(v === 'all' ? null : Number(v))}
        />
        <div className="aa-range-description">
          <strong>{projectId === null ? '全部项目汇总' : project?.name || '项目不可用'}</strong>
          <p className="hint">按全部历史分析记录累计</p>
        </div>
        <span className="badge">全部历史</span>
      </section>
      <AcceptanceSummary
        key={`${user.id}:${projectId ?? 'all'}`}
        projectId={projectId}
        onSelectProject={onSelectProject}
        onSessionEnd={onSessionEnd}
      />
    </div>
  );
}
