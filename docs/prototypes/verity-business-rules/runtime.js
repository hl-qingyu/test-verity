/* Business annotations only: never intercept or submit a business action. */
(() => {
  const catalog = __VERITY_BUSINESS_RULES__;
  const host = document.createElement('aside');
  host.id = 'businessRules';
  host.setAttribute('aria-label', '页面与操作业务规则');
  host.setAttribute('popover', 'manual');
  host.innerHTML = `<header class="br-header"><div class="br-heading"><strong>业务规则</strong><span class="br-subtitle">填写要求和操作说明</span></div><button type="button" id="brToggle" aria-expanded="true" aria-controls="brBody">收起说明</button></header><div id="brBody"><div class="br-context" aria-live="polite"></div><label class="br-search">搜索本页说明<input type="search" placeholder="历史版本、重复用例、文件大小" aria-label="查找业务规则"></label><div class="br-toolbar"><button type="button" data-br-action="expand">全部展开</button><button type="button" data-br-action="collapse">全部收起</button><button type="button" data-br-action="current">当前操作</button></div><div class="br-current"></div><div class="br-catalog"></div><p class="br-foot">本原型仅作演示，不执行真实分析。</p></div>`;
  const body = host.querySelector('#brBody');
  const list = host.querySelector('.br-catalog');
  const search = host.querySelector('input');
  const toggle = host.querySelector('#brToggle');
  const states = new Map();
  const escape = (value) => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let contextKey = '', currentIds = [], pageKey = '', modalTitle = '', lastDialog = null;
  let collapsed = matchMedia('(max-width: 1000px)').matches;
  function setCollapsed(value) {
    collapsed = value;
    document.body.classList.toggle('rules-collapsed', value);
    host.classList.toggle('br-collapsed', value);
    toggle.textContent = value ? '业务说明' : '收起说明';
    toggle.setAttribute('aria-expanded', String(!value));
    body.hidden = value;
  }
  function score(entry, text, title) {
    const identities = text.split('|');
    return Math.max(0, ...entry.matches.filter(Boolean).map(word => {
      if (title === word) return 200 + word.length;
      if (title.includes(word)) return 100 + word.length;
      if (identities.includes(word)) return 50 + word.length;
      return 0;
    }));
  }
  function render() {
    const data = catalog[pageKey] || catalog.overview;
    const query = search.value.trim().toLocaleLowerCase();
    const entries = data.entries.filter(entry => !query || JSON.stringify([entry.title, entry.groups]).toLocaleLowerCase().includes(query));
    host.querySelector('.br-context').innerHTML = `<span>当前页面</span><strong>${escape(data.name)}</strong>${modalTitle ? `<span>当前操作</span><strong>${escape(modalTitle)}</strong>` : ''}`;
    host.querySelector('.br-current').textContent = modalTitle
      ? (currentIds.length ? '已展开当前操作的说明。' : '请在下方选择要查看的操作。')
      : `本页共${data.entries.length}项说明`;
    list.innerHTML = entries.map(entry => {
      const active = currentIds.includes(entry.id);
      const open = states.get(pageKey + ':' + entry.id) ?? (active || (!modalTitle && entry === data.entries[0]));
      return `<details class="br-entry${active ? ' br-active' : ''}" data-rule-id="${entry.id}" ${open ? 'open' : ''}><summary>${escape(entry.title)}${active ? '<span class="br-badge">当前操作</span>' : ''}</summary><div class="br-entry-body">${entry.groups.map(group => `<section><h4>${escape(group.title)}</h4><ul>${group.rules.map(rule => `<li>${escape(rule)}</li>`).join('')}</ul></section>`).join('')}</div></details>`;
    }).join('') || '<p class="br-empty">本页没有匹配的规则，请更换关键词。</p>';
  }
  function update() {
    // The host is moved into the topmost modal so it stays operable under modal inertness.
    const dialogs = [...document.querySelectorAll('dialog[open]')];
    const dialog = dialogs.at(-1) || null;
    const parent = dialog || document.body;
    if (host.parentElement !== parent) {
      if (host.matches(':popover-open')) host.hidePopover();
      parent.append(host);
      host.showPopover();
    } else if (!host.matches(':popover-open')) host.showPopover();
    document.querySelectorAll('dialog.br-has-rules').forEach(d => {
      if (d !== dialog) d.classList.remove('br-has-rules');
    });
    dialog?.classList.add('br-has-rules');
    // Never include the annotation tree itself in the modal's matching text.
    const title = dialog?.querySelector('#modalTitle, .modal-header h2, h2')?.textContent?.trim() || '';
    const forms = dialog ? [...dialog.querySelectorAll('form')].map(f => f.id).join('|') : '';
    const type = typeof modalContext === 'object' && modalContext ? modalContext.type || '' : '';
    const key = typeof page === 'string' && catalog[page] ? page : 'overview';
    const signature = [key, title, forms, dialog ? type : ''].join('|');
    if (contextKey === signature && lastDialog === dialog) return;
    const newPage = key !== pageKey;
    contextKey = signature;
    pageKey = key;
    modalTitle = title;
    lastDialog = dialog;
    if (newPage) search.value = '';
    const scored = catalog[key].entries.map(entry => ({ id: entry.id, score: score(entry, forms + '|' + type, title) }));
    const best = Math.max(0, ...scored.map(item => item.score));
    currentIds = dialog && best ? scored.filter(item => item.score === best).map(item => item.id) : [];
    currentIds.forEach(id => states.set(pageKey + ':' + id, true));
    render();
    host.querySelector('.br-active')?.scrollIntoView({ block: 'nearest' });
  }
  toggle.addEventListener('click', () => setCollapsed(!collapsed));
  search.addEventListener('input', render);
  list.addEventListener('toggle', event => {
    const entry = event.target;
    if (entry instanceof HTMLDetailsElement && entry.dataset.ruleId)
      states.set(pageKey + ':' + entry.dataset.ruleId, entry.open);
  }, true);
  host.addEventListener('click', event => {
    const action = event.target.closest('[data-br-action]')?.dataset.brAction;
    if (!action) return;
    if (action === 'current') {
      search.value = '';
      currentIds.forEach(id => states.set(pageKey + ':' + id, true));
      render();
      host.querySelector('.br-active')?.scrollIntoView({ block: 'nearest' });
      return;
    }
    for (const entry of list.querySelectorAll('.br-entry')) {
      entry.open = action === 'expand';
      states.set(pageKey + ':' + entry.dataset.ruleId, entry.open);
    }
  });
  // Batch changes and ignore annotation mutations, avoiding a self-triggered render loop.
  let scheduled = false;
  new MutationObserver(records => {
    if (records.every(record => record.target === host || host.contains(record.target))) return;
    if (scheduled) return;
    scheduled = true;
    queueMicrotask(() => { scheduled = false; update(); });
  }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['open'] });
  window.addEventListener('hashchange', update);
  setCollapsed(collapsed);
  update();
})();
