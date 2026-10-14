function isBackground(kind){return ['tailor_resume','analyze_job','interview_prep','interview_review'].includes(kind);}
function resultText(result){return result?.primary_output||result?.result_markdown||result?.markdown||result?.reply||result?.summary||'';}
function resultBody(result){const body=element('div','');body.className='result-content';const primary=resultText(result);body.append(window.JobAssistantReply.render(primary));const more=result?.result_markdown||result?.markdown||'';if(more&&more.trim()!==primary.trim()){const detail=document.createElement('details');detail.className='result-evidence';detail.append(element('summary','详细依据'),window.JobAssistantReply.render(more));body.append(detail);}return body;}

const $=id=>document.getElementById(id);
const scope=crypto.randomUUID();
let seq=0,connected=false,ready=false,busy=false,polling=false,current=null,candidate=null,key='',windowId,activeTab=null,pending=false,backgroundPending=false,manual=null;
let needsSync=false,readiness=null,companyFeedbackError='',companyFeedbackSource='';
let discovered=false,pairingPending=false;
const extensionManifest=chrome.runtime.getManifest?.()||{};
$('extension-version').textContent=extensionManifest.version_name||extensionManifest.version||'未知';
const expandedArtifacts=new Set();
let historyKey='',artifactItems=[],request=null,activePath='',contextSafe=false,targetCapture=null,companyReading=null,restored=false,guide=null,serviceVersion='',serviceCapabilities=[];
const chatDrafts=new Map();let historyTarget='';
const switchButton=document.createElement('button');switchButton.id='open-job-switch';switchButton.className='text-button';switchButton.textContent='切换岗位';$('pinned-context').append(switchButton);
const switchDialog=document.createElement('dialog');switchDialog.id='job-switch-dialog';const switchHeading=document.createElement('div');switchHeading.className='dialog-heading';switchHeading.append(element('h2','切换聊天岗位'));const switchClose=element('button','收起');switchClose.id='close-job-switch';switchClose.className='text-button';switchHeading.append(switchClose);switchDialog.append(switchHeading);const switchSearch=document.createElement('input');switchSearch.id='job-switch-search';switchSearch.type='search';switchSearch.placeholder='搜索岗位或公司';switchDialog.append(switchSearch);const switchList=document.createElement('div');switchList.id='job-switch-list';switchDialog.append(switchList);document.body.append(switchDialog);
// Keep only the next action beside the pinned job. Binding management lives in More.
const chatLinkNotice=document.createElement('section');chatLinkNotice.id='chat-link-notice';chatLinkNotice.hidden=true;chatLinkNotice.setAttribute('aria-live','polite');
const chatNoticeText=element('div','');chatNoticeText.append(element('small','当前 HR 会话'));const chatNoticeTitle=element('strong','');chatNoticeTitle.id='chat-link-notice-title';chatNoticeText.append(chatNoticeTitle);chatLinkNotice.append(chatNoticeText);
for(const [id,label] of [['chat-link-use-job','切换到此岗位'],['chat-link-review','核对关联']]){const button=element('button',label);button.id=id;button.type='button';button.className='secondary';chatLinkNotice.append(button);}
$('pinned-context').after(chatLinkNotice);
const chatLinkSettings=element('details','');chatLinkSettings.id='chat-link-settings';chatLinkSettings.hidden=true;chatLinkSettings.append(element('summary','HR 会话关联 · 高级设置'));
const chatLinkCard=element('section','');chatLinkCard.id='chat-link-card';chatLinkCard.hidden=true;
for(const [tag,id,label] of [['strong','chat-link-title',''],['p','chat-link-copy',''],['button','chat-link-open-job','返回对应岗位'],['button','chat-link-save','核对并绑定当前岗位'],['button','chat-link-unbind','解绑此会话']]){const node=element(tag,label);node.id=id;if(tag==='button')node.type='button';if(id==='chat-link-save')node.className='secondary';if(id==='chat-link-unbind')node.className='text-button';chatLinkCard.append(node);}
const chatLinkMatches=element('div','');chatLinkMatches.id='chat-link-matches';chatLinkCard.append(chatLinkMatches);chatLinkSettings.append(chatLinkCard);$('chat-context-note').after(chatLinkSettings);
let chatPageActive=false,chatLinkContext=null,chatLinkResult=null,chatLinkSignature='',chatLinkTab=0,chatLinkView='',chatLinkReason='';
const chatSignature=(tab,chat)=>JSON.stringify([tab?.id,chat?.recruiter_name,chat?.company,chat?.job_title,chat?.conversation_id,chat?.job_url]);
function renderChatLink(result=null,reason=''){
 chatLinkResult=result;chatLinkReason=reason;chatLinkCard.hidden=chatLinkSettings.hidden=!chatPageActive;
 chatLinkNotice.hidden=true;
 if(!chatPageActive){chatLinkSettings.open=false;chatLinkView='';return;}
 const linked=result?.link,conflict=result?.conflict||'',matches=result?.matches||[];
 contextSafe=!!chatLinkContext&&!!linked&&!conflict&&linked.job_id===current?.id;
 const switchNeeded=!!chatLinkContext&&!!linked&&!conflict&&!contextSafe;
 chatLinkNotice.hidden=!connected||contextSafe;
 $('chat-link-use-job').hidden=!switchNeeded;$('chat-link-use-job').disabled=busy||needsSync;
 $('chat-link-review').hidden=switchNeeded;$('chat-link-review').disabled=busy;
 $('chat-link-review').textContent=reason?'查看原因':!linked&&matches.length?'核对并绑定':'查看关联';
 $('chat-link-notice-title').textContent=switchNeeded?linked.title+' · '+linked.company:reason?'当前会话尚未核验':conflict?'当前会话关联需重新核对':matches.length?'找到匹配岗位，待核对绑定':'尚未找到此会话的已建档岗位';
 $('chat-link-notice-title').title=$('chat-link-notice-title').textContent;
 const view=JSON.stringify([chatLinkContext,result,reason,current?.id]);if(view===chatLinkView)return;chatLinkView=view;
 $('chat-link-title').textContent=chatLinkContext?'当前会话：'+chatLinkContext.recruiter_name+' · '+chatLinkContext.company+' · '+chatLinkContext.job_title:'当前 HR 会话尚未核验';
 let copy=reason||'';
 if(!copy&&conflict)copy='已保存的关联与当前页面冲突：'+conflict;
 if(!copy&&result?.legacy)copy='旧版仅按聊天 URL 保存的记录已停用；请核对当前会话后重新绑定。';
 if(!copy&&matches.length)copy='已找到与当前企业、岗位相符的本地 JD；请选择并核对后绑定。';
 if(!copy)copy='没有找到匹配的已建档 JD。请点击招聘页“查看职位”，打开完整 JD 并确认岗位，再回到此会话。';
 if(matches.length&&matches.some(j=>!j.recruiter_verified))copy+=' JD 未提供招聘者姓名的候选项，需要核对上方 HR。';
 $('chat-link-copy').textContent=copy;
 if(linked&&!conflict)$('chat-link-copy').textContent='已核验关联：'+linked.title+' · '+linked.company+'。'+(result.recruiter_verified?'JD 招聘者姓名也一致。':'JD 未提供招聘者姓名，请核对上方 HR。')+'可以返回岗位，或解绑后重新绑定。';
 $('chat-link-open-job').hidden=!linked||!!conflict;$('chat-link-unbind').hidden=!linked;
 $('chat-link-save').hidden=!!linked;$('chat-link-save').disabled=!chatLinkContext||!current||!matches.some(j=>j.id===current.id);
 chatLinkMatches.replaceChildren();if(!linked&&chatLinkContext){for(const job of matches){if(job.id===current?.id)continue;const button=element('button','选定匹配岗位：'+job.title+' · '+job.company);button.type='button';button.className='secondary';button.onclick=()=>chooseChatJob(job.id);chatLinkMatches.append(button);}}
}
$('chat-link-review').onclick=()=>{openDetails();chatLinkSettings.open=true;chatLinkSettings.scrollIntoView?.({block:'nearest'});};
async function chooseChatJob(jobId){
 if(busy)return;busy=true;
 try{const expected=chatLinkSignature;await checkedChat(expected);chatDrafts.set(current?.id||'',$('message').value);const nextSeq=seq+1;const chosen=await api('/select',{scope,seq:nextSeq,job_id:jobId});seq=nextSeq;current=chosen.job;targetCapture=chosen.capture;candidate=null;contextSafe=false;historyKey='';$('message').value=chatDrafts.get(current.id)||'';await loadHistory();await checkedChat(expected).catch(()=>{chatLinkContext=null;renderChatLink(null,'HR 会话已变化，正在重新核验。');});renderChatLink(chatLinkResult,chatLinkReason);status(chatLinkResult?.link?.job_id===jobId?'已切换到此 HR 会话关联的岗位。':'已选定匹配岗位。请核对招聘者后点击绑定。');}catch(e){status(e.message,true);}finally{busy=false;showCandidate();}
}

async function renderSideJobSwitch(){const result=await api('/jobs',{scope});const list=$('job-switch-list');list.replaceChildren();const query=$('job-switch-search').value.trim().toLowerCase();for(const job of result.jobs.filter(j=>(j.title+' '+j.company).toLowerCase().includes(query))){const button=element('button',job.title+' · '+job.company);button.onclick=async()=>{try{chatDrafts.set(current?.id||'',$('message').value);const nextSeq=seq+1;const chosen=await api('/select',{scope,seq:nextSeq,job_id:job.id});seq=nextSeq;current=chosen.job;targetCapture=chosen.capture;candidate=null;contextSafe=false;historyKey='';$('message').value=chatDrafts.get(current.id)||'';switchDialog.close();await loadHistory();showCandidate();status('已手动切换聊天岗位；当前网页未必是该岗位，请使用链接记录返回详情页。');}catch(e){status(e.message,true);}};list.append(button);}if(!list.children.length)list.append(element('p','暂无匹配岗位。请先到岗位详情页读取并确认 JD。'));}
switchButton.onclick=()=>{renderSideJobSwitch().then(()=>switchDialog.showModal()).catch(e=>status(e.message,true));};$('close-job-switch').onclick=()=>switchDialog.close();$('job-switch-search').oninput=()=>renderSideJobSwitch().catch(e=>status(e.message,true));
async function checkedChat(expected=chatLinkSignature){const tab=await tabNow();if(!tab||tab.id!==chatLinkTab)throw Error('聊天页面已切换，请稍候重新核验');const observed=await chrome.tabs.sendMessage(tab.id,{type:'JA_CHAT_CONTEXT'});if(observed?.status!=='ready'||observed.stable_ms<800||chatSignature(tab,observed.chat)!==expected||chatLinkSignature!==expected)throw Error('HR 会话已变化，请等页面稳定后重新核验');return observed.chat;}
async function refreshChatLinkAfterAction(signature,chat){
 const result=await api('/link-context',{scope,chat});
 try{await checkedChat(signature);renderChatLink(result);}catch(e){chatLinkContext=null;renderChatLink(null,'刚才会话的操作已保存，当前会话已变化，正在重新核验。');throw e;}
}
$('chat-link-use-job').onclick=()=>{if(chatLinkResult?.link&&!chatLinkResult.conflict)chooseChatJob(chatLinkResult.link.job_id);};
$('chat-link-open-job').onclick=async()=>{const linked=chatLinkResult?.link,signature=chatLinkSignature;if(!linked||chatLinkResult.conflict)return;try{await checkedChat(signature);const r=await api('/links',{scope,job_id:linked.job_id});const detail=r.links.find(l=>l.kind==='job_detail');if(!detail)throw Error('尚未记录岗位详情链接，请重新打开详情页确认 JD');await checkedChat(signature);await send({type:'JA_OPEN_URL',url:detail.url});}catch(e){status(e.message,true);}};
$('chat-link-save').onclick=async()=>{if(busy||!current||!chatLinkContext)return;const signature=chatLinkSignature,jobId=current.id,binding=seq;busy=true;try{const chat=await checkedChat(signature);await api('/link-save',{scope,seq:binding,job_id:jobId,chat});await refreshChatLinkAfterAction(signature,chat);status('企业与岗位核验通过，已保存当前 HR 会话关联。');}catch(e){status(e.message,true);}finally{busy=false;showCandidate();}};
$('chat-link-unbind').onclick=async()=>{if(busy||!chatLinkResult?.link)return;const signature=chatLinkSignature,jobId=chatLinkResult.link.job_id;busy=true;try{const chat=await checkedChat(signature);await api('/link-unbind',{scope,job_id:jobId,chat});await refreshChatLinkAfterAction(signature,chat);status('已解绑当前 HR 会话；历史岗位和聊天内容未删除，可以重新选择绑定。');}catch(e){status(e.message,true);}finally{busy=false;showCandidate();}};

function waitCopy(start,status,workbench=false,attempts=0){
 const seconds=Math.max(0,Math.floor(Date.now()/1000-(Number(start)||Date.now()/1000)));
 const prefix=attempts>1?'第 '+attempts+' 次尝试 · ':'';
 if(status==='queued')return prefix+'正在排队 · 本次已等待 '+seconds+' 秒';
 if(seconds<15)return prefix+(workbench?'后台任务已交给模型':'已交给模型')+' · 本次已等待 '+seconds+' 秒';
 if(seconds<90)return prefix+'模型正在生成 · 本次已等待 '+seconds+' 秒；部分兼容 API 首段可能需要 30–90 秒';
 return prefix+'模型长请求响应较慢 · 本次已等待 '+seconds+' 秒；可以继续等待或取消任务';
}
function updateWaitLabels(){document.querySelectorAll('[data-wait-start]').forEach(n=>{n.textContent=waitCopy(n.dataset.waitStart,n.dataset.waitStatus,n.dataset.waitWorkbench==='1',Number(n.dataset.waitAttempts||0));});}
function syncConversationUI(){
 document.body.classList.toggle('needs-sync',needsSync);
 $('connection-badge').textContent=connected?'已连接':'未连接';
 if(!connected&&$('details-dialog').open)$('details-dialog').close();
 const different=needsSync||!!candidate&&(!current||signature(candidate)!==signature(targetCapture));
 $('candidate-notice').hidden=!connected||!different;
 $('candidate-title').textContent=needsSync?'岗位资料已在工作台更新':candidate?candidate.title+' · '+candidate.company:'';
 $('candidate-title').title=$('candidate-title').textContent;
 $('candidate-kicker').textContent=needsSync?'同步后可继续聊天，不覆盖工作台修改':current?'正在浏览另一岗位 · 对话目标不变':'已读取 · 尚未选定';
 $('switch-target').textContent=needsSync?'同步已保存岗位':current?'切换到这个':'聊这个岗位';
 $('switch-target').disabled=$('confirm').disabled;
 $('chat-target').title=$('chat-target').textContent;
 if(!current&&!$('messages').querySelector('.turn')){$('messages').textContent=candidate?'读到这个岗位了。可以先分析，或选定后说说你最在意什么。':'点开一个感兴趣的岗位，叫我一起看看。';}
}
function renderPairing(){
 const box=$('pairing');box.hidden=connected;
 if(connected)return;
 if(pairingPending){$('pairing-title').textContent='请在工作台确认连接';$('pairing-copy').textContent='工作台已经打开。点击“连接这个侧栏”后，这里会自动继续。';$('auto-connect').textContent='等待工作台确认…';$('auto-connect').disabled=true;return;}
 const mismatch=serviceVersion&&serviceVersion!==(extensionManifest.version_name||extensionManifest.version);
 $('pairing-title').textContent=mismatch?'工作台与侧栏版本不一致':discovered?'已找到本机工作台':'尚未找到本机工作台';
 $('pairing-copy').textContent=mismatch?`侧栏 ${extensionManifest.version_name||extensionManifest.version||'未知'} · 工作台 ${serviceVersion}。请更新同一版本后重新连接。`:discovered?'点击一次连接；工作台会要求你确认授权。':'先点击“打开 / 启动工作台”。程序运行后再连接。';
 $('auto-connect').textContent=mismatch?'重新检测':discovered?'连接我的工作台':'重新检测';$('auto-connect').disabled=false;
}
function related(s){return !!current?.company_key && s.company_capture?.company_key===current.company_key;}
function sourceSite(c){if(c?.source_site)return c.source_site;try{const h=new URL(c?.url).hostname;return h==='58.com'||h.endsWith('.58.com')?'58':h==='zhaopin.com'||h.endsWith('.zhaopin.com')?'zhaopin':'boss';}catch{return 'boss';}}
function companyMaterialCount(company){return (company?.sections?.length||0)+(company?.jobs?.length||0)+(company?.categories?.length||0);}
function canBindCompany(company=companyReading){if(!current||current.company_key||!company?.company_key||!company?.company_url||!company?.source_url)return false;const site=sourceSite(targetCapture);return !!site&&site!=='58'&&company.source_site===site&&sourceSite({url:company.company_url})===site&&sourceSite({url:company.source_url})===site&&companyMaterialCount(company)>0;}
function canSaveCompany(s){return !!current&&!!companyReading&&companyMaterialCount(s.company_capture)>0&&(related(s)||canBindCompany(s.company_capture));}
const signature=c=>c?.job_key?sourceSite(c)+':'+c.job_key:'';
function sameIdentity(s,c){if(!c||s.identity?.conflict)return false;const seen=s.capture?.job_key?s.capture:s.identity;return signature(seen)===signature(c);}
function manualHere(tab){try{return !!manual?.capture&&tab.id===manual.tabId&&sourceSite({url:tab.url})===sourceSite(manual.capture)&&new URL(tab.url).pathname===new URL(manual.capture.url).pathname;}catch{return false;}}
function canUseSnapshot(s,tab){return supported(tab)&&(manualHere(tab)||sameIdentity(s,targetCapture||candidate)||related(s));}
function status(s,error=false){$('status').textContent=s;$('status').className=error?'error':'';}
function element(tag,value){const n=document.createElement(tag);n.textContent=value;return n;}
function artifactLabel(a){const type={tailor_resume:'简历',analyze_job:'分析',interview_prep:'面试卡',interview_review:'面试复盘',suggest_reply:'HR沟通'}[a.kind]||'专项结果';const label=a.display_name||(a.display_index?type+' '+a.display_index:type);return label+' · '+weakDate(a.created||a.updated);}
function weakDate(value){const time=Number(value);if(!time)return '时间未知';const d=new Date(time*1000);return d.toLocaleDateString(undefined,{month:'2-digit',day:'2-digit'});}
function artifactMeta(a){return '完成于 '+weakDate(a.updated||a.created)+' · '+String(a.preview||'').slice(0,120);}
function selectedArtifact(){const id=$('message').dataset.referenceTaskId;return current&&id?artifactItems.find(a=>a.task_id===id):null;}
function renderReference(){const box=$('selected-reference');if(!box)return;const a=selectedArtifact();box.replaceChildren();box.hidden=!a;if(!a){$('message').dataset.referenceTaskId='';return;}const chip=element('span','引用：'+artifactLabel(a));chip.className='reference-chip';chip.title=a.preview||'';const clear=element('button','移除引用');clear.type='button';clear.className='reference-clear';clear.onclick=()=>{$('message').dataset.referenceTaskId='';renderReference();};box.append(chip,clear);}
function selectArtifact(a){if(!current||!a||a.status&&a.status!=='done'||!artifactItems.some(item=>item.task_id===a.task_id))return;$('message').dataset.referenceTaskId=a.task_id;renderReference();if(['/','/引用'].includes($('message').value.trim()))$('message').value='';$('command-menu').hidden=true;$('message').focus();}
async function send(m){const r=await chrome.runtime.sendMessage(m);if(!r?.ok)throw Error(r?.error||'扩展后台不可用');return r.value;}
const api=(path,value={})=>send({type:'JA_API',path,value});
async function syncSavedTarget(){
 const r=await api('/sync',{scope,seq});
 current=r.job;targetCapture={...targetCapture,title:r.job.title,company:r.job.company,company_key:r.job.company_key,url:r.job.url};$('message').dataset.referenceTaskId='';renderReference();
 needsSync=false;historyKey='';await loadHistory();status('已同步工作台保存的岗位资料，可以继续聊。');
}
async function tabNow(){return (await chrome.tabs.query({active:true,windowId}))[0];}
function supported(t){try{const host=new URL(t.url).hostname.toLowerCase();return ['www.zhipin.com','zhipin.com'].includes(host)||host==='zhaopin.com'||host.endsWith('.zhaopin.com')||host==='58.com'||host.endsWith('.58.com');}catch{return false;}}
function JobAssistantURL(value,path){try{const u=new URL(value);return ['www.zhipin.com','zhipin.com'].includes(u.hostname)&&u.pathname.replace(/\/$/,'')===path;}catch{return false;}}
async function snapshot(t){try{return await chrome.tabs.sendMessage(t.id,{type:'JA_SNAPSHOT'});}catch{return {status:'unavailable',reason:'请刷新招聘网页，让扩展重新连接。'};}}
function readinessMessage(){return readiness?.copy||'先在工作台补充档案并确认脱敏内容。';}
function enable(){
 const blocked=!connected||!ready;
 $('blessing').disabled=blocked||!current||needsSync||busy||pending;
 for(const b of document.querySelectorAll('[data-kind],#send'))b.disabled=blocked||needsSync||busy||(!current?!(candidate&&b.dataset.kind):(!contextSafe&&b.id!=='send'))||(isBackground(b.dataset.kind)?backgroundPending:pending)||(readiness?.state==='profile_optional'&&!['quick_analysis','companion_chat',undefined].includes(b.dataset.kind));
 $('composer-hint').textContent=!connected?'请先连接本机工作台':!ready?readinessMessage():needsSync?'先同步已保存岗位，再继续聊天':pending?'正在等待这次聊天完成':'Ctrl / ⌘ + Enter 发送';
 $('confirm').disabled=!connected||busy||(!needsSync&&(!candidate||!!(current&&signature(candidate)===signature(targetCapture))));$('save-company').disabled=!connected||busy||!canSaveCompany({company_capture:companyReading});$('resume-import').disabled=!connected||busy||$('resume-import-card').hidden;
}
async function openWorkbench(taskId='',view='',onboarding=false,page='',extra={}){const port=Number($('port').value);if(port<1024||port>65535)return;const p=new URLSearchParams();p.set('job',current?.id||'');p.set('task',taskId);if(view)p.set('view',view);if(page)p.set('page',page);if(onboarding){p.set('onboarding','1');if(!connected)p.set('pairing','1');}for(const [key,value] of Object.entries(extra))if(value!==undefined&&value!==null&&value!=='')p.set(key,String(value));const url='http://127.0.0.1:'+port+'/#'+p.toString();const opened=await send({type:'JA_OPEN_WORKBENCH',url}).catch(()=>null);if((!opened||opened.tab_id===undefined)&&chrome.tabs?.create)return chrome.tabs.create({url,active:true});return opened;}
function renderReadiness(activeGuide=false){
 const card=$('readiness-card');const blocked=connected&&!ready&&!activeGuide;
 card.hidden=!blocked;if(!blocked)return;
 const state=readiness||{title:'还差一步：完成本地档案',copy:'先在工作台补充经历并确认脱敏内容。',action_label:'去工作台继续',page:'profile'};
 $('readiness-title').textContent=state.title;$('readiness-copy').textContent=state.copy;$('readiness-open').textContent=state.action_label||'去工作台继续';$('readiness-open').onclick=()=>openWorkbench('','',false,state.page||'profile');
}
function renderOnboarding(){
 syncConversationUI();
 document.body.classList.toggle('unpaired',!connected);
 const card=$('onboarding-card');const active=!!(connected&&guide?.active);document.body.classList.toggle('guide-active',active);
 if(active)document.body.dataset.guideStep=guide.step;else delete document.body.dataset.guideStep;
 renderPairing();
 if(!active){card.hidden=true;if(!connected)$('open-onboarding').textContent=discovered?'打开工作台':'打开 / 启动工作台';else $('open-onboarding').textContent='工作台连接设置';renderReadiness(false);return;}
 const seen=candidate||targetCapture;const name=seen?seen.title+' · '+seen.company:'';let title='';let copy='';let label='';let disabled=false;let run=()=>openWorkbench('','',true);
 if(['connection','persona','profile','privacy'].includes(guide.step)){
  const detail={connection:['先连接模型','打开工作台，保存并测试一种接入方式。'],persona:['选你的搭子','选一种说话方式，再取个顺口的称呼。'],profile:['留下真实经历','上传或粘贴简历，只在本机建档。'],privacy:['核对脱敏','看一眼将发送给模型的职业信息。']}[guide.step];[title,copy]=detail;label='打开工作台，继续';
 }else if(['browse','first_reply'].includes(guide.step)){
  title=seen?'就看这个岗位':'打开一个感兴趣的岗位';copy=seen?name+'。点一次，我会确认它并给你简短判断。':'我会等页面读取完成，不会因为浏览而自动选定岗位。';label=seen?'就看这个，帮我分析':'等待读取岗位';disabled=!seen||needsSync||busy||pending||!ready;run=()=>talk('quick_analysis',undefined,true);
 }else if(guide.step==='first_reply_wait'){
  title='我正在帮你看';copy=(guide.job?guide.job.title+' · '+guide.job.company+'。':'')+'简短判断完成后会直接出现在下方。';label='正在整理……';disabled=true;
 }else if(guide.step==='first_success'){
  title='你已经会用了';copy='以后看到岗位，就这样叫我一起看。需要时，再用深入分析、简历、HR 招呼或面试卡。';label='继续看岗位';run=async()=>{try{const r=await api('/onboarding-complete',{});guide=r.guide||r.settings?.guide||null;renderOnboarding();status('首次引导完成。以后按你的节奏来。');}catch(e){status(e.message,true);}};
 }else{title='首次使用';copy='回到工作台继续设置。';label='打开工作台';}
 $('onboarding-title').textContent=title;$('onboarding-copy').textContent=copy;$('onboarding-open').textContent=label;$('onboarding-open').disabled=disabled;$('onboarding-open').onclick=run;card.hidden=false;renderReadiness(true);
}
async function invalidate(){seq++;current=null;targetCapture=null;needsSync=false;contextSafe=false;pending=false;request=null;historyKey='';$('message').dataset.referenceTaskId='';renderReference();$('messages').replaceChildren();$('progress').textContent='';if(connected)await api('/capture',{scope,seq,capture:null});}
async function detectWorkbench(){
 const ports=[Number($('port').value)||8421,...Array.from({length:10},(_,index)=>8421+index)].filter((value,index,array)=>Number.isInteger(value)&&value>=1024&&value<=65535&&array.indexOf(value)===index);
 const result=await send({type:'JA_DISCOVER',ports});discovered=result.found===true;serviceVersion=result.version||'';if(result.port)$('port').value=result.port;renderPairing();return result;
}
async function startPairing(){
 const found=await detectWorkbench();
 if(!found.found){await openWorkbench('','',true);status('工作台还未运行。已尝试打开；启动后点击“重新检测”。');return;}
 if(found.compatible===false){serviceVersion=found.version||'';renderPairing();status(`版本不一致：侧栏 ${extensionManifest.version_name||extensionManifest.version||'未知'}，工作台 ${serviceVersion||'未知'}。未发送配对请求。`,true);return;}
 const request=await send({type:'JA_PAIR_REQUEST',port:found.port});pairingPending=true;renderPairing();
 await openWorkbench('','',true,'',{pair_request:request.request_id});
 status('请在刚打开的工作台确认连接。');
}
async function pollPairing(){if(!pairingPending||connected)return;try{const result=await send({type:'JA_PAIR_STATUS'});if(result.status==='approved'){connected=true;pairingPending=false;restored=false;key='';discovered=true;renderOnboarding();status('工作台已连接，可以开始使用。');await tick();}}catch(e){pairingPending=false;renderPairing();status(e.message,true);}}
function showCandidate(){renderChatLink(chatLinkResult,chatLinkReason);$('chat-target').textContent=current?(chatPageActive&&chatLinkResult?.link?.job_id!==current.id?'已固定对话岗位：':'正在聊：')+current.title+' · '+current.company:'还未选定对话岗位';$('chat-context-note').textContent=current?(contextSafe?'使用已保存岗位与背景；浏览不会自动换目标。':'当前页面未关联目标，聊天仍针对上方已保存岗位，不会读取新页内容。'):'可直接点击分析、简历或招呼，选定眼前岗位后开始。';$('save-company').textContent=candidate&&current&&signature(candidate)!==signature(targetCapture)?'用这个岗位作参考':current&&!current.company_key&&canBindCompany(companyReading)?'确认关联这家公司并保存':'补充这家公司的背景';const c=candidate||targetCapture;$('title').textContent=c?.title||'点开一个岗位，我们一起看看';$('company').textContent=c?.company||companyReading?.name||'';$('source').hidden=!c;if(c)$('source').href=c.url;const same=current&&signature(c)===signature(targetCapture);$('captured').textContent=same?'目标岗位已固定；公司资料与对照岗位不会替换它':c?'当前浏览岗位，可以设为目标':'';const preview=String(c?.jd||'').trim();$('jd-preview').hidden=!preview;$('jd-preview').textContent=preview?`岗位正文预览（${preview.length} 字）：${preview.slice(0,220)}${preview.length>220?'…':''}`:'';$('confirm').textContent=needsSync?'同步已保存岗位':same?'已确认目标岗位':current?'改为目标岗位':'确认这个岗位';$('company-context').hidden=!companyReading&&!current;$('target-label').textContent=current?'目标：'+current.title+' · '+current.company:'先确认一个目标岗位';$('company-reading').textContent=companyReading?'正在了解：'+companyReading.name+' · '+companyReading.sections.length+'个栏目 / '+companyReading.jobs.length+'张已加载岗位卡片':'当前页尚未定位公司资料';const feedbackSource=companyReading?companyReading.company_key+'|'+companyReading.source_url:'';if(feedbackSource!==companyFeedbackSource){companyFeedbackSource=feedbackSource;companyFeedbackError='';}const materials=companyMaterialCount(companyReading);$('company-feedback').className=companyFeedbackError?'company-feedback error':'company-feedback';$('company-feedback').textContent=companyFeedbackError||(companyReading&&materials===0?'已识别公司身份，但尚未读到可保存栏目或岗位卡片。请展开介绍或打开该公司的招聘页。':'');enable();renderOnboarding();}
function renderHistory(turns,artifacts=[]){
  artifactItems=artifacts||[];
  pending=turns.some(t=>!isBackground(t.kind)&&['queued','running'].includes(t.status));backgroundPending=turns.some(t=>isBackground(t.kind)&&['queued','running'].includes(t.status));
  const encoded=JSON.stringify([turns,artifactItems]);if(encoded===historyKey){renderReference();updateWaitLabels();enable();return;}historyKey=encoded;
  const list=$('messages');const follow=historyTarget!==current?.id||list.scrollHeight-list.scrollTop-list.clientHeight<64;const previousTop=list.scrollTop;historyTarget=current?.id||'';list.replaceChildren();
  if(artifacts.length){const h=element('p','已完成专项成果 · 展开查看或引用');h.className='artifact-heading';list.append(h);for(const a of artifacts){const card=document.createElement('details');card.className='artifact-card';card.open=expandedArtifacts.has(a.task_id);card.addEventListener('toggle',()=>{if(card.isConnected){if(card.open)expandedArtifacts.add(a.task_id);else expandedArtifacts.delete(a.task_id);}});card.append(element('summary',artifactLabel(a)+(a.stale?' · 旧版本':' · 可引用')));card.append(element('small',artifactMeta(a)));const body=document.createElement('div');body.className='artifact-body';body.append(resultBody(a));const b=element('button','围绕此结果继续聊');b.type='button';b.onclick=()=>selectArtifact(a);body.append(b);card.append(body);list.append(card);}}renderReference();
  if(!turns.length)list.append(element('p','岗位已经记下了。你想先聊聊适不适合，还是准备一条招呼？'));
  for(const t of turns){
    const item=element('article','');item.className='turn';const userMessage=element('p',t.text);userMessage.className='user-message';item.append(element('small','你'),userMessage);
    if(t.kind==='companion_chat'&&['done','failed','cancelled'].includes(t.status)){
      const remember=element('button',t.fact_candidate?'可能是新经历 · 核对':'记入经历');remember.type='button';remember.className='fact-from-chat'+(t.fact_candidate?' suggested':'');remember.title='模型只提示核对，不会自动写入档案';
      remember.onclick=()=>openWorkbench('','',false,'profile',{fact_task:t.task_id}).catch(e=>status(e.message,true));
      item.append(remember);
    }
    if(t.status==='done'){
      item.append(element('small',$('buddy').textContent));
      const reply=t.workbench?(t.kind==='tailor_resume'?'岗位版简历准备好了。':(t.display_name||'专业任务')+' · '+weakDate(t.created)+'已完成。'):t.reply;
      const replyBox=window.JobAssistantReply.render(reply);replyBox.classList.add('buddy-message');item.append(replyBox);
      if(t.workbench){const detail=document.createElement('details');detail.className='turn-result';detail.append(element('summary','展开详细内容'),resultBody(t));const jump=element('button','在工作台查看完整结果');jump.type='button';jump.className='secondary';jump.onclick=()=>openWorkbench(t.task_id).catch(e=>status(e.message,true));detail.append(jump);item.append(detail);}
      if(t.stale)item.append(element('small','这条回复基于旧资料，请结合当前档案核对。'));
      if(!t.workbench){const button=element('button','复制回复');button.onclick=()=>navigator.clipboard.writeText(t.reply).catch(()=>status('请手动选择文字复制'));item.append(button);}
    }else {item.append(element('p',t.partial||(t.status==='failed'?t.error:t.status==='cancelled'?'这条任务已取消。':t.status==='queued'?'已经收到，正在排队。':t.workbench?'后台任务处理中，你可以继续聊天。':'我正在整理这次回复。')));if(['queued','running'].includes(t.status)){const wait=element('small','');wait.dataset.waitStart=t.updated||t.created;wait.dataset.waitStatus=t.status;wait.dataset.waitWorkbench=t.workbench?'1':'0';wait.dataset.waitAttempts=t.attempts||0;item.append(wait);}}
    if(['failed','queued','running'].includes(t.status)){const b=element('button',t.status==='failed'?'重试':'取消任务');b.onclick=async()=>{try{await api(t.status==='failed'?'/retry':'/cancel',{scope,seq,task_id:t.task_id});await loadHistory();}catch(e){status(e.message,true);}};item.append(b);}
    for(const p of item.querySelectorAll('p:not(.user-message)'))p.classList.add('buddy-message');list.append(item);
  }
  updateWaitLabels();$('progress').textContent=pending?'模型请求处理中；超过 90 秒仍可继续等待或取消。':backgroundPending?'后台任务处理中，可以继续聊。':'';list.scrollTop=follow?list.scrollHeight:previousTop;enable();
}
async function loadHistory(){if(!current)return;const binding={id:current.id,seq};const r=await api('/history',{scope,seq});if(current?.id!==binding.id||seq!==binding.seq||r.job_id!==binding.id)return;renderHistory(r.turns,r.artifacts||[]);}
async function tick(){
  if(busy||polling||!connected||document.visibilityState!=='visible')return;polling=true;
  try{
    const settings=await api('/status');serviceVersion=settings.version||'';serviceCapabilities=Array.isArray(settings.capabilities)?settings.capabilities:[];ready=settings.ready===true;readiness=settings.readiness||null;guide=settings.guide||null;$('buddy').textContent=settings.buddy_name||'求职搭子';if(!restored){const saved=await api('/restore',{scope,seq:++seq});if(saved?.job){current=saved.job;targetCapture=saved.capture;key=signature(saved.capture);contextSafe=true;showCandidate();loadHistory().catch(e=>status(e.message,true));}restored=true;}renderOnboarding();
    const tab=await tabNow();
    chatPageActive=!!(tab&&supported(tab)&&/\/chat|\/geek\/chat|\/im\//i.test(new URL(tab.url).pathname));
    if(chatPageActive&&!serviceCapabilities.includes('verified-chat-links')){chatLinkContext=null;chatLinkSignature='';renderChatLink(null,'本机工作台尚不支持会话核验，请同时更新侧栏和工作台。旧关联暂不启用。');}
    else if(chatPageActive){
      let observed;try{observed=await chrome.tabs.sendMessage(tab.id,{type:'JA_CHAT_CONTEXT'});}catch{observed={status:'incomplete',reason:'暂未收到会话核验信息。更新扩展后，请在方便时重新打开该招聘页面一次。'};}
      const next=observed?.status==='ready'?chatSignature(tab,observed.chat):'';
      if(next!==chatLinkSignature){chatLinkSignature=next;chatLinkContext=null;chatLinkResult=null;renderChatLink(null,'正在核验当前 HR 会话…');}
      if(observed?.status==='ready'&&observed.stable_ms>=800){
        chatLinkTab=tab.id;chatLinkContext=observed.chat;
        try{const linked=await api('/link-context',{scope,chat:observed.chat});const live=await tabNow();const latest=live?.id===tab.id?await chrome.tabs.sendMessage(tab.id,{type:'JA_CHAT_CONTEXT'}):null;if(latest?.status==='ready'&&latest.stable_ms>=800&&chatSignature(live,latest.chat)===next&&chatLinkSignature===next)renderChatLink(linked);else{chatLinkContext=null;renderChatLink(null,'HR 会话已变化，正在重新核验。');}}catch(e){renderChatLink(null,e.message);}
      }else{chatLinkContext=null;chatLinkResult=null;renderChatLink(null,observed?.reason||'等待当前 HR 会话稳定后再核验。');}
    }else{chatLinkContext=null;chatLinkResult=null;chatLinkSignature='';renderChatLink(null);}
    const path=supported(tab)?new URL(tab.url).pathname:'';
    if(chatPageActive){activeTab=tab.id;activePath=path;candidate=null;companyReading=null;$('resume-import-card').hidden=true;contextSafe=!!chatLinkContext&&!!chatLinkResult?.link&&!chatLinkResult.conflict&&chatLinkResult.link.job_id===current?.id;showCandidate();status(contextSafe?'当前 HR 会话与对话岗位已关联；消息内容需自行粘贴。':'当前 HR 会话与固定岗位不同，请使用上方提示切换或核对关联。');await loadHistory();return;}
    if(!supported(tab)){$('resume-import-card').hidden=true;contextSafe=false;candidate=null;companyReading=null;activeTab=tab?.id;activePath=path;showCandidate();status('仍可聊上方已保存岗位；当前页面内容不会进入对话。');await loadHistory();return;}
    const snap=await snapshot(tab);
    const onResume=snap.status==='resume';$('resume-import-card').hidden=!onResume;
    if(onResume){const zhaopin=snap.page_type==='zhaopin-resume';$('resume-import-source').textContent=zhaopin?'智联在线简历':'BOSS 在线简历';$('resume-import').textContent=zhaopin?'读取智联在线简历并核对':'读取在线简历并核对';}
    const relation=related(snap);
    const navigation=tab?.id!==activeTab||path!==activePath;
    if(navigation){manual=null;activeTab=tab?.id;activePath=path;}
    if(onResume){contextSafe=false;candidate=null;companyReading=null;showCandidate();status('在线简历正文尚未读取。点击上方按钮后，会先到本机工作台核对草稿。');if(current)await loadHistory();return;}
    companyReading=snap.company_capture||null;
    const manualValid=manualHere(tab);
    const observed=signature(snap.capture?.job_key?snap.capture:snap.identity);
    // Once a company ID is bound, the target is an explicit user choice.
    // Browsing another page never silently replaces that target.
    const pinned=!!current;
    if(!pinned && (navigation||(!manualValid&&candidate&&observed&&observed!==signature(candidate)))){
      await invalidate();candidate=null;key='';
    }
    let capture=snap.status==='ready'&&!snap.identity?.conflict&&(snap.identity_stable_ms??snap.stable_ms)>=800?snap.capture:null;
    if(manualValid)capture=manual.capture;
    const next=capture?signature(capture):'';
    if(capture&&next!==key){if(!pinned)await invalidate();key=next;candidate=capture;}
    if(capture)candidate=capture;
    if(!capture&&navigation)candidate=null;
    contextSafe=manualValid||sameIdentity(snap,targetCapture||candidate)||relation;
    if(!capture){
      if(current)await loadHistory();
      if(companyReading)status(companyMaterialCount(companyReading)===0?'已识别公司，但当前页没有可保存的介绍或招聘材料；打开公司介绍或招聘页后再试。':relation?'目标岗位已保留。可以保存公司介绍或招聘概况，再继续聊。':current&&canBindCompany(companyReading)?'目标岗位尚未关联公司。核对页面后，点击“确认关联这家公司并保存”。':'正在浏览公司资料。请先确认一个同站目标岗位。');
      else if(targetCapture||candidate)status(contextSafe?'仍是同一岗位，继续使用已读取的资料。':'当前页面暂未核对，仍可聊上方已保存岗位；页面分析暂不可用。');
      else status(snap.reason||'岗位还在加载，也可以用读取帮助选择 JD。');
      return;
    }
    if(pinned&&signature(capture)!==signature(targetCapture)){status(relation?'正在看同公司的另一个岗位，可加入对照；对话仍针对上方目标。':'这是另一家公司的岗位。要切换时请点“改为目标岗位”。');await loadHistory();return;}

    if(!ready)status(readinessMessage());
    else if(!current)status('已读到这个岗位，可直接选择一个快捷动作，或先确认后聊天。');
    else {status('我在，围绕这个岗位我们接着聊。');await loadHistory();}
  }catch(e){contextSafe=false;if(/岗位内容已更新/.test(e.message||''))needsSync=true;const unreachable=/Failed to fetch|fetch failed|NetworkError|TimeoutError|timed out|aborted/i.test(e.message||'');if(unreachable){connected=false;ready=false;discovered=false;pairingPending=false;status('本机工作台无法连接，请确认服务运行后重新检测。任务和对话仍保存在本机。',true);return;}const pairingLost=/未配对|重新配对|先在侧栏输入|服务已重启|401/.test(e.message||'');if(pairingLost){connected=false;status('工作台连接已失效，请重新配对。任务和对话仍保存在本机。',true);}else status(e.message+'；任务和对话仍保存在本机。',true);}finally{polling=false;showCandidate();}
}
async function confirmCandidate(){if(!candidate)throw Error('先打开一个可读取的岗位');const tab=await tabNow();const s=await snapshot(tab);if(tab.id!==activeTab||(!manualHere(tab)&&(!sameIdentity(s,candidate)||s.status!=='ready')))throw Error('页面已变化，等岗位重新读取后再确认');const chosen={...candidate};chatDrafts.set(current?.id||'', $('message').value);await invalidate();const r=await api('/capture',{scope,seq:++seq,capture:chosen});await api('/confirm',{scope,seq});current=r.job;needsSync=false;$('message').value=chatDrafts.get(current.id)||'';targetCapture=chosen;candidate=chosen;contextSafe=true;companyReading=s.company_capture||null;const settings=await api('/status');guide=settings.guide||null;readiness=settings.readiness||readiness;ready=settings.ready===true;renderOnboarding();status('目标岗位已记下，可以去了解公司介绍或其他岗位。');await loadHistory();}
$('confirm').onclick=async()=>{if(busy||(!candidate&&!needsSync))return;busy=true;enable();try{if(needsSync)await syncSavedTarget();else await confirmCandidate();}catch(e){status(e.message,true);}finally{busy=false;showCandidate();}};
const openDetails=()=>{if(!$('details-dialog').open)$('details-dialog').showModal();};
$('target-details').onclick=openDetails;$('open-details').onclick=openDetails;
$('close-details').onclick=()=>$('details-dialog').close();
$('switch-target').onclick=async()=>{await $('confirm').onclick();if(current&&signature(candidate)===signature(targetCapture))$('message').focus();};
async function talk(kind,override,chooseCandidate=false){if(!connected){status('请先连接本机工作台。',true);return;}if(!ready){renderReadiness();status(readinessMessage(),true);return;}if(needsSync||busy||(!current&&!candidate)||(isBackground(kind)?backgroundPending:pending))return;const text=override===undefined?$('message').value.trim():override;const draft=$('message').value;busy=true;enable();try{if(!current||(chooseCandidate&&candidate&&signature(candidate)!==signature(targetCapture)))await confirmCandidate();if(!['companion_chat','rest_message'].includes(kind)){const tab=await tabNow();const s=await snapshot(tab);if(chatPageActive){const chat=await checkedChat();const link=await api('/link-context',{scope,chat});if(link.conflict||link.link?.job_id!==current?.id)throw Error('当前 HR 会话尚未关联此岗位，请先核对绑定');await checkedChat();}else if(tab.id!==activeTab||!canUseSnapshot(s,tab)||new URL(tab.url).pathname!==activePath)throw Error('岗位页面已变化，请先重新确认');}if(kind==='companion_chat'&&!text)throw Error('跟搭子说点什么吧');const binding=seq;const reference=kind==='companion_chat'&&selectedArtifact()?.task_id||'';const identity=JSON.stringify([seq,kind,text,reference]);if(request?.identity!==identity)request={identity,id:crypto.randomUUID()};const r=await api('/talk',{scope,seq,kind,text,request_id:request.id,reference_task_id:reference||undefined});if(seq!==binding||current?.id!==r.job_id)return;if(override===undefined){$('message').value='';renderReference();}request=null;const routedKind=r.task?.kind||kind;status(routedKind==='tailor_resume'?'简历任务已送到工作台，完成后可以核对。':isBackground(routedKind)?'详细任务已送到工作台，完成后可以查看；侧栏仍可继续聊天。':'收到，我们一起看看。');await loadHistory();const settings=await api('/status');guide=settings.guide||null;readiness=settings.readiness||readiness;}catch(e){if(override===undefined)$('message').value=draft;status(e.message,true);}finally{busy=false;enable();renderOnboarding();}}

 $('save-company').onclick=async()=>{if(busy||!current||!companyReading)return;busy=true;enable();try{const t=await tabNow();const s=await snapshot(t);const data={...s.company_capture};if(!supported(t)||!canSaveCompany(s))throw Error(companyMaterialCount(data)===0?'当前页面没有可保存的公司栏目或岗位材料，请展开正文或打开公司招聘页后重试。':'当前公司与目标岗位不一致，未保存');if(!current.company_key){if(!canBindCompany(data))throw Error('公司身份或来源页面无法与目标岗位核对，未关联');const bound=await api('/company-bind',{scope,seq,company:data});current.company_key=bound.company_key;targetCapture={...targetCapture,company_key:bound.company_key};}if(s.status==='ready'&&!s.identity?.conflict&&s.capture?.job_key!==targetCapture?.job_key)data.peer=s.capture;const r=await api('/company-save',{scope,seq,company:data});companyFeedbackError='';$('company-saved').textContent='已保存 '+r.company.evidence.length+'条来源材料；下一条分析将使用这些背景。';$('company-feedback').className='company-feedback';$('company-feedback').textContent='已保存 '+r.company.evidence.length+' 条来源材料。';status('公司身份已确认，背景材料已补充。可以继续分析。');}catch(e){companyFeedbackSource=companyReading?companyReading.company_key+'|'+companyReading.source_url:'';companyFeedbackError=e.message;$('company-feedback').className='company-feedback error';$('company-feedback').textContent=e.message;status(e.message,true);}finally{busy=false;showCandidate();}};

$('send').onclick=()=>talk('companion_chat');document.querySelectorAll('[data-kind]').forEach(b=>b.onclick=()=>talk(b.dataset.kind));
function renderCommands(){const box=$('command-menu');if(!box)return;box.replaceChildren();
  box.append(element('p','引用已有专项成果（选择后会显示已选结果）','command-menu-heading'));
  for(const a of artifactItems){const b=element('button','');b.type='button';b.className='command-artifact';b.setAttribute('role','option');const title=element('strong',artifactLabel(a)+' · 引用');const date=element('small',artifactMeta(a));b.append(title,date);b.onclick=()=>selectArtifact(a);box.append(b);}
  box.hidden=false;
}
$('message').addEventListener('input',()=>{if(['/','/引用'].includes($('message').value.trim()))renderCommands();else $('command-menu').hidden=true;});
$('message').addEventListener('keydown',e=>{if(e.key==='Escape'){$('command-menu').hidden=true;e.preventDefault();}else if(e.key==='Enter'&&!e.ctrlKey&&!e.metaKey&&!$('command-menu').hidden){$('command-menu').querySelector('button')?.click();e.preventDefault();}});
$('message').onkeydown=e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();talk('companion_chat');}};
$('connect').onclick=async()=>{try{await send({type:'JA_PAIR',port:Number($('port').value),code:$('code').value.trim()});connected=true;restored=false;key='';$('code').value='';$('pairing').open=false;renderOnboarding();await tick();}catch(e){connected=false;$('pairing').open=true;renderOnboarding();status(e.message,true);}};
$('auto-connect').onclick=()=>startPairing().catch(e=>status(e.message,true));
$('open-onboarding').onclick=()=>openWorkbench('','',true).catch(e=>status(e.message,true));
$('disconnect').onclick=async()=>{try{await invalidate();await send({type:'JA_DISCONNECT'});connected=false;candidate=null;$('pairing').open=true;showCandidate();status('已断开，记录仍在本机工作台。');}catch(e){status(e.message,true);}};
$('workbench').onclick=()=>openWorkbench().catch(e=>status(e.message,true));$('rescan').onclick=async()=>{if(busy)return;manual=null;key='';await invalidate();await tick();};
$('resume-import').onclick=async()=>{if(busy||!connected)return;busy=true;enable();try{const t=await tabNow(),u=new URL(t.url),zhaopin=u.protocol==='https:'&&u.hostname==='i.zhaopin.com'&&u.pathname.replace(/\/$/,'')==='/resume',boss=JobAssistantURL(t.url,'/web/geek/resume');if(!boss&&!zhaopin)throw Error('请保持在 BOSS 或智联的本人在线简历页');if(!serviceCapabilities.includes('resume-import')||(zhaopin&&!serviceCapabilities.includes('zhaopin-resume-import')))throw Error('当前工作台服务 '+(serviceVersion||'版本未知')+' 尚未声明支持该站点的在线简历导入，请启动新版工作台并重新连接。');const snap=await snapshot(t);if(snap.status!=='resume'||(zhaopin&&snap.page_type!=='zhaopin-resume'))throw Error(snap.reason||'当前页面不是可读取的本人在线简历');const captured=await chrome.tabs.sendMessage(t.id,{type:'JA_RESUME_CAPTURE'});if(captured?.status!=='ready'||!captured.resume)throw Error(captured?.reason||'在线简历还没有唯一定位或加载完成');const draft=await api('/resume-import',{resume:captured.resume});await openWorkbench('','',false,'profile',{resume_import:draft.id});status('已生成本地草稿，请在工作台逐项核对；现有档案没有被覆盖。');}catch(e){status(e.message,true);}finally{busy=false;enable();}};
 $('selection-jd').onclick=async()=>{try{const t=await tabNow();if(!supported(t))throw Error('请切到招聘网页');const s=await snapshot(t),r=await chrome.tabs.sendMessage(t.id,{type:'JA_SELECTION'}),u=new URL(t.url),boss=u.pathname.match(/^\/job_detail\/([A-Za-z0-9_-]{4,200})\.html$/),zhaopin=u.pathname.match(/^\/jobdetail\/([A-Za-z0-9._~-]{4,200})\.(?:htm|html)$/i),identity=s.identity;if(!r?.text)throw Error('请先选中独立岗位页中的 JD 正文');if(boss){manual={tabId:t.id,job_key:boss[1],source_site:'boss',url:'https://www.zhipin.com'+u.pathname};}else if(zhaopin&&['www.zhaopin.com','zhaopin.com'].includes(u.hostname)&&identity?.job_key===zhaopin[1]&&identity?.source_site==='zhaopin'&&!identity.conflict){manual={tabId:t.id,job_key:zhaopin[1],source_site:'zhaopin',url:'https://www.zhaopin.com'+u.pathname};}else throw Error('只支持身份唯一的 BOSS 或智联独立岗位页；列表页不能用选中文本补录');$('fallback-jd').value=r.text;status('已读取你选中的正文，请补齐岗位与公司后核对使用。');}catch(e){status(e.message,true);}};
 $('use-jd').onclick=async()=>{try{const t=await tabNow(),u=new URL(t.url);if(!manual||t.id!==manual.tabId||u.pathname!==new URL(manual.url).pathname||sourceSite({url:t.url})!==manual.source_site)throw Error('页面已变化，请重新选择正文');const s=await snapshot(t);if(s.identity?.job_key!==manual.job_key||s.identity?.conflict)throw Error('当前岗位身份未能再次确认，请重新识别');const capture={job_key:manual.job_key,url:manual.url,title:$('fallback-title').value.trim(),company:$('fallback-company').value.trim(),jd:$('fallback-jd').value.trim(),method:'selection'};if(manual.source_site==='zhaopin')capture.source_site='zhaopin';manual.capture=capture;await tick();}catch(e){status(e.message,true);}};
$('diagnose').onclick=async()=>{try{const t=await tabNow();if(!supported(t))throw Error('请切到招聘网页');$('diagnostic-output').textContent=JSON.stringify(await chrome.tabs.sendMessage(t.id,{type:'JA_DIAGNOSTICS'}),null,2);}catch(e){status(e.message,true);}};
$('copy-diagnostic').onclick=()=>navigator.clipboard.writeText($('diagnostic-output').textContent).catch(()=>status('请手动复制诊断'));
(async()=>{windowId=(await chrome.windows.getCurrent()).id;const r=await send({type:'JA_CONNECTION'});connected=r.connected;pairingPending=r.pairing===true;if(r.port)$('port').value=r.port;if(!connected)await detectWorkbench();renderOnboarding();await tick();setInterval(()=>{updateWaitLabels();pollPairing();tick();},1500);})().catch(e=>status(e.message,true));

$('interview-workbench').onclick=()=>openWorkbench('','interview');
$('journey-workbench').onclick=()=>openWorkbench('','journey');
$('blessing').onclick=()=>talk('rest_message','');
