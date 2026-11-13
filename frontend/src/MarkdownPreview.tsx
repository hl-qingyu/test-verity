import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ReactNode } from 'react';

export function MarkdownPreview({
  text,
  renderLink,
}: {
  text: string;
  renderLink?: (href: string, children: ReactNode) => ReactNode;
}) {
  return (
    <div className="markdown-preview">
      <Markdown
        remarkPlugins={[remarkGfm]}
        // URLs are identities for the picker only: a/img never emit href/src attributes.
        urlTransform={(url) => url}
        components={{
          a: ({ children, node }) =>
            renderLink && typeof node?.properties.href === 'string' ? (
              renderLink(node.properties.href, children)
            ) : (
              <span className="markdown-link-label" title="链接仅展示名称，暂不支持跳转">
                {children}
              </span>
            ),
          img: ({ alt }) => (
            <span className="markdown-image-label">[图片：{alt || '未提供说明'}，暂不加载]</span>
          ),
          table: ({ children }) => (
            <div className="markdown-table">
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {text}
      </Markdown>
    </div>
  );
}
