import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
export function CaseDialog({
  title,
  busy,
  onClose,
  children,
  wide = false,
  className = '',
  footer,
  sideControls,
}: {
  title: string;
  busy: boolean;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
  className?: string;
  footer?: ReactNode;
  sideControls?: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  const content = (
    <>
      <header className="doc-dialog-head">
        <h2>{title}</h2>
        <button
          className="ghost small"
          type="button"
          aria-label="关闭对话框"
          disabled={busy}
          onClick={onClose}
        >
          ×
        </button>
      </header>
      <div className="panel-pad">{children}</div>
      {footer}
    </>
  );
  return (
    <dialog
      ref={ref}
      className={`account-dialog case-dialog${wide ? ' wide' : ''} ${className}`}
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault();
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      {sideControls}
      {sideControls ? <div className="case-dialog-surface">{content}</div> : content}
    </dialog>
  );
}
