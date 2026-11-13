import { useEffect, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';

type Material = { id: number; name: string; group_id: number | null };
type DragView = {
  id: number;
  name: string;
  x: number;
  y: number;
  target: number | null | undefined;
};

export function useMaterialDrag({
  projectId,
  disabled,
  onMove,
}: {
  projectId: number | undefined;
  disabled: boolean;
  onMove: (id: number, group: number | null) => void;
}) {
  const [dragView, setDragView] = useState<DragView | null>(null);
  const drag = useRef<
    | (Material & { projectId: number; pointerId: number; x: number; y: number; moved: boolean })
    | null
  >(null);
  const suppressClick = useRef(false);
  function cancel() {
    if (drag.current?.moved) suppressClick.current = true;
    drag.current = null;
    setDragView(null);
  }
  useEffect(
    () => () => {
      drag.current = null;
    },
    [projectId],
  );
  function targetGroup(x: number, y: number): number | null | undefined {
    const element = document.elementFromPoint(x, y)?.closest<HTMLElement>('[data-material-group]');
    if (!element || element.dataset.materialProject !== String(projectId)) return undefined;
    if (element.dataset.materialGroup === 'none') return null;
    const id = Number(element.dataset.materialGroup);
    return Number.isSafeInteger(id) && id > 0 ? id : undefined;
  }
  function pointerDown(e: ReactPointerEvent<HTMLDivElement>, material: Material) {
    suppressClick.current = false;
    if (
      disabled ||
      !projectId ||
      e.button !== 0 ||
      (e.target as HTMLElement).closest('input,.doc-order')
    )
      return;
    drag.current = {
      ...material,
      projectId,
      pointerId: e.pointerId,
      x: e.clientX,
      y: e.clientY,
      moved: false,
    };
  }
  function pointerMove(e: ReactPointerEvent<HTMLDivElement>) {
    const state = drag.current;
    if (!state || state.pointerId !== e.pointerId) return;
    if (disabled || state.projectId !== projectId) {
      cancel();
      return;
    }
    if (!state.moved && Math.hypot(e.clientX - state.x, e.clientY - state.y) < 7) return;
    if (!state.moved) e.currentTarget.setPointerCapture(e.pointerId);
    state.moved = true;
    setDragView({
      id: state.id,
      name: state.name,
      x: e.clientX,
      y: e.clientY,
      target: targetGroup(e.clientX, e.clientY),
    });
  }
  function pointerUp(e: ReactPointerEvent<HTMLDivElement>) {
    const state = drag.current;
    if (!state || state.pointerId !== e.pointerId) return;
    const target = targetGroup(e.clientX, e.clientY);
    suppressClick.current = state.moved;
    cancel();
    if (e.currentTarget.hasPointerCapture(e.pointerId))
      e.currentTarget.releasePointerCapture(e.pointerId);
    if (
      !disabled &&
      state.projectId === projectId &&
      state.moved &&
      target !== undefined &&
      target !== state.group_id
    )
      onMove(state.id, target);
  }
  return { dragView, suppressClick, pointerDown, pointerMove, pointerUp, cancel };
}
