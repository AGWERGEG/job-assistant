function isBackground(kind){return ['tailor_resume','analyze_job','interview_prep','interview_review'].includes(kind);}
const $=id=>document.getElementById(id);
let token='',state=null,settings=null,selected='',previewToken='',pending=false,backgroundPending=false,sending=false,historySignature='',taskSignature='',request=null;
const drafts=new Map();const interviewDrafts=new Map();const chatDrafts=new Map();let jobsSignature='';
const names={companion_chat:'和搭子聊聊',quick_analysis:'快速判断',analyze_job:'深度分析',tailor_resume:'岗位版简历',suggest_reply:'HR 招呼',rest_message:'休息寄语',closing_message:'入职结语',interview_prep:'面试准备卡',interview_review:'面试复盘'};
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function notice(s,error=false){$('notice').textContent=s;$('notice').className=error?'error':'';$('notice').style.display='block';}
async function api(path,value){const r=await fetch(path,value===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':token},body:JSON.stringify(value)});const x=await r.json();if(!r.ok)throw Error(x.error||'请求失败');return x;}
function action(id,fn){$(id).onclick=async()=>{try{await fn();}catch(e){notice(e.message,true);}};}
function form(id,fn){$(id).onsubmit=async e=>{e.preventDefault();try{await fn();}catch(e){notice(e.message,true);}};}
function profileValues(){return {name:$('profile-name').value,preferences:$('profile-preferences').value,facts:$('profile-facts').value};}
function resetPreview(){previewToken='';$('privacy-confirm').checked=false;$('privacy-approve').disabled=true;}
function enable(){for(const b of document.querySelectorAll('[data-kind],#deep-analysis'))b.disabled=b.id==='deep-analysis'&&b.dataset.taskId?!selected:!settings?.ready||!selected||(isBackground(b.dataset.kind||'analyze_job')?backgroundPending:pending)||sending;$('send').disabled=!settings?.ready||pending||sending;$('rest-wish').disabled=$('send').disabled;}
function rolePreview(){const p=settings?.personas?.[$('persona').value];$('role-preview').textContent=p?.hello||'';providerHelp();}
function fillSettings(){for(const [id,key] of [['persona','persona'],['buddy-name','buddy_name'],['user-name','user_name'],['stage','stage'],['private-terms','private_terms'],['provider','provider'],['base-url','base_url'],['api-model','api_model']])$(id).value=settings[key]||'';$('json-mode').checked=settings.json_mode;$('stream-mode').checked=settings.stream!==false;$('key-state').textContent=settings.has_api_key?'已保存密钥（不会回显）':'尚未保存密钥';$('api-fields').hidden=settings.provider!=='api';rolePreview();}
async function reloadSettings(){settings=await api('/api/companion');$('brand').textContent=settings.buddy_name||'求职搭子';$('setup-state').textContent=settings.ready?'· 已建档':'· 待完成';$('greeting').textContent=settings.ready?(settings.user_name?settings.user_name+'，':'')+'今天想一起看看什么？':'先认识一下，再一起找下一份工作。';$('hello').textContent=settings.personas[settings.persona].hello;enable();if(typeof renderOnboarding==='function')renderOnboarding(settings.guide);}
function selectJob(id){chatDrafts.set(selected,$('message').value);if($('interview-notes'))interviewDrafts.set(selected,$('interview-notes').value);selected=id||'';if(selected&&!state.jobs.some(j=>j.id===selected)){selected='';notice('这个机会不存在或已移除，已回到日常对话。',true);}$('message').value=chatDrafts.get(selected)||'';pending=false;backgroundPending=false;$('interview-notes').value=interviewDrafts.get(selected)||'';localStorage.setItem('job-assistant-target',selected);historySignature='';taskSignature='';request=null;if($('company-panel'))$('company-panel').open=false;const job=state.jobs.find(j=>j.id===selected);for(const k of ['title','company','url','jd','conversation'])$('job-'+k).value=job?.[k]||'';$('chat-title').textContent=job?job.title+' · '+(job.company||'当前岗位'):'和搭子聊聊近况';$('interview-target').textContent=job?'当前目标：'+job.title+' · '+job.company:'先选择一个岗位，再一起准备。';$('job-label').textContent=job?'已确认这个岗位':'日常求职对话';renderJobs();renderTasks();loadHistory().catch(e=>notice(e.message,true));loadVersions().catch(()=>{});loadCompany().catch(()=>{});loadJourney().catch(()=>{});renderWorkspaceStatus();enable();}
function renderJobs(){
 const sig=JSON.stringify([selected,jobQuery,state.jobs]);if(sig===jobsSignature)return;jobsSignature=sig;
 const list=$('job-list');list.replaceChildren();const filtered=state.jobs.filter(j=>!jobQuery||(j.title+' '+(j.company||'')).toLowerCase().includes(jobQuery));
 for(const j of filtered){const b=el('button',j.title,j.id===selected?'selected':'');b.append(el('small',j.company));b.onclick=()=>{selectJob(j.id);showPage('opportunities');showOpportunity('overview');if(innerWidth<=760&&!opportunityListCollapsed)$('toggle-opportunity-list').click();};list.append(b);}
 if(!state.jobs.length)list.append(el('p','在侧栏确认第一个岗位，或在这里手动添加。','empty'));else if(!filtered.length)list.append(el('p','没有找到匹配的岗位或公司。','empty'));
}
async function loadVersions(){
 const id=selected;const r=await api('/api/resume-versions',{job_id:id});if(id!==selected)return;
 const box=$('versions');box.replaceChildren();for(const id of ['compare-a','compare-b'])$(id).replaceChildren();
 for(const v of r.versions){
  for(const id of ['compare-a','compare-b']){const o=el('option',new Date(v.created*1000).toLocaleString()+' · '+v.id.slice(0,6));o.value=v.id;$(id).append(o);}
  const row=el('article',undefined,'version');row.append(el('p',new Date(v.created*1000).toLocaleString()+' · 已验收版本'));
  const b=el('button','导出 Word / PDF（本机回填）');b.onclick=()=>openResumeExport(v.id).catch(e=>notice(e.message,true));row.append(b);row.append(progressButton('我已投递这版简历','version',v.id,'applied',id));
  const d=el('details');d.append(el('summary','查看已保存正文'),el('pre',v.content));row.append(d);box.append(row);
 }
 if(r.versions.length>1)$('compare-b').selectedIndex=1;
 $('compare').disabled=r.versions.length<2;
 if(!r.versions.length)box.append(el('p','先在上方核对简历并保存，即可导出 Word / PDF。'));
}
let exportVersion='';
async function openResumeExport(id){
 const r=await api('/api/resume-export-preview',{version_id:id});exportVersion=id;
 $('export-content').value=r.content;$('export-note').textContent=r.warnings.join('\n');
 $('export-confirm').checked=false;$('export-error').textContent='';
 for(const b of document.querySelectorAll('[data-export-format]'))b.disabled=true;
 $('resume-export-dialog').showModal();
}
async function downloadResume(format){
 try{
  $('export-error').textContent='正在本机生成文件…';
  const r=await fetch('/api/resume-download',{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':token},body:JSON.stringify({version_id:exportVersion,format,content:$('export-content').value,confirmed:$('export-confirm').checked})});
  if(!r.ok)throw Error((await r.json()).error||'导出失败');
  const url=URL.createObjectURL(await r.blob());const a=el('a');a.href=url;a.download='岗位版简历.'+format;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
  $('export-error').textContent='已生成，请查看浏览器下载。回填内容未写入聊天或模型任务。';
 }catch(e){$('export-error').textContent=e.message;}
}
$('export-confirm').onchange=()=>{for(const b of document.querySelectorAll('[data-export-format]'))b.disabled=!$('export-confirm').checked;};
$('export-content').oninput=()=>{$('export-confirm').checked=false;$('export-confirm').onchange();};
$('export-close').onclick=()=>{$('resume-export-dialog').close();$('export-content').value='';exportVersion='';};
$('resume-export-dialog').addEventListener('close',()=>{$('export-content').value='';exportVersion='';});
for(const b of document.querySelectorAll('[data-export-format]'))b.onclick=()=>downloadResume(b.dataset.exportFormat);

async function copy(s){try{await navigator.clipboard.writeText(s);notice('已复制。');}catch{notice('请手动选中文字复制。',true);}}
async function loadHistory(){
  const id=selected;const r=await api('/api/history',{job_id:id});if(id!==selected)return;pending=r.turns.some(t=>!isBackground(t.kind)&&['queued','running'].includes(t.status));backgroundPending=r.turns.some(t=>isBackground(t.kind)&&['queued','running'].includes(t.status));enable();
  const sig=JSON.stringify(r.turns);if(sig===historySignature)return;historySignature=sig;const list=$('messages');const follow=list.dataset.job!==id||list.scrollHeight-list.scrollTop-list.clientHeight<64;const previousTop=list.scrollTop;list.dataset.job=id;list.replaceChildren();
  if(!r.turns.length)list.append(el('p',selected?'这个岗位已经记下了。想先看看适不适合，还是聊聊你的顾虑？':settings?.personas[settings.persona].hello||'我在，慢慢说。','empty'));
  for(const t of r.turns){const row=el('article',undefined,'turn');row.append(el('p',t.text,'user'));let message=t.status==='done'?(t.workbench?(t.kind==='tailor_resume'?'岗位版简历准备好了，可打开简历核对后保存。':(names[t.kind]||'专业任务')+'已完成，可打开对应结果查看。'):t.reply):t.status==='running'&&t.partial?t.partial:t.status==='failed'?t.error:t.status==='cancelled'?'这条任务已经取消。':t.status==='queued'?'收到，正在排队。':t.workbench?'后台任务处理中，你可以继续聊天。':'我正在整理回复。';row.append(el('p',message,'reply'));if(t.stale)row.append(el('small','这条回复对应旧资料，更新后可重新提问。'));if(t.workbench){const b=el('button','查看工作台任务');b.onclick=()=>openTask(t.task_id);row.append(b);}else if(t.status==='done'){const b=el('button','复制回复');b.onclick=()=>copy(t.reply);row.append(b);}if(['queued','running','failed'].includes(t.status)){const cancel=el('button','取消任务');cancel.onclick=()=>taskAction(t.task_id,'cancel');row.append(cancel);if(t.status==='failed'){const retry=el('button','重试');retry.onclick=()=>taskAction(t.task_id,'retry');row.append(retry);}}if(t.status==='done'&&t.kind==='suggest_reply'){row.append(progressButton('我已发出这条招呼','task',t.task_id,'greeting_sent',id));row.append(progressButton('收到面试邀请了','task',t.task_id,'interview',id));}const m=t.metrics;if(m?.total_seconds)row.append(el('small','总耗时 '+m.total_seconds+' 秒'+(m.first_response_seconds!==undefined?'，首段 '+m.first_response_seconds+' 秒':'')+'（排队 '+m.queue_seconds+' 秒，模型调用 '+m.model_seconds+' 秒）'));list.append(row);}
  list.scrollTop=follow?list.scrollHeight:previousTop;$('chat-status').textContent=pending?'消息已保存。完成后自动显示；可以打开“任务与成果”查看进度。':backgroundPending?'专业任务在后台处理，可以继续聊天；新消息不会修改已运行任务。':'对话保存在本机，按当前岗位记忆。';
}
function renderTasks(){
  if(!state)return;
  const tasks=state.tasks.filter(t=>t.job_id===selected&&isBackground(t.kind)&&(opportunityTab==='resume'?t.kind==='tailor_resume':opportunityTab==='interview'?t.kind.startsWith('interview_'):opportunityTab==='overview'?t.kind==='analyze_job':false));const sig=JSON.stringify(tasks);if(sig===taskSignature)return;
  const latestCompleted=tasks.find(t=>t.status==='done'&&t.result);
  for(const input of document.querySelectorAll('[data-draft]'))drafts.set(input.dataset.draft,input.value);
  const opened=new Map([...document.querySelectorAll('#task-list>details.task')].map(n=>[n.id,n.open]));taskSignature=sig;const box=$('task-list');box.replaceChildren();
  for(const t of tasks){const card=el('details',undefined,'task');card.id='task-'+t.id;card.open=opened.get(card.id)??(t===tasks[0]);const summary=el('summary');summary.append(el('strong',names[t.kind]||t.kind),el('small',({queued:'排队中',running:'正在处理',done:'已完成',failed:'处理失败',cancelled:'已取消'})[t.status]+' · '+new Date(t.created*1000).toLocaleString()));card.append(summary);
    if(t.result){if(isBackground(t.kind)){card.append(el('p',t.result.decision||t.result.summary));if(t.kind==='tailor_resume'){const input=el('textarea');input.dataset.draft=t.id;input.setAttribute('aria-label','核对岗位版简历');input.value=drafts.get(t.id)??t.result.primary_output??t.result.markdown;card.append(input);const save=el('button','保存这一版并导出 Word / PDF');save.onclick=async()=>{try{const v=await api('/api/resume-accept',{task_id:t.id,content:input.value});await loadVersions();await openResumeExport(v.id);notice('这一版已保存，请在本机预览回填信息并导出。');}catch(e){notice(e.message,true);}};card.append(save);}else card.append(el('pre',t.result.primary_output||t.result.summary));if(t.kind.startsWith('interview_')){card.append(el('small','这是面试准备草稿：请核对数字、个人职责、工具和成果。模型可能补写未提供的细节，未经核实不要照读；历史建议也不等于真实经历。'));const b=el('button','复制这张卡');b.onclick=()=>copy(t.result.primary_output||'');card.append(b);if(t.result.questions?.length)card.append(el('p','下次可以补充：'+t.result.questions.join('；')));}const detail=el('details');detail.append(el('summary','专业分析与修改依据'),el('pre',t.result.markdown));card.append(detail);}
      const link=el('a','下载任务 Markdown');link.href='/api/export/'+t.id;link.download=true;card.append(link);
      const read=el('button',t.viewed?'设为待查看':'我已查看这份结果');read.className='secondary';read.onclick=async()=>{try{await api('/api/result-viewed',{task_id:t.id,result_updated:t.updated,viewed:!t.viewed});await refresh();notice(t.viewed?'已设为待查看。':'已标为查看，不会改变验收或求职进展。');}catch(e){notice(e.message,true);}};card.append(read);
      if(t.kind==='analyze_job'&&t===latestCompleted){const rerun=el('button','重新分析','secondary');rerun.onclick=()=>talk('analyze_job');card.append(rerun);}
      if(t.kind==='interview_prep'){card.append(progressButton('我收到面试邀请了','task',t.id,'interview',t.job_id));card.append(progressButton('这场面试已完成','task',t.id,'interview_done',t.job_id));}
      if(t.kind==='interview_review')card.append(progressButton('这场面试已完成','task',t.id,'interview_done',t.job_id));
    }else if(t.status==='failed'){card.append(el('p',t.error_text));const b=el('button','重试');b.onclick=()=>taskAction(t.id,'retry');card.append(b);}
    if(['queued','running','failed'].includes(t.status)){const b=el('button','取消任务');b.onclick=()=>taskAction(t.id,'cancel');card.append(b);}
    if(t.metrics?.total_seconds)card.append(el('small','耗时 '+t.metrics.total_seconds+' 秒 · 模型调用 '+t.metrics.model_seconds+' 秒'));
    const details=el('details');details.append(el('summary','查看脱敏发送内容'));const pre=el('pre','展开后载入本地预览');details.append(pre);details.ontoggle=async()=>{if(details.open){try{pre.textContent=(await api('/api/task-preview',{task_id:t.id})).prompt;}catch(e){pre.textContent=e.message;}}};card.append(details);box.append(card);
  }
  if(!tasks.length)box.append(el('p',opportunityTab==='resume'?'还没有岗位简历。回到聊天点击优化简历，完成后在这里核对。':opportunityTab==='interview'?'填写上方面试信息，生成准备卡或复盘。':'需要更详细判断时，点击展开详细岗位分析。','empty'));
}
async function taskAction(id,verb){try{await api('/api/tasks/'+id+'/'+verb,{});await refresh();}catch(e){notice(e.message,true);}}
async function refresh(){state=await api('/api/state');renderJobs();renderTasks();await reloadSettings();await loadHistory();await loadCompany();await loadJourney();renderWorkspaceStatus();}
async function talk(kind,override){
  if(sending||(isBackground(kind)?backgroundPending:pending))return;const input=kind.startsWith('interview_')?$('interview-notes'):$('message');const text=override===undefined?input.value.trim():override;if(kind==='companion_chat'&&!text)return;sending=true;enable();
  try{const job=selected;const identity=JSON.stringify([job,kind,text]);if(request?.identity!==identity)request={identity,id:crypto.randomUUID()};const r=await api('/api/talk',{kind,text,job_id:job,request_id:request.id});if(selected===job){if(override===undefined)input.value='';request=null;await refresh();renderWorkspaceStatus();}notice(isBackground(kind)?'后台任务已记下，完成后在工作台查看；我们可以继续聊天。':'收到，回复会留在这段对话里。');return r;}catch(e){notice(e.message,true);return null;}finally{sending=false;enable();}
}
async function onboardingAction(action,value={},force=true){const r=await api('/api/onboarding',{action,...value});settings=r;if(!['back','continue','connection-settings'].includes(action))fillSettings();renderOnboarding(settings.guide,force);return r;}
async function guideContinue(){if(settings?.guide?.active)await onboardingAction('continue',{},true);}
async function skipOnboarding(){
 await api('/api/onboarding',{action:'skip'});
 pairingRequested=false;pairingBaseline=null;sessionStorage.removeItem('job-assistant-pairing-revision');
 const p=new URLSearchParams(location.hash.slice(1));p.delete('pairing');p.delete('onboarding');p.set('page','settings');history.replaceState(null,'','#'+p.toString());
 await reloadSettings();renderOnboarding(settings.guide,true);showPage('settings',false);$('connections').open=true;
 notice('已退出首次引导，资料已保留。可在这里修复模型接入，或从“我的档案”继续建档；脱敏确认仍需完成。');
}
async function returnToBoss(){await guideContinue();await reloadSettings();if(settings.extension_paired===false){pairingRequested=true;renderOnboarding(settings.guide,true);notice('先连接招聘侧栏，配对完成后再回 BOSS。');return;}notice('请切回 BOSS 招聘标签页，侧栏会接着带你看第一个岗位。');}
async function finishOnboarding(){await onboardingAction('complete',{},true);notice('首次引导完成。以后按自己的节奏来，需要时再叫搭子。');returnToBoss();}
form('identity-form',async()=>{const guideStep=settings?.guide?.step;await api('/api/companion',{persona:$('persona').value,buddy_name:$('buddy-name').value,user_name:$('user-name').value,stage:$('stage').value});resetPreview();await reloadSettings();if(guideStep==='persona')await onboardingAction('persona');notice('称呼记下了。接着保存档案并核对脱敏内容。');});
$('persona').onchange=rolePreview;
form('profile-form',async()=>{await api('/api/profile',profileValues());resetPreview();await refresh();await guideContinue();if(settings?.guide?.active){renderOnboarding(settings.guide,true);}else{showPage('profile');$('setup').open=true;}notice(settings.ready?'本地档案已保存，已有脱敏确认仍有效。':'本地档案已保存，请预览脱敏结果。');});
for(const id of ['profile-name','profile-preferences','profile-facts','private-terms','user-name'])$(id).addEventListener('input',resetPreview);
action('use-template',async()=>{if($('profile-facts').value.trim())throw Error('已有经历内容，请直接编辑；模板不会覆盖你的草稿。');$('profile-facts').value='教育经历：\n专业与毕业时间：\n\n工作 / 实习 / 校园经历：\n时间与职位：\n我负责的事情：\n做过的具体动作与结果：\n\n技能与证书：';resetPreview();$('profile-facts').focus();});
$('resume-file').onchange=async()=>{try{const f=$('resume-file').files[0];if(!f)return;if(f.size>5*1024*1024)throw Error('文件不能超过 5 MB');const base64=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=reject;r.readAsDataURL(f);});const r=await api('/api/documents',{name:f.name,base64});if(r.extracted)$('profile-facts').value+=($('profile-facts').value?'\n\n':'')+r.extracted;$('import-status').textContent=r.extracted?'已在本地提取，请核对后保存档案。':'未提取到文字：'+r.extraction_status+'。可粘贴简历文本。';resetPreview();}catch(e){notice(e.message,true);}};
action('privacy-preview',async()=>{if(JSON.stringify(profileValues())!==JSON.stringify({name:state.profile.name,preferences:state.profile.preferences,facts:state.profile.facts}))throw Error('经历有未保存修改，请先保存本地档案');await api('/api/companion',{private_terms:$('private-terms').value});const r=await api('/api/privacy-preview',{});previewToken=r.token;$('privacy-output').textContent=JSON.stringify(r.preview,null,2);$('privacy-note').textContent=r.note;$('privacy-confirm').checked=false;$('privacy-approve').disabled=true;await reloadSettings();});
$('privacy-confirm').onchange=()=>{$('privacy-approve').disabled=!previewToken||!$('privacy-confirm').checked;};
action('privacy-approve',async()=>{const guiding=settings?.guide?.active;await api('/api/privacy-approve',{token:previewToken,confirmed:$('privacy-confirm').checked});await reloadSettings();if(guiding)await guideContinue();$('setup').open=false;if(guiding){renderOnboarding(settings.guide,true);notice(settings.extension_paired?'档案已确认。接下来切回 BOSS，打开一个感兴趣的岗位。':'档案已确认。先连接侧栏，再回 BOSS 看岗位。');}else{showPage('settings');$('connections').open=true;notice('档案已确认。可以继续使用搭子。');}});
function providerHelp(){const useAPI=$('provider').value==='api';$('api-fields').hidden=!useAPI;$('provider-help').textContent=useAPI?'填入服务商提供的地址、模型名称和 API 密钥。保存后发送一次测试，成功才继续。支持 Chat Completions 兼容接口。':'已通过 Codex 部署并登录？选择这一项，无需填写 API 密钥。这里会检查 CLI 登录凭据，实际任务再验证网络与额度。若提示未登录，请在终端运行 codex login。';}
$('provider').onchange=providerHelp;
let savingProvider=false;
form('provider-form',async()=>{if(savingProvider)return;savingProvider=true;$('save-provider').disabled=true;const guideStep=settings?.guide?.step;try{await api('/api/companion',{provider:$('provider').value,base_url:$('base-url').value,api_model:$('api-model').value,api_key:$('api-key').value,json_mode:$('json-mode').checked,stream:$('stream-mode').checked,clear_api_key:$('clear-key').checked});$('api-key').value='';$('clear-key').checked=false;await reloadSettings();$('key-state').textContent=settings.has_api_key?'密钥已保存在本机':'未保存密钥';if(guideStep==='connection'){$('connection-status').textContent='正在测试已保存的配置……';const r=await api('/api/connection-test',{});if(r.ok!==true)throw Error(r.message||'连接未通过，请检查接入方式后重试');$('connection-status').textContent=r.message;await onboardingAction('connection');notice('接入检查通过。现在选一个合拍的搭子。');}else notice('接入方式已保存。');}catch(e){$('connection-status').textContent=e.message;throw e;}finally{savingProvider=false;$('save-provider').disabled=false;}});
action('test-connection',async()=>{$('connection-status').textContent='正在测试已保存的配置…';try{const r=await api('/api/connection-test',{});$('connection-status').textContent=r.message;}catch(e){$('connection-status').textContent=e.message;}});
action('restart-onboarding',async()=>{await onboardingAction('restart');notice('首次引导已重新打开；已有档案和设置不会被删除。');});
let pairingCode='',pairingExpires=0;
action('extension-code',async()=>{const r=await api('/api/extension-code',{});pairingCode=r.code;pairingExpires=Date.now()+r.expires_in*1000;pairingRequested=true;pairingBaseline=String(settings?.extension_pairing_revision||0);sessionStorage.setItem('job-assistant-pairing-revision',pairingBaseline);const p=new URLSearchParams(location.hash.slice(1));p.set('pairing','1');history.replaceState(null,'','#'+p.toString());$('pair-code').textContent=pairingCode;$('copy-pair-code').hidden=false;renderOnboarding(settings.guide,true);});
action('copy-pair-code',async()=>{if(Date.now()>=pairingExpires)throw Error('配对码已过期，请重新生成');await navigator.clipboard.writeText(pairingCode);notice('已复制。粘贴到侧栏的配对码栏，再点击“连接”。');});
action('extension-revoke',async()=>{await api('/api/extension-revoke',{});pairingCode='';$('copy-pair-code').hidden=true;$('pair-code').textContent='连接已撤销。';await reloadSettings();});
action('general-chat',async()=>{selectJob('');showPage('chat');});
action('new-job',async()=>{selectJob('');showPage('opportunities');showOpportunity('materials');$('job-editor').open=true;$('job-title').focus();});
form('job-form',async()=>{const value={};for(const k of ['title','company','url','jd','conversation'])value[k]=$('job-'+k).value;if(selected)value.id=selected;const j=await api('/api/jobs',value);state=await api('/api/state');selectJob(j.id);showPage('opportunities');showOpportunity('overview');$('job-editor').open=false;notice('岗位已确认，后续对话会记在这里。');});
form('chat-form',async()=>talk('companion_chat'));
document.querySelectorAll('[data-kind]').forEach(b=>b.onclick=()=>talk(b.dataset.kind));
$('deep-analysis').onclick=async()=>{try{const id=$('deep-analysis').dataset.taskId;if(id)openTask(id);else await talk('analyze_job');}catch(e){notice(e.message,true);}};action('refresh',refresh);
$('message').onkeydown=e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();talk('companion_chat');}};
function followHash(){const p=new URLSearchParams(location.hash.slice(1));if(p.get('pairing')==='1')pairingRequested=true;if(p.has('job'))selectJob(p.get('job'));if(settings.guide?.active||pairingRequested){renderOnboarding(settings.guide,true);return;}if(p.get('task')){openTask(p.get('task'));return;}const view=p.get('view');if(['interview','journey'].includes(view)){showPage('opportunities',false);showOpportunity(view==='journey'?'records':'interview',false);}else{showPage(p.get('page')||'chat',false);showOpportunity(p.get('tab')||'overview',false);}if(p.get('onboarding')==='1'){showPage('settings',false);$('connections').open=true;}else if(!settings.ready){showPage('profile',false);$('setup').open=true;}}
window.addEventListener('hashchange',followHash);
(async()=>{const session=await api('/api/session');token=session.token;$('runtime-badge').textContent='v'+session.version+' · '+(session.execution==='codex-worker'?'搭子已连接':'手动处理模式');state=await api('/api/state');await reloadSettings();fillSettings();for(const k of ['name','preferences','facts'])$('profile-'+k).value=state.profile[k]||'';$('setup').open=!settings.ready;selectJob(state.jobs.some(j=>j.id===localStorage.getItem('job-assistant-target'))?localStorage.getItem('job-assistant-target'):'');followHash();await loadJourney();if(session.execution!=='codex-worker')notice('当前未启动自动处理，请用 launch.py 启动，或通过 Codex 手动领取任务。');setInterval(()=>refresh().catch(()=>{$('chat-status').textContent='与本机工作台连接中断。记录仍在本机；服务重启后请刷新页面。';}),1000);})().catch(e=>notice(e.message,true));

let companySignature='';
async function loadCompany(){
 const id=selected;const r=await api('/api/company',{job_id:id});if(id!==selected)return;
 const signature=JSON.stringify([id,r]);if(signature===companySignature)return;companySignature=signature;
 const box=$('company-evidence');box.replaceChildren();const c=r.company;const summary=$('company-summary');
 if(!c){summary.textContent='公司与业务背景 · 尚未关联';box.append(el('p','尚未关联公司。请在新版侧栏确认带公司来源的岗位，再浏览介绍并保存。'));return;}
 summary.textContent='公司与业务背景 · '+c.name+' · '+c.evidence.length+' 条';
 box.append(el('p','已保存 '+c.evidence.length+' 条公开材料。生成新任务时最多选取最近且相关的 10 条；全部原文仍保留在这里。'));
 if(!c.evidence.length)box.append(el('p','公司已关联，还没有保存介绍或对照岗位。'));
 const kinds={introduction:'公司介绍',products:'产品与业务',recruitment:'招聘概况',peer_job:'同公司岗位参考'};
 for(const kind of Object.keys(kinds)){
  const entries=c.evidence.filter(e=>e.kind===kind);if(!entries.length)continue;const group=el('details',undefined,'company-group');group.append(el('summary',kinds[kind]+' · '+entries.length));
  for(const e of entries){
   const title=e.kind==='peer_job'?(e.title||'岗位参考'):e.kind==='recruitment'?'已加载 '+(e.jobs?.length||0)+' 个岗位卡片':kinds[e.kind];
   const d=el('details',undefined,'version company-material');d.append(el('summary',title));
   d.append(el('small',(e.label||'招聘页表述')+' · 资料 '+e.id.slice(0,8)+' · '+new Date(e.observed*1000).toLocaleString()+(e.partial?' · 内容可能折叠/截断':'')));
   if(e.text)d.append(el('pre',e.text));
   if(e.jobs)d.append(el('pre',e.jobs.map(j=>j.title+' · '+j.salary+' · '+j.conditions).join('\n')));
   if(e.categories?.length)d.append(el('p','页面显示分类：'+e.categories.join('、')));
   if(e.filters)d.append(el('p','读取时筛选：'+e.filters));
   if(e.coverage)d.append(el('small',e.coverage));
   const a=el('a','查看来源');a.href=e.source_url;a.target='_blank';a.rel='noreferrer';d.append(a);group.append(d);
  }
  box.append(group);
 }
 if(c.evidence.length){const close=el('button','收起公司背景','text-button company-collapse');close.onclick=()=>{$('company-panel').open=false;$('company-panel').scrollIntoView({block:'start'});};box.append(close);}
}

let journeySignature='';
async function loadJourney(){
 const id=selected;const r=await api('/api/journey');if(id!==selected)return;const sig=JSON.stringify([selected,r]);if(sig===journeySignature)return;journeySignature=sig;
 const s=r.summary;$('journey-summary').textContent='全部机会累计：'+s.companies+' 家公司 / '+s.applications+' 次投递，'+s.greetings+' 次招呼，'+s.resume_versions+' 个验收版本，跨度 '+s.span_days+' 天。';
 const list=$('journey-list');list.replaceChildren();list.append(el('p',selected?'下方仅显示当前机会的确认记录。':'请选择一个机会后记录实际进展。'));
 for(const e of r.events.filter(e=>e.job_id===selected)){const row=el('p',r.labels[e.kind]+' · '+(e.company||'')+' '+(e.title||'')+' · '+new Date(e.at*1000).toLocaleString()+(e.note?' · '+e.note:''));const b=el('button','撤销误记');b.onclick=async()=>{try{await api('/api/journey-remove',{id:e.id});await loadJourney();}catch(err){notice(err.message,true);}};row.append(b);if(e.kind==='interview'||e.kind==='interview_done'){const next=el('button',e.kind==='interview'?'一起准备面试':'一起复盘');next.onclick=()=>{selectJob(e.job_id);showPage('opportunities');showOpportunity('interview');$('interview-panel').scrollIntoView({behavior:'smooth'});$('interview-notes').focus();};row.append(next);}list.append(row);}
 const facts=$('fact-list');facts.replaceChildren();for(const f of r.facts){const row=el('div',undefined,'version');row.append(el('strong',f.category+' · '+f.id.slice(0,8)),el('p',f.content),el('small','来源：'+f.source));const b=el('button','移除这条事实');b.onclick=async()=>{try{await api('/api/fact-remove',{id:f.id});await refresh();resetPreview();showPage('profile');$('setup').open=true;notice('事实已移除，请重新核对脱敏档案。');}catch(e){notice(e.message,true);}};row.append(b);facts.append(row);}
}
let eventRequest=null,eventSending=false;
form('event-form',async()=>{
 if(eventSending)return;if(!selected)throw Error('请先选择当前岗位');
 const value={job_id:selected,kind:$('event-kind').value,note:$('event-note').value,confirmed:$('event-confirm').checked};
 const signature=JSON.stringify(value);if(eventRequest?.signature!==signature)eventRequest={signature,id:crypto.randomUUID()};
 eventSending=true;try{
  await api('/api/journey-event',{...value,request_id:eventRequest.id});eventRequest=null;$('event-confirm').checked=false;$('event-note').value='';
  await loadJourney();notice(value.kind==='interview'?'邀请已记下，可在下方生成面试准备卡。':'这一步已记下。');

 }finally{eventSending=false;}
});
form('fact-form',async()=>{await api('/api/fact',{category:$('fact-category').value,content:$('fact-content').value,source:$('fact-source').value,confirmed:$('fact-confirm').checked});$('fact-content').value='';$('fact-confirm').checked=false;resetPreview();await refresh();$('setup').open=true;showPage('profile');notice('事实已记入档案，请重新预览确认脱敏内容。');});
action('compare',async()=>{$('compare-output').textContent=(await api('/api/resume-compare',{a:$('compare-a').value,b:$('compare-b').value})).diff;});
action('delete-data',async()=>{const r=await api('/api/data-delete',{confirmation:$('delete-confirm').value});localStorage.removeItem('job-assistant-target');drafts.clear();interviewDrafts.clear();chatDrafts.clear();selected='';notice(r.note);setTimeout(()=>location.reload(),1500);});

action('rest-wish',()=>talk('rest_message',''));

const progressLabels={applied:'已投递',greeting_sent:'已发招呼',interview:'收到面试邀请',interview_done:'面试完成'};
let progressContext=null,progressSaving=false;
function progressButton(label,sourceType,sourceId,kind,jobId){
 const b=el('button',label);b.className='secondary';b.onclick=()=>openProgress(sourceType,sourceId,kind,jobId);return b;
}
function openProgress(sourceType,sourceId,kind,jobId){
 const job=state.jobs.find(j=>j.id===jobId);if(!job){notice('请先选择有效岗位',true);return;}
 progressContext={source_type:sourceType,source_id:sourceId,kind,job_id:jobId};progressSaving=false;
 $('progress-title').textContent='确认：'+progressLabels[kind];$('progress-target').textContent=job.title+' · '+job.company;
 $('progress-description').textContent=sourceType==='version'?'确认你已经在招聘平台投递这份验收简历；下载并不等于投递。':kind==='greeting_sent'?'确认你已经在招聘平台发出了招呼；复制文本不等于发送。':'确认这个岗位的实际面试进展；生成准备卡或复盘不会自动记账。';
 $('progress-feedback').textContent='同一来源的快捷记录只记一次；其他次真实进展可到“记录”页补充。';
 $('progress-confirm').checked=false;$('progress-save').disabled=true;$('progress-cancel').disabled=false;
 $('progress-dialog').showModal();
}
$('progress-confirm').onchange=()=>{$('progress-save').disabled=progressSaving||!$('progress-confirm').checked;};
$('progress-cancel').onclick=()=>{if(!progressSaving)$('progress-dialog').close();};
$('progress-dialog').addEventListener('cancel',e=>{if(progressSaving)e.preventDefault();});
$('progress-dialog').addEventListener('close',()=>{progressContext=null;});
$('progress-save').onclick=async()=>{
 if(progressSaving||!progressContext||!$('progress-confirm').checked)return;
 const ctx={...progressContext};progressSaving=true;$('progress-save').disabled=true;$('progress-cancel').disabled=true;
 try{
  const r=await api('/api/quick-event',{...ctx,confirmed:true});$('progress-dialog').close();await loadJourney();
  notice(r.already_recorded?'这条进展已记录过，未重复计数。':'已记录：'+progressLabels[ctx.kind]+'。可在该机会的记录页撤销误记。');
  if(ctx.kind==='interview'){selectJob(ctx.job_id);showPage('opportunities');showOpportunity('interview');}
 }catch(e){$('progress-feedback').textContent=e.message;}
 finally{progressSaving=false;$('progress-cancel').disabled=false;$('progress-save').disabled=!$('progress-confirm').checked;}
};
