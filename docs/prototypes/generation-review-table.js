// Generation review table prototype: reuses existing review/validation, synthetic data only.
const CG_PAGE_SIZE=20;
let cgHistoryOpen=true,cgScopeOpen=false,cgEvidenceKey='',cgTextQuery='',cgScopeReturn='cgScopeToggle';
const cgExpandedRows=new Set(),cgCollapsedGroups=new Set();
function cgViewKey(key) { return P().id+'|'+cgActive()?.id+'|'+key; }
function cgTableRender(focusId='') {
 const area=document.querySelector('.cg-table-scroll'),top=area?.scrollTop||0,left=area?.scrollLeft||0,y=globalThis.scrollY||0;
 const active=document.activeElement,action=active?.dataset?.action,id=active?.dataset?.id,selected=active?.dataset?.cgSelect;
 render();
 const next=document.querySelector('.cg-table-scroll');if(next){next.scrollTop=top;next.scrollLeft=left;}
 if(typeof globalThis.scrollTo==='function')globalThis.scrollTo({top:y,behavior:'instant'});
 const controls=[...document.querySelectorAll('[data-action],[data-cg-select]')];
 const focus=focusId?document.getElementById(focusId):controls.find(el=>selected?el.dataset.cgSelect===selected:el.dataset.action===action&&el.dataset.id===id);
 focus?.focus({preventScroll:true});
}
function cgSearchSuggestions(input) {
 const start=input.selectionStart,end=input.selectionEnd;
 cgTextQuery=input.value;cgPage=1;cgTableRender('cgSuggestionSearch');
 document.getElementById('cgSuggestionSearch')?.setSelectionRange(start,end);
}
function cgTableProblem(s) {
 if(cgSuccess(s)||s.status==='已忽略')return '';
 if(s.failure)return s.failure.reason;
 if(s.blocked&&!s.resolved)return s.reason||'需人工核对冲突';
 const d=s.draft||s.design,missing=['title','steps','expected'].filter(k=>!d[k]?.trim());
 if(missing.length)return '待补充：'+missing.map(k=>({title:'标题',steps:'步骤',expected:'预期'})[k]).join('、');
 return cgValidateItem(P(),s,cgActive()?.materials||[]);
}
function cgTableCell(s,key) {
 const d=s.draft||s.design,changed=s.kind==='UPDATE'&&s.before&&s.before[key]!==d[key];
 const missing=['steps','expected'].includes(key)&&!d[key]?.trim();
 return `${changed?'<div class="cg-table-diff">已修改</div>':''}<div class="cg-table-value ${missing?'is-missing':''}">${esc(d[key]|| (missing?'必填内容待补充':'—'))}</div>${changed?`<details class="cg-table-old"><summary>查看固定旧值</summary><p>${esc(s.before[key]||'（空）')}</p></details>`:''}`;
}
function cgTableRow(s) {
 const d=s.draft||s.design,expanded=cgExpandedRows.has(cgViewKey(s.key)),problem=cgTableProblem(s),done=cgSuccess(s);
 return `<tr class="cg-table-row ${expanded?'is-expanded':''} ${cgSelection.has(s.key)?'is-selected':''} ${done?'is-done':''} ${problem?'is-problem':''}" data-cg-row="${esc(s.key)}">
 <td class="cg-select-cell"><input type="checkbox" data-cg-select="${esc(s.key)}" aria-label="选择建议 ${esc(s.key)}" ${cgSelection.has(s.key)?'checked':''} ${cgReady(s)?'':'disabled'}></td>
 <td><div class="cg-table-key"><span>${esc(s.key)}</span><span>${esc(d.priority||'未设优先级')}</span>${s.draft?'<span>已修订</span>':''}</div><strong class="cg-table-title">${esc(d.title||'标题待补充')}</strong><div class="cg-table-tags">${tag(CG_TYPES[s.kind],s.kind==='UPDATE'?'orange':'green')}${tag(done?'已入库':s.status,done?'green':problem?'orange':'')}${problem?tag('需处理','orange'):''}</div>${problem?`<p class="cg-table-problem">${esc(problem)}</p>`:''}</td>
 <td>${cgTableCell(s,'pre')}</td><td>${cgTableCell(s,'steps')}</td><td>${cgTableCell(s,'expected')}</td>
 <td><div class="cg-table-actions"><button type="button" class="link" data-action="cg-row-expand" data-id="${esc(s.key)}" aria-expanded="${expanded}" aria-controls="cg-more-${esc(s.key)}">${expanded?'收起全文':'展开全文'}</button>${btn('详情修订','cg-detail',s.key,'link')}<button type="button" class="link" id="cgEvidence-${esc(s.key)}" data-action="cg-evidence" data-id="${esc(s.key)}">固定依据 · ${s.evidence?.length||0}</button>${done?btn('应用记录','cg-applied',s.key,'link'):cgReady(s)&&s.kind!=='RETIRE'&&!problem?`<button type="button" class="cg-row-review" data-action="cg-row-review" data-id="${esc(s.key)}">审核入库</button>`:''}</div></td></tr>
 <tr class="cg-table-more" id="cg-more-${esc(s.key)}" ${expanded?'':'hidden'}><td colspan="6"><div class="cg-table-more-grid">${[['description','用例描述'],['module','功能模块'],['structure','功能结构'],['type','用例类型'],['data_requirements','测试数据要求'],['cleanup','清理要求'],['remark','备注'],['reason','建议说明']].map(([k,label])=>`<section><h4>${label}</h4><p>${esc((k==='reason'?s.reason:d[k])||'—')}</p></section>`).join('')}<div class="cg-more-basis"><span class="hint">${s.case_id?'目标用例 '+esc(s.case_id)+' · 固定 v'+s.base_version:'新增用例编号在确认入库后分配'} · ${s.evidence?.length||0}条固定来源</span>${btn('查看本条需求 / 原型摘录','cg-evidence',s.key,'link')}${btn('引用提问','cg-question',s.key,'link')}</div></div></td></tr>`;
}
function cgReviewTable(r,items) {
 const visible=items.slice((cgPage-1)*CG_PAGE_SIZE,cgPage*CG_PAGE_SIZE),groups=new Map();
 for(const s of visible){if(!groups.has(s.function))groups.set(s.function,[]);groups.get(s.function).push(s);}
 const body=[...groups].map(([name,rows])=>{const all=items.filter(s=>s.function===name),closed=cgCollapsedGroups.has(cgViewKey(name)),available=rows.some(cgBulkEligible);
 return `<tr class="cg-group-head"><td colspan="6"><div class="between"><button type="button" class="ghost small" data-action="cg-group-toggle" data-id="${esc(name)}" aria-expanded="${!closed}"><span class="cg-group-arrow" aria-hidden="true">${closed?'▸':'▾'}</span><strong>${esc(name)}</strong><small>本页 ${rows.length} / 共 ${all.length}条 · 待审阅 ${all.filter(s=>s.status==='待审阅').length} · 已入库 ${all.filter(cgSuccess).length}</small></button><button type="button" class="link small" data-action="cg-select-group" data-id="${esc(name)}" ${available?'':'disabled'}>选择本组（本页）</button></div></td></tr>${closed?'':rows.map(cgTableRow).join('')}`;}).join('');
 return `<div class="cg-mobile-table-note">可横向滚动查看前置条件、步骤和预期；展开全文后在当前行连续阅读。</div><div class="cg-table-scroll" tabindex="0" aria-label="用例审阅表格，可横向滚动"><table class="cg-review-table"><caption class="screen-reader">按功能分组的用例建议，展开查看全文，勾选后批量审核</caption><colgroup><col style="width:4%"><col style="width:21%"><col style="width:16%"><col style="width:23%"><col style="width:24%"><col style="width:12%"></colgroup><thead><tr><th scope="col" class="cg-select-cell">选择</th><th scope="col">用例 / 状态</th><th scope="col">前置条件</th><th scope="col">操作步骤</th><th scope="col">预期结果</th><th scope="col">操作</th></tr></thead><tbody>${body||'<tr><td colspan="6">'+empty('没有匹配建议','调整筛选或搜索条件；没有结果不代表未读范围已覆盖。')+'</td></tr>'}</tbody></table></div>`;
}
function cgWorkbenchToolbar(r) {
 return `<div class="cg-workspace-toolbar"><div class="row"><button type="button" id="cgHistoryToggle" data-action="cg-history-toggle" aria-expanded="${cgHistoryOpen}" aria-controls="cgHistoryPanel">${icon('list')}生成记录 · ${cgRecords().length}</button><span class="hint">按功能连续审阅 · 勾选后批量审核</span></div><button type="button" id="cgScopeToggle" data-action="cg-scope-toggle" aria-expanded="${cgScopeOpen}" aria-controls="cgScopePanel">${icon('file')}固定依据与范围 · ${r?.materials.length||0}</button></div>`;
}
function cgScopeDrawer(r) {
 const s=r?.suggestions.find(s=>s.key===cgEvidenceKey);
 return `<aside id="cgScopePanel" class="panel code-analysis-context cg-scope-drawer" aria-label="固定依据与范围" ${cgScopeOpen?'':'hidden'}><div class="cg-drawer-head"><h2>${s?'本条固定依据':'固定依据与范围'}</h2><button type="button" id="cgScopeClose" class="ghost small" data-action="cg-scope-close" aria-label="关闭依据侧栏">×</button></div>${s?`<p class="cg-drawer-subtitle">${esc(s.key)} · ${esc((s.draft||s.design).title)}</p>${cgEvidence(s)}${btn('查看记录完整范围','cg-scope-all','','small')}`:cgScope(r)}</aside>`;
}
function cgBatchConfirmRender() {
 const items=cgPreview.items,problems=items.filter(i=>cgReviewProblem(i)),reuse=items.filter(i=>cgReviewDecision(i).action==='reuse').length;
 modalContext={type:'cg-preview',project:P().id,record:cgActive().id};
 openModal('确认批量入库',`<p>确认将所选的 <strong>${items.length}</strong> 条用例审核入库？</p>${reuse?`<p class="hint mt">其中 ${reuse} 条关联复用已有用例，保留原设计和测试记录。</p>`:''}${problems.length?`<p class="form-error mt" role="alert">${problems.length} 条需处理：${esc(cgReviewProblem(problems[0]))}。请返回表格修订或调整勾选后重试。</p>`:''}`,btn('取消','cg-review-close')+`<button type="button" class="primary" data-action="cg-batch-confirm" ${problems.length||!items.length?'disabled':''}>确认</button>`,false);
 document.getElementById('dialog')?.classList.add('cg-batch-confirm-dialog');
}
function cgTableAction(action,id) {
 if(action==='cg-preview'){cgPreviewOpen([...cgSelection],true);return true;}
 if(action==='cg-batch-confirm'){
  if(!cgReview?.simpleConfirm||modalContext?.type!=='cg-preview'||!cgPreview?.items.length||cgPreview.items.some(i=>cgReviewProblem(i)))return true;
  cgReview.confirmed=true;cgApply();return true;
 }
 if(action==='cg-history-toggle'){cgHistoryOpen=!cgHistoryOpen;cgTableRender('cgHistoryToggle');return true;}
 if(action==='cg-scope-toggle'){cgScopeOpen=!cgScopeOpen;cgEvidenceKey='';cgScopeReturn='cgScopeToggle';cgTableRender(cgScopeOpen?'cgScopeClose':'cgScopeToggle');return true;}
 if(action==='cg-scope-close'){cgScopeOpen=false;cgTableRender(cgScopeReturn);return true;}
 if(action==='cg-scope-all'){cgEvidenceKey='';cgTableRender('cgScopeClose');return true;}
 if(action==='cg-evidence'){cgEvidenceKey=id;cgScopeReturn='cgEvidence-'+id;cgScopeOpen=true;cgTableRender('cgScopeClose');return true;}
 if(action==='cg-expand-page'){
  const rows=cgRows(cgActive()).slice((cgPage-1)*CG_PAGE_SIZE,cgPage*CG_PAGE_SIZE),allExpanded=rows.every(s=>cgExpandedRows.has(cgViewKey(s.key)));
  for(const s of rows)allExpanded?cgExpandedRows.delete(cgViewKey(s.key)):cgExpandedRows.add(cgViewKey(s.key));
  cgTableRender();return true;
 }
 if(action==='cg-row-expand'||action==='cg-group-toggle'){
  const set=action==='cg-row-expand'?cgExpandedRows:cgCollapsedGroups,key=cgViewKey(id);set.has(key)?set.delete(key):set.add(key);cgTableRender();return true;
 }
 if(action==='cg-select-group'){
  for(const s of cgRows(cgActive()).slice((cgPage-1)*CG_PAGE_SIZE,cgPage*CG_PAGE_SIZE))if(s.function===id&&cgBulkEligible(s))cgSelection.add(s.key);
  cgTableRender();return true;
 }
 if(action==='cg-row-review'){
  const r=cgActive(),s=r?.suggestions.find(s=>s.key===id);if(!s||!cgReady(s)||s.kind==='RETIRE'||cgTableProblem(s))return true;
  modalContext={type:'cg-table',project:P().id,record:r.id,key:id};cgSingleConfirmOpen(id);return true;
 }
 return false;
}
document.addEventListener('keydown',event=>{
 if(event.key==='Escape'&&cgScopeOpen&&!document.querySelector('dialog[open]')&&!document.querySelector('[popover]:popover-open')){event.preventDefault();cgScopeOpen=false;cgTableRender(cgScopeReturn);}
});
// End generation review table prototype.
