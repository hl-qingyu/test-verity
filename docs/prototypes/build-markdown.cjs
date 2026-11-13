// Keep the standalone total prototype on the same Markdown renderer as the real page.
const fs = require('node:fs');
const path = require('node:path');
const esbuild = require('../../frontend/node_modules/esbuild');

(async () => {
  const target = process.argv[2] || require('node:path').resolve(__dirname, '../../verity-prototype.html');
  const result = await esbuild.build({
    stdin: {
      contents: `import {createElement} from 'react'; import {renderToStaticMarkup} from 'react-dom/server'; import {MarkdownPreview} from './MarkdownPreview'; import {OfficePreview} from './OfficePreview';
window.renderVerityOffice = preview => renderToStaticMarkup(createElement(OfficePreview,{preview}));
window.renderVerityMarkdown = (text,sourceId) => renderToStaticMarkup(createElement(MarkdownPreview, {text,renderLink:sourceId?(href,children)=>createElement('span',{},createElement('button',{className:'markdown-link-button', 'data-action':'doc-link', 'data-id':JSON.stringify([sourceId,href])},children),createElement('small',{className:'hint'},' '+(window.verityLinkStatus?.(sourceId,href)||'待关联'))):undefined}));
window.verityMarkdownHrefs = text => {const hrefs=[]; renderToStaticMarkup(createElement(MarkdownPreview,{text,renderLink:(href,children)=>{hrefs.push(href);return children;}}));return hrefs;};`,
      resolveDir: path.resolve(__dirname, '../../frontend/src'),
      loader: 'tsx',
    },
    bundle: true, write: false, minify: true, format: 'iife', platform: 'browser',
    define: { 'process.env.NODE_ENV': '"production"' },
  });
  let html = fs.readFileSync(target, 'utf8');
  html = html.replace(/<script data-verity-markdown>[\s\S]*?<\/script>\n?/g, '');
  const bundle = result.outputFiles[0].text.replace(/<\/script/gi, '<\\/script');
  html = html.replace('<script>', () => `<script data-verity-markdown>${bundle}</script>\n<script>`);
  const css = fs.readFileSync(path.resolve(__dirname, '../../frontend/src/style.css'), 'utf8').split('/* Markdown preview: start */')[1].split('/* Markdown preview: end */')[0];
  html = html.replace(/<style data-verity-markdown>[\s\S]*?<\/style>\n?/g, '');
  const officeCss = fs.readFileSync(path.resolve(__dirname, '../../frontend/src/style.css'),'utf8').split('/* Office preview: start */')[1].split('/* Office preview: end */')[0];
  html = html.replace('</head>', () => `<style data-verity-markdown>${css}\n${officeCss}</style>\n</head>`);
  fs.writeFileSync(target, html);
  console.log('Total prototype Markdown renderer updated.');
})().catch(error => { console.error(error); process.exitCode = 1; });
