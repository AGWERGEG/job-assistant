function isBackground(kind){return ['tailor_resume','analyze_job','interview_prep','interview_review'].includes(kind);}
const $=id=>document.getElementById(id);
const scope=crypto.randomUUID();
let seq=0,connected=false,ready=false,busy=false,current=null,candidate=null,key='',windowId,activeTab=null,pending=false,backgroundPending=false,manual=null;
let needsSync=false;
let historyKey='',request=null,activePath='',contextSafe=false,targetCapture=null,companyReading=null,restored=false,guide=null;
const chatDrafts=new Map();let historyTarget='';
function syncConversationUI(){
 document.body.classList.toggle('needs-sync',needsSync);
 $('connection-badge').textContent=connected?'已连接':'未连接';
 if(!connected&&$('details-dialog').open)$('details-dialog').close();
 const different=needsSync||!!candidate&&(!current||candidate.job_key!==targetCapture?.job_key);
 $('candidate-notice').hidden=!connected||!different;
 $('candidate-title').textContent=needsSync?'岗位资料已在工作台更新':candidate?candidate.title+' · '+candidate.company:'';
 $('candidate-title').title=$('candidate-title').textContent;
 $('candidate-kicker').textContent=needsSync?'同步后可继续聊天，不覆盖工作台修改':current?'正在浏览另一岗位 · 对话目标不变':'已读取 · 尚未选定';
 $('switch-target').textContent=needsSync?'同步已保存岗位':current?'切换到这个':'聊这个岗位';
 $('switch-target').disabled=$('confirm').disabled;
 $('chat-target').title=$('chat-target').textContent;
 if(!current&&!$('messages').querySelector('.turn')){$('messages').textContent=candidate?'读到这个岗位了。可以先分析，或选定后说说你最在意什么。':'点开一个感兴趣的岗位，叫我一起看看。';}
}
function related(s){return !!current?.company_key && s.company_capture?.company_key===current.company_key;}
const signature=c=>c?.job_key||'';
function sameIdentity(s,c){return !!c && !s.identity?.conflict && (s.identity?.job_key||s.capture?.job_key)===c.job_key;}
function manualHere(tab){return !!manual?.capture && tab.id===manual.tabId && new URL(tab.url).pathname===new URL(manual.capture.url).pathname;}
function canUseSnapshot(s,tab){return supported(tab)&&(manualHere(tab)||sameIdentity(s,targetCapture||candidate)||related(s));}
function status(s,error=false){$('status').textContent=s;$('status').className=error?'error':'';}
function element(tag,value){const n=document.createElement(tag);n.textContent=value;return n;}
async function send(m){const r=await chrome.runtime.sendMessage(m);if(!r?.ok)throw Error(r?.error||'扩展后台不可用');return r.value;}
const api=(path,value={})=>send({type:'JA_API',path,value});
async function syncSavedTarget(){
 const r=await api('/sync',{scope,seq});
 current=r.job;targetCapture={...targetCapture,title:r.job.title,company:r.job.company,company_key:r.job.company_key,url:r.job.url};
 needsSync=false;historyKey='';await loadHistory();status('已同步工作台保存的岗位资料，可以继续聊。');
}
async function tabNow(){return (await chrome.tabs.query({active:true,windowId}))[0];}
function supported(t){try{return ['www.zhipin.com','zhipin.com'].includes(new URL(t.url).hostname);}catch{return false;}}
async function snapshot(t){try{return await chrome.tabs.sendMessage(t.id,{type:'JA_SNAPSHOT'});}catch{return {status:'unavailable',reason:'请刷新招聘网页，让扩展重新连接。'};}}
function enable(){$('blessing').disabled=!connected||!ready||!current||needsSync||busy||pending;for(const b of document.querySelectorAll('[data-kind],#send'))b.disabled=!connected||!ready||needsSync||busy||(!current?!(candidate&&b.dataset.kind):(!contextSafe&&b.id!=='send'))||(isBackground(b.dataset.kind)?backgroundPending:pending);$('confirm').disabled=!connected||busy||(!needsSync&&(!candidate||!!(current&&candidate.job_key===targetCapture?.job_key)));$('save-company').disabled=!connected||busy||!current||!companyReading||companyReading.company_key!==current.company_key;}
function openWorkbench(taskId='',view='',onboarding=false){const port=Number($('port').value);if(port>=1024&&port<=65535)chrome.tabs.create({url:'http://127.0.0.1:'+port+'/#job='+(current?.id||'')+'&task='+taskId+(view?'&view='+encodeURIComponent(view):'')+(onboarding?'&onboarding=1'+(!connected?'&pairing=1':''):'')});}
function renderOnboarding(){
 syncConversationUI();
 document.body.classList.toggle('unpaired',!connected);
 const card=$('onboarding-card');const active=!!(connected&&guide?.active);document.body.classList.toggle('guide-active',active);
 if(active)document.body.dataset.guideStep=guide.step;else delete document.body.dataset.guideStep;
 if(!active){card.hidden=true;if(!connected){$('pairing').open=true;$('open-onboarding').textContent='打开工作台，获取配对码';}else $('open-onboarding').textContent='工作台连接设置';return;}
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
 $('onboarding-title').textContent=title;$('onboarding-copy').textContent=copy;$('onboarding-open').textContent=label;$('onboarding-open').disabled=disabled;$('onboarding-open').onclick=run;card.hidden=false;
}
async function invalidate(){seq++;current=null;targetCapture=null;needsSync=false;contextSafe=false;pending=false;request=null;historyKey='';$('messages').replaceChildren();$('progress').textContent='';if(connected)await api('/capture',{scope,seq,capture:null});}
function showCandidate(){$('chat-target').textContent=current?'正在聊：'+current.title+' · '+current.company:'还未选定对话岗位';$('chat-context-note').textContent=current?(contextSafe?'使用已保存岗位与背景；浏览不会自动换目标。':'当前页面未关联目标，聊天仍针对上方已保存岗位，不会读取新页内容。'):'可直接点击分析、简历或招呼，选定眼前岗位后开始。';$('save-company').textContent=candidate&&current&&candidate.job_key!==targetCapture?.job_key?'用这个岗位作参考':'补充这家公司的背景';const c=candidate||targetCapture;$('title').textContent=c?.title||'点开一个岗位，我们一起看看';$('company').textContent=c?.company||companyReading?.name||'';$('source').hidden=!c;if(c)$('source').href=c.url;const same=current&&c?.job_key===targetCapture?.job_key;$('captured').textContent=same?'目标岗位已固定；公司资料与对照岗位不会替换它':c?'当前浏览岗位，可以设为目标':'';$('confirm').textContent=needsSync?'同步已保存岗位':same?'已确认目标岗位':current?'改为目标岗位':'确认这个岗位';$('company-context').hidden=!companyReading&&!current;$('target-label').textContent=current?'目标：'+current.title+' · '+current.company:'先确认一个目标岗位';$('company-reading').textContent=companyReading?'正在了解：'+companyReading.name+' · '+companyReading.sections.length+'个栏目 / '+companyReading.jobs.length+'张已加载岗位卡片':'当前页尚未定位公司资料';enable();renderOnboarding();}
function renderHistory(turns){
  pending=turns.some(t=>!isBackground(t.kind)&&['queued','running'].includes(t.status));backgroundPending=turns.some(t=>isBackground(t.kind)&&['queued','running'].includes(t.status));
  const encoded=JSON.stringify(turns);if(encoded===historyKey){enable();return;}historyKey=encoded;
  const list=$('messages');const follow=historyTarget!==current?.id||list.scrollHeight-list.scrollTop-list.clientHeight<64;const previousTop=list.scrollTop;historyTarget=current?.id||'';list.replaceChildren();
  if(!turns.length)list.append(element('p','岗位已经记下了。你想先聊聊适不适合，还是准备一条招呼？'));
  for(const t of turns){
    const item=element('article','');item.className='turn';const userMessage=element('p',t.text);userMessage.className='user-message';item.append(element('small','你'),userMessage);
    if(t.status==='done'){
      item.append(element('small',$('buddy').textContent));
      item.append(element('p',t.workbench?(t.kind==='tailor_resume'?'岗位版简历准备好了，去工作台核对、编辑并保存。':'专业任务已完成，可以到工作台查看。'):t.reply));
      if(t.stale)item.append(element('small','这条回复基于旧资料，请结合当前档案核对。'));
      const button=element('button',t.workbench?'去工作台查看':'复制回复');button.onclick=()=>t.workbench?openWorkbench(t.task_id):navigator.clipboard.writeText(t.reply).catch(()=>status('请手动选择文字复制'));item.append(button);
    }else item.append(element('p',t.partial||(t.status==='failed'?t.error:t.status==='cancelled'?'这条任务已取消。':t.status==='queued'?'已经收到，正在排队。':t.workbench?'后台任务处理中，你可以继续聊天。':'我正在整理这次回复。')));
    if(['failed','queued','running'].includes(t.status)){const b=element('button',t.status==='failed'?'重试':'取消任务');b.onclick=async()=>{try{await api(t.status==='failed'?'/retry':'/cancel',{scope,seq,task_id:t.task_id});await loadHistory();}catch(e){status(e.message,true);}};item.append(b);}
    for(const p of item.querySelectorAll('p:not(.user-message)'))p.classList.add('buddy-message');list.append(item);
  }
  $('progress').textContent=pending?'正在整理回复…':backgroundPending?'后台任务处理中，可以继续聊。':'';list.scrollTop=follow?list.scrollHeight:previousTop;enable();
}
async function loadHistory(){if(!current)return;const binding={id:current.id,seq};const r=await api('/history',{scope,seq});if(current?.id!==binding.id||seq!==binding.seq||r.job_id!==binding.id)return;renderHistory(r.turns);}
async function tick(){
  if(busy||!connected||document.visibilityState!=='visible')return;busy=true;
  try{
    const settings=await api('/status');$('buddy').textContent=settings.buddy_name||'求职搭子';if(!restored){const saved=await api('/restore',{scope,seq:++seq});if(saved?.job){current=saved.job;targetCapture=saved.capture;key=signature(saved.capture);await loadHistory();}restored=true;}ready=settings.ready===true;guide=settings.guide||null;$('buddy').textContent=settings.buddy_name||'求职搭子';renderOnboarding();
    const tab=await tabNow();
    const path=supported(tab)?new URL(tab.url).pathname:'';
    if(!supported(tab)){contextSafe=false;candidate=null;companyReading=null;activeTab=tab?.id;activePath=path;showCandidate();status('仍可聊上方已保存岗位；当前页面内容不会进入对话。');await loadHistory();return;}
    const snap=await snapshot(tab);
    const relation=related(snap);
    const navigation=tab?.id!==activeTab||path!==activePath;
    if(navigation){manual=null;activeTab=tab?.id;activePath=path;}
    companyReading=snap.company_capture||null;
    const manualValid=manualHere(tab);
    const observed=snap.identity?.job_key||snap.capture?.job_key;
    // Once a company ID is bound, the target is an explicit user choice.
    // Browsing another page never silently replaces that target.
    const pinned=!!current;
    if(!pinned && (navigation||(!manualValid&&candidate&&observed&&observed!==candidate.job_key))){
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
      if(companyReading)status(relation?'目标岗位已保留。可以保存公司介绍或招聘概况，再继续聊。':'正在浏览公司资料。请先从这家公司确认一个目标岗位。');
      else if(targetCapture||candidate)status(contextSafe?'仍是同一岗位，继续使用已读取的资料。':'当前页面暂未核对，仍可聊上方已保存岗位；页面分析暂不可用。');
      else status(snap.reason||'岗位还在加载，也可以用读取帮助选择 JD。');
      return;
    }
    if(pinned&&capture.job_key!==targetCapture.job_key){status(relation?'正在看同公司的另一个岗位，可加入对照；对话仍针对上方目标。':'这是另一家公司的岗位。要切换时请点“改为目标岗位”。');await loadHistory();return;}

    if(!ready)status('先在工作台完成角色设置与脱敏档案确认。');
    else if(!current)status('已读到这个岗位，可直接选择一个快捷动作，或先确认后聊天。');
    else {status('我在，围绕这个岗位我们接着聊。');await loadHistory();}
  }catch(e){contextSafe=false;if(/岗位内容已更新/.test(e.message||''))needsSync=true;const pairingLost=/未配对|重新配对|先在侧栏输入|服务已重启|401/.test(e.message||'');if(pairingLost){connected=false;$('pairing').open=true;status('工作台连接已失效，请重新配对。任务和对话仍保存在本机。',true);}else status(e.message+'；任务和对话仍保存在本机。',true);}finally{busy=false;showCandidate();}
}
async function confirmCandidate(){if(!candidate)throw Error('先打开一个可读取的岗位');const tab=await tabNow();const s=await snapshot(tab);if(tab.id!==activeTab||(!manualHere(tab)&&(!sameIdentity(s,candidate)||s.status!=='ready')))throw Error('页面已变化，等岗位重新读取后再确认');const chosen={...candidate};chatDrafts.set(current?.id||'', $('message').value);await invalidate();const r=await api('/capture',{scope,seq:++seq,capture:chosen});await api('/confirm',{scope,seq});current=r.job;needsSync=false;$('message').value=chatDrafts.get(current.id)||'';targetCapture=chosen;candidate=chosen;contextSafe=true;companyReading=s.company_capture||null;guide=(await api('/status')).guide||null;renderOnboarding();status('目标岗位已记下，可以去了解公司介绍或其他岗位。');await loadHistory();}
$('confirm').onclick=async()=>{if(busy||(!candidate&&!needsSync))return;busy=true;enable();try{if(needsSync)await syncSavedTarget();else await confirmCandidate();}catch(e){status(e.message,true);}finally{busy=false;showCandidate();}};
const openDetails=()=>{if(!$('details-dialog').open)$('details-dialog').showModal();};
$('target-details').onclick=openDetails;$('open-details').onclick=openDetails;
$('close-details').onclick=()=>$('details-dialog').close();
$('switch-target').onclick=async()=>{await $('confirm').onclick();if(current&&candidate?.job_key===targetCapture?.job_key)$('message').focus();};
async function talk(kind,override,chooseCandidate=false){if(!connected||!ready||needsSync||busy||(!current&&!candidate)||(isBackground(kind)?backgroundPending:pending))return;const text=override===undefined?$('message').value.trim():override;const draft=$('message').value;busy=true;enable();try{if(!current||(chooseCandidate&&candidate&&candidate.job_key!==targetCapture?.job_key))await confirmCandidate();if(!['companion_chat','rest_message'].includes(kind)){const tab=await tabNow();const s=await snapshot(tab);if(tab.id!==activeTab||!canUseSnapshot(s,tab)||new URL(tab.url).pathname!==activePath)throw Error('岗位页面已变化，请先重新确认');}if(kind==='companion_chat'&&!text)throw Error('跟搭子说点什么吧');const binding=seq;const identity=JSON.stringify([seq,kind,text]);if(request?.identity!==identity)request={identity,id:crypto.randomUUID()};const r=await api('/talk',{scope,seq,kind,text,request_id:request.id});if(seq!==binding||current?.id!==r.job_id)return;if(override===undefined)$('message').value='';request=null;status(kind==='tailor_resume'?'简历任务已送到工作台，完成后可以核对。':'收到，我们一起看看。');await loadHistory();guide=(await api('/status')).guide||null;}catch(e){if(override===undefined)$('message').value=draft;status(e.message,true);}finally{busy=false;enable();renderOnboarding();}}

$('save-company').onclick=async()=>{if(busy||!current||!companyReading)return;busy=true;enable();try{const t=await tabNow();const s=await snapshot(t);if(!supported(t)||!related(s))throw Error('当前公司与目标岗位不一致，未保存');const data={...s.company_capture};if(s.status==='ready'&&!s.identity?.conflict&&s.capture?.job_key!==targetCapture?.job_key){data.peer=s.capture;}const r=await api('/company-save',{scope,seq,company:data});$('company-saved').textContent='已保存 '+r.company.evidence.length+'条来源材料；下一条分析将使用这些背景。';status('公司背景已补充。可以问我产品、客户或这个岗位在业务中的作用。');}catch(e){status(e.message,true);}finally{busy=false;enable();}};

$('send').onclick=()=>talk('companion_chat');document.querySelectorAll('[data-kind]').forEach(b=>b.onclick=()=>talk(b.dataset.kind));
$('message').onkeydown=e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();talk('companion_chat');}};
$('connect').onclick=async()=>{try{await send({type:'JA_PAIR',port:Number($('port').value),code:$('code').value.trim()});connected=true;restored=false;key='';$('code').value='';$('pairing').open=false;renderOnboarding();await tick();}catch(e){connected=false;$('pairing').open=true;renderOnboarding();status(e.message,true);}};
$('open-onboarding').onclick=()=>openWorkbench('','',true);
$('disconnect').onclick=async()=>{try{await invalidate();await send({type:'JA_DISCONNECT'});connected=false;candidate=null;$('pairing').open=true;showCandidate();status('已断开，记录仍在本机工作台。');}catch(e){status(e.message,true);}};
$('workbench').onclick=()=>openWorkbench();$('rescan').onclick=async()=>{if(busy)return;manual=null;key='';await invalidate();await tick();};
$('selection-jd').onclick=async()=>{try{const t=await tabNow();if(!supported(t))throw Error('请切到招聘网页');const r=await chrome.tabs.sendMessage(t.id,{type:'JA_SELECTION'});const match=new URL(t.url).pathname.match(/^\/job_detail\/([A-Za-z0-9_-]{4,200})\.html$/);if(!r?.text||!match)throw Error('请在独立岗位页选中 JD 正文');$('fallback-jd').value=r.text;manual={tabId:t.id,job_key:match[1]};}catch(e){status(e.message,true);}};
$('use-jd').onclick=async()=>{try{const t=await tabNow();if(!manual||t.id!==manual.tabId||new URL(t.url).pathname!=='/job_detail/'+manual.job_key+'.html')throw Error('页面已变化，请重新选择正文');manual.capture={job_key:manual.job_key,url:'https://www.zhipin.com/job_detail/'+manual.job_key+'.html',title:$('fallback-title').value.trim(),company:$('fallback-company').value.trim(),jd:$('fallback-jd').value.trim(),method:'selection'};await tick();}catch(e){status(e.message,true);}};
$('diagnose').onclick=async()=>{try{const t=await tabNow();if(!supported(t))throw Error('请切到招聘网页');$('diagnostic-output').textContent=JSON.stringify(await chrome.tabs.sendMessage(t.id,{type:'JA_DIAGNOSTICS'}),null,2);}catch(e){status(e.message,true);}};
$('copy-diagnostic').onclick=()=>navigator.clipboard.writeText($('diagnostic-output').textContent).catch(()=>status('请手动复制诊断'));
(async()=>{windowId=(await chrome.windows.getCurrent()).id;const r=await send({type:'JA_CONNECTION'});connected=r.connected;if(r.port)$('port').value=r.port;$('pairing').open=!connected;renderOnboarding();await tick();setInterval(tick,1500);})().catch(e=>status(e.message,true));

$('interview-workbench').onclick=()=>openWorkbench('','interview');
$('journey-workbench').onclick=()=>openWorkbench('','journey');
$('blessing').onclick=()=>talk('rest_message','');
