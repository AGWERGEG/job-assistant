// npm install --prefix <scratch-dir> jsdom@26
// NODE_PATH=<scratch-dir>/node_modules node --test tests/test_extension.cjs
const {test}=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');const {JSDOM}=require('jsdom');
const dir=path.join(__dirname,'../extension');
const code=n=>fs.readFileSync(path.join(dir,n),'utf8');
const jd='负责客户沟通与产品演示，了解客户需求并配合技术团队推进方案测试，要求本科，能够整理用户反馈并进行基础数据统计。';
function documentFixture(key='job0001'){
 const dom=new JSDOM(`<div class="job-banner"><div class="name"><h1>销售 ${key}</h1></div><span class="salary">8—12K</span></div><div class="company-info"><span class="company-name">虚构公司</span></div><div class="job-detail"><div class="job-sec-text">${jd}<span style="display:none">不要读我</span></div></div>`,{url:`https://www.zhipin.com/job_detail/${key}.html`,runScripts:'outside-only'});
 const w=dom.window;w.HTMLElement.prototype.getClientRects=function(){return [{width:20,height:20}];};w.eval(code('extractor.js'));return dom;
}
test('independent job extraction strips tracking + hidden content; ten job switches',()=>{
 const dom=documentFixture();const w=dom.window;
 for(let i=0;i<10;i++){
  const key='job000'+i;w.document.querySelector('h1').textContent='销售 '+key;
  const r=w.JobAssistantExtractor.extract(w.document,`https://www.zhipin.com/job_detail/${key}.html?token=secret`);
  assert.equal(r.status,'ready');assert.equal(r.capture.job_key,key);assert.equal(r.capture.title,'销售 '+key);
  assert.ok(!r.capture.url.includes('secret'));assert.ok(!r.capture.jd.includes('不要读我'));
 }
 dom.window.close();
});
test('missing identity / ambiguous panes / short JD fail closed',()=>{
 const dom=documentFixture();const w=dom.window;
 assert.equal(w.JobAssistantExtractor.extract(w.document,'https://www.zhipin.com/web/geek/jobs').status,'unavailable');
 const copy=w.document.querySelector('.job-detail').cloneNode(true);w.document.body.append(copy);
 assert.equal(w.JobAssistantExtractor.extract(w.document,w.location.href).status,'ambiguous');copy.remove();
 w.document.querySelector('.job-sec-text').textContent='加载中';
 assert.equal(w.JobAssistantExtractor.extract(w.document,w.location.href).status,'incomplete');
 dom.window.close();
});
test('URL and embedded detail link mismatch rejected; chat is not scraped',()=>{
 const dom=documentFixture();const w=dom.window;
 const link=w.document.createElement('a');link.href='https://www.zhipin.com/job_detail/job9999.html';link.textContent='查看职位';w.document.querySelector('.job-detail').append(link);
 assert.equal(w.JobAssistantExtractor.extract(w.document,w.location.href).status,'incomplete');
 assert.equal(w.JobAssistantExtractor.extract(w.document,'https://www.zhipin.com/web/geek/chat').status,'chat');
 dom.window.close();
});
async function settle(){for(let i=0;i<10;i++)await new Promise(r=>setImmediate(r));}
test('2026 split view resolves description by heading and more-info link, binds company from matching card',()=>{
 const dom=documentFixture();const w=dom.window;
 w.document.body.innerHTML=`<ul><li><a href="/job_detail/job0001.html">大客户经理</a><a href="/gongsi/companyA.html">测试机器人公司</a></li><li><a href="/job_detail/job0002.html">其他岗位</a><a href="/gongsi/companyB.html">其他公司</a></li></ul><article class="new-layout"><div><span>大客户经理</span><span>\ue031-\ue035K</span></div><h3>职位描述</h3><div>${jd}<span hidden>隐形假要求</span></div><h2>测试招聘经理</h2><p>测试机器人公司 · 招聘经理</p><a href="/job_detail/job0001.html?securityId=secret">查看更多信息</a></article>`;
 let result=w.JobAssistantExtractor.extract(w.document,'https://www.zhipin.com/web/geek/jobs');
 assert.equal(result.status,'ready');assert.equal(result.capture.title,'大客户经理');assert.equal(result.capture.company,'测试机器人公司');assert.equal(result.capture.job_key,'job0001');
 assert.ok(!result.capture.jd.includes('招聘经理'));assert.ok(!result.capture.jd.includes('隐形'));assert.ok(!/[\uE000-\uF8FF]/.test(result.capture.jd));assert.ok(!result.capture.url.includes('secret'));
 w.document.querySelector('article span').textContent='其他岗位';
 result=w.JobAssistantExtractor.extract(w.document,'https://www.zhipin.com/web/geek/jobs');assert.equal(result.status,'ready');assert.equal(result.capture.job_key,'job0001');
 w.document.querySelector('article a').href='/job_detail/job0002.html';
 result=w.JobAssistantExtractor.extract(w.document,'https://www.zhipin.com/web/geek/jobs');assert.equal(result.status,'ready');assert.equal(result.capture.company,'其他公司');
 const report=w.JobAssistantExtractor.diagnose(w.document,'https://www.zhipin.com/web/geek/jobs');assert.ok(!JSON.stringify(report).includes('测试招聘经理'));assert.ok(!JSON.stringify(report).includes(jd));dom.window.close();
});
test('real diagnostic layout uses p.desc and more-job-btn even when list/detail titles differ slightly',()=>{
 const dom=documentFixture();const w=dom.window;
 w.document.body.innerHTML=`<div class="job-list-container"><ul><li class="job-card-wrapper selected"><a class="job-name" href="/job_detail/job0001.html">GPU算力销售...</a><a class="company-name" href="/gongsi/companyA.html">网鼎科技</a></li></ul></div><div class="job-detail-container"><div class="job-detail-box"><div class="job-detail-header"><h2 class="job-name">GPU算力销售</h2></div><div class="job-detail-body"><div class="job-detail-operate"></div><h3 class="title">职位描述</h3><ul class="job-label-list"><li>ToB</li></ul><p class="desc">${jd}</p><div class="job-boss-info">招聘者信息不要进入JD</div><div class="job-address">地址不要进入JD</div><a class="more-job-btn" href="/job_detail/job0001.html?securityId=secret">查看更多信息</a></div></div></div>`;
 let result=w.JobAssistantExtractor.extract(w.document,'https://www.zhipin.com/web/geek/jobs?ka=header-jobs');
 assert.equal(result.status,'ready');assert.equal(result.capture.title,'GPU算力销售');assert.equal(result.capture.company,'网鼎科技');assert.ok(result.capture.jd.includes(jd));assert.ok(!result.capture.jd.includes('招聘者'));
 w.document.querySelector('.job-detail-header h2').textContent='完全不同岗位';
 result=w.JobAssistantExtractor.extract(w.document,'https://www.zhipin.com/web/geek/jobs');assert.equal(result.status,'incomplete');dom.window.close();
});
test('independent page with multiple legacy blocks isolates 职位描述 rather than company introduction',()=>{
 const dom=documentFixture();const w=dom.window;
 w.document.body.innerHTML=`<div class="job-banner"><h1>市场商务助理</h1></div><main><section><h3>职位描述</h3><div class="new-text">${jd}</div></section><section><h3>公司介绍</h3><div class="job-sec-text">其他企业内容</div></section><aside><a href="/gongsi/abc.html">测试智能</a></aside><div class="job-sec-text">推荐内容</div></main>`;
 const result=w.JobAssistantExtractor.extract(w.document,w.location.href);assert.equal(result.status,'ready');assert.equal(result.capture.company,'测试智能');assert.ok(result.capture.jd.includes(jd));assert.ok(!result.capture.jd.includes('企业内容'));dom.window.close();
});
test('diagnostic independent layout with two job-sec-text chooses block under 职位描述',()=>{
 const dom=documentFixture('job0003');const w=dom.window;
 w.document.body.innerHTML=`<div class="job-banner"><div class="job-primary"><h1>央企直聘销售经理</h1><span class="salary">15-20K</span></div></div><section class="job-detail"><h3>职位描述</h3><div class="job-sec-text">${jd}</div><h3>公司介绍</h3><div class="job-sec-text">中国人寿相关企业介绍，上市公司，企业规模和品牌信息，不是岗位职责。</div></section><aside><a class="company-name" href="/gongsi/chinalife.html">中国人寿</a></aside>`;
 const result=w.JobAssistantExtractor.extract(w.document,'https://www.zhipin.com/job_detail/job0003.html?ka=index');
 assert.equal(result.status,'ready');assert.equal(result.capture.title,'央企直聘销售经理');assert.equal(result.capture.company,'中国人寿');assert.ok(result.capture.jd.includes(jd));assert.ok(!result.capture.jd.includes('企业介绍'));dom.window.close();
});
test('independent company resolver accepts one gongsi link and diagnostic exposes structure only',()=>{
 const dom=documentFixture('job0004');const w=dom.window;
 w.document.body.innerHTML=`<header class="job-primary"><h1>销售经理</h1></header><main class="job-detail"><div><h3>职位描述</h3><div class="job-sec-text">${jd}</div></div><div><h3>任职要求</h3><div class="job-sec-text">本科及以上，有销售经验。</div></div><div><h3>公司介绍</h3><div class="job-sec-text">这里是公司介绍模块，不能合并进职位正文。</div></div></main><aside><a href="/gongsi/companyOnly.html"><span>灵核数智</span></a></aside>`;
 const result=w.JobAssistantExtractor.extract(w.document,'https://www.zhipin.com/job_detail/job0004.html');assert.equal(result.status,'ready');assert.equal(result.capture.company,'灵核数智');assert.ok(result.capture.jd.includes(jd));assert.ok(!result.capture.jd.includes('公司介绍模块'));
 const d=w.JobAssistantExtractor.diagnose(w.document,'https://www.zhipin.com/job_detail/job0004.html');assert.equal(d.adapter_version,'0.6.0-diagnostic');assert.equal(d.text_blocks.length,3);assert.equal(d.candidates.company_links.length,1);assert.ok(!JSON.stringify(d).includes('灵核数智'));assert.ok(!JSON.stringify(d).includes(jd));dom.window.close();
});
test('exact 0.4.4 diagnostic layout selects direct job-detail-section text and excludes salary/company text',()=>{
 const dom=documentFixture('job0005');const w=dom.window;
 w.document.body.innerHTML=`<div class="job-banner"><div class="job-primary"><h1>销售经理</h1></div></div><main class="job-detail"><div class="job-detail-section"><div class="job-sec-text">${jd}</div></div><div class="detail-section-item salary-info"><h3>薪资详情</h3><div class="job-sec-text">薪资范围：10000-15000元/月，按回款提成。</div></div><div class="detail-section-item company-info-box"><h3>公司介绍</h3><a href="/gongsi/core.html">灵核数智</a><div class="job-sec-text fold-text">公司介绍内容，有融资和规模等信息，不是岗位正文。</div></div></main><footer>${Array.from({length:46},(_,i)=>`<a href="/gongsi/other${i}.html"></a>`).join('')}</footer>`;
 const result=w.JobAssistantExtractor.extract(w.document,'https://www.zhipin.com/job_detail/job0005.html?ka=hot-job-2');assert.equal(result.status,'ready');assert.equal(result.capture.company,'灵核数智');assert.ok(result.capture.jd.includes(jd));assert.ok(!result.capture.jd.includes('薪资范围'));assert.ok(!result.capture.jd.includes('公司介绍内容'));dom.window.close();
});
test('independent exact page accepts job-detail-section even when it is not under job-detail',()=>{
 const dom=documentFixture('75faeae95aa030030nF53Nu9EFFY');const w=dom.window;
 const body='岗位职责：负责来料检验、质量异常跟进和供应商协同，整理检验记录并推动问题闭环。任职资格与要求：大专及以上，能读懂基础图纸，具备良好沟通能力。';
 w.document.body.innerHTML=`<div class="job-banner"><div class="job-primary"><h1>来料检验员</h1></div></div><div class="job-detail"><div class="job-detail-placeholder"></div></div><main class="detail-page"><section class="job-detail-section"><h3 class="section-title">职位描述</h3><div class="job-sec-text">${body}</div></section><section class="detail-section-item salary-info"><h3>薪资</h3><div class="job-sec-text">8-12K·13薪</div></section><section class="detail-section-item company-info-box"><h3>公司介绍</h3><a href="/gongsi/moxin.html">魔芯（杭州）科技</a><div class="job-sec-text fold-text">公司介绍内容，不是岗位职责。</div></section></main>${Array.from({length:46},(_,i)=>`<a href="/gongsi/other${i}.html"></a>`).join('')}`;
 const result=w.JobAssistantExtractor.extract(w.document,'https://www.zhipin.com/job_detail/75faeae95aa030030nF53Nu9EFFY.html');
 assert.equal(result.status,'ready');assert.equal(result.capture.title,'来料检验员');assert.equal(result.capture.company,'魔芯（杭州）科技');assert.ok(result.capture.jd.includes('岗位职责'));assert.ok(!result.capture.jd.includes('公司介绍内容'));assert.ok(!result.capture.jd.includes('8-12K·13薪'));
 const d=w.JobAssistantExtractor.diagnose(w.document,'https://www.zhipin.com/job_detail/75faeae95aa030030nF53Nu9EFFY.html');assert.equal(d.adapter_version,'0.6.0-diagnostic');assert.equal(d.text_blocks.length,3);dom.window.close();
});
function panelHarness(options={}){
 const dom=new JSDOM(code('panel.html'),{url:'https://extension-test.invalid/panel.html',runScripts:'outside-only',pretendToBeVisual:true});const w=dom.window;
 const controls={key:'job0001',calls:[],tick:null,turns:[],tabId:10,opens:[],holdHistory:false,jd,stable:3000,status:'ready',hint:null,companyKey:'',companyCapture:null,boundJob:'',...options};
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
 w.setInterval=fn=>{controls.tick=fn;return 1;};
 const capture=()=>({job_key:controls.key,url:'https://www.zhipin.com/job_detail/'+controls.key+'.html',title:controls.key,company:'虚构公司',company_key:controls.companyKey,jd:controls.jd,method:'dom'});
 w.chrome={windows:{getCurrent:async()=>({id:1})},tabs:{query:async()=>[{id:controls.tabId,url:controls.url||capture().url}],sendMessage:async()=>({status:controls.status,capture:controls.status==='ready'?capture():undefined,stable_ms:controls.stable,identity:controls.hint,company_capture:controls.companyCapture}),create:async x=>controls.opens.push(x)},runtime:{sendMessage:async m=>{
  if(m.type==='JA_CONNECTION')return {ok:true,value:{connected:controls.connected!==false,port:8421}};
  if(m.type==='JA_API'){
   controls.calls.push(m);
   if(m.path==='/restore'){
    if(!controls.saved)return {ok:true,value:{job:null,seq:m.value.seq}};
    controls.boundJob=controls.saved.job_key;return {ok:true,value:{seq:m.value.seq,job:{id:controls.saved.job_key,title:controls.saved.title,company:'虚构公司',company_key:controls.saved.company_key||'',url:controls.saved.url},capture:controls.saved}};
   }
   if(m.path==='/status')return {ok:true,value:{ready:true,buddy_name:'小树',worker_enabled:true,guide:controls.guide||null}};
   if(m.path==='/capture'){controls.boundJob=m.value.capture?.job_key||'';return {ok:true,value:{seq:m.value.seq,job:m.value.capture?{id:m.value.capture.job_key,title:m.value.capture.title,company_key:controls.companyKey,company:'虚构公司',url:m.value.capture.url,revision:1}:null}};}
   if(m.path==='/confirm')return {ok:true,value:{confirmed:true}};
   if(m.path==='/history'){
    if(controls.staleRevision)return {ok:false,error:'岗位内容已更新，请重新识别并确认'};
    if(controls.holdHistory)return await new Promise(resolve=>{controls.resolveHistory=resolve;});
    return {ok:true,value:{seq:m.value.seq,job_id:controls.boundJob,turns:controls.turns}};
   }
   if(m.path==='/talk'){
    const task={task_id:'task1',kind:m.value.kind,text:m.value.text,status:'queued',workbench:m.value.kind==='tailor_resume'};
    controls.turns.push(task);return {ok:true,value:{seq:m.value.seq,job_id:controls.boundJob,task:{id:'task1',status:'queued'}}};
   }
   if(m.path==='/sync'){controls.staleRevision=false;return {ok:true,value:{seq:m.value.seq,job:{id:controls.boundJob,title:'工作台修改后的岗位',company:'虚构公司',url:capture().url,revision:2}}};}
   if(m.path==='/onboarding-complete'){controls.guide={active:false,step:'complete',job:null};return {ok:true,value:{guide:controls.guide}};}
   if(m.path==='/company-save')return {ok:true,value:{company:{evidence:[{}]},seq:m.value.seq,job_id:controls.boundJob}};
  }
  return {ok:true,value:{}};
 }}};
 w.eval(code('panel.js'));return {dom,w,controls};
}
test('unpaired sidebar opens workbench pairing before asking for a job',async()=>{
 const {dom,w,controls}=panelHarness({connected:false});await settle();assert.equal(w.document.getElementById('pairing').open,true);
 assert.match(w.document.getElementById('open-onboarding').textContent,/获取配对码/);w.document.getElementById('open-onboarding').click();await settle();
 assert.match(controls.opens.at(-1).url,/pairing=1/);assert.equal(controls.calls.length,0);dom.window.close();
});
test('compact target switch stays explicit and restores per-job unsent drafts',async()=>{
 const {dom,w,controls}=panelHarness();await settle();
 assert.equal(w.document.getElementById('candidate-notice').hidden,false);
 w.document.getElementById('switch-target').click();await settle();assert.equal(controls.boundJob,'job0001');
 assert.equal(w.document.getElementById('candidate-notice').hidden,true);
 w.document.getElementById('message').value='给原岗位的草稿';
 w.document.getElementById('target-details').click();assert.equal(w.document.getElementById('details-dialog').open,true);
 w.document.getElementById('close-details').click();assert.equal(w.document.getElementById('details-dialog').open,false);
 controls.key='job0002';await controls.tick();await settle();assert.equal(controls.boundJob,'job0001');
 assert.equal(w.document.getElementById('candidate-notice').hidden,false);
 w.document.getElementById('switch-target').click();await settle();assert.equal(controls.boundJob,'job0002');assert.equal(w.document.getElementById('message').value,'');
 controls.key='job0001';await controls.tick();await settle();w.document.getElementById('switch-target').click();await settle();
 assert.equal(w.document.getElementById('message').value,'给原岗位的草稿');assert.equal(controls.calls.filter(c=>c.path==='/talk').length,0);dom.window.close();
});
test('first guide action explicitly replaces restored A with visible B before analysis',async()=>{
 const saved={job_key:'old0001',title:'原岗位',company:'虚构公司',url:'https://www.zhipin.com/job_detail/old0001.html',jd};
 const {dom,w,controls}=panelHarness({saved,guide:{active:true,step:'first_reply',job:{id:'old0001'}}});await settle();
 w.document.getElementById('onboarding-open').click();await settle();
 assert.equal(controls.boundJob,'job0001');assert.equal(controls.calls.filter(c=>c.path==='/confirm').length,1);assert.equal(controls.calls.filter(c=>c.path==='/talk').length,1);dom.window.close();
});
test('restored same job guide analyzes without reconfirmation and carries input',async()=>{
 const saved={job_key:'job0001',title:'已确认目标',company:'虚构公司',url:'https://www.zhipin.com/job_detail/job0001.html',method:'restored'};
 const {dom,w,controls}=panelHarness({saved,guide:{active:true,step:'first_reply',job:{id:'job0001'}}});await settle();
 w.document.getElementById('message').value='重点看薪资结构';w.document.getElementById('onboarding-open').click();await settle();
 const call=controls.calls.find(c=>c.path==='/talk');assert.ok(call);assert.equal(call.value.text,'重点看薪资结构');
 assert.equal(controls.calls.filter(c=>c.path==='/confirm').length,0);dom.window.close();
});
test('first shortcut preserves typed constraints through confirmation',async()=>{
 const {dom,w,controls}=panelHarness();await settle();w.document.getElementById('message').value='只考虑杭州';
 w.document.querySelector('[data-kind="quick_analysis"]').click();await settle();
 assert.equal(controls.calls.find(c=>c.path==='/talk').value.text,'只考虑杭州');dom.window.close();
});
test('revision conflict offers explicit sync without recapturing and preserves draft',async()=>{
 const {dom,w,controls}=panelHarness();await settle();w.document.getElementById('confirm').click();await settle();
 const captures=controls.calls.filter(c=>c.path==='/capture').length;controls.staleRevision=true;
 w.document.getElementById('message').value='继续刚才的问题';await controls.tick();await settle();
 assert.equal(w.document.getElementById('switch-target').textContent,'同步已保存岗位');assert.equal(w.document.getElementById('send').disabled,true);
 w.document.getElementById('switch-target').click();await settle();await controls.tick();await settle();
 assert.equal(controls.calls.filter(c=>c.path==='/sync').length,1);assert.equal(controls.calls.filter(c=>c.path==='/capture').length,captures);
 assert.equal(w.document.getElementById('message').value,'继续刚才的问题');assert.equal(w.document.getElementById('send').disabled,false);
 assert.match(w.document.getElementById('chat-target').textContent,/工作台修改后/);dom.window.close();
});
test('side panel reads without model calls and shortcuts can explicitly select first job',async()=>{
 const {dom,w,controls}=panelHarness();await settle();
 assert.equal(w.document.getElementById('title').textContent,'job0001');
 const button=w.document.querySelector('[data-kind="quick_analysis"]');assert.equal(button.disabled,false);
 assert.equal(controls.calls.filter(c=>c.path==='/talk').length,0);
 assert.equal(controls.calls.filter(c=>c.path==='/capture'&&c.value.capture).length,0);
 w.document.getElementById('confirm').click();await settle();assert.equal(button.disabled,false);
 button.click();await settle();assert.equal(controls.calls.filter(c=>c.path==='/talk').length,1);
 assert.match(w.document.getElementById('messages').textContent,/排队/);
 controls.turns[0].status='done';controls.turns[0].reply='可以先问清日常工作';
 await controls.tick();await settle();assert.match(w.document.getElementById('messages').textContent,/日常工作/);
 controls.key='job0002';await controls.tick();await settle();
 assert.equal(w.document.getElementById('title').textContent,'job0002');assert.equal(button.disabled,true);
 assert.ok(w.document.getElementById('messages').textContent.includes('可以先问清'));assert.equal(controls.boundJob,'job0001');
 dom.window.close();
});
test('first-use side panel combines explicit job confirmation and first analysis',async()=>{
 const {dom,w,controls}=panelHarness({guide:{active:true,step:'browse',job:null}});await settle();
 assert.equal(w.document.getElementById('onboarding-card').hidden,false);
 assert.match(w.document.getElementById('onboarding-open').textContent,/就看这个/);
 assert.equal(controls.calls.filter(c=>c.path==='/confirm').length,0);
 w.document.getElementById('onboarding-open').click();await settle();
 assert.equal(controls.calls.filter(c=>c.path==='/confirm').length,1);assert.equal(controls.calls.filter(c=>c.path==='/talk').length,1);
 assert.equal(controls.calls.find(c=>c.path==='/talk').value.kind,'quick_analysis');dom.window.close();
});
test('first useful reply can finish onboarding inside the side panel',async()=>{
 const {dom,w,controls}=panelHarness({guide:{active:true,step:'first_success',job:{id:'job0001',title:'岗位A',company:'虚构公司'}}});await settle();
 assert.match(w.document.getElementById('onboarding-card').textContent,/已经会用/);w.document.getElementById('onboarding-open').click();await settle();
 assert.equal(controls.calls.filter(c=>c.path==='/onboarding-complete').length,1);assert.equal(w.document.body.classList.contains('guide-active'),false);dom.window.close();
});
test('side panel conversation submits text and blocks duplicate clicks until complete',async()=>{
 const {dom,w,controls}=panelHarness();await settle();w.document.getElementById('confirm').click();await settle();
 w.document.getElementById('message').value='我缺少相关经验，应该怎么说？';
 w.document.getElementById('send').click();w.document.getElementById('send').click();await settle();
 const calls=controls.calls.filter(c=>c.path==='/talk');assert.equal(calls.length,1);assert.equal(calls[0].value.kind,'companion_chat');assert.match(calls[0].value.text,/相关经验/);assert.ok(calls[0].value.request_id);
 assert.equal(w.document.getElementById('send').disabled,true);dom.window.close();
});
test('resume delivery opens exact job/task in workbench',async()=>{
 const {dom,w,controls}=panelHarness();await settle();w.document.getElementById('confirm').click();await settle();
 w.document.querySelector('[data-kind="tailor_resume"]').click();await settle();
 controls.turns[0].status='done';controls.turns[0].reply='整份简历不应占满侧栏';
 await controls.tick();await settle();
 const messages=w.document.getElementById('messages');assert.ok(!messages.textContent.includes('整份简历不应占满侧栏'));
 Array.from(messages.querySelectorAll('button')).find(b=>b.textContent==='去工作台查看').click();
 assert.match(controls.opens[0].url,/#job=job0001&task=task1$/);dom.window.close();
});
test('page changing immediately before click blocks old job submission',async()=>{
 const {dom,w,controls}=panelHarness();await settle();w.document.getElementById('confirm').click();await settle();
 controls.key='job0002';w.document.querySelector('[data-kind="suggest_reply"]').click();await settle();
 assert.equal(controls.calls.filter(c=>c.path==='/talk').length,0);assert.match(w.document.getElementById('status').textContent,/页面已变化/);dom.window.close();
});
test('same job scrolling and unstable body keep confirmation, history and original snapshot',async()=>{
 const {dom,w,controls}=panelHarness();controls.url='https://www.zhipin.com/web/geek/jobs';await settle();
 w.document.getElementById('confirm').click();await settle();
 controls.turns=[{task_id:'saved',kind:'companion_chat',text:'之前的问题',status:'done',reply:'之前的回复'}];
 await controls.tick();await settle();
 const before=controls.calls.filter(c=>c.path==='/capture').length;
 controls.jd+='展开更多内容，薪资说明';controls.stable=0;
 await controls.tick();await settle();
 assert.equal(controls.calls.filter(c=>c.path==='/capture').length,before);
 assert.equal(w.document.getElementById('confirm').textContent,'已确认目标岗位');
 assert.match(w.document.getElementById('messages').textContent,/之前的回复/);
 w.document.querySelector('[data-kind="suggest_reply"]').click();await settle();
 assert.equal(controls.calls.filter(c=>c.path==='/talk').length,1);
 dom.window.close();
});
test('missing body keeps pinned chat usable without reading uncertain page',async()=>{
 const {dom,w,controls}=panelHarness();controls.url='https://www.zhipin.com/web/geek/jobs';await settle();
 w.document.getElementById('confirm').click();await settle();
 controls.turns=[{task_id:'saved',kind:'companion_chat',text:'问题',status:'done',reply:'保留回复'}];
 controls.status='unavailable';controls.hint={job_key:'job0001',source:'selected-card'};
 await controls.tick();await settle();assert.equal(w.document.getElementById('send').disabled,false);
 const before=controls.calls.filter(c=>c.path==='/capture').length;
 controls.hint={job_key:null};await controls.tick();await settle();
 assert.equal(w.document.getElementById('send').disabled,false);
 assert.match(w.document.getElementById('messages').textContent,/保留回复/);
 assert.equal(controls.calls.filter(c=>c.path==='/capture').length,before);
 controls.status='ready';controls.stable=0;await controls.tick();await settle();
 assert.equal(w.document.getElementById('send').disabled,false);dom.window.close();
});
test('left card switching to B preserves explicitly labelled A chat',async()=>{
 const {dom,w,controls}=panelHarness();controls.url='https://www.zhipin.com/web/geek/jobs';await settle();
 w.document.getElementById('confirm').click();await settle();
 controls.status='incomplete';controls.hint={job_key:'job0002',source:'selected-card',conflict:true};
 await controls.tick();await settle();
 assert.equal(w.document.getElementById('send').disabled,false);
 assert.equal(controls.boundJob,'job0001');
 controls.key='job0002';controls.status='ready';controls.hint={job_key:'job0002'};
 await controls.tick();await settle();assert.equal(w.document.getElementById('title').textContent,'job0002');
 assert.equal(w.document.getElementById('confirm').disabled,false);dom.window.close();
});
test('identity detector uses selected card independent of description and ignores active detail labels',()=>{
 const dom=documentFixture();const w=dom.window;
 w.document.body.innerHTML='<div class="job-list-container"><ul><li class="job-card-wrapper selected"><a href="/job_detail/job0001.html">A</a></li></ul></div><div class="job-detail-container"><span class="active">展开内容</span><a class="more-job-btn" href="/job_detail/job0001.html">查看更多信息</a></div>';
 let r=w.JobAssistantExtractor.pageIdentity(w.document,'https://www.zhipin.com/web/geek/jobs');
 assert.equal(r.job_key,'job0001');assert.equal(r.conflict,false);
 w.document.querySelector('li a').href='/job_detail/job0002.html';
 r=w.JobAssistantExtractor.pageIdentity(w.document,'https://www.zhipin.com/web/geek/jobs');assert.equal(r.job_key,'job0002');assert.equal(r.conflict,true);dom.window.close();
});
test('content snapshot does not mistake right-pane clicks for left card selection',async()=>{
 const dom=documentFixture();const w=dom.window;let listener;
 w.document.body.innerHTML='<div class="job-list-container"><li class="job-card-wrapper selected"><a href="/job_detail/job0001.html"><span>岗位A</span></a></li><li class="job-card-wrapper"><a href="/job_detail/job0002.html"><span id="pick-b">岗位B</span></a></li></div><div class="job-detail-container"><a class="more-job-btn" href="/job_detail/job0001.html">更多信息</a><a id="right-link" href="/job_detail/job0003.html">相关推荐</a></div>';
 w.history.replaceState({},'', '/web/geek/jobs');
 w.JobAssistantExtractor.extract=()=>({status:'ready',capture:{job_key:'job0001',jd}});
 w.chrome={runtime:{id:'test-extension',onMessage:{addListener:fn=>listener=fn}}};w.eval(code('content.js'));
 const snap=()=>{let result;listener({type:'JA_SNAPSHOT'},{id:'test-extension'},x=>result=x);return result;};
 w.document.getElementById('right-link').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
 assert.equal(snap().status,'ready');
 w.document.getElementById('pick-b').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
 const result=snap();assert.equal(result.status,'incomplete');assert.equal(result.identity.job_key,'job0002');dom.window.close();
});
test('company overview and peer pages preserve explicit target across tabs',async()=>{
 const {dom,w,controls}=panelHarness();controls.companyKey='companyA';await settle();w.document.getElementById('confirm').click();await settle();
 const count=controls.calls.filter(c=>c.path==='/capture').length;
 controls.tabId=12;controls.url='https://www.zhipin.com/gongsi/companyA.html';controls.status='company';controls.companyCapture={company_key:'companyA',name:'虚构公司',sections:[{kind:'introduction',text:jd}],jobs:[]};
 await controls.tick();await settle();assert.equal(controls.calls.filter(c=>c.path==='/capture').length,count);assert.equal(w.document.getElementById('send').disabled,false);assert.match(w.document.getElementById('target-label').textContent,/job0001/);
 w.document.getElementById('save-company').click();await settle();assert.equal(controls.calls.filter(c=>c.path==='/company-save').length,1);
 controls.key='job0002';controls.status='ready';controls.url='https://www.zhipin.com/gongsi/job/companyA.html';
 await controls.tick();await settle();assert.equal(controls.boundJob,'job0001');assert.equal(w.document.getElementById('confirm').textContent,'改为目标岗位');
 w.document.getElementById('message').value='这个对照岗位说明什么';w.document.getElementById('send').click();await settle();assert.equal(controls.boundJob,'job0001');
 dom.window.close();
});
test('other company page does not replace target or allow merging',async()=>{
 const {dom,w,controls}=panelHarness();controls.companyKey='companyA';await settle();w.document.getElementById('confirm').click();await settle();
 controls.url='https://www.zhipin.com/gongsi/companyB.html';controls.status='company';controls.companyCapture={company_key:'companyB',name:'其他公司',sections:[],jobs:[]};
 await controls.tick();await settle();assert.equal(controls.boundJob,'job0001');assert.equal(w.document.getElementById('save-company').disabled,true);assert.equal(w.document.getElementById('send').disabled,false);dom.window.close();
});
test('reopened sidebar restores target and history without recapturing JD',async()=>{
 const saved={job_key:'job0001',title:'上次确认的岗位',url:'https://www.zhipin.com/job_detail/job0001.html',method:'restored'};
 const {dom,w,controls}=panelHarness({saved,turns:[{task_id:'old',status:'done',kind:'companion_chat',text:'上一轮',reply:'记得这段对话'}]});await settle();
 assert.equal(controls.boundJob,'job0001');assert.match(w.document.getElementById('messages').textContent,/记得这段对话/);
 assert.equal(controls.calls.filter(c=>c.path==='/capture'&&c.value.capture).length,0);assert.equal(w.document.getElementById('send').disabled,false);dom.window.close();
});
test('streaming partial text is visible before task completion',async()=>{
 const {dom,w,controls}=panelHarness();await settle();w.document.getElementById('confirm').click();await settle();
 controls.turns=[{task_id:'stream',kind:'companion_chat',text:'问题',status:'running',partial:'已经收到第一句。'}];await controls.tick();await settle();
 assert.match(w.document.getElementById('messages').textContent,/已经收到第一句/);assert.equal(w.document.getElementById('send').disabled,true);dom.window.close();
});
test('company page extracts introduction/products, excludes biographies, strips collection label',()=>{
 const dom=documentFixture();const w=dom.window;w.history.replaceState({},'', '/gongsi/companyA~.html');
 w.document.body.innerHTML='<h1>有赞 <span>收藏</span></h1><section><h3>公司简介</h3><div>企业为商家提供软件服务，拥有社交电商、新零售和门店管理业务。</div></section><section><h3>产品介绍</h3><ul><li>零售产品：全渠道经营工具，帮助商家门店与网店增长。</li></ul></section><aside><h3>高管介绍</h3><div>不要读取个人姓名和履历。</div></aside>';
 const r=w.JobAssistantExtractor.extract(w.document,w.location.href);assert.equal(r.status,'company');assert.equal(r.company_capture.name,'有赞');assert.equal(r.company_capture.sections.length,2);assert.ok(!JSON.stringify(r.company_capture).includes('个人姓名'));dom.window.close();
});
test('independent company name ignores many unrelated recommendation links',()=>{
 const dom=documentFixture();const w=dom.window;w.document.body.innerHTML='<h1>销售经理</h1><div class="sider-company"><div class="company-info"><a href="/gongsi/companyA~.html">有赞</a></div></div><div class="job-detail-section"><div class="job-sec-text">'+jd+'</div></div><div class="company-info-box"><h3>公司介绍</h3><div class="job-sec-text">企业为商家提供软件服务，拥有社交电商、新零售和门店管理业务。</div></div><footer><a href="/gongsi/other123.html">其他推荐公司</a></footer>';
 const r=w.JobAssistantExtractor.extract(w.document,w.location.href);assert.equal(r.status,'ready');assert.equal(r.capture.company,'有赞');assert.equal(r.capture.company_key,'companyA~');assert.ok(!r.capture.jd.includes('社交电商'));dom.window.close();
});
test('company recruitment split recognizes colon heading and company without links on cards',()=>{
 const dom=documentFixture();const w=dom.window;w.history.replaceState({},'', '/gongsi/job/companyA~.html');
 w.document.body.innerHTML='<h1>有赞招聘</h1><a href="/gongsi/job/160000/companyA~.html">销售(280)</a><div class="job-list-container"><ul><li class="job-card-wrapper selected"><a href="/job_detail/job0001.html">销售经理</a><span class="salary">15-30K</span><span>招聘者不要采集</span></li></ul></div><article><h3>职位描述：</h3><div>'+jd+'</div><a href="/job_detail/job0001.html">查看更多信息</a></article><aside><a href="/job_detail/other123.html">精选外部岗位</a></aside>';
 const r=w.JobAssistantExtractor.extract(w.document,w.location.href);assert.equal(r.status,'ready');assert.equal(r.capture.company,'有赞');assert.equal(r.company_capture.jobs.length,1);assert.deepEqual([...r.company_capture.categories],['销售(280)']);assert.ok(!JSON.stringify(r.company_capture).includes('招聘者'));dom.window.close();
});
test('extension background rejects content-script callers, keeps pair token in session only',async()=>{
 const vm=require('node:vm');let listener;let session={};let fetches=0;
 const chrome={sidePanel:{setPanelBehavior:async()=>{}},runtime:{id:'a'.repeat(32),getURL:p=>'chrome-extension://'+'a'.repeat(32)+'/'+p,onMessage:{addListener:fn=>listener=fn}},storage:{session:{get:async()=>session,set:async x=>{session={...session,...x};},remove:async()=>{session={};}}}};
 const sandbox={chrome,AbortSignal,Error,Number,JSON,Set,fetch:async()=>{fetches++;return {ok:true,json:async()=>({token:'only-in-background'})};}};
 vm.runInNewContext(code('background.js'),sandbox);
 const caller={id:chrome.runtime.id,url:chrome.runtime.getURL('panel.html')};
 assert.equal(listener({type:'JA_PAIR',code:'123',port:8421},{id:caller.id,url:'https://www.zhipin.com/'},()=>{}),false);
 assert.equal(fetches,0);
 const call=m=>new Promise(resolve=>listener(m,caller,resolve));
 const pair=await call({type:'JA_PAIR',code:'123',port:8421});assert.equal(pair.value.connected,true);assert.equal(pair.value.token,undefined);
 const arbitrary=await call({type:'JA_API',path:'/../../api/state',value:{}});assert.equal(arbitrary.ok,false);assert.equal(fetches,1);
 const complete=await call({type:'JA_API',path:'/onboarding-complete',value:{}});assert.equal(complete.ok,true);assert.equal(fetches,2);
 await call({type:'JA_DISCONNECT'});assert.equal(fetches,3);assert.equal((await call({type:'JA_CONNECTION'})).value.connected,false);
});
test('background resume does not disable sidebar chat or quick analysis',async()=>{
 const {dom,w,controls}=panelHarness();await settle();w.document.getElementById('confirm').click();await settle();
 w.document.querySelector('[data-kind="tailor_resume"]').click();await settle();
 controls.turns[0].status='running';await controls.tick();await settle();
 assert.equal(w.document.getElementById('send').disabled,false);
 assert.equal(w.document.querySelector('[data-kind="quick_analysis"]').disabled,false);
 assert.equal(w.document.querySelector('[data-kind="tailor_resume"]').disabled,true);
 w.document.getElementById('message').value='这个岗位适合长期发展吗';w.document.getElementById('send').click();await settle();
 assert.equal(controls.calls.filter(c=>c.path==='/talk').length,2);
 assert.equal(w.document.getElementById('send').disabled,true);dom.window.close();
});
test('interview entry keeps pinned job and does not launch model or record progress',async()=>{
 const {dom,w,controls}=panelHarness();await settle();w.document.getElementById('confirm').click();await settle();
 w.document.getElementById('interview-workbench').click();await settle();
 assert.match(controls.opens[0].url,/#job=job0001&task=&view=interview$/);
 assert.equal(controls.calls.filter(c=>c.path==='/talk').length,0);
 controls.turns=[{task_id:'prep1',kind:'interview_prep',workbench:true,status:'running',text:'准备面试'}];await controls.tick();await settle();
 assert.equal(w.document.getElementById('send').disabled,false);
 dom.window.close();
});
test('rest sends one model chat request and preserves unsent draft',async()=>{
 const {dom,w,controls}=panelHarness();await settle();w.document.getElementById('confirm').click();await settle();
 w.document.getElementById('message').value='尚未发送的问题';w.document.getElementById('blessing').click();await settle();
 const calls=controls.calls.filter(c=>c.path==='/talk');assert.equal(calls.length,1);assert.equal(calls[0].value.kind,'rest_message');
 assert.equal(w.document.getElementById('message').value,'尚未发送的问题');
 assert.equal(controls.calls.filter(c=>c.path==='/blessing').length,0);dom.window.close();
});
test('first shortcut confirms candidate once and refuses changed page before capture',async()=>{
 const first=panelHarness();await settle();first.w.document.querySelector('[data-kind="quick_analysis"]').click();await settle();
 assert.equal(first.controls.calls.filter(c=>c.path==='/confirm').length,1);assert.equal(first.controls.calls.filter(c=>c.path==='/talk').length,1);first.dom.window.close();
 const next=panelHarness();await settle();next.controls.key='job0002';next.w.document.querySelector('[data-kind="quick_analysis"]').click();await settle();
 assert.equal(next.controls.calls.filter(c=>c.path==='/talk').length,0);assert.equal(next.controls.calls.filter(c=>c.path==='/confirm').length,0);next.dom.window.close();
});
test('uncertain and unrelated pages allow labelled pinned chat but no new page analysis',async()=>{
 const {dom,w,controls}=panelHarness();await settle();w.document.getElementById('confirm').click();await settle();
 controls.url='https://example.org/';await controls.tick();await settle();
 assert.match(w.document.getElementById('chat-target').textContent,/job0001/);
 assert.equal(w.document.getElementById('send').disabled,false);assert.equal(w.document.querySelector('[data-kind="quick_analysis"]').disabled,true);
 w.document.getElementById('message').value='我们继续聊之前的岗位';w.document.getElementById('send').click();await settle();
 assert.equal(controls.boundJob,'job0001');assert.equal(controls.calls.filter(c=>c.path==='/talk').length,1);dom.window.close();
});
