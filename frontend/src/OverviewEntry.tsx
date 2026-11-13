import { Link, useLocation } from 'react-router-dom';
import { useMemo } from 'react';
import type { ReactNode } from 'react';
import { overviewModules } from './overviewApi';
import type { OverviewModule } from './overviewApi';

export type OverviewTarget = {
  id: number;
  recordType: 'task' | 'report' | 'run';
  group: string;
  state: string;
};
const allowed: Record<OverviewModule, Record<string, string[]>> = {
  requirements: { risks: ['PENDING', 'NEEDS_INFO'] },
  generate: { suggestions: ['PENDING'], questions: ['PENDING'] },
  coverage: { findings: ['待确认', '已确认待处理'] },
  code: { findings: ['PENDING', 'CONFIRMED', 'NEEDS_EVIDENCE'] },
  changes: {
    impacts: ['PENDING', 'CONFIRMED', 'NEEDS_EVIDENCE'],
    regressions: ['PENDING', 'DEFERRED'],
  },
};
export function parseOverviewTarget(
  search: string,
  projectId: number | undefined,
  module: OverviewModule,
): OverviewTarget | null {
  const query = new URLSearchParams(search);
  if (!query.has('overview')) return null;
  if (query.get('overview') !== '1' || query.get('project') !== String(projectId))
    throw Error('该概览入口不属于当前项目，请重新选择。');
  const rawId = query.get('record') || '',
    id = Number(rawId),
    recordType = query.get('record_type') || '',
    group = query.get('group') || '',
    state = query.get('state') || '';
  const types =
    module === 'requirements'
      ? ['task', 'report']
      : ['generate', 'coverage'].includes(module)
        ? ['run']
        : ['task'];
  if (
    !/^[1-9]\d*$/.test(rawId) ||
    !Number.isSafeInteger(id) ||
    !types.includes(recordType) ||
    !!group !== !!state ||
    (group && !allowed[module][group]?.includes(state)) ||
    (module === 'requirements' && recordType === 'task' && group)
  )
    throw Error('概览入口已失效，请返回所属模块重新选择。');
  return { id, recordType: recordType as OverviewTarget['recordType'], group, state };
}
export function OverviewEntry({
  projectId,
  projectLoading = false,
  module,
  children,
}: {
  projectId: number | undefined;
  projectLoading?: boolean;
  module: OverviewModule;
  children: (target: OverviewTarget | null) => ReactNode;
}) {
  const { search, pathname } = useLocation();
  const parsed = useMemo(() => {
    try {
      return { target: parseOverviewTarget(search, projectId, module), error: '' };
    } catch (e) {
      return { target: null, error: (e as Error).message };
    }
  }, [search, projectId, module]);
  const target = parsed.target;
  if (projectLoading && new URLSearchParams(search).has('overview'))
    return (
      <section className="panel panel-pad" role="status">
        正在读取项目，稍后核对概览入口…
      </section>
    );
  if (parsed.error) {
    return (
      <section className="panel panel-pad" role="alert">
        <h1>无法打开概览目标</h1>
        <p>{parsed.error}</p>
        <div className="row mt">
          <Link className="action primary" to={pathname}>
            返回所属模块
          </Link>
          <Link className="action ghost" to="/">
            返回概览
          </Link>
        </div>
      </section>
    );
  }
  const clear = new URLSearchParams(search);
  clear.delete('group');
  clear.delete('state');
  const stateLabel =
    target?.state === 'PENDING'
      ? module === 'requirements'
        ? '待确认'
        : module === 'generate'
          ? target.group === 'questions'
            ? '有待澄清事项'
            : '有待审建议'
          : target.group === 'regressions'
            ? '待审阅'
            : '待处理'
      : (
          {
            NEEDS_INFO: '已确认待补充',
            CONFIRMED: '已确认',
            NEEDS_EVIDENCE: '需补充证据',
            DEFERRED: '暂缓',
          } as Record<string, string>
        )[target?.state || ''] || target?.state;
  return (
    <>
      {target && (
        <div className="ov-scope-note" role="status">
          <span>
            来自项目概览 · {overviewModules[module][0]} · 记录 {target.id}
            {stateLabel ? ` · ${stateLabel}` : ''}
          </span>
          <div className="row">
            <Link className="action ghost small" to={pathname}>
              查看模块全部记录
            </Link>
            {target.state && (
              <Link className="action ghost small" to={`${pathname}?${clear}`}>
                清除概览筛选
              </Link>
            )}
            <Link className="action ghost small" to="/">
              返回概览
            </Link>
          </div>
        </div>
      )}
      {children(target)}
    </>
  );
}
