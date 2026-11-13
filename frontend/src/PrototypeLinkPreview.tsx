import { useState } from 'react';
import { CaseDialog } from './CaseDialog';
import { prototypeUrl } from './prototypeApi';

export function PrototypeLinkPreview({ name, url }: { name: string; url: string }) {
  const [load, setLoad] = useState(0),
    [expanded, setExpanded] = useState(false);
  const target = prototypeUrl(url),
    sameOrigin = target && new URL(target).origin === location.origin;
  const external = target && (
    <a
      className="action small"
      href={target}
      target="_blank"
      rel="noopener noreferrer"
      referrerPolicy="no-referrer"
    >
      新窗口打开 ↗
    </a>
  );
  const frame = (key: string) =>
    target && !sameOrigin ? (
      <iframe
        key={key}
        className="prototype-link-frame"
        title={`${name} · 实时原型预览`}
        src={target}
        sandbox="allow-scripts allow-same-origin allow-popups allow-downloads"
        referrerPolicy="no-referrer"
      />
    ) : (
      <p className="hint">本站链接请在新窗口打开。</p>
    );
  return (
    <>
      <div className="panel-pad">
        <div className="row mb">
          <button
            className="primary small"
            disabled={!target || !!sameOrigin}
            onClick={() => setLoad((v) => v + 1)}
          >
            {load ? '刷新预览' : '加载预览'}
          </button>
          <button
            className="small"
            disabled={!target || !!sameOrigin}
            onClick={() => setExpanded(true)}
          >
            放大查看
          </button>
          {external}
        </div>
        <p className="hint prototype-url">{url}</p>
        {load ? (
          frame(String(load))
        ) : (
          <div className="empty">
            <h3>原型链接预览</h3>
            <p>点击加载后访问原网站，展示其页面树、画面与批注。</p>
          </div>
        )}
        <p className="hint mt">
          实时网页 ·
          未保存页面快照。若空白、被限制或需要登录，请使用新窗口打开；平台不会自动抓取或发送页面给
          AI。
        </p>
      </div>
      {expanded && (
        <CaseDialog
          title={`${name} · 实时预览`}
          busy={false}
          onClose={() => setExpanded(false)}
          wide
          className="prototype-link-dialog"
        >
          {frame('expanded')}
          <div className="row mt">
            {external}
            <button onClick={() => setExpanded(false)}>关闭</button>
          </div>
          <p className="hint">未保存页面快照；外站可能限制内嵌显示。</p>
        </CaseDialog>
      )}
    </>
  );
}
