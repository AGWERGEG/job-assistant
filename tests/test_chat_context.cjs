const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');

const code=fs.readFileSync(path.join(__dirname,'../extension/extractor.js'),'utf8');
const contentCode=fs.readFileSync(path.join(__dirname,'../extension/content.js'),'utf8');
const url='https://www.zhipin.com/web/geek/chat';
function fixture(html){
 const dom=new JSDOM(html,{url,runScripts:'outside-only'});
 dom.window.HTMLElement.prototype.getClientRects=function(){return [{width:20,height:20}];};
 dom.window.eval(code);
 return dom;
}
const header=(name='郭芮',company='有赞',title='业务主管')=>`<div class="chat-header"><span>${name} ${company} | ${title}</span></div>`;
const strip=(title='有赞AI销售-产品力强高提成 16-25K 杭州',extra='')=>`<div class="job-strip"><span>${title}</span>${extra}</div>`;

test('selected 点众科技 conversation never borrows 郭芮 from contact list',()=>{
 const dom=fixture('<div class="chat-layout"><div class="contact-list"><div>郭芮 有赞 业务主管</div><div>昨天 董先生 深圳市同数营科技 招聘主管</div></div><main class="selected-conversation"><div class="chat-header"><span>李先生</span><span>点众科技</span><span>HR招聘</span><button>更多</button></div><div class="job-strip"><span>短剧编剧/责编</span><span>15-25K</span><span>深圳</span><span>查看职位</span></div><div class="messages">私人聊天不参与核验</div></main></div>');
 const result=dom.window.JobAssistantExtractor.chatContext(dom.window.document,url);
 assert.equal(result.status,'ready');
 assert.deepEqual({...result.chat},{url,recruiter_name:'李先生',company:'点众科技',job_title:'短剧编剧/责编'});
 dom.window.close();
});

test('accepts an unlisted HR job title and reads only adjacent header and salary strip',()=>{
 const dom=fixture(`<aside><nav>全部 未读 新招呼</nav><div>董先生 另一家公司 产品经理</div></aside><main>${header()}${strip()}<div class="messages">会话正文不得进入提取结果</div></main>`);
 const result=dom.window.JobAssistantExtractor.chatContext(dom.window.document,url);
 assert.equal(result.status,'ready');
 assert.equal(result.chat.recruiter_name,'郭芮');
 assert.equal(result.chat.company,'有赞');
 assert.equal(result.chat.job_title,'有赞AI销售-产品力强高提成');
 assert.ok(!JSON.stringify(result).includes('全部'));
 assert.ok(!JSON.stringify(result).includes('董先生'));
 assert.ok(!JSON.stringify(result).includes('会话正文'));
 dom.window.close();
});

test('contaminated contact-list header is rejected instead of binding the wrong HR',()=>{
 const dom=fixture(`<main><div class="chat-header">全部 未读 新招呼 仅沟通 更多 15:32 郭芮 有赞 业务主管 [送达] 您好，我对这个岗位非常感兴趣 15:31 张晶晶 深信服科技 郭芮 有赞业务主管 更多</div>${strip('有赞AI销售-产品力强高提成 16-25K 杭州','<a href="/job_detail/current1.html">查看职位</a>')}</main>`);
 const result=dom.window.JobAssistantExtractor.chatContext(dom.window.document,url);
 assert.equal(result.status,'incomplete');assert.equal(result.chat,undefined);dom.window.close();
});

test('left contact-list salary and view-position rows cannot be combined with current header',()=>{
 const dom=fixture(`<aside><div>${header('董先生','旧公司','招聘主管')}${strip('旧职位 8-12K 深圳','<a href="/job_detail/list999.html">查看职位</a>')}</div><div>全部 未读 新招呼 董先生</div></aside><main>${header('郭芮','有赞','业务主管')}${strip('有赞AI销售 16-25K 杭州','<a href="/job_detail/current1.html?ka=chat">查看职位</a>')}<div>私人消息 99-100K</div></main>`);
 const result=dom.window.JobAssistantExtractor.chatContext(dom.window.document,url);
 assert.equal(result.status,'incomplete','multiple structurally valid pairs must fail closed');
 dom.window.close();
});

test('multiple adjacent conversation pairs are ambiguous and return no contact data',()=>{
 const dom=fixture(`<main>${header('郭芮','有赞','业务主管')}${strip('有赞AI销售 16-25K 杭州')}<section>${header('董先生','有赞','产品负责人')}${strip('数据产品经理 20-30K 杭州')}</section></main>`);
 const result=dom.window.JobAssistantExtractor.chatContext(dom.window.document,url);
 assert.equal(result.status,'incomplete');
 assert.equal(result.chat,undefined);
 dom.window.close();
});

test('header switching updates the selected identity while preserving salary-only layout',()=>{
 const dom=fixture(`<main>${header('郭芮','有赞','业务主管')}${strip('有赞AI销售 16-25K 杭州')}</main>`);
 const read=()=>dom.window.JobAssistantExtractor.chatContext(dom.window.document,url);
 assert.equal(read().chat.recruiter_name,'郭芮');
 dom.window.document.querySelector('.chat-header span').textContent='李女士 云栖科技 | 客户成功总监';
 dom.window.document.querySelector('.job-strip span').textContent='客户成功经理 18-24K 杭州';
 const changed=read();
 assert.equal(changed.status,'ready');
 assert.equal(changed.chat.recruiter_name,'李女士');
 assert.equal(changed.chat.company,'云栖科技');
 assert.equal(changed.chat.job_title,'客户成功经理');
 dom.window.close();
});

test('keeps validated public BOSS job URLs and ignores untrusted link URLs',()=>{
 const dom=fixture(`<main>${header()}${strip('有赞AI销售 16-25K 杭州','<a href="https://www.zhipin.com/job_detail/job1234.html?ka=chat">查看职位</a>')}</main>`);
 const accepted=dom.window.JobAssistantExtractor.chatContext(dom.window.document,url);
 assert.equal(accepted.status,'ready');
 assert.equal(accepted.chat.job_url,'https://www.zhipin.com/job_detail/job1234.html');
 dom.window.document.querySelector('.job-strip').innerHTML='<span>有赞AI销售 16-25K 杭州</span><a href="https://evil.example/job_detail/evil1.html">查看职位</a>';
 const rejected=dom.window.JobAssistantExtractor.chatContext(dom.window.document,url);
 assert.equal(rejected.status,'ready');
 assert.equal(rejected.chat.job_url,undefined);
 dom.window.close();
});

test('real BOSS nested job strip accepts icon text and nearby wrapped header',()=>{
 const dom=fixture('<main><div class="conversation"><div class="head-wrap"><div>王女士 杭州隐律科技有限公司 招聘者</div></div><div class="job-wrap"><div><span>私域销售</span><span>8-13K</span><span>杭州</span><a>查看职位\uE031</a></div></div></div></main>');
 const result=dom.window.JobAssistantExtractor.chatContext(dom.window.document,url);
 assert.equal(result.status,'ready');assert.equal(result.chat.recruiter_name,'王女士');assert.equal(result.chat.company,'杭州隐律科技有限公司');assert.equal(result.chat.job_title,'私域销售');dom.window.close();
});

test('online status appended to HR header is excluded from identity',()=>{
 const dom=fixture('<main><div class="chat-header">范女士 杭州大辰臻境科技 | 人事经理 在线</div><div class="job-strip"><span>暖通 销售代表</span><b>8-12K</b><span>杭州</span></div><div class="message-list">请问在考虑新的工作机会吗？</div></main>');
 const result=dom.window.JobAssistantExtractor.chatContext(dom.window.document,url);
 assert.equal(result.status,'ready');assert.equal(result.chat.recruiter_name,'范女士');assert.equal(result.chat.company,'杭州大辰臻境科技');assert.equal(result.chat.job_title,'暖通 销售代表');dom.window.close();
});

test('real BOSS header trailing more action is excluded from identity',()=>{
 const dom=fixture('<main><div class=\"chat-header\">胡女士 贞观汉文化 校长 <span>更多</span></div>'+strip('课程顾问主管（销售主管) 18-25K 杭州','<span>查看职位</span>')+'</main>');
 const result=dom.window.JobAssistantExtractor.chatContext(dom.window.document,url);
 assert.equal(result.status,'ready');assert.equal(result.chat.url,url);assert.equal(result.chat.recruiter_name,'胡女士');assert.equal(result.chat.company,'贞观汉文化');assert.equal(result.chat.job_title,'课程顾问主管（销售主管)');dom.window.close();
});

test('separate header text nodes support business roles and online badges without reading list ancestors',()=>{
 const dom=fixture('<aside><nav>全部 未读 新招呼 仅沟通 更多</nav><div>10:48 郭芮 有赞 业务主管 [送达] 私人消息</div><div>昨天 董先生 旧公司 招聘主管</div></aside><main><div class="chat-header"><span>郭芮</span><span>有赞</span><span>业务主管</span><span>在线</span><button>更多</button></div><div class="job-strip"><div><span>有赞AI销售</span><span>16-25K</span><span>杭州</span></div><div><span>查看职位</span></div></div><div>私人消息</div></main>');
 const result=dom.window.JobAssistantExtractor.chatContext(dom.window.document,url);
 assert.equal(result.status,'ready');assert.equal(result.chat.recruiter_name,'郭芮');assert.equal(result.chat.company,'有赞');assert.equal(result.chat.job_title,'有赞AI销售');dom.window.close();
});

test('content script reuses chat context between mutations and ignores message-only changes',async()=>{
 const dom=fixture(`<main class="message-wrapper"><div class="chat-header">郭芮 有赞 业务主管</div>${strip()}<div class="message-list">初始消息</div></main>`),w=dom.window;
 let listener,calls=0;w.chrome={runtime:{id:'test-extension',getURL:p=>'chrome-extension://test/'+p,onMessage:{addListener:fn=>{listener=fn;}}}};
 const original=w.JobAssistantExtractor.chatContext;w.JobAssistantExtractor.chatContext=(...args)=>{calls++;return original(...args);};w.eval(contentCode);
 const read=()=>new Promise(resolve=>listener({type:'JA_CHAT_CONTEXT'},{id:'test-extension'},resolve));
 await read();await read();assert.equal(calls,1);
 w.document.querySelector('.message-list').textContent='新消息内容变化';await new Promise(r=>setTimeout(r,0));await read();assert.equal(calls,1);
 w.document.querySelector('.chat-header').textContent='李女士 云栖科技 招聘主管';await new Promise(r=>setTimeout(r,0));await read();assert.equal(calls,2);
 dom.window.close();
});

test('compact flattened business header is read without the preceding contact list',()=>{
 const dom=fixture('<aside><div>全部 未读 新招呼</div><div>董先生 旧公司 招聘主管</div></aside><main><div>郭芮 有赞 业务主管</div>'+strip('有赞AI销售 16-25K 杭州')+'</main>');
 const result=dom.window.JobAssistantExtractor.chatContext(dom.window.document,url);
 assert.equal(result.status,'ready');assert.equal(result.chat.recruiter_name,'郭芮');assert.equal(result.chat.company,'有赞');assert.ok(!JSON.stringify(result).includes('董先生'));dom.window.close();
});
