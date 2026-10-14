// npm install --prefix <scratch-dir> jsdom@26
// NODE_PATH=<scratch-dir>/node_modules node --test tests/test_extension.cjs
const {test}=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');const {JSDOM}=require('jsdom');
const {webcrypto}=require('node:crypto');const {TextEncoder}=require('node:util');
const dir=path.join(__dirname,'../extension');
const code=n=>fs.readFileSync(path.join(dir,n),'utf8');
const manifest=JSON.parse(code('manifest.json'));const extensionVersion=manifest.version_name||manifest.version;
const jd='负责客户沟通与产品演示，了解客户需求并配合技术团队推进方案测试，要求本科，能够整理用户反馈并进行基础数据统计。';
async function hmacHex(token,nonce){const key=await webcrypto.subtle.importKey('raw',new TextEncoder().encode(token),{name:'HMAC',hash:'SHA-256'},false,['sign']);return Array.from(new Uint8Array(await webcrypto.subtle.sign('HMAC',key,new TextEncoder().encode(nonce))),b=>b.toString(16).padStart(2,'0')).join('');}
function backgroundContext(chrome,fetch){return {chrome,AbortSignal,Error,Number,JSON,Set,Array,TextEncoder,crypto:webcrypto,fetch};}
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
test('BOSS JD recruiter excludes the online badge while keeping the visible name',()=>{
 const dom=documentFixture('job0001');const w=dom.window;
 w.document.body.innerHTML=`<ul class="job-list-container"><li class="job-card-wrapper selected"><a class="job-name" href="/job_detail/job0001.html">销售经理</a><a class="company-name" href="/gongsi/company1234.html">示例科技</a></li></ul><article class="new-layout"><div class="detail-title"><h2>销售经理</h2></div><h2>职位描述</h2><p class="desc">${jd}</p><div class="job-boss-info"><h2 class="name">陈先生 <span>在线</span></h2></div><a href="/job_detail/job0001.html">查看更多信息</a></article>`;
 const result=w.JobAssistantExtractor.extract(w.document,'https://www.zhipin.com/web/geek/jobs');
 assert.equal(result.status,'ready');assert.equal(result.capture.recruiter_name,'陈先生');
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
test('nested duplicate JD blocks merge but distinct valid descriptions remain ambiguous',()=>{
 const dom=documentFixture();const w=dom.window;
 w.document.body.innerHTML=`<header><h1>销售经理</h1></header><div class="company-info"><span class="company-name">虚构公司</span></div><main><section class="job-detail-section"><div class="job-sec-text"><div class="job-detail-description">${jd}</div></div></section><section class="job-detail-section"><div class="job-sec-text">另一份独立岗位正文：负责渠道拓展、线索跟进和客户关系维护，要求具备相关行业经验与较强的沟通能力。</div></section></main>`;
 assert.equal(w.JobAssistantExtractor.extract(w.document,w.location.href).status,'ambiguous');
 w.document.querySelectorAll('.job-detail-section')[1].remove();
 const result=w.JobAssistantExtractor.extract(w.document,w.location.href);assert.equal(result.status,'ready');assert.ok(result.capture.jd.includes(jd));dom.window.close();
});
test('URL and embedded detail link mismatch rejected; chat is not scraped',()=>{
 const dom=documentFixture();const w=dom.window;
 const link=w.document.createElement('a');link.href='https://www.zhipin.com/job_detail/job9999.html';link.textContent='查看职位';w.document.querySelector('.job-detail').append(link);
 assert.equal(w.JobAssistantExtractor.extract(w.document,w.location.href).status,'incomplete');
 assert.equal(w.JobAssistantExtractor.extract(w.document,'https://www.zhipin.com/web/geek/chat').status,'chat');
 dom.window.close();
});
test('BOSS chat context uses the selected header and job strip, never message text',()=>{
 const dom=documentFixture();const w=dom.window;
 w.document.body.innerHTML='<section class="chat-pane"><div class="chat-header"><span>张先生</span><span>虚构公司</span><span>招聘主管</span></div><div class="job-strip"><span>技术支持 8-12K 深圳</span><span>查看职位</span></div><div class="message-list">这里是私人聊天正文，不应进入关联信息</div></section>';
 const first=w.JobAssistantExtractor.chatContext(w.document,'https://www.zhipin.com/web/geek/chat');
 assert.equal(first.status,'ready');assert.equal(first.chat.recruiter_name,'张先生');assert.equal(first.chat.company,'虚构公司');assert.equal(first.chat.job_title,'技术支持');assert.ok(!JSON.stringify(first).includes('私人聊天'));
 w.document.querySelector('.chat-header').innerHTML='<span>李女士</span><span>另一公司</span><span>招聘者</span>';
 w.document.querySelector('.job-strip span').textContent='产品经理 12-18K 杭州';
 const second=w.JobAssistantExtractor.chatContext(w.document,'https://www.zhipin.com/web/geek/chat');
 assert.equal(second.chat.recruiter_name,'李女士');assert.equal(second.chat.company,'另一公司');assert.equal(second.chat.job_title,'产品经理');dom.window.close();
});
test('BOSS selected chat is read when its job strip has no view-position control',()=>{
 const dom=documentFixture();const w=dom.window;
 w.document.body.innerHTML='<aside><div>旧联系人 旧公司 招聘主管</div></aside><section class="chat-pane"><div class="chat-header"><span>董先生</span><span>深圳市同数营科技</span><span>招聘主管</span></div><div class="job-strip"><span>AI平台GEO推广经理 6-11K 深圳</span></div><div class="message-list">私人消息：薪资 7-13K，不得用于关联</div></section>';
 const result=w.JobAssistantExtractor.chatContext(w.document,'https://www.zhipin.com/web/geek/chat');
 assert.equal(result.status,'ready');assert.deepEqual({...result.chat},{url:'https://www.zhipin.com/web/geek/chat',recruiter_name:'董先生',company:'深圳市同数营科技',job_title:'AI平台GEO推广经理'});
 assert.ok(!JSON.stringify(result).includes('私人消息'));dom.window.close();
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
test('online resume is only captured explicitly and excludes platform side content',()=>{
 const dom=documentFixture();const w=dom.window;const url='https://www.zhipin.com/web/geek/resume?ka=header-resume';
 w.document.body.innerHTML=`<nav><span>个人信息</span><span>个人优势</span><span>工作经历</span></nav><main><h2>我的在线简历</h2><div class="resume-user"><strong class="resume-name">测试同学</strong><span>138******00</span><span>masked***@mail.test</span></div><section class="resume-section"><h3>个人优势</h3><ul><li>擅长客户沟通与项目复盘，能够协同团队推进交付。</li></ul></section><section class="resume-section"><h3>期望职位</h3><ul><li>产品运营 · 杭州</li></ul></section><section class="resume-section"><h3>工作经历</h3><ul><li>虚构科技 · 运营助理 · 负责用户访谈与周报复盘。</li><li>样例公司 · 实习生 · 支持活动执行。</li></ul></section><section class="resume-section"><h3>项目经历</h3></section><section class="resume-section"><h3>教育经历</h3><ul><li>示例大学 · 本科</li></ul></section><section class="resume-section"><h3>资格证书</h3><ul><li>大学英语四级</li></ul></section><section class="resume-section"><h3>自定义添加</h3><ul><li>志愿者经历 展示你的志愿者精神</li></ul></section></main><aside><h3>附件管理</h3><p>私人附件.pdf</p><h3>简历诊断</h3><p>平台建议：补充项目经历</p><p>隐私设置</p></aside><footer>服务热线 4000000000</footer>`;
 const passive=w.JobAssistantExtractor.extract(w.document,url);assert.equal(passive.status,'resume');assert.equal(passive.page_type,'boss-resume');assert.ok(!JSON.stringify(passive).includes('客户沟通'));
 const explicit=w.JobAssistantExtractor.extractResume(w.document,url);assert.equal(explicit.status,'ready');assert.equal(explicit.resume.name,'测试同学');assert.equal(explicit.resume.sections.work.items.length,2);assert.equal(explicit.resume.sections.projects.status,'empty');assert.equal(explicit.resume.sections.custom.status,'empty');
 const serialized=JSON.stringify(explicit);assert.ok(!serialized.includes('私人附件'));assert.ok(!serialized.includes('平台建议'));assert.ok(!serialized.includes('138'));assert.ok(!serialized.includes('masked'));
 assert.equal(w.JobAssistantExtractor.extractResume(w.document,'https://www.zhipin.com/web/geek/jobs').status,'unsupported');dom.window.close();
});
test('generic Zhaopin detail extraction is read-only and fail-closed on missing fields',()=>{
 const dom=documentFixture();const w=dom.window;dom.reconfigure({url:'https://jobs.zhaopin.com/jobdetail/abc12345.html'});
 w.document.body.innerHTML='<h1>客户经理</h1><div class="company-name">智联虚构公司</div><h2>职位描述</h2><div>负责客户沟通、需求跟进和方案介绍，维护项目进度并整理反馈；要求表达清楚，能够使用办公软件。</div>';
 let r=w.JobAssistantExtractor.extract(w.document,w.location.href);assert.equal(r.status,'ready');assert.equal(r.capture.source_site,'zhaopin');assert.equal(r.capture.title,'客户经理');assert.equal(r.capture.company,'智联虚构公司');assert.ok(r.capture.jd.includes('客户沟通'));
 w.document.querySelector('.company-name').remove();r=w.JobAssistantExtractor.extract(w.document,w.location.href);assert.equal(r.status,'incomplete');dom.window.close();
});
test('Zhaopin list page binds one visible detail to its unique jobdetail link',()=>{
 const dom=documentFixture();const w=dom.window;dom.reconfigure({url:'https://www.zhaopin.com/jobs/?pageMode=recommend'});
 w.document.body.innerHTML='<main><section><h2>AI产品技术支持 6000-9000元</h2><a href="/companydetail/CZ443657520.htm">中电金信软件有限公司</a><h3>职位描述</h3><div>工作职责：负责企业客户AI产品技术支持，处理配置、模型调优和API集成问题，跟进工单并配合销售完成方案演示。任职要求：熟悉大模型相关技术，具备沟通与故障排查能力。</div><a href="/jobdetail/CC443657520J40879944909.htm">查看更多职位信息</a></section></main>';
 const r=w.JobAssistantExtractor.extract(w.document,w.location.href);assert.equal(r.status,'ready');assert.equal(r.capture.job_key,'CC443657520J40879944909');assert.equal(r.capture.company,'中电金信软件有限公司');assert.match(r.capture.title,/AI产品技术支持/);dom.window.close();
});
test('generic 58 detail extraction accepts job responsibility headings',()=>{
 const dom=documentFixture();const w=dom.window;dom.reconfigure({url:'https://hz.58.com/job/detail/zz987654.html'});
 w.document.body.innerHTML='<h1>招商主管</h1><div class="company-name">58虚构企业</div><h3>岗位职责</h3><p>负责商户拓展与客户维护，跟进合作进展，整理客户需求并协同团队完成签约；维护客户关系，记录沟通结果并协同团队推进后续合作。</p>';
 const r=w.JobAssistantExtractor.extract(w.document,w.location.href);assert.equal(r.status,'ready');assert.equal(r.capture.source_site,'58');assert.equal(r.capture.job_key,'zz987654');dom.window.close();
});
test('58 category URL requires explicit job fields, not a nearby text guess',()=>{
 const dom=documentFixture();const w=dom.window;dom.reconfigure({url:'https://lf.58.com/zpshengchankaifa/67714798680634x.shtml?tracking=discard'});
 w.document.body.innerHTML='<main><div class="pos_info"><div>普工/操作工 8000-11000 元/月</div><span class="pos_name">廊坊广阳直招操作工包吃住活儿简单</span></div><div class="pos_description"><h3>职位描述</h3><div class="posDes">廊坊安能物流【招聘岗位】装卸工【工作内容】负责货物装车卸车，并对货物进行有序放置。【人员要求】识字，吃苦耐劳。</div></div><h3>公司介绍</h3><p>企业介绍不要进入JD。</p></main><aside><a href="https://qy.58.com/122735700710216/">上海安能聚创供应链管理有限公司</a></aside>';
 const r=w.JobAssistantExtractor.extract(w.document,w.location.href);assert.equal(r.status,'ready');assert.equal(r.capture.job_key,'67714798680634x');assert.equal(r.capture.company,'上海安能聚创供应链管理有限公司');assert.match(r.capture.title,/普工|操作工/);assert.ok(!r.capture.jd.includes('企业介绍'));
 dom.window.close();
});
function panelHarness(options={}){
 const dom=new JSDOM(code('panel.html'),{url:'https://extension-test.invalid/panel.html',runScripts:'outside-only',pretendToBeVisual:true});const w=dom.window;
 const controls={key:'job0001',calls:[],tick:null,turns:[],tabId:10,opens:[],holdHistory:false,jd,stable:3000,status:'ready',hint:null,companyKey:'',companyCapture:null,selectedText:jd,boundJob:'',...options};
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
 w.setInterval=fn=>{controls.tick=fn;return 1;};
 const capture=()=>({job_key:controls.key,url:controls.captureUrl||'https://www.zhipin.com/job_detail/'+controls.key+'.html',title:controls.key,company:'虚构公司',company_key:controls.companyKey,jd:controls.jd,method:'dom',...(controls.sourceSite?{source_site:controls.sourceSite}:{})});
 w.chrome={windows:{getCurrent:async()=>({id:1})},tabs:{query:async()=>[{id:controls.tabId,url:controls.url||capture().url}],sendMessage:async(_id,message)=>message?.type==='JA_RESUME_CAPTURE'?controls.resumeCapture:message?.type==='JA_SELECTION'?({text:controls.selectedText,url:controls.url||capture().url}):message?.type==='JA_CHAT_CONTEXT'?(controls.chatContext||{status:'ready',stable_ms:3000,chat:{url:controls.url||'https://www.zhipin.com/web/geek/chat',recruiter_name:'张先生',company:'虚构公司',job_title:'原岗位'}}):({status:controls.status,page_type:controls.pageType,capture:controls.status==='ready'?capture():undefined,stable_ms:controls.stable,identity:controls.hint,company_capture:controls.companyCapture}),create:async x=>controls.opens.push(x)},runtime:{getManifest:()=>manifest,sendMessage:async m=>{
  if(m.type==='JA_CONNECTION')return {ok:true,value:{connected:controls.connected!==false,port:8421}};
  if(m.type==='JA_DISCOVER'){const version=controls.workbenchVersion||extensionVersion;return {ok:true,value:{found:controls.discovered!==false,port:8421,version,compatible:version===extensionVersion,pairing:'confirmation'}};}
  if(m.type==='JA_PAIR_REQUEST')return {ok:true,value:{requested:true,port:8421,request_id:'pair-request-test',expires_in:300}};
  if(m.type==='JA_PAIR_STATUS')return {ok:true,value:controls.pairApproved?{status:'approved',connected:true,port:8421}:{status:'pending',port:8421}};
  if(m.type==='JA_API'){
   controls.calls.push(m);
   if(m.path==='/status'&&controls.statusError)return {ok:false,error:controls.statusError};
   if(m.path==='/restore'){
    if(!controls.saved)return {ok:true,value:{job:null,seq:m.value.seq}};
    controls.boundJob=controls.saved.job_key;return {ok:true,value:{seq:m.value.seq,job:{id:controls.saved.job_key,title:controls.saved.title,company:'虚构公司',company_key:controls.saved.company_key||'',url:controls.saved.url},capture:controls.saved}};
   }
   if(m.path==='/status'){const isReady=controls.ready!==false;return {ok:true,value:{version:controls.serviceVersion||extensionVersion,capabilities:controls.capabilities===undefined?['resume-import','pair-confirmation','verified-chat-links']:controls.capabilities,ready:isReady,readiness:controls.readiness||(isReady?{state:'ready'}:{state:'profile_required',title:'还差一步：补充你的经历',copy:'先在本机补充经历，搭子才知道怎样帮你看岗位。',action_label:'去工作台补充档案',page:'profile'}),buddy_name:'小树',worker_enabled:true,guide:controls.guide||null}};}
   if(m.path==='/capture'){controls.boundJob=m.value.capture?.job_key||'';return {ok:true,value:{seq:m.value.seq,job:m.value.capture?{id:m.value.capture.job_key,title:m.value.capture.title,company_key:controls.companyKey,company:'虚构公司',url:m.value.capture.url,revision:1}:null}};}
   if(m.path==='/confirm')return {ok:true,value:{confirmed:true}};
   if(m.path==='/history'){
    if(controls.staleRevision)return {ok:false,error:'岗位内容已更新，请重新识别并确认'};
    if(controls.holdHistory)return await new Promise(resolve=>{controls.resolveHistory=resolve;});
    return {ok:true,value:{seq:m.value.seq,job_id:controls.boundJob,turns:controls.turns,artifacts:controls.artifacts||[]}};
   }
   if(m.path==='/talk'){
    const task={task_id:'task1',kind:m.value.kind,text:m.value.text,status:'queued',workbench:m.value.kind==='tailor_resume'};
    controls.turns.push(task);return {ok:true,value:{seq:m.value.seq,job_id:controls.boundJob,task:{id:'task1',status:'queued'}}};
   }
   if(m.path==='/sync'){controls.staleRevision=false;return {ok:true,value:{seq:m.value.seq,job:{id:controls.boundJob,title:'工作台修改后的岗位',company:'虚构公司',url:capture().url,revision:2}}};}
   if(m.path==='/onboarding-complete'){controls.guide={active:false,step:'complete',job:null};return {ok:true,value:{guide:controls.guide}};}
   if(m.path==='/company-save')return {ok:true,value:{company:{evidence:[{}]},seq:m.value.seq,job_id:controls.boundJob}};
   if(m.path==='/company-bind'){controls.companyBound=m.value.company.company_key;return {ok:true,value:{company_key:controls.companyBound,seq:m.value.seq,job_id:controls.boundJob}};}
   if(m.path==='/resume-import')return {ok:true,value:{id:'draft-resume-1'}};
   if(m.path==='/jobs')return {ok:true,value:{jobs:[{id:'job0001',title:'原岗位',company:'虚构公司'},{id:'job0002',title:'另一岗位',company:'虚构公司'}]}};
   if(m.path==='/select'){controls.boundJob=m.value.job_id;const chosen={job_key:m.value.job_id,title:m.value.job_id,company:'虚构公司',url:'https://www.zhipin.com/job_detail/'+m.value.job_id+'.html'};return {ok:true,value:{seq:m.value.seq,job:{id:m.value.job_id,title:chosen.title,company:chosen.company,url:chosen.url,revision:1},capture:chosen}};}
   if(m.path==='/link-context'){if(controls.holdLink)return await new Promise(resolve=>{controls.resolveLink=resolve;});return {ok:true,value:{link:controls.linkedChat||null,conflict:'',matches:controls.linkedChat?[]:controls.matches||[{id:'job0001',title:'原岗位',company:'虚构公司'},{id:'job0002',title:'另一岗位',company:'虚构公司'}]}};}
   if(m.path==='/link-save'){controls.linkedChat={job_id:controls.boundJob,title:controls.boundJob,company:'虚构公司'};return {ok:true,value:{link:controls.linkedChat}};}
   if(m.path==='/link-unbind'){controls.linkedChat=null;return {ok:true,value:{unbound:true}};}
   if(m.path==='/links')return {ok:true,value:{links:[{kind:'job_detail',url:'https://www.zhipin.com/job_detail/'+m.value.job_id+'.html'}]}};
  }
  return {ok:true,value:{}};
 }}};
 w.eval(code('reply-format.js'));w.eval(code('panel.js'));return {dom,w,controls};
}
test('sidebar deep analysis hotkey sends an explicit background task',async()=>{
 const {dom,w,controls}=panelHarness();await settle();
 w.document.getElementById('confirm').click();await settle();
 const button=w.document.querySelector('.actions [data-kind="analyze_job"]');
 assert.ok(button);assert.equal(button.type,'button');assert.equal(button.disabled,false);
 button.click();await settle();
 const talks=controls.calls.filter(call=>call.path==='/talk');
 assert.equal(talks.length,1);assert.equal(talks[0].value.kind,'analyze_job');
 dom.window.close();
});
test('job confirmation shows only a bounded text preview of the captured JD',async()=>{
 const longJD='虚构岗位正文'.repeat(80);const {dom,w}=panelHarness({jd:longJD});await settle();
 const preview=w.document.getElementById('jd-preview');assert.equal(preview.hidden,false);assert.ok(preview.textContent.includes('岗位正文预览'));
 assert.ok(preview.textContent.length<longJD.length);assert.ok(preview.textContent.includes('…'));dom.window.close();
});
test('sidebar slash menu distinguishes task commands and labeled result references',async()=>{
 const artifacts=[
  {task_id:'analysis-a-1111',kind:'analyze_job',label:'深入分析',status:'done',created:100,updated:100,preview:'第一份：客户留存风险',result_markdown:'结果 A'},
  {task_id:'analysis-a-2222',kind:'analyze_job',label:'深入分析',status:'done',created:200,updated:200,preview:'第二份：团队目标待核实',result_markdown:'结果 B'},
 ];
 const {dom,w,controls}=panelHarness({turns:[],artifacts});await settle();w.document.getElementById('confirm').click();await settle();
 const input=w.document.getElementById('message');input.value='/';input.dispatchEvent(new w.Event('input',{bubbles:true}));await settle();
 const menu=w.document.getElementById('command-menu');assert.doesNotMatch(menu.textContent,/创建新的专项任务/);assert.equal(menu.querySelectorAll('.command-artifact').length,2);assert.doesNotMatch(menu.textContent,/tailor_resume|analyze_job|suggest_reply/);
 const second=[...menu.querySelectorAll('.command-artifact')].find(b=>b.textContent.includes('第二份'));assert.ok(second);second.click();await settle();assert.equal(w.document.getElementById('selected-reference').hidden,false);assert.match(w.document.getElementById('selected-reference').textContent,/分析/);
 input.value='请解释这份结果';w.document.getElementById('send').click();await settle();const talk=controls.calls.find(c=>c.path==='/talk');assert.equal(talk.value.reference_task_id,'analysis-a-2222');assert.equal(talk.value.text,'请解释这份结果');dom.window.close();
});
test('sidebar renders primary output when markdown preview is absent',async()=>{
 const artifacts=[{task_id:'primary-1',kind:'analyze_job',status:'done',created:100,updated:100,preview:'主结果',primary_output:'主输出文本'}];
 const {dom,w}=panelHarness({turns:[],artifacts});await settle();w.document.getElementById('confirm').click();await settle();
 assert.match(w.document.getElementById('messages').textContent,/主输出文本/);dom.window.close();
});
test('sidebar chat fact link carries only task id into local workbench',async()=>{
 const message='我独立整理过客户反馈。';
 const turns=[{task_id:'chat-fact-1',kind:'companion_chat',text:message,reply:'这段可以核对。',fact_candidate:true,status:'done',created:1,updated:2}];
 const {dom,w,controls}=panelHarness({turns});await settle();
 w.document.getElementById('confirm').click();await settle();
 const remember=w.document.querySelector('.turn .fact-from-chat');assert.ok(remember);assert.match(remember.textContent,/可能是新经历/);
 remember.click();await settle();
 const url=controls.opens.at(-1).url;
 assert.match(url,/fact_task=chat-fact-1/);assert.doesNotMatch(url,/客户反馈/);
 dom.window.close();
});
test('unpaired sidebar opens workbench pairing before asking for a job',async()=>{
 const {dom,w,controls}=panelHarness({connected:false});await settle();assert.equal(w.document.getElementById('pairing').hidden,false);
 assert.match(w.document.getElementById('auto-connect').textContent,/连接我的工作台/);w.document.getElementById('auto-connect').click();await settle();
 assert.match(controls.opens.at(-1).url,/pair_request=pair-request-test/);assert.match(w.document.getElementById('pairing-title').textContent,/确认连接/);assert.equal(controls.calls.length,0);dom.window.close();
});
test('sidebar blocks pairing when discovered workbench release differs',async()=>{
 const {dom,w,controls}=panelHarness({connected:false,workbenchVersion:'1.0.0-rc.4.3.1'});await settle();
 assert.match(w.document.getElementById('pairing-title').textContent,/版本不一致/);
 w.document.getElementById('auto-connect').click();await settle();
 assert.equal(controls.calls.length,0);assert.doesNotMatch(w.document.getElementById('status').textContent,/已连接/);dom.window.close();
});
test('network failure clears the connected badge without deleting target or draft',async()=>{
 const {dom,w,controls}=panelHarness();await settle();w.document.getElementById('confirm').click();await settle();
 w.document.getElementById('message').value='保留这份草稿';const before=controls.calls.filter(c=>c.path==='/capture').length;
 controls.statusError='Failed to fetch';await controls.tick();await settle();
 assert.equal(w.document.getElementById('connection-badge').textContent,'未连接');
 assert.equal(w.document.getElementById('pairing').hidden,false);
 assert.match(w.document.getElementById('status').textContent,/本机工作台无法连接/);
 assert.equal(w.document.getElementById('message').value,'保留这份草稿');
 assert.equal(controls.calls.filter(c=>c.path==='/capture').length,before);dom.window.close();
});
test('site support works in panel without the content-script extractor global',async()=>{
 for(const url of ['https://www.zhaopin.com/jobs/','https://lf.58.com/zpshengchankaifa/67714798680634x.shtml']){
  const {dom,w}=panelHarness({url});await settle();
  assert.equal(w.JobAssistantExtractor,undefined);
  assert.equal(w.document.getElementById('title').textContent,'job0001');dom.window.close();
 }
});
test('Zhaopin explicit company save binds an unlinked pinned target before saving materials',async()=>{
 const targetUrl='https://www.zhaopin.com/jobdetail/JOB123456.htm';
 const company={source_site:'zhaopin',company_key:'zhaopin:CZ123456',company_url:'https://www.zhaopin.com/companydetail/CZ123456.htm',source_url:'https://www.zhaopin.com/companydetail/CZ123456.htm',name:'虚构智联公司',sections:[{kind:'introduction',text:'虚构企业向客户提供软件实施与持续支持。'}],jobs:[],categories:[]};
 const {dom,w,controls}=panelHarness({key:'JOB123456',url:targetUrl,captureUrl:targetUrl,sourceSite:'zhaopin',hint:{job_key:'JOB123456',source_site:'zhaopin',source:'url'},companyCapture:null});await settle();
 w.document.getElementById('confirm').click();await settle();assert.equal(controls.boundJob,'JOB123456');
 controls.url=company.source_url;controls.status='company';controls.hint=null;controls.companyCapture=company;await controls.tick();await settle();
 const save=w.document.getElementById('save-company');assert.equal(save.disabled,false);assert.match(save.textContent,/确认关联这家公司/);const capturesBefore=controls.calls.filter(c=>c.path==='/capture').length;save.click();await settle();
 assert.equal(controls.calls.filter(c=>c.path==='/company-bind').length,1);assert.equal(controls.calls.filter(c=>c.path==='/company-save').length,1);assert.equal(controls.companyBound,company.company_key);assert.equal(controls.calls.filter(c=>c.path==='/capture').length,capturesBefore);assert.match(w.document.getElementById('status').textContent,/身份已确认/);dom.window.close();
});
test('Zhaopin selection fallback requires a unique direct-job identity and carries its site URL',async()=>{
 const url='https://www.zhaopin.com/jobdetail/JOB987654.htm?track=private';
 const hint={job_key:'JOB987654',source_site:'zhaopin',url:'https://www.zhaopin.com/jobdetail/JOB987654.htm',source:'url'};
 const {dom,w,controls}=panelHarness({url,status:'incomplete',hint});await settle();
 w.document.getElementById('selection-jd').click();await settle();
 w.document.getElementById('fallback-title').value='虚构岗位';w.document.getElementById('fallback-company').value='虚构智联公司';
 w.document.getElementById('use-jd').click();await settle();w.document.getElementById('confirm').click();await settle();
 const call=controls.calls.find(c=>c.path==='/capture'&&c.value.capture);assert.ok(call);assert.equal(call.value.capture.source_site,'zhaopin');assert.equal(call.value.capture.url,'https://www.zhaopin.com/jobdetail/JOB987654.htm');assert.ok(!call.value.capture.url.includes('track=private'));assert.equal(call.value.capture.job_key,'JOB987654');dom.window.close();
});
test('same raw job id on different sites is a different target',async()=>{
 const {dom,w,controls}=panelHarness();await settle();w.document.getElementById('confirm').click();await settle();
 controls.url='https://hz.58.com/job/detail/job0001.html';controls.captureUrl=controls.url;controls.sourceSite='58';
 await controls.tick();await settle();
 assert.equal(w.document.getElementById('confirm').textContent,'改为目标岗位');
 assert.match(w.document.getElementById('status').textContent,/另一家公司的岗位/);dom.window.close();
});
test('skipped guide never leaves a silently disabled side panel',async()=>{
 const {dom,w,controls}=panelHarness({ready:false,readiness:{state:'profile_required',title:'还差一步：补充你的经历',copy:'模型接入会保留。先在本机补充经历。',action_label:'去工作台补充档案',page:'profile'}});await settle();
 assert.equal(w.document.getElementById('readiness-card').hidden,false);assert.match(w.document.getElementById('readiness-card').textContent,/补充你的经历/);assert.equal(w.document.getElementById('send').disabled,true);assert.match(w.document.getElementById('composer-hint').textContent,/模型接入会保留/);
 w.document.getElementById('readiness-open').click();await settle();assert.match(controls.opens.at(-1).url,/page=profile/);dom.window.close();
});
test('unpaired sidebar explains missing service and keeps manual pairing in advanced details',async()=>{
 const {dom,w,controls}=panelHarness({connected:false,discovered:false});await settle();assert.match(w.document.getElementById('pairing-title').textContent,/尚未找到/);
 assert.equal(w.document.getElementById('manual-pairing').open,false);w.document.getElementById('open-onboarding').click();await settle();assert.match(controls.opens.at(-1).url,/127\.0\.0\.1:8421/);dom.window.close();
});
test('online resume import requires an explicit click and opens local review',async()=>{
 const resume={schema:'job-assistant.boss-resume.v1',source_url:'https://www.zhipin.com/web/geek/resume',name:'测试同学',sections:{advantage:{status:'present',items:['善于沟通']},expectations:{status:'empty',items:[]},work:{status:'empty',items:[]},projects:{status:'empty',items:[]},education:{status:'empty',items:[]},certificates:{status:'empty',items:[]},custom:{status:'empty',items:[]}}};
 const {dom,w,controls}=panelHarness({url:'https://www.zhipin.com/web/geek/resume',status:'resume',resumeCapture:{status:'ready',resume}});await settle();
 assert.equal(w.document.getElementById('resume-import-card').hidden,false);assert.equal(controls.calls.filter(c=>c.path==='/resume-import').length,0);
 w.document.getElementById('resume-import').click();await settle();assert.equal(controls.calls.filter(c=>c.path==='/resume-import').length,1);assert.match(controls.opens.at(-1).url,/resume_import=draft-resume-1/);dom.window.close();
});
test('Zhaopin resume import requires its capability and sends an explicit local draft',async()=>{
 const resume={schema:'job-assistant.zhaopin-resume.v1',source_url:'https://i.zhaopin.com/resume',name:'',sections:{advantage:{status:'present',items:['虚构优势']},expectations:{status:'empty',items:[]},work:{status:'empty',items:[]},projects:{status:'empty',items:[]},education:{status:'empty',items:[]},certificates:{status:'empty',items:[]},custom:{status:'empty',items:[]}}};
 const {dom,w,controls}=panelHarness({url:'https://i.zhaopin.com/resume',status:'resume',pageType:'zhaopin-resume',serviceVersion:'1.0.0-rc.4.3.5',capabilities:['resume-import','zhaopin-resume-import','pair-confirmation'],resumeCapture:{status:'ready',resume}});await settle();
 assert.match(w.document.getElementById('resume-import').textContent,/智联/);
 assert.equal(controls.calls.filter(c=>c.path==='/resume-import').length,0);
 w.document.getElementById('resume-import').click();await settle();
 assert.equal(controls.calls.filter(c=>c.path==='/resume-import').length,1);
 assert.equal(controls.calls.find(c=>c.path==='/resume-import').value.resume.schema,resume.schema);
 assert.match(controls.opens.at(-1).url,/resume_import=draft-resume-1/);dom.window.close();
});
test('online resume import explains stale workbench instead of generic missing route',async()=>{
 const {dom,w,controls}=panelHarness({url:'https://www.zhipin.com/web/geek/resume',status:'resume',serviceVersion:'1.0.0-rc.3',capabilities:[]});await settle();w.document.getElementById('resume-import').click();await settle();
 assert.match(w.document.getElementById('status').textContent,/当前工作台服务 1\.0\.0-rc\.3 尚未声明支持/);assert.equal(controls.calls.filter(c=>c.path==='/resume-import').length,0);dom.window.close();
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
test('sidebar manual switch lists saved jobs and changes the pinned target only on click',async()=>{
 const {dom,w,controls}=panelHarness({saved:{job_key:'job0001',title:'原岗位',company:'虚构公司',url:'https://www.zhipin.com/job_detail/job0001.html'}});await settle();
 w.document.getElementById('open-job-switch').click();await settle();
 const dialog=w.document.getElementById('job-switch-dialog');assert.equal(dialog.open,true);assert.equal(controls.boundJob,'job0001');
 [...dialog.querySelectorAll('#job-switch-list button')].find(b=>b.textContent.includes('另一岗位')).click();await settle();
 assert.equal(controls.boundJob,'job0002');assert.equal(dialog.open,false);
 assert.ok(controls.calls.some(c=>c.path==='/select'&&c.value.job_id==='job0002'));dom.window.close();
});
test('unlinked HR chat shows guidance and can record only the chosen job',async()=>{
 const saved={job_key:'job0001',title:'原岗位',company:'虚构公司',url:'https://www.zhipin.com/job_detail/job0001.html'};
 const {dom,w,controls}=panelHarness({saved,url:'https://www.zhipin.com/web/geek/chat?to=123',status:'chat'});await settle();
 assert.equal(w.document.getElementById('chat-link-card').hidden,false);
 assert.match(w.document.getElementById('chat-link-copy').textContent,/核对后绑定/);
 w.document.getElementById('chat-link-save').click();await settle();
 assert.ok(controls.calls.some(c=>c.path==='/link-save'&&c.value.chat.url.includes('to=123')));
 assert.match(w.document.getElementById('chat-link-title').textContent,/当前会话/);dom.window.close();
});
test('switching HR contacts at the same URL clears the previous binding card',async()=>{
 const saved={job_key:'job0001',title:'原岗位',company:'虚构公司',url:'https://www.zhipin.com/job_detail/job0001.html'};
 const {dom,w,controls}=panelHarness({saved,url:'https://www.zhipin.com/web/geek/chat',status:'chat',linkedChat:{job_id:'job0001',title:'原岗位',company:'虚构公司'}});await settle();
 assert.match(w.document.getElementById('chat-link-copy').textContent,/已核验关联/);
 controls.chatContext={status:'ready',stable_ms:3000,chat:{url:controls.url,recruiter_name:'李女士',company:'另一公司',job_title:'产品经理'}};
 controls.linkedChat=null;await controls.tick();await settle();
 assert.match(w.document.getElementById('chat-link-title').textContent,/李女士/);
 assert.doesNotMatch(w.document.getElementById('chat-link-card').textContent,/已核验关联：原岗位/);
 assert.equal(w.document.getElementById('chat-link-open-job').hidden,true);dom.window.close();
});
test('HR binding can be unbound and verified again without deleting the job',async()=>{
 const saved={job_key:'job0001',title:'原岗位',company:'虚构公司',url:'https://www.zhipin.com/job_detail/job0001.html'};
 const {dom,w,controls}=panelHarness({saved,url:'https://www.zhipin.com/web/geek/chat',status:'chat',linkedChat:{job_id:'job0001',title:'原岗位',company:'虚构公司'}});await settle();
 w.document.getElementById('chat-link-unbind').click();await settle();
 assert.ok(controls.calls.some(c=>c.path==='/link-unbind'));
 assert.equal(w.document.getElementById('chat-link-save').hidden,false);
 w.document.getElementById('chat-link-save').click();await settle();
 assert.ok(controls.calls.some(c=>c.path==='/link-save'&&c.value.job_id==='job0001'));dom.window.close();
});
test('historical HR binding requires explicit target switch before job actions',async()=>{
 const saved={job_key:'job0001',title:'原岗位',company:'虚构公司',url:'https://www.zhipin.com/job_detail/job0001.html'};
 const {dom,w,controls}=panelHarness({saved,url:'https://www.zhipin.com/web/geek/chat',status:'chat',linkedChat:{job_id:'job0002',title:'另一岗位',company:'虚构公司'}});await settle();
 assert.equal(controls.boundJob,'job0001');assert.match(w.document.getElementById('chat-target').textContent,/已固定对话岗位/);
 assert.equal(w.document.querySelector('[data-kind="quick_analysis"]').disabled,true);
 w.document.getElementById('chat-link-use-job').click();await settle();
 assert.equal(controls.boundJob,'job0002');assert.equal(w.document.querySelector('[data-kind="quick_analysis"]').disabled,false);
 w.document.querySelector('[data-kind="quick_analysis"]').click();await settle();
 assert.equal(controls.calls.filter(c=>c.path==='/talk').length,1);dom.window.close();
});
test('HR management stays in advanced settings and a matching binding leaves the chat unobstructed',async()=>{
 const saved={job_key:'job0001',title:'原岗位',company:'虚构公司',url:'https://www.zhipin.com/job_detail/job0001.html'};
 const {dom,w,controls}=panelHarness({saved,url:'https://www.zhipin.com/web/geek/chat',status:'chat',linkedChat:{job_id:'job0001',title:'原岗位',company:'虚构公司'}});await settle();
 const el=id=>w.document.getElementById(id);
 assert.equal(el('chat-link-notice').hidden,true);
 assert.equal(el('details-dialog').open,false);assert.equal(el('chat-link-settings').open,false);
 for(const id of ['chat-link-card','chat-link-open-job','chat-link-unbind'])assert.ok(el('details-dialog').contains(el(id)));
 el('open-details').click();el('chat-link-settings').open=true;
 assert.equal(el('details-dialog').open,true);assert.equal(el('chat-link-open-job').hidden,false);
 assert.equal(controls.calls.filter(c=>c.path==='/link-unbind').length,0);dom.window.close();
});
test('switching between bound HR contacts shows an inline action without changing the pinned job',async()=>{
 const saved={job_key:'job0001',title:'原岗位',company:'虚构公司',url:'https://www.zhipin.com/job_detail/job0001.html'};
 const {dom,w,controls}=panelHarness({saved,url:'https://www.zhipin.com/web/geek/chat',status:'chat',linkedChat:{job_id:'job0001',title:'原岗位',company:'虚构公司'}});await settle();
 const el=id=>w.document.getElementById(id);
 controls.chatContext={status:'ready',stable_ms:3000,chat:{url:controls.url,recruiter_name:'李女士',company:'虚构公司',job_title:'另一岗位'}};
 controls.linkedChat={job_id:'job0002',title:'另一岗位',company:'虚构公司'};await controls.tick();await settle();
 assert.equal(controls.boundJob,'job0001');assert.equal(el('chat-link-notice').hidden,false);
 assert.equal(el('chat-link-use-job').hidden,false);assert.ok(el('chat-link-notice').contains(el('chat-link-use-job')));
 assert.match(el('chat-link-notice-title').textContent,/另一岗位/);assert.equal(el('details-dialog').open,false);
 el('chat-link-use-job').click();await settle();assert.equal(controls.boundJob,'job0002');assert.equal(el('chat-link-notice').hidden,true);
 controls.chatContext={status:'ready',stable_ms:3000,chat:{url:controls.url,recruiter_name:'张先生',company:'虚构公司',job_title:'原岗位'}};
 controls.linkedChat={job_id:'job0001',title:'原岗位',company:'虚构公司'};await controls.tick();await settle();
 assert.equal(controls.boundJob,'job0002');assert.equal(el('chat-link-notice').hidden,false);assert.match(el('chat-link-notice-title').textContent,/原岗位/);
 controls.chatContext={status:'incomplete',reason:'头部正在加载'};await controls.tick();await settle();
 assert.equal(el('chat-link-use-job').hidden,true);assert.doesNotMatch(el('chat-link-notice-title').textContent,/原岗位/);
 dom.window.close();
});
test('unbound chat opens verification on request and hides the inline notice after binding',async()=>{
 const saved={job_key:'job0001',title:'原岗位',company:'虚构公司',url:'https://www.zhipin.com/job_detail/job0001.html'};
 const {dom,w,controls}=panelHarness({saved,url:'https://www.zhipin.com/web/geek/chat',status:'chat'});await settle();
 const el=id=>w.document.getElementById(id);
 assert.equal(el('details-dialog').open,false);assert.equal(el('chat-link-notice').hidden,false);
 el('chat-link-review').click();assert.equal(el('details-dialog').open,true);assert.equal(el('chat-link-settings').open,true);
 el('chat-link-save').click();await settle();assert.equal(el('chat-link-notice').hidden,true);
 el('chat-link-unbind').click();await settle();assert.equal(el('chat-link-notice').hidden,false);
 assert.equal(controls.boundJob,'job0001');dom.window.close();
});
test('late link lookup cannot restore the previous HR card and unchanged polling preserves buttons',async()=>{
 const saved={job_key:'job0001',title:'原岗位',company:'虚构公司',url:'https://www.zhipin.com/job_detail/job0001.html'};
 const {dom,w,controls}=panelHarness({saved,url:'https://www.zhipin.com/web/geek/chat',status:'chat'});await settle();
 const matchButton=w.document.querySelector('#chat-link-matches button');await controls.tick();await settle();
 assert.equal(w.document.querySelector('#chat-link-matches button'),matchButton);
 controls.holdLink=true;controls.tick();await settle();
 controls.chatContext={status:'ready',stable_ms:3000,chat:{url:controls.url,recruiter_name:'李女士',company:'乙公司',job_title:'产品经理'}};
 controls.resolveLink({ok:true,value:{link:{job_id:'job0001',title:'旧关联岗位',company:'甲公司'},matches:[],conflict:''}});await settle();
 assert.doesNotMatch(w.document.getElementById('chat-link-card').textContent,/旧关联岗位/);
 assert.equal(w.document.getElementById('chat-link-open-job').hidden,true);dom.window.close();
});
test('missing local JD shows guidance and disables binding',async()=>{
 const {dom,w}=panelHarness({url:'https://www.zhipin.com/web/geek/chat',status:'chat',matches:[]});await settle();
 assert.match(w.document.getElementById('chat-link-copy').textContent,/没有找到匹配的已建档 JD/);
 assert.equal(w.document.getElementById('chat-link-save').disabled,true);dom.window.close();
});
test('new sidebar refuses unverified URL binding with an older workbench',async()=>{
 const {dom,w,controls}=panelHarness({url:'https://www.zhipin.com/web/geek/chat',status:'chat',capabilities:['resume-import']});await settle();
 assert.match(w.document.getElementById('chat-link-copy').textContent,/同时更新侧栏和工作台/);
 assert.equal(controls.calls.filter(c=>c.path==='/link-context').length,0);
 assert.equal(w.document.getElementById('chat-link-save').disabled,true);dom.window.close();
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
 const messages=w.document.getElementById('messages');assert.ok(messages.textContent.includes('整份简历不应占满侧栏'));
 const expand=Array.from(messages.querySelectorAll('summary')).find(b=>b.textContent==='展开详细内容');
 assert.ok(expand);expand.parentElement.open=true;assert.match(messages.textContent,/整份简历不应占满侧栏/);assert.equal(controls.opens.length,0);dom.window.close();
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
test('slow polling and history refresh never disable sending for restored target',async()=>{
 const saved={job_key:'job0001',title:'上次确认的岗位',url:'https://www.zhipin.com/job_detail/job0001.html',method:'restored'};
 const {dom,w,controls}=panelHarness({saved,holdHistory:true});
 await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));
 assert.equal(controls.boundJob,'job0001');assert.equal(w.document.getElementById('send').disabled,false);
 w.document.getElementById('message').value='打招呼';w.document.getElementById('send').click();await new Promise(r=>setImmediate(r));
 assert.equal(controls.calls.filter(c=>c.path==='/talk').length,1);
 controls.holdHistory=false;if(controls.resolveHistory)controls.resolveHistory({ok:true,value:{seq:1,job_id:'job0001',turns:controls.turns}});await settle();dom.window.close();
});
test('streaming partial text is visible before task completion',async()=>{
 const {dom,w,controls}=panelHarness();await settle();w.document.getElementById('confirm').click();await settle();
 controls.turns=[{task_id:'stream',kind:'companion_chat',text:'问题',status:'running',partial:'已经收到第一句。'}];await controls.tick();await settle();
 assert.match(w.document.getElementById('messages').textContent,/已经收到第一句/);assert.equal(w.document.getElementById('send').disabled,true);dom.window.close();
});
test('slow model wait shows elapsed seconds instead of looking frozen',async()=>{
 const {dom,w,controls}=panelHarness();await settle();w.document.getElementById('confirm').click();await settle();
 controls.turns=[{task_id:'slow',kind:'quick_analysis',text:'慢请求',status:'running',created:Date.now()/1000-300,updated:Date.now()/1000-70,attempts:2,workbench:false}];
 await controls.tick();await settle();assert.match(w.document.getElementById('messages').textContent,/第 2 次尝试/);assert.match(w.document.getElementById('messages').textContent,/本次已等待 70/);assert.doesNotMatch(w.document.getElementById('messages').textContent,/300 秒/);assert.match(w.document.getElementById('messages').textContent,/30–90 秒/);dom.window.close();
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
 const chrome={sidePanel:{setPanelBehavior:async()=>{}},runtime:{id:'a'.repeat(32),getManifest:()=>manifest,getURL:p=>'chrome-extension://'+'a'.repeat(32)+'/'+p,onMessage:{addListener:fn=>listener=fn}},storage:{session:{get:async()=>session,set:async x=>{session={...session,...x};},remove:async key=>{delete session[key];}}}};
 const token='synthetic-paired-token';
 const fetch=async(url,options={})=>{fetches++;if(url.endsWith('/challenge')){const nonce=JSON.parse(options.body).nonce;return {ok:true,json:async()=>({version:extensionVersion,nonce,proof:await hmacHex(token,nonce)})};}if(url.endsWith('/discover'))return {ok:true,json:async()=>({version:extensionVersion,pairing:'confirmation'})};if(url.endsWith('/pair'))return {ok:true,json:async()=>({token,version:extensionVersion})};return {ok:true,json:async()=>({})};};
 vm.runInNewContext(code('background.js'),backgroundContext(chrome,fetch));
 const caller={id:chrome.runtime.id,url:chrome.runtime.getURL('panel.html')};
 assert.equal(listener({type:'JA_PAIR',code:'123',port:8421},{id:caller.id,url:'https://www.zhipin.com/'},()=>{}),false);
 assert.equal(fetches,0);
 const call=m=>new Promise(resolve=>listener(m,caller,resolve));
 const pair=await call({type:'JA_PAIR',code:'123',port:8421});assert.equal(pair.value.connected,true,JSON.stringify(pair));assert.equal(pair.value.token,undefined);
 const arbitrary=await call({type:'JA_API',path:'/../../api/state',value:{}});assert.equal(arbitrary.ok,false);assert.equal(fetches,2);
 const complete=await call({type:'JA_API',path:'/onboarding-complete',value:{}});assert.equal(complete.ok,true,JSON.stringify(complete));assert.equal(fetches,4);
 await call({type:'JA_DISCONNECT'});assert.equal(fetches,6);assert.equal((await call({type:'JA_CONNECTION'})).value.connected,false);
});
test('background confirmation pairing binds request to session and stores token only after approval',async()=>{
 const vm=require('node:vm');let listener;let session={};let statusCalls=0;
 const chrome={sidePanel:{setPanelBehavior:async()=>{}},runtime:{id:'a'.repeat(32),getManifest:()=>manifest,getURL:p=>'chrome-extension://'+'a'.repeat(32)+'/'+p,onMessage:{addListener:fn=>listener=fn}},storage:{session:{get:async keys=>{if(Array.isArray(keys))return Object.fromEntries(keys.map(k=>[k,session[k]]));return {[keys]:session[keys]};},set:async x=>{session={...session,...x};},remove:async key=>{delete session[key];}}}};
 const fetch=async url=>{if(url.includes('/discover'))return {ok:true,json:async()=>({version:extensionVersion,pairing:'confirmation'})};if(url.includes('/pair-request'))return {ok:true,json:async()=>({request_id:'request-1',expires_in:300})};if(url.includes('/pair-status')){statusCalls++;return {ok:true,json:async()=>statusCalls>1?({status:'approved',token:'private-token',version:extensionVersion}):({status:'pending'})};}return {ok:true,json:async()=>({})};};
 vm.runInNewContext(code('background.js'),{chrome,AbortSignal,Error,Number,JSON,Set,Array,fetch});const caller={id:chrome.runtime.id,url:chrome.runtime.getURL('panel.html')};const call=m=>new Promise(resolve=>listener(m,caller,resolve));
 assert.equal((await call({type:'JA_DISCOVER',ports:[8421]})).value.found,true);await call({type:'JA_PAIR_REQUEST',port:8421});assert.equal(session.connection,undefined);assert.equal((await call({type:'JA_PAIR_STATUS'})).value.status,'pending');assert.equal(session.connection,undefined);assert.equal((await call({type:'JA_PAIR_STATUS'})).value.connected,true);assert.equal(session.connection.token,'private-token');assert.equal(session.pairing,undefined);
});
test('discovery prefers the side panel release when the default port still hosts an older service',async()=>{
 const vm=require('node:vm');let listener;
 const chrome={sidePanel:{setPanelBehavior:async()=>{}},runtime:{id:'a'.repeat(32),getManifest:()=>({version_name:'1.0.0-rc.4.3.20'}),getURL:p=>'chrome-extension://'+'a'.repeat(32)+'/'+p,onMessage:{addListener:fn=>listener=fn}},storage:{session:{get:async()=>({}),set:async()=>{},remove:async()=>{}}}};
 const fetch=async url=>({ok:true,json:async()=>({version:url.includes(':8421/')?'1.0.0-rc.4.3.5':'1.0.0-rc.4.3.20',pairing:'confirmation'})});
 vm.runInNewContext(code('background.js'),{chrome,AbortSignal,Error,Number,JSON,Set,Array,fetch});
 const caller={id:chrome.runtime.id,url:chrome.runtime.getURL('panel.html')};const call=m=>new Promise(resolve=>listener(m,caller,resolve));
 const selected=(await call({type:'JA_DISCOVER',ports:[8421,8422]})).value;
 assert.equal(selected.port,8422);assert.equal(selected.version,'1.0.0-rc.4.3.20');
});
test('a saved pairing stays on its original port and rejects a mismatched service before forwarding data',async()=>{
 const vm=require('node:vm');let listener;let attempts=[];const session={connection:{port:8421,token:'bound-token',version:extensionVersion}};
 const chrome={sidePanel:{setPanelBehavior:async()=>{}},runtime:{id:'a'.repeat(32),getManifest:()=>manifest,getURL:p=>'chrome-extension://'+'a'.repeat(32)+'/'+p,onMessage:{addListener:fn=>listener=fn}},storage:{session:{get:async()=>session,set:async x=>Object.assign(session,x),remove:async k=>{delete session[k];}}}};
 const fetch=async(url,options={})=>{attempts.push({url,options});return {ok:true,json:async()=>({version:'1.0.0-rc.4.3.1',nonce:JSON.parse(options.body||'{}').nonce,proof:'0'.repeat(64)})};};
 vm.runInNewContext(code('background.js'),backgroundContext(chrome,fetch));const caller={id:chrome.runtime.id,url:chrome.runtime.getURL('panel.html')};const call=m=>new Promise(resolve=>listener(m,caller,resolve));
 const found=(await call({type:'JA_DISCOVER',ports:[8421,8422]})).value;assert.equal(found.found,false);assert.equal(found.needsRepair,true);assert.equal(found.port,8421);assert.equal(attempts.length,1);assert.match(attempts[0].url,/:8421\//);assert.match(attempts[0].url,/challenge/);
 attempts=[];const forwarded=await call({type:'JA_API',path:'/capture',value:{capture:{jd:'synthetic'}}});assert.equal(forwarded.ok,false);assert.equal(attempts.length,1);assert.match(attempts[0].url,/:8421\//);assert.match(attempts[0].url,/challenge/);
});
test('same-version impostor and replayed challenge never receive page or user data; valid proof preserves calls',async()=>{
 const vm=require('node:vm');let listener;let mode='impostor';let prior=null;const token='fake-token-for-test-only';const attempts=[];const session={connection:{port:8421,token,version:extensionVersion}};
 const chrome={sidePanel:{setPanelBehavior:async()=>{}},runtime:{id:'a'.repeat(32),getManifest:()=>manifest,getURL:p=>'chrome-extension://'+'a'.repeat(32)+'/'+p,onMessage:{addListener:fn=>listener=fn}},storage:{session:{get:async()=>session,set:async x=>Object.assign(session,x),remove:async k=>{delete session[k];}}}};
 const fetch=async(url,options={})=>{
  const path=new URL(url).pathname;const body=JSON.parse(options.body||'{}');attempts.push({path,body,token:options.headers?.['X-Bridge-Token']});
  if(path.endsWith('/challenge')){
   if(mode==='replay'&&prior)return {ok:true,json:async()=>prior};
   const proof=mode==='impostor'?'0'.repeat(64):await hmacHex(token,body.nonce);
   const response={version:extensionVersion,nonce:body.nonce,proof};if(mode==='correct')prior=response;
   return {ok:true,json:async()=>response};
  }
  if(path.endsWith('/discover'))return {ok:true,json:async()=>({version:extensionVersion,pairing:'confirmation'})};
  return {ok:true,json:async()=>({accepted:true})};
 };
 vm.runInNewContext(code('background.js'),backgroundContext(chrome,fetch));const caller={id:chrome.runtime.id,url:chrome.runtime.getURL('panel.html')};const call=m=>new Promise(resolve=>listener(m,caller,resolve));
 const sensitive={capture:{jd:'虚构JD原文-不应发给假服务',recruiter_name:'虚构HR',user_original:'虚构用户原话'}};
 let result=await call({type:'JA_API',path:'/capture',value:sensitive});assert.equal(result.ok,false);assert.equal(attempts.length,1);assert.equal(attempts[0].path,'/bridge/challenge');assert.equal(attempts[0].token,undefined);assert.deepEqual(attempts[0].body,Object.fromEntries([['nonce',attempts[0].body.nonce]]));assert.match(attempts[0].body.nonce,/^[0-9a-f]{64}$/);
 attempts.length=0;result=await call({type:'JA_DISCOVER',ports:[8421]});assert.equal(result.value.found,false);assert.equal(attempts.length,1);assert.equal(attempts[0].path,'/bridge/challenge');
 mode='correct';attempts.length=0;result=await call({type:'JA_DISCOVER',ports:[8421]});assert.equal(result.value.found,true);assert.deepEqual(attempts.map(x=>x.path),['/bridge/challenge','/bridge/discover']);
 attempts.length=0;result=await call({type:'JA_API',path:'/capture',value:sensitive});assert.equal(result.ok,true,JSON.stringify(result));assert.deepEqual(attempts.map(x=>x.path),['/bridge/challenge','/bridge/capture']);assert.equal(attempts[0].token,undefined);assert.equal(attempts[1].token,token);assert.deepEqual(attempts[1].body,sensitive);
 mode='replay';attempts.length=0;result=await call({type:'JA_API',path:'/capture',value:sensitive});assert.equal(result.ok,false);assert.deepEqual(attempts.map(x=>x.path),['/bridge/challenge']);assert.notEqual(attempts[0].body.nonce,prior.nonce);
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


test('panel keeps full detailed report available when a separate primary output exists',async()=>{
 const artifacts=[{task_id:'full-report',kind:'analyze_job',status:'done',created:100,updated:100,primary_output:'## 主结论\n**先核对产品**',result_markdown:'# 完整详细依据\n\n材料尚未证明团队压力。'}];
 const {dom,w}=panelHarness({turns:[],artifacts});await settle();w.document.getElementById('confirm').click();await settle();
 const body=w.document.querySelector('.artifact-body');assert.match(body.textContent,/主结论/);assert.match(body.textContent,/完整详细依据/);assert.ok(body.querySelector('.result-evidence'));assert.equal(body.querySelector('h3').textContent,'完整详细依据');assert.doesNotMatch(body.textContent,/\*\*|##/);dom.window.close();
});
