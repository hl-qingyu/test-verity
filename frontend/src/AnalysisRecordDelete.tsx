import { useEffect, useRef, useState } from 'react';
import { apiRequest } from './api/http';
import { CaseDialog } from './CaseDialog';
import { Icon } from './Icon';

import { deletionErrors, parseDeletion } from './analysisDeletionApi';
import type { DeletionInfo } from './analysisDeletionApi';

export function AnalysisRecordDelete({
  base,
  id,
  projectId,
  refreshKey,
  canDelete,
  iconOnly = false,
  recordTitle,
  onDeleted,
  onSessionEnd,
}: {
  base: string;
  id: number | string;
  projectId: number;
  refreshKey?: string | number;
  canDelete?: boolean;
  iconOnly?: boolean;
  recordTitle?: string;
  onDeleted?: () => void;
  onSessionEnd: () => void;
}) {
  const [info, setInfo] = useState<DeletionInfo | null>(null),
    [open, setOpen] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [reload, setReload] = useState(0);
  const pending = useRef(false),
    controller = useRef<AbortController | null>(null),
    trigger = useRef<HTMLButtonElement | null>(null);
  const url = `${base}/${id}`;
  const checkKey = open ? null : refreshKey;
  const errorText = (e: unknown) => {
    const code = e instanceof Error ? e.message : '';
    if (code === 'not_authenticated') {
      onSessionEnd();
      return '登录已失效，请重新登录。';
    }
    return deletionErrors[code] || '删除结果尚未确认，请重新核对或刷新列表。';
  };
  const wasOpen = useRef(false);
  useEffect(() => {
    if (wasOpen.current && !open) trigger.current?.focus();
    wasOpen.current = open;
  }, [open]);
  useEffect(() => {
    if (canDelete !== undefined && (!open || !canDelete)) return;
    const c = new AbortController();
    controller.current = c;
    setInfo(null);
    setError('');
    apiRequest<unknown>(`${url}/deletion`, { signal: c.signal })
      .then((v) => parseDeletion(v, Number(id), projectId))
      .then((v) => {
        if (!c.signal.aborted) setInfo(v);
      })
      .catch((e) => {
        if (!c.signal.aborted) {
          if (e instanceof Error && e.message === 'not_authenticated') onSessionEnd();
          setError(
            deletionErrors[e instanceof Error ? e.message : ''] || '无法核对删除权限，请重试。',
          );
        }
      });
    return () => c.abort();
  }, [url, id, projectId, checkKey, reload, onSessionEnd, canDelete, open]);

  async function remove() {
    if (!info || info.active || !info.can_delete || pending.current) return;
    const c = controller.current;
    if (!c || c.signal.aborted) return;
    pending.current = true;
    setBusy(true);
    setError('');
    try {
      const value = await apiRequest<unknown>(`${url}/delete`, {
        method: 'POST',
        signal: c.signal,
        body: JSON.stringify({ confirmed: true, revision: info.revision }),
      });
      const o = value as { id?: number; project_id?: number; deleted?: boolean } | null;
      if (!o || o.id !== Number(id) || o.project_id !== projectId || o.deleted !== true)
        throw Error('analysis_delete_response_invalid');
      if (!c.signal.aborted) {
        setOpen(false);
        onDeleted?.();
        requestAnimationFrame(() => document.querySelector<HTMLElement>('main')?.focus());
      }
    } catch (e) {
      if (!c.signal.aborted) setError(errorText(e));
    } finally {
      pending.current = false;
      if (!c.signal.aborted) setBusy(false);
    }
  }
  if (canDelete === false || (info && !info.can_delete)) return null;
  return (
    <>
      <button
        ref={trigger}
        type="button"
        className={iconOnly ? 'ghost small analysis-record-delete' : 'danger small'}
        aria-label={iconOnly ? `删除分析记录：${recordTitle || info?.title || id}` : undefined}
        title={iconOnly ? `删除记录：${recordTitle || info?.title || id}` : undefined}
        disabled={busy || (canDelete === undefined && !info && !error)}
        onClick={() => {
          setOpen(true);
          setReload((v) => v + 1);
        }}
      >
        {iconOnly ? <Icon name="trash" /> : '删除记录'}
      </button>
      {open && (
        <CaseDialog title="确认删除分析记录" busy={busy} onClose={() => setOpen(false)}>
          {!info && !error && <p role="status">正在核对权限及关联任务…</p>}
          {info && (
            <>
              <p>确定删除「{info.title}」吗？</p>
              <p className="doc-note">
                删除后，项目成员均无法在分析列表查看此记录，概览和 AI
                结果验收统计同步移除。需求分析的关联任务与报告一并处理。
              </p>
              <p className="hint">
                原始输入、报告、对话与审计保留；已入库用例不受影响，暂不支持恢复。
              </p>
              {info.active && (
                <p className="form-error" role="alert">
                  {deletionErrors.analysis_delete_active}
                </p>
              )}
            </>
          )}
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <div className="row">
            <button disabled={busy} onClick={() => setOpen(false)}>
              取消
            </button>
            {error && (
              <button disabled={busy} onClick={() => setReload((v) => v + 1)}>
                重新核对
              </button>
            )}
            <button
              className="danger"
              disabled={busy || !info || info.active || !!error}
              onClick={() => void remove()}
            >
              {busy ? '正在删除…' : '确认删除'}
            </button>
          </div>
        </CaseDialog>
      )}
    </>
  );
}
