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
 const controls={calls:[],data,errors,company:fixture.company||null};w.setInterval=fn=>{controls.refresh=fn;return 1;};
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'));};
 const settings={ready,persona:'gentle',buddy_name:'小伴',personas:{gentle:{hello:'你好'},direct:{hello:'直接说判断。'}},provider:'api',voice_enabled:true,voice_base_url:'https://api.openai.com/v1',voice_stt_model:'gpt-transcribe',voice_tts_model:'gpt-4o-mini-tts',voice_name:'marin',voice_cloud_ready:false,voice_local_stt_ready:false,...(fixture.settings||{})};
 controls.settings=settings;controls.connectionOK=true;
 w.fetch=async(url,init)=>{const value=init?.body?JSON.parse(init.body):null;controls.calls.push([url,value]);let r={};
  if(url==='/api/session')r={token:'local-test',version:'0.10.0',execution:'codex-worker'};
  if(url==='/api/state')r=data;
  if(url==='/api/companion')r=settings;
  if(url==='/api/onboarding'){if(value?.action==='connection')settings.guide={active:true,step:'persona',job:null};if(value?.action==='back')settings.guide={active:true,step:'connection',job:null};if(value?.action==='connection-settings')settings.guide={active:true,step:'connection',job:null};if(['complete','skip'].includes(value?.action))settings.guide={active:false,step:'complete',job:null};r=settings;}
  if(url==='/api/connection-test')r={ok:controls.connectionOK,message:controls.connectionOK?'连接正常':'未找到本机 Codex'};
  if(url==='/api/extension-code')r={code:'test-pairing-code',expires_in:300};
  if(url==='/api/history')r={turns:[]};
  if(url==='/api/resume-versions')r={versions:[]};
  if(url==='/api/company')r={company:controls.company};
  if(url==='/api/result-viewed'){data.tasks.find(t=>t.id===value.task_id).viewed=value.viewed;r={viewed:value.viewed};}
  if(url==='/api/quick-event')r={already_recorded:false};
  if(url==='/api/journey')r={summary:{companies:0,applications:0,greetings:0,resume_versions:0,span_days:0},events:[],facts:[]};
  return {ok:true,json:async()=>r};
 };
 vm.runInContext(fs.readFileSync(path.join(root,'workspace.js'),'utf8'),dom.getInternalVMContext());vm.runInContext(fs.readFileSync(path.join(root,'app.js'),'utf8'),dom.getInternalVMContext());
 return {w,dom,controls};
}
test('returning user lands in chat, setup/settings hidden, no duplicate IDs',async()=>{
 const {w,dom,controls}=harness('#job=a');await settle();
 assert.deepEqual(controls.errors,[]);assert.equal(w.document.getElementById('screen-chat').hidden,false);
 assert.equal(w.document.getElementById('screen-profile').hidden,true);assert.equal(w.document.getElementById('screen-settings').hidden,true);
 const ids=[...w.document.querySelectorAll('[id]')].map(n=>n.id);assert.equal(new Set(ids).size,ids.length);
 assert.equal(w.document.getElementById('chat-panel').closest('#screen-chat').id,'screen-chat');dom.window.close();
});
test('cloud voice controls disclose privacy and keep text as the confirmed input',async()=>{
 const {w,dom,controls}=harness('#job=a');await settle();
 assert.match(w.document.getElementById('voice-settings').textContent,/原始音频默认不保存/);
 assert.match(w.document.getElementById('voice-settings').textContent,/AI 合成声音/);
 assert.equal(w.document.getElementById('voice-record').type,'button');
 assert.equal(w.document.getElementById('interview-voice-record').type,'button');
 w.document.querySelector('[data-page="settings"]').click();
 w.document.getElementById('voice-api-key').value='synthetic-voice-key';
 w.document.getElementById('provider-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await settle();
 const saved=controls.calls.find(c=>c[0]==='/api/companion'&&c[1]?.voice_stt_model)[1];
 assert.equal(saved.voice_stt_model,'gpt-transcribe');assert.equal(saved.voice_tts_model,'gpt-4o-mini-tts');assert.equal(saved.voice_api_key,'synthetic-voice-key');
 assert.equal(controls.calls.some(c=>c[0]==='/api/talk'),false);dom.window.close();
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
 assert.equal(w.document.body.classList.contains('first-use-mode'),false);assert.equal(w.document.getElementById('screen-settings').hidden,false);assert.equal(controls.settings.ready,false);
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
 assert.equal(w.document.body.dataset.guideStep,'connection');assert.match(w.document.getElementById('pair-code').textContent,/成功/);
 assert.equal(w.document.getElementById('screen-settings').hidden,false);dom.window.close();
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
 w.document.querySelector('[data-opportunity="interview"]').click();assert.match(w.document.getElementById('task-list').textContent,/B的面试卡/);assert.doesNotMatch(w.document.getElementById('task-list').textContent,/A的简历/);
 [...w.document.querySelectorAll('#job-list button')].find(n=>n.textContent.includes('岗位A')).click();await settle();assert.equal(w.document.getElementById('message').value,'给A的问题');dom.window.close();
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
