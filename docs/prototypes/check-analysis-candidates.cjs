const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const paths=process.argv.slice(2);if(!paths.length)paths.push('C:/Users/geekonup/Documents/Codex/2026-08-17/new-chat/outputs/verity-prototype.html','outputs/prototype-pending/verity-prototype.html');
for(const path of paths){
 const html=fs.readFileSync(path,'utf8'),start=html.indexOf('<!-- Shared analysis candidate review:');assert.ok(start>0);
 const block=html.slice(start).match(/<script>([\s\S]*?)<\/script>/)[1];assert.ok(!/\b(fetch|XMLHttpRequest|alert|confirm|prompt)\s*\(/.test(block));
 const project={},handlers=[],events={preventDefault(){},stopImmediatePropagation(){}};let modal='',message='',data={},saves=0;
 const context=vm.createContext({viewCode:()=>'<code/>',viewChanges:()=>'<changes/>',viewCoverage:()=>'<coverage/>',riskReportPage:()=>'<risks/>',cgQuestionsView:()=>'<questions/>',
 P:()=>project,btn:(name,action)=>`<button data-action="${action}">${name}</button>`,tag:t=>t,esc:x=>String(x).replaceAll('<','&lt;'),label:(t,c)=>t+c,
 openModal:(title,body,footer)=>modal=title+body+footer,closeModal:()=>{},toast:t=>message=t,error:t=>message=t,formData:()=>data,save:()=>saves++,document:{addEventListener:(type,handler)=>handlers.push(handler)}});
 vm.runInContext(block,context);
 for(const name of ['viewCode','viewChanges','viewCoverage','riskReportPage'])assert.match(context[name](),/候选与待处理问题/);
 assert.match(context.cgQuestionsView(),/其他有效建议可继续人工审核/);
 const click=action=>handlers[0]({...events,target:{closest:()=>({dataset:{action}})}});
 click('candidate-preview');assert.match(modal,/P2/);assert.match(modal,/P1/);
 click('candidate-save-draft');assert.equal(saves,0);assert.match(message,/处理说明/);
 data={candidate_json:'{"priority":"P1"}',reason:'人工保留P1'};click('candidate-save-draft');assert.equal(saves,1);assert.equal(project.analysisCandidateDrafts.length,1);
 click('candidate-preview');assert.match(modal,/P2/);assert.match(modal,/已保存1次人工修订/);
 console.log('PASS: shared candidate entry, both conflicting values, immutable original and reason-required manual history: '+path);
}
