const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');
const {JSDOM}=require('jsdom');
const vm=require('node:vm');
const root=path.join(__dirname,'..','web');
const settle=async()=>{for(let i=0;i<15;i++)await new Promise(r=>setImmediate(r));};
function harness(hash='',ready=true,fixture={}){
 const dom=new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'),{url:'http://127.0.0.1:8421/'+hash,runScripts:'outside-only'});const w=dom.window;
 const errors=[];w.addEventListener('error',e=>errors.push(e.message));w.HTMLElement.prototype.scrollIntoView=function(){};
 const data={profile:{name:'测试',preferences:'',facts:'经历'},jobs:[{id:'a',title:'岗位A',company:'公司A'},{id:'b',title:'岗位B',company:'公司B'}],tasks:[{id:'resume-a',kind:'tailor_resume',job_id:'a',status:'done',created:1,result:{primary_output:'A的简历',markdown:'说明'}},{id:'interview-b',kind:'interview_prep',job_id:'b',status:'done',created:2,result:{primary_output:'B的面试卡',markdown:'说明'}}],...(fixture.data||{})};
 const controls={calls:[],responses:[],data,errors,company:fixture.company||null,research:fixture.research||{preview_id:'preview-test',company_name:'公司A',question:'主要做什么？',sources:[{url:'https://example.com/about',excerpt:'公司公开介绍摘录',source_type:'public_web_page',confidence:'unverified',observed_at:1}],facts:[],warnings:[]},hidden:false,now:undefined,holdState:false,holdTaskResult:false};Object.defineProperty(w.document,'hidden',{configurable:true,get:()=>controls.hidden});const nativeNow=w.Date.now.bind(w.Date);w.Date.now=()=>controls.now===undefined?nativeNow():controls.now;w.setInterval=fn=>{controls.poll=fn;return 1;};
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'));};
 const settings={ready,persona:'gentle',buddy_name:'小伴',personas:{gentle:{hello:'你好'},direct:{hello:'直接说判断。'}},provider:'api',...(fixture.settings||{})};
 controls.settings=settings;controls.connectionOK=true;
 const stateSummary=()=>({...data,tasks:data.tasks.map(task=>({...task,result:task.result?{summary:task.result.summary||'',decision:task.result.decision||''}:null}))});
 w.fetch=async(url,init)=>{const value=init?.body?JSON.parse(init.body):null;controls.calls.push([url,value,init]);const parsed=new URL(url,'http://127.0.0.1:8421');if(parsed.pathname==='/api/state'&&controls.holdState)return new Promise(resolve=>{controls.releaseState=()=>resolve({ok:true,json:async()=>stateSummary()});});if(parsed.pathname.startsWith('/api/task-result/')){const id=decodeURIComponent(parsed.pathname.slice('/api/task-result/'.length));const task=data.tasks.find(item=>item.id===id);if(controls.holdTaskResult)return new Promise(resolve=>{controls.releaseTaskResult=()=>resolve({ok:true,json:async()=>({task_id:id,updated:task?.updated,result:task?.result})});});const response={task_id:id,updated:task?.updated,result:task?.result};controls.responses.push([url,response]);return {ok:!!task,json:async()=>response};}let r={};
  if(url==='/api/session')r={token:'local-test',version:'0.10.0',execution:'codex-worker'};
  if(parsed.pathname==='/api/state'){r=stateSummary();controls.responses.push([url,r]);}
  if(url==='/api/companion')r=settings;
  if(url==='/api/search-test')r={ok:true,message:'本次搜索取得固定公司来源'};
  if(url==='/api/models')r={models:['fixture-model']};
  if(url==='/api/onboarding'){if(value?.action==='connection')settings.guide={active:true,step:'persona',job:null};if(value?.action==='back')settings.guide={active:true,step:'connection',job:null};if(value?.action==='connection-settings')settings.guide={active:true,step:'connection',job:null};if(['complete','skip'].includes(value?.action))settings.guide={active:false,step:'complete',job:null};r=settings;}
  if(url==='/api/connection-test')r={ok:controls.connectionOK,message:controls.connectionOK?'连接正常':'未找到本机 Codex'};
  if(url==='/api/extension-code')r={code:'test-pairing-code',expires_in:300};
  if(url==='/api/pair-request-info')r={request_id:value.request_id,status:'pending',extension_hint:'abcdef…1234',expires_in:300};
  if(url==='/api/pair-request-approve')r={approved:true,status:'approved'};
  if(url==='/api/profile-import-draft')r=fixture.profileImport||{};
  if(url==='/api/mock-interview/export')r={package_id:'practice-test',job_id:value.job_id,prompt:'已脱敏面试提示词',filename:'面试.md',note:'请核对'};
  if(url==='/api/mock-interview/preview')r={package_id:'practice-test',job_id:value.job_id,target:'岗位A',preview_token:'reviewed',result:{summary:'练习总结',strengths:[],improvements:[],next_steps:[],turns:[]}};
  if(url==='/api/mock-interview/records')r={records:[]};
  if(url==='/api/history')r={turns:fixture.turns||[],artifacts:fixture.artifacts||[]};
  if(url==='/api/chat-fact-draft')r=fixture.factDraft||{task_id:value.task_id,job_id:'a',content:'我独立整理过客户反馈。',source:'用户聊天核对 · '+value.task_id.slice(0,8),saved:false};
  if(url==='/api/fact')settings.ready=false;
  if(url==='/api/privacy-preview')r={token:'fact-preview',preview:{confirmed_facts:[{content:'我独立整理过客户反馈。'}]},note:'请核对脱敏内容。'};
  if(url==='/api/privacy-approve')settings.ready=true;
  if(url==='/api/resume-versions')r={versions:[]};
  if(url==='/api/company')r={company:controls.company};
  if(url==='/api/company-research')r=controls.research;
  if(url==='/api/company-research-confirm'){controls.company=fixture.confirmedCompany||controls.company;r={company:controls.company};}
  if(url==='/api/result-viewed'){data.tasks.find(t=>t.id===value.task_id).viewed=value.viewed;r={viewed:value.viewed};}
  if(url==='/api/quick-event')r={already_recorded:false};
  if(url==='/api/journey')r={summary:{companies:0,applications:0,greetings:0,resume_versions:0,span_days:0},events:[],facts:[]};
  if(url==='/api/job-links')r={links:fixture.links||[]};
  return {ok:true,json:async()=>r};
 };
 vm.runInContext(fs.readFileSync(path.join(root,'workspace.js'),'utf8'),dom.getInternalVMContext());vm.runInContext(fs.readFileSync(path.join(root,'..','extension','reply-format.js'),'utf8'),dom.getInternalVMContext());vm.runInContext(fs.readFileSync(path.join(root,'app.js'),'utf8'),dom.getInternalVMContext());
 vm.runInContext(fs.readFileSync(path.join(root,'mock-interview.js'),'utf8'),dom.getInternalVMContext());
 controls.refresh=()=>w.refresh();return {w,dom,controls};
}
test('access fragment is consumed only by session POST, removed from URL, and local reads use the new token',async()=>{
 const {w,dom,controls}=harness('#access=one-time-fragment&job=a');await settle();
 const session=controls.calls.filter(([url])=>url==='/api/session');assert.equal(session.length,1);
 assert.equal(session[0][2].method,'POST');assert.equal(session[0][2].headers['X-Local-Token'],'one-time-fragment');
 assert.doesNotMatch(JSON.stringify(session[0][1]),/one-time-fragment/);assert.doesNotMatch(w.location.hash,/access=/);assert.match(w.location.hash,/job=a/);
 const state=controls.calls.find(([url])=>url.startsWith('/api/state'));assert.ok(state);assert.equal(state[2].method,undefined);assert.equal(state[2].headers['X-Local-Token'],'local-test');
 for(const [url,value,init] of controls.calls.slice(1)){assert.equal(init?.headers?.['X-Local-Token'],'local-test',`${url} should use the session token`);assert.doesNotMatch(JSON.stringify(value),/one-time-fragment/);}
 dom.window.close();
});
test('polling skips hidden pages, waits five seconds when idle, and never overlaps refreshes',async()=>{
 const {w,dom,controls}=harness();await settle();controls.calls.length=0;controls.now=100000;
 controls.hidden=true;controls.poll();await settle();assert.equal(controls.calls.filter(([url])=>url.startsWith('/api/state')).length,0);
 controls.hidden=false;controls.poll();await settle();assert.equal(controls.calls.filter(([url])=>url.startsWith('/api/state')).length,1);
 controls.now+=1000;controls.poll();await settle();assert.equal(controls.calls.filter(([url])=>url.startsWith('/api/state')).length,1);
 controls.now+=4000;controls.poll();await settle();assert.equal(controls.calls.filter(([url])=>url.startsWith('/api/state')).length,2);
 controls.holdState=true;controls.now+=5000;controls.poll();await settle();assert.equal(controls.calls.filter(([url])=>url.startsWith('/api/state')).length,3);
 controls.now+=6000;controls.poll();await settle();assert.equal(controls.calls.filter(([url])=>url.startsWith('/api/state')).length,3);
 controls.releaseState();controls.holdState=false;await settle();controls.now+=6000;controls.poll();await settle();assert.equal(controls.calls.filter(([url])=>url.startsWith('/api/state')).length,4);
 dom.window.close();
});
test('refresh preserves unsaved model settings form values',async()=>{
 const {w,dom}=harness();await settle();w.document.querySelector('[data-page="settings"]').click();
 w.document.getElementById('provider').value='api';w.document.getElementById('base-url').value='https://unsaved.example/v1';w.document.getElementById('api-model').value='unsaved-model';w.document.getElementById('buddy-name').value='未保存称呼';
 await w.refresh();await settle();assert.equal(w.document.getElementById('base-url').value,'https://unsaved.example/v1');assert.equal(w.document.getElementById('api-model').value,'unsaved-model');assert.equal(w.document.getElementById('buddy-name').value,'未保存称呼');dom.window.close();
});
test('chat switch opens job list directly and changes the active conversation',async()=>{
 const {w,dom,controls}=harness();await settle();
 [...w.document.querySelectorAll('.chat-tools button')].find(b=>b.textContent==='切换岗位').click();
 const dialog=w.document.getElementById('job-switch-dialog');assert.equal(dialog.open,true);
 assert.equal(dialog.querySelectorAll('#job-switch-list button').length,2);
 [...dialog.querySelectorAll('#job-switch-list button')].find(b=>b.textContent.includes('岗位B')).click();await settle();
 assert.equal(dialog.open,false);assert.match(w.document.getElementById('chat-title').textContent,/岗位B/);
 assert.ok(controls.calls.some(([url,value])=>url==='/api/history'&&value.job_id==='b'));
 dom.window.close();
});
test('blank template leaves facts empty and records the explicit skip choice',async()=>{
 const {w,dom,controls}=harness('',false,{data:{profile:{name:'',preferences:'',facts:''}},settings:{guide:{active:true,step:'profile'}}});await settle();
 const blank=w.document.getElementById('use-template');assert.match(blank.textContent,/空白模板/);blank.click();await settle();
 assert.equal(w.document.getElementById('profile-facts').value,'');
 assert.ok(controls.calls.some(([url,value])=>url==='/api/onboarding'&&value.action==='blank-profile'));
 dom.window.close();
});
test('external mock interview requires review and switching jobs invalidates import',async()=>{
 const {w,dom,controls}=harness('#job=a&view=interview');await settle();assert.deepEqual(controls.errors,[]);
 w.document.getElementById('mock-export').click();await settle();assert.match(w.document.getElementById('mock-prompt').value,/已脱敏/);
 const input=w.document.getElementById('mock-result-input');input.value='synthetic';input.dispatchEvent(new w.Event('input'));
 w.document.getElementById('mock-preview').click();await settle();assert.equal(w.document.getElementById('mock-import').disabled,true);
 w.document.getElementById('mock-import-confirm').click();w.document.getElementById('mock-import').click();await settle();
 assert.equal(controls.calls.filter(c=>c[0]==='/api/mock-interview/import').length,1);
 w.document.getElementById('mock-preview').click();await settle();w.document.getElementById('mock-import-confirm').click();
 [...w.document.querySelectorAll('#job-list button')].find(b=>b.textContent.includes('岗位B')).click();await settle();
 assert.equal(w.document.getElementById('mock-import').disabled,true);assert.equal(input.value,'');
 assert.equal(controls.calls.filter(c=>c[0]==='/api/talk'||c[0]==='/api/fact'||c[0]==='/api/journey-event').length,0);dom.window.close();
});
test('returning user lands in chat, setup/settings hidden, no duplicate IDs',async()=>{
 const {w,dom,controls}=harness('#job=a');await settle();
 assert.deepEqual(controls.errors,[]);assert.equal(w.document.getElementById('screen-chat').hidden,false);
 assert.equal(w.document.getElementById('screen-profile').hidden,true);assert.equal(w.document.getElementById('screen-settings').hidden,true);
 const ids=[...w.document.querySelectorAll('[id]')].map(n=>n.id);assert.equal(new Set(ids).size,ids.length);
 assert.equal(w.document.getElementById('chat-panel').closest('#screen-chat').id,'screen-chat');dom.window.close();
});
test('online resume draft appends only after review and never overwrites existing profile',async()=>{
 const profileImport={id:'draft1',content:{name:'新姓名',sections:{advantage:{status:'present',items:['善于沟通']},expectations:{status:'present',items:['产品运营 · 杭州']},work:{status:'present',items:['样例公司 · 负责活动复盘']},projects:{status:'empty',items:[]},education:{status:'unavailable',items:[]},certificates:{status:'empty',items:[]},custom:{status:'empty',items:[]}}},editor:{name:'新姓名',preferences:'产品运营 · 杭州',facts:'个人优势：\n善于沟通\n\n工作经历：\n样例公司 · 负责活动复盘'},warnings:['掩码联系方式需要补充']};
 const {w,dom,controls}=harness('#page=profile&resume_import=draft1',true,{profileImport});await settle();assert.deepEqual(controls.errors,[]);
 assert.equal(w.document.getElementById('screen-profile').hidden,false);assert.equal(w.document.getElementById('resume-import-preview').hidden,false);assert.equal(w.document.getElementById('profile-name').value,'测试');
 assert.equal(w.document.getElementById('resume-import-apply').disabled,true);w.document.getElementById('resume-import-confirm').click();w.document.getElementById('resume-import-apply').click();
 assert.equal(w.document.getElementById('profile-name').value,'测试');assert.match(w.document.getElementById('profile-facts').value,/^经历/);assert.match(w.document.getElementById('profile-facts').value,/样例公司/);assert.match(w.document.getElementById('profile-preferences').value,/产品运营/);
 assert.equal(controls.calls.filter(c=>c[0]==='/api/profile').length,0);assert.match(w.document.getElementById('resume-import-status').textContent,/还没有保存/);dom.window.close();
});
test('online resume keeps different same-length experience items',async()=>{
 const previous='负责客户需求梳理与售后技术支持。'.repeat(3),incoming='负责财务预算编制与年度成本分析。'.repeat(3);assert.equal(previous.length,incoming.length);assert.notEqual(previous,incoming);
 const profileImport={id:'draft-distinct',content:{name:'测试',sections:{advantage:{status:'empty',items:[]},expectations:{status:'empty',items:[]},work:{status:'present',items:[incoming]},projects:{status:'empty',items:[]},education:{status:'empty',items:[]},certificates:{status:'empty',items:[]},custom:{status:'empty',items:[]}}},editor:{name:'测试',preferences:'',facts:'工作经历：\n'+incoming},warnings:[]};
 const {w,dom}=harness('#page=profile&resume_import=draft-distinct',true,{data:{profile:{name:'测试',preferences:'',facts:previous}},profileImport});await settle();
 w.document.getElementById('resume-import-confirm').click();w.document.getElementById('resume-import-apply').click();
 const facts=w.document.getElementById('profile-facts').value;assert.ok(facts.includes(previous));assert.ok(facts.includes(incoming));assert.match(w.document.getElementById('resume-import-status').textContent,/相似内容均已保留/);dom.window.close();
});
test('online resume removes only exact normalized duplicates',async()=>{
 const item='负责用户反馈整理与活动复盘。';
 const profileImport={id:'draft-exact',content:{name:'测试',sections:{advantage:{status:'empty',items:[]},expectations:{status:'empty',items:[]},work:{status:'present',items:[item]},projects:{status:'empty',items:[]},education:{status:'empty',items:[]},certificates:{status:'empty',items:[]},custom:{status:'empty',items:[]}}},editor:{name:'测试',preferences:'',facts:'工作经历：\n'+item},warnings:[]};
 const {w,dom}=harness('#page=profile&resume_import=draft-exact',true,{data:{profile:{name:'测试',preferences:'',facts:'工作经历：\n'+item}},profileImport});await settle();
 w.document.getElementById('resume-import-confirm').click();w.document.getElementById('resume-import-apply').click();
 const facts=w.document.getElementById('profile-facts').value;assert.equal(facts.split(item).length-1,1);dom.window.close();
});
test('read acknowledgement changes inbox but not career progress; read results stay accessible',async()=>{
 const {w,dom,controls}=harness('#job=a&task=resume-a');await settle();
 assert.match(w.document.getElementById('delivery-inbox').textContent,/待查看/);
 [...w.document.querySelectorAll('#task-list button')].find(b=>b.textContent==='我已查看这份结果').click();await settle();
 assert.equal(controls.data.tasks[0].viewed,true);
 assert.doesNotMatch(w.document.getElementById('delivery-inbox').textContent,/岗位A/);
 w.document.getElementById('toggle-read-results').click();assert.match(w.document.getElementById('delivery-inbox').textContent,/已查看/);
 assert.match(w.document.getElementById('delivery-inbox').textContent,/岗位A/);
 assert.equal(controls.calls.filter(c=>c[0]==='/api/quick-event'||c[0]==='/api/journey-event').length,0);dom.window.close();
});
test('quick progress requires confirmation and binds the original job despite navigation',async()=>{
 const {w,dom,controls}=harness('#job=a');await settle();
 w.document.getElementById('record-invitation').click();await settle();
 assert.match(w.document.getElementById('progress-target').textContent,/岗位A/);
 assert.equal(w.document.getElementById('progress-save').disabled,true);
 w.document.getElementById('progress-cancel').click();assert.equal(controls.calls.filter(c=>c[0]==='/api/quick-event').length,0);
 w.document.getElementById('record-invitation').click();await settle();
 // Simulate a background navigation while the original confirmation is open.
 [...w.document.querySelectorAll('#job-list button')].find(b=>b.textContent.includes('岗位B')).click();await settle();
 w.document.getElementById('progress-confirm').click();w.document.getElementById('progress-save').click();w.document.getElementById('progress-save').click();await settle();
 const calls=controls.calls.filter(c=>c[0]==='/api/quick-event');assert.equal(calls.length,1);assert.equal(calls[0][1].job_id,'a');assert.equal(calls[0][1].confirmed,true);
 assert.equal(w.document.getElementById('opportunity-interview').hidden,false);assert.match(w.document.getElementById('opportunity-title').textContent,/岗位A/);dom.window.close();
});
test('new user goes to profile, connection form stays reachable',async()=>{
 const {w,dom,controls}=harness('',false);await settle();assert.deepEqual(controls.errors,[]);
 assert.equal(w.document.getElementById('screen-profile').hidden,false);
 w.document.querySelector('[data-page="settings"]').click();assert.equal(w.document.getElementById('screen-settings').hidden,false);dom.window.close();
});
test('first-use guide focuses one step and only advances after connection test',async()=>{
 const guide={active:true,step:'connection',job:null};
 const {w,dom,controls}=harness('#onboarding=1',true,{settings:{guide}});await settle();
 assert.deepEqual(controls.errors,[]);assert.equal(w.document.getElementById('screen-settings').hidden,false);
 assert.equal(w.document.body.classList.contains('first-use-mode'),true);assert.equal(w.document.body.dataset.guideStep,'connection');
 assert.match(w.document.getElementById('onboarding-flow').textContent,/连接模型/);assert.equal(w.document.getElementById('save-provider').textContent,'保存并测试连接');
 w.document.getElementById('provider-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await settle();
 assert.equal(controls.calls.filter(c=>c[0]==='/api/connection-test').length,1);assert.equal(w.document.body.dataset.guideStep,'persona');
 assert.equal(w.document.getElementById('screen-profile').hidden,false);assert.equal(w.document.querySelectorAll('#onboarding-flow .guide-role-card').length,2);dom.window.close();
});
test('first-use guide exposes back and skip controls',async()=>{
 const guide={active:true,step:'persona',job:null};
 const {w,dom,controls}=harness('#onboarding=1',true,{settings:{guide}});await settle();
 assert.match(w.document.getElementById('onboarding-flow').textContent,/上一步/);assert.match(w.document.getElementById('onboarding-flow').textContent,/跳过引导/);
 [...w.document.querySelectorAll('#onboarding-flow button')].find(b=>b.textContent==='上一步').click();await settle();assert.equal(controls.calls.some(c=>c[1]?.action==='back'),true);
 w.document.getElementById('guide-skip').click();await settle();assert.equal(controls.calls.some(c=>c[1]?.action==='skip'),true);
 await controls.refresh();await settle();assert.equal(w.document.body.classList.contains('first-use-mode'),false);assert.equal(w.document.getElementById('screen-settings').hidden,false);dom.window.close();
});
test('saving unchanged approved profile during guide review stays on next visible step',async()=>{
 const {w,dom,controls}=harness('#onboarding=1',true,{settings:{guide:{active:true,step:'profile',reviewing:true}}});await settle();
 const fetch=w.fetch;w.fetch=async(url,init)=>{if(url==='/api/onboarding'&&JSON.parse(init.body).action==='continue')controls.settings.guide={active:true,step:'browse',job:null};return fetch(url,init);};
 w.document.getElementById('profile-form').dispatchEvent(new w.Event('submit',{cancelable:true}));await settle();await controls.refresh();await settle();
 assert.equal(w.document.body.dataset.guideStep,'browse');assert.equal(w.document.getElementById('screen-chat').hidden,false);
 assert.equal(w.document.getElementById('onboarding-flow').parentElement.id,'screen-chat');dom.window.close();
});
test('skip exits forced pairing too, without marking privacy ready',async()=>{
 const {w,dom,controls}=harness('#onboarding=1&pairing=1',false,{settings:{extension_paired:false,guide:{active:true,step:'pairing'}}});await settle();
 assert.equal(w.document.getElementById('guide-back').disabled,true);w.document.getElementById('guide-skip').click();await settle();await controls.refresh();await settle();
 assert.equal(w.document.body.classList.contains('first-use-mode'),false);assert.equal(w.document.getElementById('screen-profile').hidden,false);assert.equal(controls.settings.ready,false);
 assert.equal(w.location.hash.includes('pairing='),false);dom.window.close();
});
test('unpaired onboarding exposes code without a job or hash and resumes LLM setup after pairing',async()=>{
 const {w,dom,controls}=harness('',false,{settings:{extension_paired:false,guide:{active:true,step:'pairing'}}});await settle();
 assert.deepEqual(controls.errors,[]);assert.equal(w.document.getElementById('screen-settings').hidden,false);
 assert.equal(w.document.body.dataset.guideStep,'pairing');assert.equal(w.document.getElementById('connections').open,true);
 w.document.getElementById('extension-code').click();await settle();assert.equal(w.document.getElementById('pair-code').textContent,'test-pairing-code');
 await controls.refresh();await settle();assert.equal(w.document.getElementById('pair-code').textContent,'test-pairing-code');
 assert.equal(controls.calls.filter(c=>c[0]==='/api/talk').length,0);
 controls.settings.extension_paired=true;controls.settings.extension_pairing_revision=1;controls.settings.guide={active:true,step:'connection'};await controls.refresh();await settle();
 assert.equal(w.document.getElementById('settings-sidebar-status').textContent,'已连接');assert.equal(w.document.getElementById('sidebar-connection-badge').textContent,'已连接');
 assert.equal(w.document.body.dataset.guideStep,'connection');assert.match(w.document.getElementById('pair-code').textContent,/成功/);
 assert.equal(w.document.getElementById('screen-settings').hidden,false);dom.window.close();
});
test('pair request page requires explicit confirmation and avoids copy paste code',async()=>{
 const {w,dom,controls}=harness('#pair_request=request-1&onboarding=1',false,{settings:{extension_paired:false,guide:{active:true,step:'pairing'}}});await settle();
 assert.equal(w.document.getElementById('pair-request-card').hidden,false);assert.equal(w.document.getElementById('pairing-default').hidden,true);
 assert.match(w.document.getElementById('pair-request-copy').textContent,/abcdef/);assert.equal(w.document.getElementById('pair-request-approve').disabled,true);
 w.document.getElementById('pair-request-confirm').click();w.document.getElementById('pair-request-approve').click();await settle();
 assert.equal(controls.calls.filter(c=>c[0]==='/api/pair-request-approve').length,1);assert.match(w.document.getElementById('pair-request-copy').textContent,/连接成功/);
 const hashChanged=new Promise(resolve=>w.addEventListener('hashchange',resolve,{once:true}));
 w.location.hash='#pair_request=request-2&onboarding=1';await hashChanged;await settle();
 const confirm=w.document.getElementById('pair-request-confirm'),approve=w.document.getElementById('pair-request-approve');
 assert.equal(confirm.closest('label').hidden,false);assert.equal(confirm.checked,false);assert.equal(approve.hidden,false);assert.equal(approve.disabled,true);
 approve.click();await settle();assert.equal(controls.calls.filter(c=>c[0]==='/api/pair-request-approve').length,1);
 confirm.click();approve.click();await settle();
 const approvals=controls.calls.filter(c=>c[0]==='/api/pair-request-approve');assert.equal(approvals.length,2);assert.equal(approvals[1][1].request_id,'request-2');dom.window.close();
});
test('connection false result never advances onboarding and allows retry',async()=>{
 const {w,dom,controls}=harness('#onboarding=1',false,{settings:{extension_paired:true,guide:{active:true,step:'connection'}}});await settle();controls.connectionOK=false;
 const submit=()=>w.document.getElementById('provider-form').dispatchEvent(new w.Event('submit',{cancelable:true}));submit();await settle();
 assert.equal(controls.calls.filter(c=>c[0]==='/api/onboarding').length,0);assert.equal(w.document.body.dataset.guideStep,'connection');
 assert.match(w.document.getElementById('connection-status').textContent,/未找到/);assert.equal(w.document.getElementById('save-provider').disabled,false);
 controls.connectionOK=true;submit();await settle();assert.equal(w.document.body.dataset.guideStep,'persona');dom.window.close();
});
test('returning user can reopen pairing without losing completed onboarding',async()=>{
 const {w,dom,controls}=harness('#pairing=1',true,{settings:{extension_paired:true,extension_pairing_revision:1,guide:{active:false,step:'complete'}}});await settle();
 assert.equal(w.document.body.dataset.guideStep,'pairing');w.document.getElementById('extension-code').click();await settle();await controls.refresh();await settle();
 assert.equal(w.document.getElementById('pair-code').textContent,'test-pairing-code');
 controls.settings.extension_pairing_revision=2;await controls.refresh();await settle();
 assert.equal(w.document.body.classList.contains('first-use-mode'),false);assert.equal(w.document.getElementById('screen-settings').hidden,false);
 assert.equal(controls.calls.filter(c=>c[0]==='/api/onboarding').length,0);dom.window.close();
});
test('task drawer opens exact result and material tab keeps edits available',async()=>{
 const {w,dom,controls}=harness('#job=a');await settle();
 w.document.getElementById('session-open').click();assert.equal(w.document.getElementById('session-dialog').open,true);
 [...w.document.querySelectorAll('#delivery-inbox button')].find(b=>b.textContent.includes('岗位B')).click();await settle();
 assert.equal(w.document.getElementById('session-dialog').open,false);assert.equal(w.document.getElementById('task-interview-b').open,true);
 w.document.querySelector('[data-opportunity="materials"]').click();assert.equal(w.document.getElementById('company-panel').closest('#opportunity-materials').hidden,false);
 assert.equal(w.document.getElementById('deliveries').hidden,true);
 w.document.getElementById('new-job').click();await settle();assert.equal(w.document.getElementById('job-editor').open,true);assert.equal(w.document.getElementById('opportunity-materials').hidden,false);
 assert.equal(controls.calls.filter(c=>c[0]==='/api/talk').length,0);dom.window.close();
});
test('old task link opens correct job and resume tab; interview and journey links work',async()=>{
 for(const [hash,tab,title] of [['#job=a&task=resume-a','resume','岗位A'],['#job=b&view=interview','interview','岗位B'],['#job=a&view=journey','records','岗位A']]){
  const {w,dom,controls}=harness(hash);await settle();assert.deepEqual(controls.errors,[]);
  assert.equal(w.document.getElementById('screen-opportunities').hidden,false);
  assert.equal(w.document.getElementById('opportunity-'+tab).hidden,false);
  assert.match(w.document.getElementById('opportunity-title').textContent,new RegExp(title));dom.window.close();
 }
});
test('navigation preserves drafts and filters tasks to chosen job and tab',async()=>{
 const {w,dom,controls}=harness('#job=a&task=resume-a');await settle();
 assert.deepEqual(controls.errors,[]);assert.ok(w.document.querySelector('[data-draft]'),'resume deep link must render its editable draft');
 w.document.querySelector('[data-draft]').value='未保存编辑';
 w.document.querySelector('[data-opportunity="interview"]').click();assert.equal(w.document.querySelector('[data-draft]'),null);
 w.document.querySelector('[data-opportunity="resume"]').click();assert.equal(w.document.querySelector('[data-draft]').value,'未保存编辑');
 w.document.getElementById('message').value='给A的问题';
 [...w.document.querySelectorAll('#job-list button')].find(n=>n.textContent.includes('岗位B')).click();await settle();
 assert.equal(w.document.getElementById('message').value,'');
 w.document.querySelector('[data-opportunity="interview"]').click();await settle();assert.match(w.document.getElementById('task-list').textContent,/B的面试卡/);assert.doesNotMatch(w.document.getElementById('task-list').textContent,/A的简历/);
 [...w.document.querySelectorAll('#job-list button')].find(n=>n.textContent.includes('岗位A')).click();await settle();assert.equal(w.document.getElementById('message').value,'给A的问题');dom.window.close();
});
test('500 historical reports stay out of summary polling and open loads the exact full task',async()=>{
 const marker='PRIVATE_REPORT_BODY_MARKER';const long='详细报告正文'+marker+'。'.repeat(8000);
 const tasks=Array.from({length:500},(_,i)=>({id:'report-'+String(i).padStart(4,'0'),kind:'analyze_job',job_id:'a',status:'done',created:1000-i,updated:2000-i,summary:'岗位分析摘要 '+i,result:{summary:'岗位分析摘要 '+i,decision:'先核对目标 '+i,primary_output:long+' '+i,markdown:long+' 依据 '+i}}));
 const {w,dom,controls}=harness('#job=a',true,{data:{tasks}});await settle();
 const stateResponse=controls.responses.find(([url])=>url.startsWith('/api/state?summary=1'))?.[1];assert.ok(stateResponse);assert.equal(stateResponse.tasks.length,500);
 const polled=JSON.stringify(stateResponse);assert.ok(polled.length<700000);assert.ok(!polled.includes(marker));assert.ok(!polled.includes('primary_output'));assert.ok(!polled.includes('markdown'));
 const resultCalls=controls.calls.filter(([url])=>url.startsWith('/api/task-result/'));assert.equal(resultCalls.length,1);assert.equal(resultCalls[0][0],'/api/task-result/report-0000');assert.ok(w.document.getElementById('task-list').textContent.includes(marker));
 assert.equal(controls.calls.filter(([url])=>url==='/api/talk').length,0);dom.window.close();
});
test('resume draft editor waits for full result and keeps edits across summary refresh',async()=>{
 const task={id:'resume-lazy',kind:'tailor_resume',job_id:'a',status:'done',created:10,updated:20,result:{summary:'简历结果已完成',decision:'先核对成果',primary_output:'完整简历正文',markdown:'依据'}};
 const {w,dom,controls}=harness('#job=a&task=resume-lazy',true,{data:{tasks:[task]}});controls.holdTaskResult=true;await settle();
 assert.equal(w.document.querySelector('[data-draft]'),null,'do not create an editable blank draft while full content is loading');
 controls.releaseTaskResult();await settle();const input=w.document.querySelector('[data-draft]');assert.ok(input);assert.equal(input.value,'完整简历正文');
 input.value='用户尚未保存的简历修改';input.dispatchEvent(new w.Event('input',{bubbles:true}));controls.data.tasks[0].metrics={total_seconds:12};await controls.refresh();await settle();
 assert.equal(w.document.querySelector('[data-draft]').value,'用户尚未保存的简历修改');dom.window.close();
});
test('recent delivery opens its own job and tab, not currently selected job',async()=>{
 const {w,dom}=harness('#job=a');await settle();
 [...w.document.querySelectorAll('#delivery-inbox button')].find(n=>n.textContent.includes('岗位B')).click();await settle();
 assert.match(w.document.getElementById('opportunity-title').textContent,/岗位B/);
 assert.equal(w.document.getElementById('opportunity-interview').hidden,false);dom.window.close();
});
test('deep analysis button opens an existing result without starting another model task',async()=>{
 const analysis={id:'analysis-a',kind:'analyze_job',job_id:'a',status:'done',created:3,viewed:false,result:{summary:'已有判断',primary_output:'已有详细结果',markdown:'已有依据'}};
 const {w,dom,controls}=harness('#job=a',true,{data:{profile:{name:'测试',preferences:'',facts:'经历'},jobs:[{id:'a',title:'岗位A',company:'公司A'}],tasks:[analysis]}});await settle();
 assert.equal(w.document.getElementById('deep-analysis').textContent,'查看详细分析');w.document.getElementById('deep-analysis').click();await settle();
 assert.equal(w.document.getElementById('screen-opportunities').hidden,false);assert.ok(w.document.getElementById('task-analysis-a'));
 assert.equal(controls.calls.filter(c=>c[0]==='/api/talk').length,0);dom.window.close();
});
test('completed task names use readable type and number instead of internal kind',async()=>{
 const tasks=[1,2].map((n,i)=>({id:'analysis-'+n,kind:'analyze_job',job_id:'a',status:'done',created:3+i,viewed:false,result:{summary:'已有判断'+n,primary_output:'已有详细结果'+n,markdown:'# 依据'+n}}));
 const {w,dom}=harness('#job=a',true,{data:{profile:{name:'测试',preferences:'',facts:'经历'},jobs:[{id:'a',title:'岗位A',company:'公司A'}],tasks}});await settle();
 const labels=[...w.document.querySelectorAll('#task-list summary strong')].map(n=>n.textContent);assert.deepEqual(labels,['分析 1 · 01/01','分析 2 · 01/01']);assert.doesNotMatch(w.document.getElementById('task-list').textContent,/analyze_job|tailor_resume/);assert.doesNotMatch(w.document.getElementById('task-list').textContent,/# 依据/);dom.window.close();
});
test('dedicated deep analysis hotkey creates a background task for the selected job',async()=>{
 const {w,dom,controls}=harness('#job=a');await settle();
 const button=w.document.querySelector('#chat-form [data-kind="analyze_job"]');
 assert.ok(button);assert.equal(button.type,'button');button.click();await settle();
 const calls=controls.calls.filter(([url])=>url==='/api/talk');
 assert.equal(calls.length,1);assert.equal(calls[0][1].kind,'analyze_job');
 assert.equal(calls[0][1].job_id,'a');dom.window.close();
});
test('slash menu distinguishes new task commands from specific result references',async()=>{
 const artifacts=[
  {task_id:'analysis-a-1111',kind:'analyze_job',label:'深入分析',status:'done',created:100,updated:100,preview:'第一份：客户留存风险',result_markdown:'结果 A'},
  {task_id:'analysis-a-2222',kind:'analyze_job',label:'深入分析',status:'done',created:200,updated:200,preview:'第二份：团队目标待核实',result_markdown:'结果 B'},
 ];
 const {w,dom,controls}=harness('#job=a',true,{artifacts});await settle();
 const input=w.document.getElementById('message');input.value='/';input.dispatchEvent(new w.Event('input',{bubbles:true}));await settle();
 const menu=w.document.getElementById('command-menu');assert.doesNotMatch(menu.textContent,/创建新的专项任务/);assert.equal(menu.querySelectorAll('.command-artifact').length,2);assert.doesNotMatch(menu.textContent,/tailor_resume|analyze_job|suggest_reply/);
 const second=[...menu.querySelectorAll('.command-artifact')].find(b=>b.textContent.includes('第二份'));assert.ok(second);second.click();await settle();
 assert.equal(w.document.getElementById('selected-reference').hidden,false);assert.match(w.document.getElementById('selected-reference').textContent,/分析 2/);assert.doesNotMatch(w.document.getElementById('selected-reference').textContent,/tailor_resume|analyze_job|suggest_reply/);
 input.value='请解释这份结果';await w.document.getElementById('chat-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await settle();
 const talk=controls.calls.find(c=>c[0]==='/api/talk');assert.equal(talk[1].reference_task_id,'analysis-a-2222');assert.equal(talk[1].text,'请解释这份结果');
 dom.window.close();
});
test('slash only offers result references and does not create task commands',async()=>{
 const artifacts=[{task_id:'analysis-a-1111',kind:'analyze_job',label:'深入分析',status:'done',created:100,updated:100,preview:'旧结果',result_markdown:'旧结果'}];
 const {w,dom,controls}=harness('#job=a',true,{artifacts});await settle();
 const input=w.document.getElementById('message');input.value='/';input.dispatchEvent(new w.Event('input',{bubbles:true}));await settle();
 assert.equal([...w.document.querySelectorAll('#command-menu button')].some(b=>b.textContent.includes('创建任务')),false);
 assert.equal(input.value,'/');dom.window.close();
});
test('chat experience opens fact review and requires privacy approval before returning to chat',async()=>{
 const turns=[{task_id:'chat-fact-1',kind:'companion_chat',text:'我独立整理过客户反馈。',reply:'这是可用经历。',fact_candidate:true,status:'done',created:1,updated:2}];
 const {w,dom,controls}=harness('#job=a',true,{turns});await settle();
 const remember=w.document.querySelector('.turn .fact-from-chat');assert.ok(remember);assert.match(remember.textContent,/可能是新经历/);remember.click();await settle();
 assert.equal(w.document.getElementById('fact-content').value,turns[0].text);
 assert.equal(w.document.getElementById('screen-profile').hidden,false);
 w.document.getElementById('fact-confirm').checked=true;
 w.document.querySelector('#fact-form button:not([type="button"])').click();await settle();
 const saved=controls.calls.find(([url])=>url==='/api/fact');
 assert.equal(saved[1].chat_task_id,'chat-fact-1');assert.equal(saved[1].confirmed,true);
 assert.match(w.document.getElementById('privacy-output').textContent,/客户反馈/);
 w.document.getElementById('privacy-confirm').click();
 w.document.getElementById('privacy-approve').click();await settle();
 assert.ok(controls.calls.some(([url])=>url==='/api/privacy-approve'));
 assert.equal(w.document.getElementById('screen-chat').hidden,false);
 dom.window.close();
});
test('dense workspace starts compact and still exposes every task, opportunity and company source',async()=>{
 const tasks=Array.from({length:14},(_,i)=>({id:'analysis-'+i,kind:'analyze_job',job_id:'b',status:'done',created:100-i,viewed:false,result:{summary:'判断'+i,primary_output:'结果'+i,markdown:'依据'+i}}));
 const evidence=Array.from({length:8},(_,i)=>({id:String(i).repeat(64),kind:i<2?'introduction':'peer_job',title:'参考岗位'+i,text:'公开材料'+i,source_url:'https://www.zhipin.com/job_detail/source'+i+'.html',observed:100-i,label:i<2?'企业自述':'招聘方表述'}));
 const {w,dom,controls}=harness('#job=a',true,{data:{profile:{name:'测试',preferences:'',facts:'经历'},jobs:[{id:'a',title:'岗位A',company:'公司A'},{id:'b',title:'岗位B',company:'公司B'},{id:'c',title:'岗位C',company:'公司C'}],tasks},company:{name:'公司A',revision:8,evidence}});await settle();
 assert.deepEqual(controls.errors,[]);assert.equal(w.document.getElementById('delivery-inbox-panel').open,false);
 assert.match(w.document.getElementById('delivery-inbox-summary').textContent,/待查看 14/);assert.equal(w.document.querySelectorAll('#delivery-inbox .delivery-link').length,3);
 w.document.getElementById('toggle-all-results').click();assert.equal(w.document.querySelectorAll('#delivery-inbox .delivery-link').length,14);
 assert.equal(w.document.getElementById('company-panel').open,false);assert.match(w.document.getElementById('company-summary').textContent,/8 条/);assert.equal(w.document.querySelectorAll('.company-group').length,2);
 w.document.getElementById('toggle-opportunity-list').click();assert.equal(w.document.querySelector('.opportunity-layout').classList.contains('list-collapsed'),true);
 w.document.getElementById('toggle-opportunity-list').click();const search=w.document.getElementById('job-search');search.value='公司B';search.dispatchEvent(new w.Event('input'));assert.equal(w.document.querySelectorAll('#job-list button').length,1);assert.match(w.document.getElementById('job-list').textContent,/岗位B/);
 dom.window.close();
});
test('slow chat task displays elapsed model wait and cancel action',async()=>{
 const slow={id:'slow-a',kind:'quick_analysis',job_id:'a',status:'running',created:Date.now()/1000-400,updated:Date.now()/1000-95,attempts:2};
 const {w,dom,controls}=harness('#job=a',true,{data:{profile:{name:'测试',preferences:'',facts:'经历'},jobs:[{id:'a',title:'岗位A',company:'公司A'}],tasks:[slow]}});const fetch=w.fetch;w.fetch=async(url,init)=>url==='/api/history'?{ok:true,json:async()=>({turns:[{task_id:'slow-a',kind:'quick_analysis',text:'慢请求',status:'running',created:slow.created,updated:slow.updated,attempts:2,workbench:false}]})}:fetch(url,init);await settle();
 w.document.getElementById('message').value='';await controls.refresh();await settle();
 assert.match(w.document.getElementById('messages').textContent,/第 2 次尝试/);assert.match(w.document.getElementById('messages').textContent,/本次已等待 9[5-9] 秒/);assert.doesNotMatch(w.document.getElementById('messages').textContent,/400 秒/);assert.match(w.document.getElementById('messages').textContent,/取消任务/);dom.window.close();
});
test('model connection settings fetch models and require explicit task assignment confirmation',async()=>{
 const connection={id:'fixture-connection',name:'虚构连接',base_url:'https://api.example.invalid/v1',api_model:'fixture-model',has_api_key:true};
 const {w,dom,controls}=harness('#page=settings',true,{settings:{connections:[connection],task_models:{}}});await settle();
 w.document.getElementById('connection-id').value=connection.id;
 w.document.getElementById('connection-url').value=connection.base_url;
 w.document.getElementById('connection-fetch-models').click();await settle();
 assert.deepEqual(controls.calls.find(c=>c[0]==='/api/models')[1],{connection_id:connection.id});
 assert.equal(w.document.getElementById('connection-model-list').options[1].value,'fixture-model');
 const role=w.document.querySelector('[data-intent="resume"]');role.value=connection.id;role.dispatchEvent(new w.Event('change'));
 w.document.querySelector('[data-model-intent="resume"]').value='fixture-model';
 w.document.getElementById('task-model-save').click();await settle();
 assert.equal(controls.calls.filter(c=>c[0]==='/api/companion'&&c[1]?.task_models).length,0);
 w.document.getElementById('task-model-confirm').checked=true;w.document.getElementById('task-model-save').click();await settle();
 const save=controls.calls.find(c=>c[0]==='/api/companion'&&c[1]?.task_models);
 assert.equal(save[1].task_models.resume.connection_id,connection.id);assert.equal(save[1].task_models_confirmed,true);
 dom.window.close();
});
test('removing a model connection also clears task assignments that reference it',async()=>{
 const connection={id:'fixture-connection',name:'虚构连接',base_url:'https://api.example.invalid/v1',api_model:'fixture-model',has_api_key:true};
 const {w,dom,controls}=harness('#page=settings',true,{settings:{connections:[connection],task_models:{resume:{connection_id:connection.id,model:'fixture-model'}}}});await settle();
 [...w.document.querySelectorAll('#connection-list button')].find(b=>b.textContent==='移除连接').click();await settle();
 assert.equal(w.document.getElementById('connection-remove-confirm').hidden,false);assert.match(w.document.getElementById('connection-remove-copy').textContent,/简历/);
 assert.equal(controls.calls.filter(c=>c[0]==='/api/companion'&&Array.isArray(c[1]?.connections)).length,0);
 w.document.getElementById('connection-remove-yes').click();await settle();
 const update=controls.calls.find(c=>c[0]==='/api/companion'&&Array.isArray(c[1]?.connections));
 assert.equal(update[1].connections.length,0);assert.equal(update[1].task_models.resume,undefined);dom.window.close();
});

test('settings shows connection usage, saved task assignments, and a pending preview',async()=>{
 const connection={id:'fixture-connection',name:'虚构连接',base_url:'https://api.example.invalid/v1',api_model:'fixture-model',has_api_key:true};
 const {w,dom}=harness('#page=settings',true,{settings:{connections:[connection],task_models:{resume:{connection_id:connection.id,model:'fixture-model'}}}});await settle();
 assert.match(w.document.getElementById('connection-list').textContent,/使用任务：简历/);
 assert.match(w.document.getElementById('task-model-assignments').textContent,/已生效：虚构连接 · fixture-model/);
 const sel=w.document.querySelector('[data-intent="resume"]');sel.value='';sel.dispatchEvent(new w.Event('change'));await settle();
 assert.match(w.document.getElementById('task-model-preview').textContent,/保存前变更预览/);assert.match(w.document.getElementById('task-model-preview').textContent,/虚构连接 · fixture-model → 沿用默认接入/);dom.window.close();
});

test('default model status separates saved configuration from tested success',async()=>{
 const {w,dom,controls}=harness('#page=settings',true,{settings:{provider:'api',base_url:'https://api.example.invalid/v1',api_model:'fixture-model'}});await settle();
 assert.equal(w.document.getElementById('settings-model-status').textContent,'已保存待测试');
 w.document.getElementById('test-connection').click();await settle();assert.equal(w.document.getElementById('settings-model-status').textContent,'本次测试通过');
 controls.connectionOK=false;w.document.getElementById('test-connection').click();await settle();assert.equal(w.document.getElementById('settings-model-status').textContent,'已保存待测试');dom.window.close();
});

test('company research previews sources and saves only after explicit confirmation',async()=>{
 const company={name:'公司A',revision:2,evidence:[]};
 const {w,dom,controls}=harness('#job=a',true,{company});await settle();
 const open=w.document.getElementById('company-research-open');assert.equal(open.hidden,false);open.click();
 const area=w.document.getElementById('company-research');assert.equal(area.hidden,false);
 const question=w.document.getElementById('company-research-question');question.value='主要做什么？';
 w.document.getElementById('company-research-form').dispatchEvent(new w.Event('submit',{cancelable:true}));await settle();
 const research=controls.calls.find(c=>c[0]==='/api/company-research');assert.equal(research[1].job_id,'a');assert.equal(research[1].company_name,undefined);assert.equal(research[1].question,'主要做什么？');assert.equal(research[1].allow_network,true);
 assert.equal(w.document.getElementById('company-research-preview').hidden,false);assert.match(w.document.getElementById('company-research-sources').textContent,/公司公开介绍摘录/);assert.equal(w.document.getElementById('company-research-confirm').disabled,false);
 assert.equal(controls.calls.filter(c=>c[0]==='/api/company-research-confirm').length,0);
 w.document.getElementById('company-research-confirm').click();await settle();
 const confirm=controls.calls.find(c=>c[0]==='/api/company-research-confirm');assert.equal(confirm[1].job_id,'a');assert.equal(confirm[1].confirmed,true);assert.equal(confirm[1].preview_id,'preview-test');assert.equal(confirm[1].research,undefined);assert.equal(w.document.getElementById('company-research').hidden,true);
 dom.window.close();
});

test('company research cancellation discards preview without saving',async()=>{
 const {w,dom,controls}=harness('#job=a',true,{company:{name:'公司A',revision:1,evidence:[]}});await settle();
 w.document.getElementById('company-research-open').click();w.document.getElementById('company-research-question').value='产品方向';
 w.document.getElementById('company-research-form').dispatchEvent(new w.Event('submit',{cancelable:true}));await settle();
 w.document.getElementById('company-research-discard').click();await settle();
 assert.ok(controls.calls.some(c=>c[0]==='/api/company-research-discard'&&c[1].preview_id==='preview-test'));
 assert.equal(w.document.getElementById('company-research').hidden,true);assert.equal(w.document.getElementById('company-research-preview').hidden,true);assert.equal(controls.calls.filter(c=>c[0]==='/api/company-research-confirm').length,0);dom.window.close();
});


test('company research works without manual background and lists confirmed research materials',async()=>{
 const {w,dom}=harness('#job=a',true,{company:null});await settle();
 assert.equal(w.document.getElementById('company-research-open').hidden,false);
 assert.match(w.document.getElementById('company-evidence').textContent,/直接研究/);
 dom.window.close();
 const next=harness('#job=a',true,{company:{name:'公司A',revision:1,evidence:[{id:'r1',kind:'research',source_url:'https://example.com/about',text:'来自公开页面的业务信息',source_type:'public_web_page',observed:1}]}});await settle();
 assert.match(next.w.document.getElementById('company-evidence').textContent,/公开研究资料/);
 assert.match(next.w.document.getElementById('company-evidence').textContent,/来自公开页面的业务信息/);next.dom.window.close();
});

test('late research response after switching jobs is discarded and cannot bind the new job',async()=>{
 const {w,dom,controls}=harness('#job=a');await settle();
 let deliver;const orig=w.fetch;w.fetch=async(url,init)=>url==='/api/company-research'?new Promise(resolve=>{deliver=resolve;}):orig(url,init);
 w.document.getElementById('company-research-open').click();w.document.getElementById('company-research-question').value='产品与业务';
 w.document.getElementById('company-research-form').dispatchEvent(new w.Event('submit',{cancelable:true}));await settle();
 [...w.document.querySelectorAll('#job-list button')].find(b=>b.textContent.includes('岗位B')).click();await settle();
 deliver({ok:true,json:async()=>({...controls.research,preview_id:'late-a'})});await settle();
 assert.equal(w.document.getElementById('company-research-preview').hidden,true);
 assert.ok(controls.calls.some(c=>c[0]==='/api/company-research-discard'&&c[1].job_id==='a'&&c[1].preview_id==='late-a'));
 assert.equal(controls.calls.filter(c=>c[0]==='/api/company-research-confirm').length,0);dom.window.close();
});

test('canceling an in-flight research prevents a late preview from reappearing',async()=>{
 const {w,dom,controls}=harness('#job=a');await settle();let deliver;const orig=w.fetch;
 w.fetch=async(url,init)=>url==='/api/company-research'?new Promise(resolve=>{deliver=resolve;}):orig(url,init);
 w.document.getElementById('company-research-open').click();w.document.getElementById('company-research-question').value='产品与业务';
 w.document.getElementById('company-research-form').dispatchEvent(new w.Event('submit',{cancelable:true}));await settle();
 w.document.getElementById('company-research-cancel').click();deliver({ok:true,json:async()=>({...controls.research,preview_id:'canceled'})});await settle();
 assert.equal(w.document.getElementById('company-research').hidden,true);assert.equal(w.document.getElementById('company-research-preview').hidden,true);
 assert.ok(controls.calls.some(c=>c[0]==='/api/company-research-discard'&&c[1].preview_id==='canceled'));dom.window.close();
});

test('return to BOSS opens a tab during the user gesture before any awaited onboarding action',async()=>{
 const {w,dom}=harness('',true,{settings:{extension_paired:true,guide:{active:true,step:'browse'}}});await settle();
 let didOpen=false;w.open=(url)=>{assert.equal(url,'https://www.zhipin.com/web/geek/job-recommend/');didOpen=true;};
 [...w.document.querySelectorAll('#onboarding-flow button')].find(b=>b.textContent==='回到 BOSS 继续').click();assert.equal(didOpen,true);
 const link=w.document.querySelector('a.boss-fallback');assert.ok(link);assert.equal(link.target,'_blank');await settle();dom.window.close();
});


test('research company shortcut opens the current company form without submitting a chat or task',async()=>{
 const {w,dom,controls}=harness('#job=a');await settle();
 [...w.document.querySelectorAll('.chat-tools button')].find(b=>b.textContent==='研究公司').click();
 assert.equal(w.document.getElementById('screen-opportunities').hidden,false);assert.equal(w.document.getElementById('company-panel').open,true);
 assert.equal(w.document.getElementById('company-research').hidden,false);assert.equal(controls.calls.filter(c=>c[0]==='/api/talk'||c[0]==='/api/company-research').length,0);dom.window.close();
});


test('research search configuration is separate from task models and never re-displays the saved key',async()=>{
 const {w,dom,controls}=harness('#page=settings',true,{settings:{search_provider:'tavily',has_search_api_key:true}});await settle();
 assert.equal(w.document.getElementById('search-provider').value,'tavily');assert.equal(w.document.getElementById('search-api-key').value,'');
 w.document.getElementById('test-search').click();await settle();assert.ok(controls.calls.some(c=>c[0]==='/api/search-test'));assert.match(w.document.getElementById('search-status').textContent,/固定公司/);
 w.document.getElementById('search-api-key').value='dummy-search-token';w.document.getElementById('save-search').click();await settle();
 const saved=controls.calls.find(c=>c[0]==='/api/companion'&&c[1]?.search_api_key);assert.equal(saved[1].search_api_key,'dummy-search-token');assert.equal(w.document.getElementById('search-api-key').value,'');assert.equal(saved[1].task_models,undefined);dom.window.close();
});

test('research preview distinguishes already saved sources and disables redundant confirmation',async()=>{
 const {w,dom}=harness('#job=a');await settle();
 w.renderCompanyResearchPreview({company_name:'虚构公司',preview_id:'saved-preview',sources:[{url:'https://example.com/a',title:'已保存来源',excerpt:'虚构来源正文',already_saved:true,source_type:'public_search_excerpt'}]});
 assert.match(w.document.getElementById('company-research-summary').textContent,/没有新增来源/);
 assert.equal(w.document.getElementById('company-research-confirm').disabled,true);
 assert.match(w.document.getElementById('company-research-sources').textContent,/已保存/);dom.window.close();
});
