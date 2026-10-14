const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const code=fs.readFileSync(require('node:path').join(__dirname,'../extension/extractor.js'),'utf8');
const jd='岗位职责：负责客户需求分析、产品演示和技术支持，整理实施方案并跟进反馈。任职要求：能够独立排查问题，具备清晰的沟通表达能力。';
function page(html,url){const d=new JSDOM(html,{url,runScripts:'outside-only'});d.window.HTMLElement.prototype.getClientRects=()=>[{width:20,height:20}];d.window.eval(code);return d;}
// Classes and nesting from Edge's structure-only diagnostics; all content is fictional.
function zhaopin(){return page(`<aside><a href="/jobdetail/OTHER1234.htm">另一岗位</a></aside>
<div class="job-detail-modules__detail">
 <div class="job-detail-modules__summary-wrap"><section class="job-detail-summary">
  <h1 class="job-detail-summary__title"><span class="job-detail-summary__title-text">售前支持工程师</span><span class="job-detail-summary__salary">1-1.5万</span></h1>
  <a href="/companydetail/CZ123456.htm">虚构公司甲</a>
 </section></div>
 <div class="job-detail-modules__scroll"><div class="job-detail-modules__body">
  <section class="job-detail-card"><div class="job-detail-card__header"><div class="job-detail-card__title-wrap"><h3 class="job-detail-card__title"><span>职位描述</span></h3></div></div><div class="job-detail-card__body"><div>软件产品</div><div>${jd}</div></div></section>
  <section class="job-detail-publisher-card"><h3>职位发布者</h3><div>招聘经理 · 虚构公司甲</div></section>
  <section class="job-company-info-card"><h3>公司信息</h3><a href="/companydetail/CZ123456.htm">虚构公司甲</a><p>公司介绍不可混进职位正文</p><a href="/jobdetail/TEST123456.htm">查看更多职位信息</a></section>
 </div></div>
</div>`,'https://www.zhaopin.com/jobs/');}
test('real Zhaopin nested cards bind summary, JD and detail link without recruiter fallback',()=>{
 const d=zhaopin(),w=d.window,r=w.JobAssistantExtractor.extract(w.document,w.location.href);
 assert.equal(r.status,'ready');assert.equal(r.capture.title,'售前支持工程师');assert.equal(r.capture.company,'虚构公司甲');assert.equal(r.capture.job_key,'TEST123456');
 assert.equal(r.capture.source_site,'zhaopin');assert.equal(r.capture.company_key,'zhaopin:CZ123456');assert.equal(r.capture.company_url,'https://www.zhaopin.com/companydetail/CZ123456.htm');
 assert.ok(r.capture.jd.includes(jd));assert.ok(!/招聘经理|公司介绍/.test(r.capture.jd));d.window.close();
});
test('Zhaopin company detail reads only explicitly headed public sections',()=>{
 const d=page(`<main><h1>虚构公司甲</h1><h2>公司简介</h2><p>虚构公司为客户提供经营管理软件、项目实施和持续技术服务。</p><h2>产品介绍</h2><div>虚构产品甲用于整理客户订单并跟进服务过程。</div><h2>管理团队</h2><p>此段不作为企业业务资料。</p><section class="recommend-box"><h2>推荐公司</h2><p>不得读取推荐材料。</p></section></main>`,'https://www.zhaopin.com/companydetail/CZ123456.htm');
 const w=d.window,r=w.JobAssistantExtractor.extract(w.document,w.location.href);
 assert.equal(r.status,'company');assert.equal(r.company_capture.source_site,'zhaopin');assert.equal(r.company_capture.company_key,'zhaopin:CZ123456');
 assert.deepEqual([...r.company_capture.sections.map(x=>x.kind)],['introduction','products']);assert.ok(!JSON.stringify(r.company_capture.sections).includes('推荐材料'));assert.ok(!JSON.stringify(r.company_capture.sections).includes('管理团队'));d.window.close();
});
test('Zhaopin company recruitment keeps only loaded company job cards, not recommendations',()=>{
 const d=page(`<main><h1>虚构公司甲招聘</h1><div class="job-onlinelist"><div class="job-onlinelist__jobs__link">
  <div class="job-onlinelist__jobs__item clearfix"><div class="job-onlinelist__jobs__info fl"><div class="job-onlinelist__jobs__info__title"><a class="job-onlinelist__jobs__info__href" href="/jobdetail/CCL123456J001.htm?refcode=private">售前支持</a><span class="job-onlinelist__jobs__info__salary">8000-12000元</span></div><div class="job-onlinelist__jobs__welfare"><strong class="job-onlinelist__jobs__welfare__txt">杭州</strong><strong class="job-onlinelist__jobs__welfare__txt">大专</strong></div><div class="job-onlinelist__jobs__staff">虚构招聘者姓名不要采集</div></div></div>
  <div class="job-onlinelist__jobs__item clearfix"><div class="job-onlinelist__jobs__info fl"><div class="job-onlinelist__jobs__info__title"><a class="job-onlinelist__jobs__info__href" href="/jobdetail/CCL123456J002.htm">客户成功</a><span class="job-onlinelist__jobs__info__salary">9000-13000元</span></div></div></div>
 </div></div><section class="job-recommend"><h2>精选职位推荐</h2><article><a href="/jobdetail/OTHER9999.htm">其他公司的推荐岗位</a></article></section></main>`,'https://www.zhaopin.com/companydetail/jobs-CZL123456/');
 const w=d.window,r=w.JobAssistantExtractor.extract(w.document,w.location.href);
 assert.equal(r.status,'company');assert.equal(r.company_capture.company_key,'zhaopin:CZL123456');
 assert.deepEqual(Array.from(r.company_capture.jobs.map(x=>x.job_key)),['CCL123456J001','CCL123456J002']);
 assert.equal(r.company_capture.jobs[0].url,'https://www.zhaopin.com/jobdetail/CCL123456J001.htm');
 assert.equal(r.company_capture.jobs[0].salary,'8000-12000元');assert.match(r.company_capture.jobs[0].conditions,/杭州/);
 assert.ok(!JSON.stringify(r.company_capture.jobs).includes('虚构招聘者姓名'));assert.ok(!JSON.stringify(r.company_capture.jobs).includes('OTHER9999'));d.window.close();
});
test('Zhaopin missing summary does not invent a title from recruiter or other cards',()=>{
 const d=zhaopin(),w=d.window;w.document.querySelector('.job-detail-modules__summary-wrap').remove();
 assert.notEqual(w.JobAssistantExtractor.extract(w.document,w.location.href).status,'ready');d.window.close();
});
test('Zhaopin standalone detail identity is available for explicit selection fallback without tracking parameters',()=>{
 const d=page('<main><h1>岗位标题</h1></main>','https://www.zhaopin.com/jobdetail/JOB987654.htm?track=private');
 const hint=d.window.JobAssistantExtractor.pageIdentity(d.window.document,d.window.location.href);
 assert.equal(hint.job_key,'JOB987654');assert.equal(hint.source_site,'zhaopin');assert.equal(hint.url,'https://www.zhaopin.com/jobdetail/JOB987654.htm');assert.ok(!JSON.stringify(hint).includes('private'));d.window.close();
});
test('Zhaopin resume structure diagnostics return label/tag/class/count only',()=>{
 const privateMarker='虚构简历正文勿输出：示例公司、联系方式和项目业绩';
 const d=page(`<main class="resume-root"><section class="resume-module"><div class="module-title">个人优势</div><div class="module-content"><p>${privateMarker}</p></div></section><section class="work-module"><div class="work-heading">工作／实习经历</div><article class="work-item"><span>虚构企业</span><p>${privateMarker}</p></article></section><aside><h3>附件</h3><p>附件不应进入结构诊断。</p></aside></main>`,'https://i.zhaopin.com/resume');
 const report=d.window.JobAssistantExtractor.diagnose(d.window.document,d.window.location.href),serialized=JSON.stringify(report);
 assert.equal(report.path,'/resume');assert.equal(report.status,'unavailable');assert.equal(report.resume_structure.length,2);assert.deepEqual([...report.resume_structure.map(x=>x.label)],['个人优势','工作／实习经历']);assert.ok(serialized.includes('resume-module'));assert.ok(serialized.includes('work-item'));assert.ok(!serialized.includes(privateMarker));assert.ok(!serialized.includes('虚构企业'));assert.ok(!serialized.includes('附件不应'));d.window.close();
 const boss=page('<main><h2>个人优势</h2></main>','https://www.zhipin.com/web/geek/resume');assert.equal(boss.window.JobAssistantExtractor.diagnose(boss.window.document,boss.window.location.href).resume_structure,null);boss.window.close();
});
test('Zhaopin explicit resume import uses body sections despite diagnosis-scroll classes and duplicate jobs-bar navigation',()=>{
 const d=page(`<div class="online-resume">
  <section class="diagnosis-scroll__update-unifiedpurpose"><div class="zp-evalution-title clearfix"><span class="zp-evalution-title-text fl">个人优势</span></div><div class="zp-evalution-content"><p>虚构优势：擅长客户需求整理与方案沟通。</p></div></section>
  <section class="resume-wanna-wrapper diagnosis-scroll__update-unifiedpurpose jump-to"><p class="wanna-title clearfix">求职意向</p><div><div class="wanna-title__item-warpper wanna-title__job-container">售前工程师 · 杭州</div><div class="wanna-title__item-warpper wanna-title__job-container">解决方案顾问 · 上海</div><div class="wanna-title__item-warpper wanna-title__job-container">客户成功经理 · 远程</div></div></section>
  <section class="resume-job-exp-wrapper diagnosis-scroll__update-workexperience"><p class="job-exp-title clearfix">工作／实习经历</p><div class="job-exp-add-null"><button>添加工作经验</button></div><div class="job-exp-pre-wrapper"><div class="job-exp-pre-item">虚构科技公司 · 售前实习 · 协助整理产品演示材料。</div><div class="job-exp-pre-item">样例信息公司 · 客户支持 · 整理需求并跟进试用。</div><p class="clearfix"><span class="show-all">查看全部</span></p></div></section>
  <section class="diagnosis-scroll__update-unifiedpurpose"><p>教育经历</p><ul><li>示例大学 · 本科</li></ul></section>
  <section class="diagnosis-scroll__update-unifiedpurpose"><p>项目经历</p><button>添加项目经历</button></section>
  <section><p>培训经历</p><button>添加培训经历</button></section>
  <section><p>语言能力</p><button>添加语言能力</button></section>
  <section><p>专业技能</p><button>添加专业技能</button></section>
  <section><p>证书</p><ul><li>虚构技能证书</li></ul></section>
 </div><ul class="jobs-bar__list">${['个人优势','求职意向','工作／实习经历','教育经历','项目经历','培训经历','语言能力','专业技能','获得证书'].map(label=>`<li class="jobs-bar__list__item"><a class="jobs-bar__link">${label}</a></li>`).join('')}</ul>
 <aside class="resume-diagnosis"><p>虚构诊断建议，不得导入。</p></aside>`, 'https://i.zhaopin.com/resume');
 const w=d.window,passive=w.JobAssistantExtractor.extract(w.document,w.location.href);
 assert.equal(passive.status,'resume');assert.ok(!JSON.stringify(passive).includes('虚构优势'));
 const result=w.JobAssistantExtractor.extractResume(w.document,w.location.href);
 assert.equal(result.status,'ready');assert.equal(result.resume.schema,'job-assistant.zhaopin-resume.v1');
 assert.deepEqual(Array.from(result.resume.sections.advantage.items),['虚构优势：擅长客户需求整理与方案沟通。']);
 assert.deepEqual(Array.from(result.resume.sections.expectations.items),['售前工程师 · 杭州','解决方案顾问 · 上海','客户成功经理 · 远程']);
 assert.deepEqual(Array.from(result.resume.sections.work.items),['虚构科技公司 · 售前实习 · 协助整理产品演示材料。','样例信息公司 · 客户支持 · 整理需求并跟进试用。']);
 assert.deepEqual(Array.from(result.resume.sections.certificates.items),['虚构技能证书']);
 assert.equal(result.resume.sections.projects.status,'empty',JSON.stringify(result.resume.sections.projects));
 assert.equal(result.resume.sections.custom.status,'empty');
 assert.ok(!JSON.stringify(result).includes('虚构诊断建议'));
 assert.ok(!JSON.stringify(result).includes('查看全部'));
 const duplicate=w.document.querySelector('.online-resume section').cloneNode(true);
 w.document.querySelector('.online-resume').append(duplicate);
 assert.equal(w.JobAssistantExtractor.extractResume(w.document,w.location.href).resume.sections.advantage.status,'unavailable');
 duplicate.remove();
 d.window.close();
});
test('Zhaopin agency listing uses the one verified company link in the detail root',()=>{
 const d=zhaopin(),w=d.window;
 w.document.querySelector('.job-detail-summary a').remove();
 w.document.querySelector('.job-detail-summary').insertAdjacentHTML('beforeend','<span>客户公司：某科技公司</span>');
 const r=w.JobAssistantExtractor.extract(w.document,w.location.href);
 assert.equal(r.status,'ready');assert.equal(r.capture.company,'虚构公司甲');d.window.close();
});
test('Zhaopin rejects ambiguous detail links and conflicting direct URL',()=>{
 const d=zhaopin(),w=d.window;
 assert.notEqual(w.JobAssistantExtractor.extract(w.document,'https://www.zhaopin.com/jobdetail/DIFFERENT123.htm').status,'ready');
 w.document.querySelector('.job-detail-modules__body').insertAdjacentHTML('beforeend','<a href="/jobdetail/DIFFERENT123.htm">另一详情</a>');
 assert.notEqual(w.JobAssistantExtractor.extract(w.document,w.location.href).status,'ready');d.window.close();
});
test('real 58 uses pos_name, not breadcrumb h1, category or recommendation',()=>{
 const d=page(`<div class="bread"><h1>城区普工招聘</h1></div><div class="leftCon">
 <div class="item_con pos_info"><div class="pos_base_info"><span class="pos_title">普工/操作工</span><span class="pos_salary">8000元/月</span></div><span class="pos_name">虚构物流园装卸工</span></div>
 <div class="item_con"><div class="subitem_con pos_description"><h2 class="title">职位描述</h2><div class="posDes">${jd}</div></div><div class="comp_intro">公司介绍不要读</div></div></div>
 <div class="rightCon"><a href="https://qy.58.com/123456789/">虚构物流公司</a><a href="https://qy.58.com/hz_/">其他行业</a><a href="https://qy.58.com/123456789/#joblist">28</a></div>`,'https://lf.58.com/zpshengchankaifa/67714798680634x.shtml');
 const w=d.window,r=w.JobAssistantExtractor.extract(w.document,w.location.href);
 assert.equal(r.status,'ready');assert.equal(r.capture.title,'虚构物流园装卸工');assert.equal(r.capture.company,'虚构物流公司');assert.equal(r.capture.jd,jd);
 w.document.querySelector('.pos_name').remove();assert.notEqual(w.JobAssistantExtractor.extract(w.document,w.location.href).status,'ready');d.window.close();
});
