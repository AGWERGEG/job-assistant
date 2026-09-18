/* Reorganize the existing forms without cloning IDs, data or backend APIs. */
let workspacePage='chat', opportunityTab='overview', inboxSignature='', showReadResults=false, showAllInbox=false, jobQuery='';
let opportunityListCollapsed=localStorage.getItem('job-assistant-opportunity-list')==='collapsed';
let onboardingSignature='';
let pairingRequested=new URLSearchParams(location.hash.slice(1)).get('pairing')==='1';
let pairingBaseline=sessionStorage.getItem('job-assistant-pairing-revision');
const workspaceTitles={chat:'继续聊',opportunities:'我的机会',profile:'我的档案',settings:'设置'};
function mountWorkspace(){
 const main=document.querySelector('main');
 const nav=document.createElement('nav');nav.className='workspace-nav';nav.setAttribute('aria-label','主要导航');
 for(const [key,label] of Object.entries(workspaceTitles)){
  const b=document.createElement('button');b.textContent=label;b.dataset.page=key;b.onclick=()=>showPage(key);nav.append(b);
 }
 main.prepend(nav);
 const screens={};
 for(const key of Object.keys(workspaceTitles)){const section=document.createElement('section');section.id='screen-'+key;section.hidden=key!=='chat';screens[key]=section;main.append(section);}
 const move=(id,parent)=>parent.append(document.getElementById(id));
 move('welcome',screens.chat);
 const status=document.createElement('section');status.id='resume-session';status.className='panel compact-session';
 const target=document.createElement('p');target.id='session-target';status.append(target);
 for(const [label,page,tab] of [['选择 / 查看机会','opportunities','overview'],['查看简历','opportunities','resume'],['准备面试','opportunities','interview']]){
  const b=document.createElement('button');b.className='secondary';b.textContent=label;b.onclick=()=>{showPage(page);showOpportunity(tab);};status.append(b);
 }
 const pendingPanel=document.createElement('details');pendingPanel.id='delivery-inbox-panel';pendingPanel.className='inbox-panel';
 const pendingSummary=document.createElement('summary');pendingSummary.id='delivery-inbox-summary';pendingSummary.textContent='任务提醒 · 正在读取';pendingPanel.append(pendingSummary);
 const pending=document.createElement('div');pending.id='delivery-inbox';pendingPanel.append(pending);
 const inboxActions=document.createElement('div');inboxActions.className='inbox-actions';
 const toggleAll=document.createElement('button');toggleAll.id='toggle-all-results';toggleAll.className='text-button';toggleAll.textContent='查看全部任务';toggleAll.onclick=()=>{showAllInbox=!showAllInbox;toggleAll.textContent=showAllInbox?'只看最近三项':'查看全部任务';inboxSignature='';renderWorkspaceStatus();};inboxActions.append(toggleAll);
 const toggle=document.createElement('button');toggle.id='toggle-read-results';toggle.className='text-button';toggle.textContent='显示已查看结果';toggle.onclick=()=>{showReadResults=!showReadResults;toggle.textContent=showReadResults?'隐藏已查看结果':'显示已查看结果';inboxSignature='';renderWorkspaceStatus();};inboxActions.append(toggle);pendingPanel.append(inboxActions);status.append(pendingPanel);screens.chat.append(status);
 move('chat-panel',screens.chat);
 screens.chat.insertBefore(document.getElementById('chat-panel'),status);
 const chat=document.getElementById('chat-panel');const form=document.getElementById('chat-form');
 form.prepend(chat.querySelector('.task-actions'));
 form.querySelectorAll('[data-kind]').forEach(button=>button.type='button');
 const chatTools=document.createElement('div');chatTools.className='chat-tools';
 for(const [label,run] of [['切换岗位',()=>showPage('opportunities')],['任务与成果',()=>document.getElementById('session-dialog').showModal()]]){
  const b=document.createElement('button');b.className='text-button';b.textContent=label;if(label==='任务与成果')b.id='session-open';b.onclick=()=>{run();if(label==='任务与成果')document.getElementById('delivery-inbox-panel').open=true;};chatTools.append(b);
 }chat.querySelector('.section-title').append(chatTools);
 const sessionDialog=document.createElement('dialog');sessionDialog.id='session-dialog';sessionDialog.setAttribute('aria-label','任务与成果');
 const sessionClose=document.createElement('button');sessionClose.className='text-button';sessionClose.textContent='收起';sessionClose.onclick=()=>sessionDialog.close();sessionDialog.append(sessionClose,status);document.body.append(sessionDialog);
 pendingPanel.open=false;
 const list=document.getElementById('job-list').closest('section');list.id='opportunity-list';
 const listHeading=list.querySelector('h2');const listHeader=document.createElement('div');listHeader.className='opportunity-list-header';listHeading.before(listHeader);listHeader.append(listHeading);
 const collapse=document.createElement('button');collapse.id='toggle-opportunity-list';collapse.className='text-button';listHeader.append(collapse);
 const search=document.createElement('input');search.id='job-search';search.type='search';search.placeholder='搜索岗位或公司';search.setAttribute('aria-label','搜索岗位或公司');search.oninput=()=>{jobQuery=search.value.trim().toLowerCase();jobsSignature='';renderJobs();};document.getElementById('job-list').before(search);
 const split=document.createElement('div');split.className='opportunity-layout';screens.opportunities.append(split);split.append(list);
 const body=document.createElement('section');split.append(body);
 const syncOpportunityList=()=>{split.classList.toggle('list-collapsed',opportunityListCollapsed);list.classList.toggle('collapsed',opportunityListCollapsed);collapse.textContent=opportunityListCollapsed?'展开':'收起';collapse.setAttribute('aria-expanded',String(!opportunityListCollapsed));collapse.setAttribute('aria-label',opportunityListCollapsed?'展开我的机会':'收起我的机会');};
 collapse.onclick=()=>{opportunityListCollapsed=!opportunityListCollapsed;localStorage.setItem('job-assistant-opportunity-list',opportunityListCollapsed?'collapsed':'expanded');syncOpportunityList();};syncOpportunityList();
 const heading=document.createElement('h1');heading.id='opportunity-title';body.append(heading);
 const back=document.createElement('button');back.textContent='围绕这个机会继续聊';back.onclick=()=>showPage('chat');body.append(back);const invitation=document.createElement('button');invitation.id='record-invitation';invitation.className='secondary';invitation.textContent='我收到面试邀请了';invitation.onclick=()=>openProgress('job',selected,'interview',selected);body.append(invitation);
 const tabs=document.createElement('nav');tabs.className='opportunity-tabs';tabs.setAttribute('aria-label','机会资料');
 for(const [key,label] of Object.entries({overview:'分析',resume:'简历',interview:'面试',materials:'岗位与公司',records:'记录'})){
  const b=document.createElement('button');b.textContent=label;b.dataset.opportunity=key;b.onclick=()=>showOpportunity(key);tabs.append(b);
 }
 body.append(tabs);
 for(const key of ['overview','resume','interview','materials','records']){const area=document.createElement('section');area.id='opportunity-'+key;area.hidden=key!=='overview';body.append(area);}
 move('job-editor',document.getElementById('opportunity-materials'));
 move('company-panel',document.getElementById('opportunity-materials'));
 const deep=document.getElementById('deep-analysis');deep.textContent='生成详细岗位分析';document.getElementById('opportunity-overview').prepend(deep);
 const resumeAction=document.createElement('button');resumeAction.dataset.kind='tailor_resume';resumeAction.textContent='为这个岗位优化简历';resumeAction.className='secondary';document.getElementById('opportunity-resume').append(resumeAction);
 move('interview-panel',document.getElementById('opportunity-interview'));
 move('journey-panel',document.getElementById('opportunity-records'));
 move('deliveries',document.getElementById('opportunity-overview'));
 move('resume-versions-panel',document.getElementById('opportunity-resume'));
 move('setup',screens.profile);move('facts-panel',screens.profile);
 move('connections',screens.settings);document.getElementById('connections').open=true;
 move('data-panel',screens.settings);
 const guide=document.createElement('p');guide.className='panel';guide.id='onboarding-guide';
 guide.textContent='先认识彼此 → 保存真实经历 → 核对脱敏内容 → 在设置中连接模型和侧栏。已保存的内容会保留，不必重新填写。';
 const setupLink=document.createElement('button');setupLink.textContent='检查模型与侧栏连接';setupLink.onclick=()=>showPage('settings');guide.append(setupLink);screens.profile.prepend(guide);
 const firstUse=document.createElement('section');firstUse.id='onboarding-flow';firstUse.className='panel onboarding-flow';firstUse.hidden=true;firstUse.setAttribute('aria-live','polite');screens.chat.prepend(firstUse);
 document.querySelector('.workspace')?.remove();
 showPage('chat',false);showOpportunity('overview',false);
}
function syncWorkspaceURL(){
 const p=new URLSearchParams();if(selected)p.set('job',selected);p.set('page',workspacePage);p.set('tab',opportunityTab);
 history.replaceState(null,'','#'+p.toString());
}
function showPage(page,update=true){
 if(!Object.hasOwn(workspaceTitles,page))page='chat';workspacePage=page;
 document.body.dataset.workspacePage=page;
 if(document.getElementById('session-dialog')?.open&&page!=='chat')document.getElementById('session-dialog').close();
 for(const key of Object.keys(workspaceTitles))document.getElementById('screen-'+key).hidden=key!==page;
 document.querySelectorAll('[data-page]').forEach(b=>{b.classList.toggle('active',b.dataset.page===page);b.setAttribute('aria-current',b.dataset.page===page?'page':'false');});
 if(update){syncWorkspaceURL();document.querySelector('.workspace-nav').scrollIntoView({block:'start'});}
}
function showOpportunity(tab,update=true){
 if(!['overview','resume','interview','materials','records'].includes(tab))tab='overview';opportunityTab=tab;
 for(const key of ['overview','resume','interview','materials','records'])document.getElementById('opportunity-'+key).hidden=key!==tab;
 document.querySelectorAll('[data-opportunity]').forEach(b=>{b.classList.toggle('active',b.dataset.opportunity===tab);b.setAttribute('aria-pressed',String(b.dataset.opportunity===tab));});
 const deliveries=document.getElementById('deliveries');deliveries.hidden=['records','materials'].includes(tab);const destination=document.getElementById('opportunity-'+tab);
 if(tab==='resume')destination.prepend(deliveries);else destination.append(deliveries);
 document.querySelector('#deliveries > p').textContent=tab==='resume'?'先核对草稿，再保存、回填与导出。原始档案保持不变。':'完整结果与依据保存在这里，聊天只显示状态和查看入口。';
 document.querySelector('#deliveries h2').textContent={overview:'详细分析',resume:'岗位简历 · 核对与交付',interview:'面试准备与复盘',materials:'任务',records:'任务'}[tab];
 if(typeof renderTasks==='function'){taskSignature='';renderTasks();}
 if(update)syncWorkspaceURL();
}
function onboardingCopy(step,job){
 const name=job?job.title+' · '+job.company:'';
 return {
  connection:['第 1 步 · 连接模型','选一种接入方式。我们会在保存后立即测试，成功才进入下一步。'],
  persona:['第 2 步 · 选你的搭子','选一种说话方式，给搭子取个顺口的称呼。'],
  profile:['第 3 步 · 留下真实经历','上传或粘贴简历，在本机建档。经历不会因为页面切换而丢失。'],
  privacy:['第 4 步 · 核对脱敏','先预览将发送给模型的职业信息，确认无误后再继续。'],
  pairing:['连接招聘侧栏','先生成配对码，填入浏览器侧栏的“连接我的工作台”。连接成功后，这里会自动进入下一步。'],
  browse:['接下来，去看一个岗位','回到 BOSS，点开一个你在意的岗位。侧栏读到后，会只留一个下一步按钮。'],
  first_reply:['让搭子看第一个岗位','已选定 '+name+'。回到侧栏，点“就看这个，帮我分析”。'],
  first_reply_wait:['正在看第一个岗位','简短判断会直接出现在侧栏。这一步不需要再做选择。'],
  first_success:['你已经会用了','以后看到岗位，就可以这样叫搭子一起看。深入分析、简历和面试卡留给真正需要时再用。']
 }[step]||['一起开始',''];
}
function renderOnboarding(guide,force=false){
 const card=document.getElementById('onboarding-flow');if(!card)return;
 if(pairingRequested&&pairingBaseline===null){pairingBaseline=String(settings?.extension_pairing_revision||0);sessionStorage.setItem('job-assistant-pairing-revision',pairingBaseline);}
 if(pairingRequested&&settings?.extension_paired&&String(settings.extension_pairing_revision)!==pairingBaseline){pairingRequested=false;pairingBaseline=null;sessionStorage.removeItem('job-assistant-pairing-revision');force=true;const p=new URLSearchParams(location.hash.slice(1));p.delete('pairing');history.replaceState(null,'','#'+p.toString());if(!guide?.active)showPage('settings',false);}
 if(pairingRequested)guide={active:true,step:'pairing'};
 $('pairing-status').textContent=settings?.extension_paired&&!pairingRequested?'侧栏已配对。可以返回 BOSS 继续。':'等待侧栏连接。把配对码填入侧栏后点击“连接”。';
 $('pair-port').textContent=location.port||'8421';
 if(typeof pairingCode!=='undefined'&&pairingCode){if(settings?.extension_paired&&!pairingRequested){pairingCode='';$('pair-code').textContent='配对成功';$('copy-pair-code').hidden=true;}else if(Date.now()>=pairingExpires){$('pair-code').textContent='配对码已过期，请重新生成';$('copy-pair-code').hidden=true;}}
 document.body.classList.toggle('first-use-mode',!!guide?.active);if(guide?.active)document.body.dataset.guideStep=guide.step;else delete document.body.dataset.guideStep;
 if(!guide?.active){$('save-provider').textContent='保存接入方式';$('save-identity').textContent='记住我们的称呼';$('save-profile').textContent='保存本地档案';$('privacy-approve').textContent='确认档案，开始一起找工作';card.hidden=true;onboardingSignature='';return;}
 const host={connection:'settings',pairing:'settings',persona:'profile',profile:'profile',privacy:'profile'}[guide.step]||'chat';
 const destination=document.getElementById('screen-'+host);if(destination&&card.parentElement!==destination)destination.prepend(card);
 const sig=JSON.stringify(guide);if(sig===onboardingSignature&&!force)return;onboardingSignature=sig;card.hidden=false;card.replaceChildren();
 const [title,copy]=onboardingCopy(guide.step,guide.job);card.append(el('p','首次使用','eyebrow'),el('h1',title),el('p',copy));
 const actions=document.createElement('div');actions.className='guide-actions';
 const navigation=document.createElement('div');navigation.className='guide-navigation';
 const back=el('button','上一步','secondary');back.id='guide-back';back.disabled=guide.step==='pairing';back.onclick=async()=>{try{await onboardingAction('back',{step:guide.step},true);notice('已返回上一步；已有设置和资料仍保留。');}catch(e){notice(e.message,true);}};navigation.append(back);
 const skip=el('button','跳过引导，进入工作台','text-button');skip.id='guide-skip';skip.onclick=async()=>{try{await skipOnboarding();}catch(e){notice(e.message,true);}};navigation.append(skip);
 const connection=el('button','检查 / 更换模型接入','text-button');connection.id='guide-connection';connection.hidden=['connection','pairing'].includes(guide.step);connection.onclick=async()=>{try{await onboardingAction('connection-settings',{},true);}catch(e){notice(e.message,true);}};navigation.append(connection);
 if(guide.step==='pairing'){$('connections').open=true;if(settings?.extension_paired&&!pairingRequested){const b=el('button','侧栏已连接，继续');b.onclick=()=>guideContinue().catch(e=>notice(e.message,true));actions.append(b);}}
 if(guide.step==='connection'){$('connections').open=true;$('save-provider').textContent='保存并测试连接';}
 if(guide.step==='persona'){
  $('setup').open=true;
  const roles=document.createElement('div');roles.className='guide-role-options';
  for(const [id,title,words] of [['gentle','温柔搭子','先别急着否定自己，我们看看岗位最看重什么。'],['direct','直球搭子','先说判断：可以聊，但有两个条件要问清。']]){
   const role=document.createElement('button');role.type='button';role.className='guide-role-card';role.classList.toggle('selected',$('persona').value===id);role.append(el('strong',title),el('small',words));role.onclick=()=>{$('persona').value=id;rolePreview();renderOnboarding(guide,true);$('buddy-name').focus();};roles.append(role);
  }card.append(roles);$('save-identity').textContent='记住这个称呼，继续';
 }
 if(guide.step==='profile'){$('setup').open=true;$('save-profile').textContent='保存经历，继续';}
 if(guide.step==='privacy'){$('setup').open=true;$('privacy-approve').textContent='确认脱敏，继续';if(guide.reviewing&&settings.ready){const b=el('button','沿用已确认档案，继续');b.onclick=()=>guideContinue().catch(e=>notice(e.message,true));actions.append(b);}}
 if(['browse','first_reply'].includes(guide.step)){const b=el('button','回到 BOSS 继续');b.onclick=()=>returnToBoss();actions.append(b);}
 if(guide.step==='first_reply_wait'){const b=el('button','回到侧栏看结果');b.onclick=()=>returnToBoss();actions.append(b);}
 if(guide.step==='first_success'){const b=el('button','结束引导，继续看岗位');b.onclick=async()=>{await finishOnboarding();};actions.append(b);}
 if(actions.childNodes.length)card.append(actions);
 card.append(navigation);
 showPage(host,false);
}
function openTask(id){
 if(document.getElementById('session-dialog').open)document.getElementById('session-dialog').close();
 const task=state.tasks.find(t=>t.id===id);if(!task){notice('任务暂未载入，请稍后刷新',true);return;}
 if(selected!==task.job_id)selectJob(task.job_id);
 if(!isBackground(task.kind)){showPage('chat');return;}
 showPage('opportunities');showOpportunity(task.kind==='tailor_resume'?'resume':task.kind.startsWith('interview_')?'interview':'overview');
 const taskCard=document.getElementById('task-'+id);if(taskCard)taskCard.open=true;
 taskCard?.scrollIntoView({block:'start',behavior:'smooth'});
}
function renderWorkspaceStatus(){
 const job=state.jobs.find(j=>j.id===selected);
 document.getElementById('session-target').textContent=job?'正在聊：'+job.title+' · '+job.company:'不选岗位也可以聊聊近况。';
 document.getElementById('opportunity-title').textContent=job?job.title+' · '+job.company:'选择一个机会';
 document.getElementById('onboarding-guide').hidden=!!settings?.ready;document.getElementById('record-invitation').disabled=!job;
 const deep=document.getElementById('deep-analysis');const analyses=state.tasks.filter(t=>t.job_id===selected&&t.kind==='analyze_job').sort((a,b)=>(b.created||0)-(a.created||0));const active=analyses.find(t=>['queued','running'].includes(t.status));const complete=analyses.find(t=>t.status==='done'&&t.result);const target=active||complete;
 deep.dataset.taskId=target?.id||'';deep.textContent=active?'查看分析进度':complete?'查看详细分析':'生成详细岗位分析';
 const inbox=document.getElementById('delivery-inbox');const sig=JSON.stringify([showReadResults,showAllInbox,state.tasks.map(t=>[t.id,t.status,t.job_id,t.viewed,t.created]),state.jobs.map(j=>[j.id,j.title])]);if(sig===inboxSignature)return;inboxSignature=sig;inbox.replaceChildren();
 const relevant=state.tasks.filter(t=>isBackground(t.kind)&&['done','running','queued','failed'].includes(t.status)).sort((a,b)=>(b.created||0)-(a.created||0));
 const groups=[['处理中',relevant.filter(t=>['queued','running'].includes(t.status))],['需要处理',relevant.filter(t=>t.status==='failed')],['待查看',relevant.filter(t=>t.status==='done'&&!t.viewed)]];
 if(showReadResults)groups.push(['已查看',relevant.filter(t=>t.status==='done'&&t.viewed)]);
 const summary=groups.filter(g=>g[1].length&&g[0]!=='已查看').map(g=>g[0]+' '+g[1].length).join(' · ');document.getElementById('delivery-inbox-summary').textContent='任务提醒 · '+(summary||'暂无待办');
 const attention=relevant.filter(t=>t.status!=='done'||!t.viewed).length;document.getElementById('session-open').textContent='任务与成果'+(attention?' · '+attention:'');
 if(!groups.some(g=>g[1].length)){const empty=document.createElement('p');empty.textContent='暂时没有待处理结果。已查看内容仍保留在对应机会中。';inbox.append(empty);}
 let remaining=showAllInbox?Infinity:3;
 for(const [label,tasks] of groups){if(!tasks.length||remaining<=0)continue;const visible=tasks.slice(0,remaining);remaining-=visible.length;const section=document.createElement('section');const heading=document.createElement('h3');heading.textContent=label+' · '+tasks.length;section.append(heading);inbox.append(section);
 for(const t of visible){
  const j=state.jobs.find(j=>j.id===t.job_id);const b=document.createElement('button');b.className='delivery-link';
  b.textContent=(names[t.kind]||'任务')+' · '+(j?.title||'岗位')+' · '+({done:'查看结果',running:'处理中',queued:'排队中',failed:'失败，可重试'})[t.status];b.onclick=()=>openTask(t.id);section.append(b);
 }
 }
 document.getElementById('toggle-all-results').hidden=relevant.length<=3;
}
mountWorkspace();
