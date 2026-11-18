// Analysis record deletion prototype: local synthetic data only.
function adDeleteRows(module) {
  return {
    requirements: P().riskReports || [],
    code: (P().tasks || []).filter((r) => r.module === 'code'),
    changes: P().changeAnalyses || [],
    generate: P().generationRecords || [],
    coverage: P().caseReviews || [],
  }[module] || [];
}
function adCanDelete(r) {
  return !!r && (admin() || S.role === '项目负责人' || [r.owner, r.actor, r.createdBy].includes(S.role));
}
function adActive(r) {
  const active = (x) => ['QUEUED', 'RUNNING', '排队中', '分析中', '生成中', '执行中'].includes(x.state || x.status);
  return active(r) || [...(r.batches || []), ...(r.chat || []), ...(r.applications || [])].some(active);
}
function adDeleteControl(module, r) {
  if (!r || r.deletedAt || !adCanDelete(r)) return '';
  if (module === 'requirements') return btn('删除记录', 'ad-delete', module + ':' + r.id, 'danger small');
  return `<button type="button" class="ghost small analysis-record-delete" data-action="ad-delete" data-id="${esc(module + ':' + r.id)}" aria-label="删除分析记录：${esc(r.title)}" title="删除记录：${esc(r.title)}">${icon('trash')}</button>`;
}
function adDeleteAction(action, identity) {
  const [module, ...parts] = identity.split(':'), id = parts.join(':'),
    r = adDeleteRows(module).find((x) => String(x.id) === id);
  if (!r || r.deletedAt || !adCanDelete(r)) return;
  if (action === 'ad-delete') {
    modalContext = { type: 'analysis-delete', module, id };
    openModal('确认删除分析记录',
      `<p>确定删除「${esc(r.title)}」吗？</p><p class="notice warn">删除后，项目成员均无法在分析列表查看此记录，概览和 AI 结果验收统计同步移除。需求分析的关联任务与报告一并处理。</p><p class="hint mt">原始输入、报告、对话与审计保留；已入库用例不受影响，暂不支持恢复。</p>${adActive(r) ? '<p class="inline-error mt">还有排队或执行中的任务，请先取消或等待结束。</p>' : ''}`,
      btn('取消', 'close') + (adActive(r) ? '' : btn('确认删除', 'ad-delete-confirm', identity, 'danger')));
    return;
  }
  if (action !== 'ad-delete-confirm' || adActive(r)) return;
  r.deletedAt = new Date().toISOString();
  r.deletedBy = S.role;
  (P().deletedAnalysisRecords ||= []).push({module, record: r});
  const rows = module === 'code' ? P().tasks : {requirements:P().riskReports, changes:P().changeAnalyses, generate:P().generationRecords, coverage:P().caseReviews}[module];
  rows.splice(rows.indexOf(r), 1);
  if (module === 'requirements') { riskView.report = ''; riskSourceFilter = ''; riskCurrentPage = 1; }
  if (module === 'code') { codeSelectedRecord = ''; }
  if (module === 'changes') { changeSelected = ''; changePage = 1; changeChatOpen = false; }
  if (module === 'generate') { cgSelected = ''; cgPage = 1; cgSelection.clear(); cgChatOpen = false; }
  if (module === 'coverage') { crSelected = ''; crPage = 1; }
  ovScope = null;
  closeModal(); save(); render();
  const main = document.getElementById('main');
  main?.setAttribute('tabindex', '-1'); main?.focus();
}
// End analysis record deletion prototype.
