import { createGuards } from './api/guards';
export type NativeSession = {
  id: number;
  status: string;
  error_code: string;
  kind?: 'chat' | 'generation';
  epoch?: string;
  turn_status?: 'running' | 'completed' | 'failed' | 'interrupted';
  turn_error?: string;
  replay_rows?: number;
  replay_cols?: number;
  resumable?: boolean;
};
export function nativeSessionLabel(session: NativeSession | null) {
  if (!session) return '尚未启动';
  if (session.turn_status === 'running' && !['QUEUED', 'RUNNING'].includes(session.status))
    return 'CLI 进程已结束';
  if (session.turn_status) {
    const labels = {
      running: '正在分析',
      completed: '本轮已完成',
      failed: '本轮已失败',
      interrupted: '本轮已中断',
    };
    const label = labels[session.turn_status];
    return session.turn_status !== 'running' && session.status === 'RUNNING'
      ? `${label} · CLI 等待输入`
      : label;
  }
  const statuses: Record<string, string> = {
    QUEUED: '排队中',
    RUNNING: session.kind === 'chat' ? '对话进程运行中' : '正在启动 CLI',
    COMPLETED: '已完成',
    FAILED: '执行失败',
    CANCELLED: '已停止',
  };
  return statuses[session.status] || session.status;
}
export function nativeTurnFailure(session: NativeSession | null) {
  if (session?.turn_status !== 'failed') return '';
  if (session.turn_error?.includes('stream closed before response.completed'))
    return '上游响应在完成前断开，CLI 本轮分析已失败。';
  return session.turn_error || 'CLI 本轮分析已失败，请查看终端错误记录。';
}
export function nativeSessionUrl(base: string, session: NativeSession) {
  return `${base}/${session.kind === 'generation' ? 'generation/' : ''}${session.id}`;
}
export function terminalEnabled(value: unknown) {
  return object(value).enabled === true;
}
const guards = createGuards('generation_response_invalid');
const object = guards.obj;

export function sessionResponse(value: unknown): NativeSession | null {
  const response = object(value);
  if (response.session === null) return null;
  const s = object(response.session);
  if (
    !Number.isSafeInteger(s.id) ||
    Number(s.id) <= 0 ||
    typeof s.status !== 'string' ||
    typeof s.error_code !== 'string' ||
    (s.kind !== undefined && s.kind !== 'chat' && s.kind !== 'generation') ||
    (s.epoch !== undefined && typeof s.epoch !== 'string') ||
    (s.resumable !== undefined && typeof s.resumable !== 'boolean') ||
    (s.turn_status !== undefined &&
      !['running', 'completed', 'failed', 'interrupted'].includes(String(s.turn_status))) ||
    (s.turn_error !== undefined && typeof s.turn_error !== 'string') ||
    (s.replay_rows !== undefined &&
      (!Number.isInteger(s.replay_rows) ||
        Number(s.replay_rows) < 8 ||
        Number(s.replay_rows) > 120)) ||
    (s.replay_cols !== undefined &&
      (!Number.isInteger(s.replay_cols) ||
        Number(s.replay_cols) < 20 ||
        Number(s.replay_cols) > 300))
  )
    throw Error('generation_response_invalid');
  return {
    id: Number(s.id),
    status: s.status,
    error_code: s.error_code,
    kind: s.kind as NativeSession['kind'],
    epoch: s.epoch as string | undefined,
    ...(s.resumable !== undefined ? { resumable: s.resumable as boolean } : {}),
    ...(s.turn_status !== undefined
      ? { turn_status: s.turn_status as NativeSession['turn_status'] }
      : {}),
    ...(s.turn_error !== undefined ? { turn_error: s.turn_error as string } : {}),
    ...(s.replay_rows !== undefined ? { replay_rows: s.replay_rows as number } : {}),
    ...(s.replay_cols !== undefined ? { replay_cols: s.replay_cols as number } : {}),
  };
}
export function terminalSocket(url: string, cursor = 0) {
  if (!Number.isSafeInteger(cursor) || cursor < 0) throw Error('generation_response_invalid');
  return new WebSocket(
    `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}${url}/socket?cursor=${cursor}`,
  );
}

export function parseTerminalFrame(raw: string) {
  const frame = object(JSON.parse(raw));
  if (frame.type === 'ready') return { type: 'ready' as const };
  if (frame.type === 'state') return { type: 'state' as const, session: sessionResponse(frame) };
  if (
    frame.type !== 'output' ||
    !Array.isArray(frame.chunks) ||
    frame.chunks.some((c: unknown) => typeof c !== 'string')
  )
    throw Error('generation_response_invalid');
  const resizes: { index: number; rows: number; cols: number }[] = [];
  if (frame.resizes !== undefined) {
    if (!Array.isArray(frame.resizes)) throw Error('generation_response_invalid');
    for (const value of frame.resizes) {
      const size = object(value);
      if (
        !Number.isInteger(size.index) ||
        Number(size.index) < 0 ||
        Number(size.index) >= frame.chunks.length ||
        !Number.isInteger(size.rows) ||
        Number(size.rows) < 8 ||
        Number(size.rows) > 120 ||
        !Number.isInteger(size.cols) ||
        Number(size.cols) < 20 ||
        Number(size.cols) > 300 ||
        (resizes.length && Number(size.index) < resizes[resizes.length - 1].index)
      )
        throw Error('generation_response_invalid');
      resizes.push({ index: Number(size.index), rows: Number(size.rows), cols: Number(size.cols) });
    }
  }
  return { type: 'output' as const, chunks: frame.chunks as string[], resizes };
}
