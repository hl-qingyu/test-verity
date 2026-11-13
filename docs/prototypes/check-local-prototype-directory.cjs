const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const paths=process.argv.slice(2);
if(!paths.length)paths.push('outputs/prototype-pending/verity-prototype.html');
for(const path of paths){
  const html=fs.readFileSync(path,'utf8');
  for(const m of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g))new vm.Script(m[1]);
  const script=html.match(/<script id="local-prototype-directory">([\s\S]*?)<\/script>/)[1];
  const context=vm.createContext({assert,crypto:require('node:crypto').webcrypto,Map,Date,console});
  vm.runInContext(`let p={docs:[]},page='prototypes',selectedPrototype='',lastError='',modal='';const P=()=>p,docRoot=d=>d.documentId||d.id,esc=s=>String(s).replaceAll('<','&lt;'),btn=(label,action)=>'<button data-action="'+action+'">'+label+'</button>',icon=()=>'',note=s=>s;function viewPrototypes(){return '<div class="head-actions"></div>'}function prototypePreviewContent(){return 'old'}function render(){}function toast(){}function save(){}function closeModal(){}function error(m){lastError=m}function openModal(t,b){modal=t+b}const document={addEventListener(){}};${script}`,context);
  vm.runInContext(`
    assert.match(viewPrototypes(),/上传目录/);
    lpdDraft={id:'',files:[{path:'pages/a.html',size:10},{path:'assets/notes.js',size:20}],original:[]};
    assert.equal(lpdSave({name:'目录',group:'',description:''},[]),undefined);assert.equal(p.docs.length,0);
    const first=lpdSave({name:'目录',group:'',description:'说明'},['pages/a.html']);assert.equal(first.files.length,1);assert.equal(first.version,'v1');
    lpdDraft={id:first.id,files:[{path:'new.html',size:12}],original:[]};const next=lpdSave({name:'目录',group:'',description:''},['new.html']);
    assert.equal(first.archived,true);assert.equal(next.documentId,first.id);assert.equal(next.version,'v2');assert.equal(first.files[0].path,'pages/a.html');
    assert.match(prototypePreviewContent(next),/new.html/);assert.match(prototypePreviewContent(next),/未调用AI|不上传平台或调用AI/);
    assert.match(lpdTree([{path:'a/<unsafe>.html'}]),/&lt;unsafe>/);
  `,context);
  console.log('Local directory prototype: upload, selection, immutable versions and preview passed: '+path);
}
