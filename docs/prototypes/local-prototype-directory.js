// Local directory prototype: browser demonstration only; no server or AI requests.
let lpdDraft = null;
const lpdBodies = new Map();
const lpdBaseView = viewPrototypes;
viewPrototypes = function () {
  return lpdBaseView().replace('<div class="head-actions">', '<div class="head-actions">' + btn(icon('folder') + '上传目录', 'lpd-add'));
};
const lpdBasePreview = prototypePreviewContent;
prototypePreviewContent = function (d) {
  if (d.type !== 'DIRECTORY') return lpdBasePreview(d);
  return `<section class="panel-pad lpd-files">${note('本地目录 · ' + esc(d.version) + ' · ' + (d.files || []).length + ' 个文件。原型仅在浏览器演示，不上传平台或调用AI。')}<p class="hint">每次上传保存一份完整新版本；历史版本及分析依据保留。点击目录展开，点击文件查看。</p>${lpdTree(d.files || [], false, d.id)}${btn('选择本次分析文件', 'lpd-analysis', d.id, 'small')}</section>`;
};
function lpdTree(files, selectable = true, id = '') {
  const root = new Map();
  for (const entry of files) {
    const path = typeof entry === 'string' ? entry : entry.path;
    let node = root;
    const parts = path.split('/');
    for (const [i, part] of parts.entries()) {
      if (i === parts.length - 1) node.set(part, path);
      else { if (!node.has(part)) node.set(part, new Map()); node = node.get(part); }
    }
  }
  function nodes(tree) {
    return [...tree.entries()].map(([name, node]) => typeof node === 'string'
      ? `<div class="lpd-file">${selectable ? `<label class="check"><input type="checkbox" name="lpdFile" value="${esc(node)}" checked><span>${esc(name)}</span></label>` : `<details><summary>${esc(name)}</summary><pre>${esc(lpdBodies.get(id + ':' + node) || '仅保存文件清单；重新选择目录可查看正文。')}</pre></details>`}</div>`
      : `<details class="lpd-folder"><summary>${selectable ? '<input type="checkbox" checked aria-label="选择目录" data-lpd-folder>' : ''}${esc(name)}/</summary>${nodes(node)}</details>`).join('');
  }
  return `<div class="lpd-tree">${nodes(root)}</div>`;
}
function lpdOpen(id = '') {
  const old = P().docs.find(d => d.id === id && !d.archived && !d.deletedAt);
  lpdDraft = { id: old?.id || '', name: old?.name || '', files: [], original: [] };
  openModal(old ? '上传目录新版本' : '上传本地目录', `<form id="lpdForm"><fieldset class="proto-form-section"><legend>资料信息</legend><div class="form-grid">${label('资料名称', inp('name', old?.name || '', '默认使用目录名', 'text', true))}${requirementSelect('资料分组', 'group', prototypeGroups().map(g => ({ value: g, label: g || '未分组' })), old?.group || '')}${label('页面 / 交互说明', '<textarea name="description" rows="2">' + esc(old?.description || '') + '</textarea>', 'span2')}</div></fieldset><fieldset class="proto-form-section"><legend>本地目录</legend><p class="hint">正式功能上传所选文件至平台，在项目内共享；本原型仅演示，不上传平台。新版保留历史。</p><input id="lpdPicker" type="file" webkitdirectory multiple hidden><div class="row">${btn('选择目录', 'lpd-pick', '', 'small')}${btn('载入虚构目录示例', 'lpd-demo', '', 'ghost small')}</div><div id="lpdFiles" class="mt"><p class="hint">尚未选择目录</p></div></fieldset></form>`, btn('取消', 'close') + btn('上传目录', 'lpd-save', '', 'primary'), true);
  document.getElementById('lpdPicker').onchange = async event => {
    const files = [...event.target.files];
    if (!files.length) return;
    const root = files[0].webkitRelativePath.split('/')[0];
    lpdDraft.original = files;
    const permitted = files.filter(f => /\.(html?|css|js|ts|jsx|tsx|vue|json|md|txt|svg|png|jpe?g|webp)$/i.test(f.name) && !f.webkitRelativePath.split('/').some(p => /^(\.env(?:\..*)?|\.git|\.ssh|\.aws|node_modules|dist|build|credentials\.json|secrets\.(json|ya?ml))$/i.test(p)));
    lpdDraft.files = permitted.map(f => ({ path: f.webkitRelativePath.slice(root.length + 1), size: f.size }));
    lpdDraft.name = root;
    document.getElementById('lpdForm').elements.name.value ||= root;
    document.getElementById('lpdFiles').innerHTML = `<p class="hint">${esc(root)} · ${permitted.length} 个可上传文件 · 已排除 ${files.length - permitted.length} 个不支持或敏感文件</p>${lpdTree(lpdDraft.files)}<div class="row mt">${btn('全选', 'lpd-all', '', 'small')}${btn('清空', 'lpd-clear', '', 'ghost small')}</div>`;
  };
}
function lpdSave(form, selected) {
  if (!lpdDraft || !selected.length) return error('请至少选择一个可上传的文件');
  const old = P().docs.find(d => d.id === lpdDraft.id);
  const id = 'proto-dir-' + crypto.randomUUID();
  const files = lpdDraft.files.filter(f => selected.includes(f.path));
  if (files.length !== selected.length || !form.name.trim()) return error('请核对名称及所选文件');
  const number = old ? Number(old.directoryVersion || 1) + 1 : 1;
  const value = { id, documentId: old ? docRoot(old) : id, name: form.name.trim(), group: old?.group || form.group || '', description: form.description || '', type: 'DIRECTORY', materialKind: 'prototype', version: 'v' + number, directoryVersion: number, files, size: files.reduce((n, f) => n + f.size, 0) + ' B', createdAt: new Date().toLocaleString(), order: old?.order ?? P().docs.length };
  if (old) old.archived = true;
  P().docs.push(value);
  for (const file of lpdDraft.original) {
    const path = file.webkitRelativePath.split('/').slice(1).join('/');
    if (selected.includes(path) && !/\.(png|jpe?g|webp)$/i.test(path)) file.text().then(text => lpdBodies.set(id + ':' + path, text));
  }
  selectedPrototype = id;
  lpdDraft = null;
  save(); closeModal(); render();
  toast('目录版本演示已保存；未上传平台或调用AI');
  return value;
}
document.addEventListener('change', event => {
  if (!event.target.matches('[data-lpd-folder]')) return;
  event.target.closest('details').querySelectorAll('input[type="checkbox"]').forEach(input => input.checked = event.target.checked);
});
document.addEventListener('click', event => {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const action = button.dataset.action, id = button.dataset.id || '';
  const target = P().docs.find(d => d.id === id);
  if (action === 'proto-update' && target?.type === 'DIRECTORY') {
    event.preventDefault(); event.stopImmediatePropagation(); lpdOpen(id); return;
  }
  if (!action.startsWith('lpd-')) return;
  event.preventDefault(); event.stopImmediatePropagation();
  if (action === 'lpd-add') lpdOpen();
  if (action === 'lpd-pick') document.getElementById('lpdPicker').click();
  if (action === 'lpd-demo') {
    lpdDraft.files = [{ path: 'pages/订单.html', size: 840 }, { path: 'assets/annotations.js', size: 250 }, { path: 'assets/style.css', size: 320 }];
    document.getElementById('lpdForm').elements.name.value ||= '订单原型（虚构目录）';
    document.getElementById('lpdFiles').innerHTML = lpdTree(lpdDraft.files) + '<p class="hint">虚构示例，只演示目录结构和文件勾选。</p>';
  }
  if (action === 'lpd-all' || action === 'lpd-clear') document.getElementById('lpdFiles').querySelectorAll('input').forEach(input => input.checked = action === 'lpd-all');
  if (action === 'lpd-save') { const form = formData('lpdForm'); if (form) lpdSave(form, [...document.querySelectorAll('[name=lpdFile]:checked')].map(i => i.value)); }
  if (action === 'lpd-analysis' && target) openModal('选择分析文件 · ' + esc(target.name), note('固定目录版本 ' + esc(target.version) + '；仅勾选文件用于本次分析。这里只演示选材，不调用AI。') + lpdTree(target.files), btn('取消', 'close') + btn('确认文件范围', 'lpd-analysis-save', '', 'primary'), true);
  if (action === 'lpd-analysis-save') { const count = document.querySelectorAll('[name=lpdFile]:checked').length; if (!count) return error('请至少选择一个文件'); closeModal(); toast('演示已选择 ' + count + ' 个固定版本文件；未调用AI'); }
}, true);
if (page === 'prototypes') render();
