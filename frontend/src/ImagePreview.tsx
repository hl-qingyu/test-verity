import { useCallback, useEffect, useRef, useState } from 'react';
import { Icon } from './Icon';

export function imageZoom(current: number, factor: number) {
  return Math.min(400, Math.max(10, Math.round(current * factor)));
}

export function ImagePreview({
  url,
  name,
  onError,
}: {
  url: string;
  name: string;
  onError: () => void;
}) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  return (
    <div className="doc-image">
      <button
        ref={trigger}
        type="button"
        className="image-preview-trigger"
        aria-label={`查看大图：${name}`}
        title="点击查看大图"
        onClick={() => setOpen(true)}
      >
        <img src={url} alt={name} onError={onError} />
      </button>
      {open && (
        <ImageViewer
          url={url}
          name={name}
          onClose={() => {
            setOpen(false);
            requestAnimationFrame(() => trigger.current?.focus());
          }}
        />
      )}
    </div>
  );
}

function ImageViewer({ url, name, onClose }: { url: string; name: string; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null),
    viewport = useRef<HTMLDivElement>(null),
    picture = useRef<HTMLImageElement>(null);
  const [zoom, setZoom] = useState<number | null>(null),
    [size, setSize] = useState({ width: 0, height: 0 }),
    [failed, setFailed] = useState(false);
  const changeZoom = useCallback((factor: number) => {
    const img = picture.current,
      view = viewport.current;
    if (!img?.naturalWidth || !view) return;
    const fit =
      Math.min(view.clientWidth / img.naturalWidth, view.clientHeight / img.naturalHeight, 1) * 100;
    setZoom((value) => imageZoom(value ?? fit, factor));
  }, []);
  useEffect(() => {
    const modal = dialog.current;
    modal?.showModal();
    return () => modal?.close();
  }, []);
  useEffect(() => {
    const view = viewport.current;
    const wheel = (event: WheelEvent) => {
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        changeZoom(event.deltaY < 0 ? 1.25 : 0.8);
      }
    };
    view?.addEventListener('wheel', wheel, { passive: false });
    return () => view?.removeEventListener('wheel', wheel);
  }, [changeZoom]);
  return (
    <dialog
      ref={dialog}
      className="image-viewer"
      aria-label={`图片大图：${name}`}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onKeyDown={(event) => {
        if (['+', '=', '-'].includes(event.key)) {
          event.preventDefault();
          changeZoom(event.key === '-' ? 0.8 : 1.25);
        }
      }}
    >
      <header className="image-viewer-header">
        <strong>{name}</strong>
        <div className="image-viewer-controls">
          <button
            type="button"
            aria-label="缩小图片"
            disabled={failed || !size.width || zoom === 10}
            onClick={() => changeZoom(0.8)}
          >
            −
          </button>
          <output aria-live="polite">{zoom === null ? '适应窗口' : `${zoom}%`}</output>
          <button
            type="button"
            aria-label="放大图片"
            disabled={failed || !size.width || zoom === 400}
            onClick={() => changeZoom(1.25)}
          >
            ＋
          </button>
          <button type="button" disabled={failed || !size.width} onClick={() => setZoom(100)}>
            原尺寸
          </button>
          <button type="button" disabled={failed || !size.width} onClick={() => setZoom(null)}>
            适应窗口
          </button>
          <button type="button" aria-label="关闭大图" title="关闭（Esc）" onClick={onClose}>
            <Icon name="close" />
          </button>
        </div>
      </header>
      <div
        ref={viewport}
        className={`image-viewer-viewport${zoom === null ? ' fit' : ''}`}
        tabIndex={0}
        aria-label="图片查看区域，可滚动查看细节"
      >
        {failed ? (
          <p role="alert">图片无法显示，请关闭后下载原件查看。</p>
        ) : (
          <img
            ref={picture}
            src={url}
            alt={name}
            draggable={false}
            style={
              zoom !== null
                ? { width: (size.width * zoom) / 100, height: (size.height * zoom) / 100 }
                : undefined
            }
            onLoad={(event) =>
              setSize({
                width: event.currentTarget.naturalWidth,
                height: event.currentTarget.naturalHeight,
              })
            }
            onError={() => setFailed(true)}
          />
        )}
      </div>
      <footer>Ctrl / ⌘＋滚轮或＋ / − 缩放 · 放大后滚动查看 · Esc 关闭</footer>
    </dialog>
  );
}
