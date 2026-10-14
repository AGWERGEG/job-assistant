function isBackground(kind){return ['tailor_resume','analyze_job','interview_prep','interview_review'].includes(kind);}
const $=id=>document.getElementById(id);
let token='',state=null,settings=null,selected='',previewToken='',pending=false,backgroundPending=false,sending=false,historySignature='',taskSignature='',request=null;
let profileImport=null,profileImportId='';
let chatFactTaskId='',chatFactReturn=false;
let artifacts=[];let referenceTaskId='';const expandedResults=new Set(),expandedArtifacts=new Set();const taskResults=new Map(),taskResultLoads=new Set();
function resultText(result){return result?.primary_output||result?.reply||result?.result_markdown||result?.markdown||result?.summary||'';}
function resultBody(result){const box=el('div',undefined,'result-content');const primary=resultText(result);box.append(window.JobAssistantReply.render(primary));const more=result?.result_markdown||result?.markdown||'';if(more&&more.trim()!==primary.trim()){const detail=el('details',undefined,'result-evidence');detail.append(el('summary','详细依据'),window.JobAssistantReply.render(more));box.append(detail);}return box;}
const drafts=new Map();const interviewDrafts=new Map();const chatDrafts=new Map();let jobsSignature='';
const names={companion_chat:'和搭子聊聊',quick_analysis:'快速判断',analyze_job:'深度分析',tailor_resume:'岗位版简历',suggest_reply:'HR 招呼',rest_message:'休息寄语',closing_message:'入职结语',interview_prep:'面试准备卡',interview_review:'面试复盘'};
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function readableType(kind){return ({tailor_resume:'简历',analyze_job:'分析',quick_analysis:'快速判断',interview_prep:'面试卡',interview_review:'面试复盘',suggest_reply:'HR沟通'}[kind]||'任务');}
function taskDisplayName(t, all=state?.tasks||[]){const label=t.display_name||(()=>{const same=all.filter(x=>x.job_id===t.job_id&&x.kind===t.kind).sort((a,b)=>(a.created||0)-(b.created||0)||String(a.id).localeCompare(String(b.id)));return readableType(t.kind)+' '+(same.findIndex(x=>x.id===t.id)+1);})();return label+' · '+weakDate(t.created);}
function artifactLabel(a){const index=a.display_index||((artifacts.findIndex(item=>item.task_id===a.task_id)+1)||1);const label=a.display_name||(readableType(a.kind)+' '+index);return label+' · '+weakDate(a.created||a.updated);}
function weakDate(value){const time=Number(value);if(!time)return '时间未知';const d=new Date(time*1000);return d.toLocaleDateString(undefined,{month:'2-digit',day:'2-digit'});}
function artifactMeta(a){return '完成于 '+weakDate(a.updated||a.created)+' · '+String(a.preview||'').slice(0,120);}
function selectedArtifact(){return selected&&referenceTaskId?artifacts.find(a=>a.task_id===referenceTaskId):null;}
function renderReference(){const box=$('selected-reference');if(!box)return;const a=selectedArtifact();box.replaceChildren();box.hidden=!a;if(!a){referenceTaskId='';return;}const chip=el('span','引用：'+artifactLabel(a),'reference-chip');chip.title=a.preview||'';const clear=el('button','移除引用','reference-clear');clear.type='button';clear.onclick=()=>{referenceTaskId='';renderReference();};box.append(chip,clear);}
function selectArtifact(a){if(!a||a.status&&a.status!=='done'||!artifacts.some(item=>item.task_id===a.task_id))return;referenceTaskId=a.task_id;renderReference();const input=$('message');if(['/','/引用'].includes(input.value.trim()))input.value='';$('command-menu').hidden=true;input.focus();}
function notice(s,error=false){$('notice').textContent=s;$('notice').className=error?'error':'';$('notice').style.display='block';}
const readCache=new Map();
async function api(path,value){const cacheState=value===undefined&&path==='/api/state?summary=1';const cached=cacheState?readCache.get(path):null;const headers={'X-Local-Token':token};if(cached)headers['If-None-Match']=cached.tag;const r=await fetch(path,value===undefined?{headers}:{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify(value)});if(r.status===304&&cached)return cached.value;const x=await r.json();if(!r.ok)throw Error(x.error||'请求失败');const tag=cacheState?r.headers?.get('ETag'):null;if(tag)readCache.set(path,{tag,value:x});return x;}
function action(id,fn){$(id).onclick=async()=>{try{await fn();}catch(e){notice(e.message,true);}};}
function form(id,fn){$(id).onsubmit=async e=>{e.preventDefault();try{await fn();}catch(e){notice(e.message,true);}};}
function profileValues(){return {name:$('profile-name').value,preferences:$('profile-preferences').value,facts:$('profile-facts').value};}
function resetPreview(){previewToken='';$('privacy-confirm').checked=false;$('privacy-approve').disabled=true;}
const profileImportLabels={advantage:'个人优势',expectations:'期望职位',work:'工作经历',projects:'项目经历',education:'教育经历',certificates:'资格证书',custom:'其他经历'};
function clearProfileImportHash(){const p=new URLSearchParams(location.hash.slice(1));p.delete('resume_import');p.set('page','profile');history.replaceState(null,'','#'+p.toString());}
async function prepareChatFact(taskId){
 const draft=await api('/api/chat-fact-draft',{task_id:taskId});
 chatFactTaskId=draft.task_id;chatFactReturn=false;
 $('fact-category').value='补充';$('fact-content').value=draft.content;
 $('fact-source').value=draft.source;$('fact-confirm').checked=false;
 $('chat-fact-note').hidden=false;$('chat-fact-cancel').hidden=false;
 if(draft.job_id&&state.jobs.some(j=>j.id===draft.job_id))selectJob(draft.job_id);
 showPage('profile');$('facts-panel').open=true;$('fact-content').focus();
 notice(draft.saved?'这段对话已有一条已核对事实；保存将更新同一条记录。':'请核对或修改这段本人经历，然后确认记入档案。');
}
function clearChatFactDraft(){
 chatFactTaskId='';$('chat-fact-note').hidden=true;$('chat-fact-cancel').hidden=true;
 $('fact-content').value='';$('fact-source').value='用户确认';$('fact-confirm').checked=false;
}
async function loadProfileImport(id){
 if(!id||profileImportId===id)return;profileImportId=id;profileImport=null;
 const box=$('resume-import-preview');box.hidden=false;$('resume-import-summary').textContent='正在从本机读取草稿……';$('resume-import-sections').replaceChildren();$('resume-import-warnings').replaceChildren();$('resume-import-confirm').checked=false;$('resume-import-apply').disabled=true;
 try{
  const draft=await api('/api/profile-import-draft',{id});profileImport=draft;
  const sourceLabel=draft.source==='zhaopin-online-resume'?'智联':draft.source==='boss-online-resume'?'BOSS':'本人';document.querySelector('#resume-import-preview .eyebrow').textContent='来自 '+sourceLabel+' 在线简历 · 本地草稿';
  const present=Object.values(draft.content.sections).filter(s=>s.status==='present').length;
  $('resume-import-summary').textContent='已读到 '+present+' 个有内容的栏目。没有内容与未能读取会分开标记；此时尚未改动本地档案。';
  for(const [key,label] of Object.entries(profileImportLabels)){
   const section=draft.content.sections[key];const stateLabel={present:'已读取 '+section.items.length+' 条',empty:'页面显示为空',unavailable:'本次未能读取'}[section.status];
   const row=el('details');row.append(el('summary',label+' · '+stateLabel));if(section.status==='present')row.append(el('pre',section.items.join('\n\n')));$('resume-import-sections').append(row);
  }
  for(const warning of draft.warnings)$('resume-import-warnings').append(el('p',warning,'resume-import-warning'));
  $('resume-import-status').textContent='请对照现有档案与上方导入内容。只有去除空白和常见标点后完全相同的条目会去重；其他内容都会保留并加入编辑器，可能重复的经历请手动核对。';
 }catch(e){profileImportId='';$('resume-import-summary').textContent=e.message;$('resume-import-status').textContent='可以返回对应招聘网站的本人在线简历页重新读取。';}
}
function normalizeResumeSegment(value){return String(value||'').replace(/[\u3000\t\r]+/g,' ').replace(/[•·▪●]/g,' ').replace(/[，、；：]/g,',').replace(/\s+/g,' ').trim().toLowerCase();}
function splitResumeSegments(value){return String(value||'').split(/\n{2,}|\n(?=(?:个人优势|工作经历|项目经历|教育经历|资格证书|其他经历|期望职位)\s*[：:])/).map(s=>s.trim()).filter(Boolean);}
function mergeEditorValue(oldValue,newValue){
 const existing=splitResumeSegments(oldValue),incoming=splitResumeSegments(newValue),normalized=new Set(existing.map(normalizeResumeSegment).filter(Boolean));
 for(const segment of incoming){const n=normalizeResumeSegment(segment);if(!n||normalized.has(n))continue;existing.push(segment);normalized.add(n);}
 return existing.join('\n\n');
}
function enable(){const blank=settings?.readiness?.state==='profile_optional';for(const b of document.querySelectorAll('[data-kind],#deep-analysis')){const kind=b.dataset.kind||'analyze_job';b.disabled=(b.id==='deep-analysis'&&b.dataset.taskId?!selected:!settings?.ready||!selected||(isBackground(kind)?backgroundPending:pending)||sending)||(blank&&!['quick_analysis','companion_chat'].includes(kind));if(blank&&b.disabled&&kind!=='companion_chat')b.title='先补充真实经历后再使用个人化功能';}$('send').disabled=!settings?.ready||pending||sending;$('rest-wish').disabled=$('send').disabled;}
function rolePreview(){const p=settings?.personas?.[$('persona').value];$('role-preview').textContent=p?.hello||'';providerHelp();}
const modelIntents={intent_judgment:'意图判断',daily_chat:'日常聊天',deep_analysis:'深入分析',resume:'简历',interview:'面试',hr:'HR 沟通'};
let pendingConnectionRemoval=null,defaultConnectionTestState='unknown';
function collectTaskModels(){const task_models={};for(const [intent,label] of Object.entries(modelIntents)){const connection_id=document.querySelector(`[data-intent="${intent}"]`)?.value||'',model=document.querySelector(`[data-model-intent="${intent}"]`)?.value.trim()||'';if(connection_id)task_models[intent]={connection_id,model};}return task_models;}
function taskModelsEqual(a,b){return JSON.stringify(a||{})===JSON.stringify(b||{});}
function renderTaskModelPreview(){const preview=$('task-model-preview');if(!preview)return;const next=collectTaskModels(),saved=settings?.task_models||{};if(taskModelsEqual(next,saved)){preview.textContent='当前没有待保存的任务指派变更。';preview.className='settings-preview';return;}const lines=[];for(const intent of Object.keys(modelIntents)){const old=saved[intent],cur=next[intent];if(JSON.stringify(old)===JSON.stringify(cur))continue;const oldLabel=old?((settings.connections||[]).find(c=>c.id===old.connection_id)?.name||old.connection_id)+' · '+old.model:'沿用默认接入';const curLabel=cur?((settings.connections||[]).find(c=>c.id===cur.connection_id)?.name||cur.connection_id)+' · '+(cur.model||'未填写模型'):'沿用默认接入';lines.push(modelIntents[intent]+'：'+oldLabel+' → '+curLabel);}preview.textContent='保存前变更预览：\n'+lines.join('\n');preview.className='settings-preview settings-preview-changed';}
function beginConnectionRemoval(c){pendingConnectionRemoval=c;const assigned=Object.entries(settings?.task_models||{}).filter(([,a])=>a.connection_id===c.id).map(([intent,a])=>modelIntents[intent]+' · '+a.model);$('connection-remove-copy').textContent=assigned.length?'将移除「'+c.name+'」，并清除这些任务的连接指派：'+assigned.join('、')+'。':'将移除「'+c.name+'」。';$('connection-remove-confirm').hidden=false;}
function renderModelConnections(){
 const list=$('connection-list');list.replaceChildren();const conns=settings?.connections||[];
 for(const c of conns){const usages=Object.entries(settings?.task_models||{}).filter(([,a])=>a.connection_id===c.id).map(([intent])=>modelIntents[intent]);const row=el('div',undefined,'connection-row');row.append(el('strong',c.name+' · '+(c.api_model||'未设默认模型')),el('small',c.base_url+' · '+(c.has_api_key?'已保存密钥':'未保存密钥')),el('small','使用任务：'+(usages.length?usages.join('、'):'暂无，未被任务指派')));const b=el('button','编辑连接','secondary');b.type='button';b.onclick=()=>{ $('connection-id').value=c.id;$('connection-name').value=c.name;$('connection-url').value=c.base_url;$('connection-model').value=c.api_model;$('connection-key').value='';$('connection-key-state').textContent=c.has_api_key?'已保存密钥（不会回显）':'尚未保存密钥';$('connection-model-status').textContent='';};const remove=el('button','移除连接','secondary');remove.type='button';remove.onclick=()=>beginConnectionRemoval(c);row.append(b,remove);list.append(row);}
 if(!conns.length)list.append(el('p','尚未添加独立连接。原来的单 API 接入仍可继续使用。','empty'));
 const assignments=$('task-model-assignments');assignments.replaceChildren();for(const [intent,label] of Object.entries(modelIntents)){const row=el('div',undefined,'task-model-row');const name=el('label',label);const sel=document.createElement('select');sel.dataset.intent=intent;sel.append(new Option('沿用默认接入',''));for(const c of conns){const option=new Option(c.name+(c.has_api_key?'':' · 需添加密钥'),c.id);option.disabled=!c.has_api_key;sel.append(option);}const old=settings?.task_models?.[intent];sel.value=old?.connection_id||'';const effective=el('small',old?'已生效：'+((conns.find(c=>c.id===old.connection_id)?.name||old.connection_id)+' · '+old.model):'当前生效：默认模型');name.append(sel,effective);sel.addEventListener('change',()=>{$('task-model-confirm').checked=false;renderTaskModelPreview();});row.append(name);const model=document.createElement('input');model.dataset.modelIntent=intent;model.placeholder='模型名';model.maxLength=200;model.value=old?.model||'';model.addEventListener('input',()=>{$('task-model-confirm').checked=false;renderTaskModelPreview();});row.append(model);assignments.append(row);}renderTaskModelPreview();
}
function renderSettingsStatus(){
 const ready=Boolean(settings?.ready);$('settings-profile-status').textContent=ready?'已确认档案':'尚未完成建档';$('settings-profile-detail').textContent=(settings?.user_name||'未设置昵称')+' · '+(settings?.buddy_name||'小伴')+' · 保存在本机';$('settings-profile-summary').textContent=ready?'档案已确认；修改事实后需要重新核对脱敏。':'先完成个人档案与脱敏确认。';
 const configured=settings?.provider==='codex'||Boolean(settings?.base_url&&settings?.api_model);const apiModel=settings?.provider==='api'?(settings?.api_model||'兼容 API'):'本机 Codex';const modelState=!configured?'未配置':defaultConnectionTestState==='passed'?'本次测试通过':'已保存待测试';$('settings-model-status').textContent=modelState;$('settings-model-detail').textContent=configured?(apiModel+' · 聊天与未单独指派的新任务'):'请填写服务地址和模型名称';$('model-connection-badge').textContent=modelState;
 const paired=Boolean(settings?.extension_paired);$('settings-sidebar-status').textContent=paired?'已连接':'未连接';$('settings-sidebar-detail').textContent=paired?'可读取已确认岗位':'需要在浏览器侧栏完成配对';$('sidebar-connection-badge').textContent=paired?'已连接':'未连接';$('settings-state').textContent=ready?'· 档案已确认':'· 待完成档案';$('connection-count').textContent=(settings?.connections?.length||0)+' 个连接';
}
function fillSettings(){$('search-provider').value=settings.search_provider||'public';$('search-key-state').textContent=settings.search_provider==='tavily'?(settings.has_search_api_key?'Tavily · 已保存密钥，待测试':'Tavily · 未保存密钥'):'免密钥搜索 · 可用性有限';$('search-key-fields').hidden=$('search-provider').value!=='tavily';for(const [id,key] of [['persona','persona'],['buddy-name','buddy_name'],['user-name','user_name'],['stage','stage'],['private-terms','private_terms'],['provider','provider'],['base-url','base_url'],['api-model','api_model']])$(id).value=settings[key]||'';$('json-mode').checked=settings.json_mode;$('stream-mode').checked=settings.stream!==false;$('key-state').textContent=settings.has_api_key?'已保存密钥（不会回显）':'尚未保存密钥';$('api-fields').hidden=settings.provider!=='api';renderModelConnections();renderSettingsStatus();rolePreview();}
async function reloadSettings(){settings=await api('/api/companion');$('brand').textContent=settings.buddy_name||'求职搭子';$('setup-state').textContent=settings.readiness?.state==='profile_optional'?'· 空白档案':settings.ready?'· 已建档':'· '+(settings.readiness?.state==='privacy_required'?'待确认脱敏':'待补充档案');$('greeting').textContent=settings.ready?(settings.user_name?settings.user_name+'，':'')+'今天想一起看看什么？':settings.readiness?.title||'先认识一下，再一起找下一份工作。';$('hello').textContent=settings.personas[settings.persona].hello;renderSettingsStatus();enable();if(typeof renderOnboarding==='function')renderOnboarding(settings.guide);}
function selectJob(id){chatDrafts.set(selected,$('message').value);if($('interview-notes'))interviewDrafts.set(selected,$('interview-notes').value);selected=id||'';resetCompanyResearch(true);referenceTaskId='';renderReference();if(selected&&!state.jobs.some(j=>j.id===selected)){selected='';notice('这个机会不存在或已移除，已回到日常对话。',true);}$('message').value=chatDrafts.get(selected)||'';pending=false;backgroundPending=false;$('interview-notes').value=interviewDrafts.get(selected)||'';localStorage.setItem('job-assistant-target',selected);historySignature='';taskSignature='';request=null;if($('company-panel'))$('company-panel').open=false;const job=state.jobs.find(j=>j.id===selected);for(const k of ['title','company','url','jd','conversation'])$('job-'+k).value=job?.[k]||'';$('chat-title').textContent=job?job.title+' · '+(job.company||'当前岗位'):'和搭子聊聊近况';$('interview-target').textContent=job?'当前目标：'+job.title+' · '+job.company:'先选择一个岗位，再一起准备。';$('job-label').textContent=job?'已确认这个岗位':'日常求职对话';renderJobs();renderTasks();loadHistory().catch(e=>notice(e.message,true));loadVersions().catch(()=>{});loadCompany().catch(()=>{});loadJourney().catch(()=>{});if(typeof loadJobLinks==='function')loadJobLinks().catch(()=>{});renderWorkspaceStatus();enable();if(typeof loadMockInterviews==='function')loadMockInterviews().catch(()=>{});}
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
function waitCopy(start,status,workbench=false,attempts=0){
 const seconds=Math.max(0,Math.floor(Date.now()/1000-(Number(start)||Date.now()/1000)));
 const prefix=attempts>1?'第 '+attempts+' 次尝试 · ':'';
 if(status==='queued')return prefix+'正在排队 · 本次已等待 '+seconds+' 秒';
 if(seconds<15)return prefix+(workbench?'后台任务已交给模型':'已交给模型')+' · 本次已等待 '+seconds+' 秒';
 if(seconds<90)return prefix+'模型正在生成 · 本次已等待 '+seconds+' 秒；部分兼容 API 首段可能需要 30–90 秒';
 return prefix+'模型长请求响应较慢 · 本次已等待 '+seconds+' 秒；可以继续等待或取消任务';
}
function updateWaitLabels(){document.querySelectorAll('[data-wait-start]').forEach(n=>{n.textContent=waitCopy(n.dataset.waitStart,n.dataset.waitStatus,n.dataset.waitWorkbench==='1',Number(n.dataset.waitAttempts||0));});}
async function loadHistory(){
  const id=selected;const r=await api('/api/history',{job_id:id});if(id!==selected)return;pending=r.turns.some(t=>!isBackground(t.kind)&&['queued','running'].includes(t.status));backgroundPending=r.turns.some(t=>isBackground(t.kind)&&['queued','running'].includes(t.status));enable();
  artifacts=r.artifacts||[];
  const sig=JSON.stringify([r.turns,artifacts]);if(sig===historySignature){updateWaitLabels();return;}historySignature=sig;const list=$('messages');const follow=list.dataset.job!==id||list.scrollHeight-list.scrollTop-list.clientHeight<64;const previousTop=list.scrollTop;list.dataset.job=id;list.replaceChildren();
  if(!r.turns.length)list.append(el('p',selected?'这个岗位已经记下了。想先看看适不适合，还是聊聊你的顾虑？':settings?.personas[settings.persona].hello||'我在，慢慢说。','empty'));
  if(artifacts.length){const heading=el('p','已完成的专项结果 · 可展开查看或引用','artifact-heading');list.append(heading);for(const a of artifacts){const card=el('details',undefined,'artifact-card');card.open=expandedArtifacts.has(a.task_id);card.addEventListener('toggle',()=>{if(card.isConnected){if(card.open)expandedArtifacts.add(a.task_id);else expandedArtifacts.delete(a.task_id);}});card.dataset.resultId=a.task_id;card.open=expandedResults.has(a.task_id);card.ontoggle=()=>{if(card.open)expandedResults.add(a.task_id);else expandedResults.delete(a.task_id);};card.append(el('summary',artifactLabel(a)+' · '+(a.stale?'旧版本':'可引用')));card.append(el('small',artifactMeta(a)));const body=el('div',undefined,'artifact-body');body.append(resultBody(a));const ref=el('button','围绕此结果继续聊');ref.type='button';ref.onclick=()=>selectArtifact(a);body.append(ref);card.append(body);list.append(card);}}
  renderReference();
  for(const t of r.turns){const row=el('article',undefined,'turn');row.append(el('p',t.text,'user'));if(t.kind==='companion_chat'&&['done','failed','cancelled'].includes(t.status)){const save=el('button',t.fact_candidate?'可能是新经历 · 核对':'记入经历','fact-from-chat');save.type='button';if(t.fact_candidate)save.classList.add('suggested');save.title='模型只提示核对，不会自动写入档案';save.onclick=()=>prepareChatFact(t.task_id).catch(e=>notice(e.message,true));row.append(save);}let message=t.status==='done'?(t.workbench?(t.kind==='tailor_resume'?'岗位版简历准备好了。':(t.display_name||names[t.kind]||'专业任务')+'已完成。'):t.reply):t.status==='running'&&t.partial?t.partial:t.status==='failed'?t.error:t.status==='cancelled'?'这条任务已经取消。':t.status==='queued'?'收到，正在排队。':t.workbench?'后台任务处理中，你可以继续聊天。':'我正在整理回复。';const reply=t.status==='done'?window.JobAssistantReply.render(message):el('p',message);reply.classList.add('reply');row.append(reply);if(t.status==='done'&&t.workbench&&t.result_markdown){const detail=el('details',undefined,'turn-result');detail.append(el('summary','展开详细内容'));detail.append(resultBody(t));const jump=el('button','在“我的机会”查看','secondary');jump.type='button';jump.onclick=()=>openTask(t.task_id);detail.append(jump);row.append(detail);}if(['queued','running'].includes(t.status)){const wait=el('small','');wait.dataset.waitStart=t.updated||t.created;wait.dataset.waitStatus=t.status;wait.dataset.waitWorkbench=t.workbench?'1':'0';wait.dataset.waitAttempts=t.attempts||0;row.append(wait);}if(t.stale)row.append(el('small','这条回复对应旧资料，更新后可重新提问。'));if(t.workbench&&t.status!=='done'){const b=el('button','在“我的机会”查看');b.className='secondary';b.onclick=()=>openTask(t.task_id);row.append(b);}else if(t.status==='done'&&!t.workbench){const b=el('button','复制回复');b.onclick=()=>copy(t.reply);row.append(b);}if(['queued','running','failed'].includes(t.status)){const cancel=el('button','取消任务');cancel.onclick=()=>taskAction(t.task_id,'cancel');row.append(cancel);if(t.status==='failed'){const retry=el('button','重试');retry.onclick=()=>taskAction(t.task_id,'retry');row.append(retry);}}if(t.status==='done'&&t.kind==='suggest_reply'){row.append(progressButton('我已发出这条招呼','task',t.task_id,'greeting_sent',id));row.append(progressButton('收到面试邀请了','task',t.task_id,'interview',id));}const m=t.metrics;if(m?.total_seconds){let cost='输入 '+(m.prompt_chars||0)+' 字';if(m.input_tokens!==undefined)cost+=' / '+m.input_tokens+' tokens';if(m.output_tokens!==undefined)cost+='，输出 '+m.output_tokens+' tokens';row.append(el('small','总耗时 '+m.total_seconds+' 秒'+(m.first_response_seconds!==undefined?'，首段 '+m.first_response_seconds+' 秒':'')+'（排队 '+m.queue_seconds+' 秒，模型调用 '+m.model_seconds+' 秒；'+cost+'）'));}list.append(row);}
  updateWaitLabels();list.scrollTop=follow?list.scrollHeight:previousTop;$('chat-status').textContent=pending?'模型请求处理中；超过 90 秒仍可继续等待或取消。':backgroundPending?'专业任务在后台处理，可以继续聊天；新消息不会修改已运行任务。':'对话保存在本机，按当前岗位记忆。';
}
function taskResultKey(id,updated){return String(id)+'\n'+String(updated);}
async function loadTaskResult(id,updated){
 const key=taskResultKey(id,updated),task=state?.tasks.find(item=>item.id===id);
 if(taskResults.has(key)||taskResultLoads.has(key)||!task||task.updated!==updated)return;
 taskResultLoads.add(key);
 try{
  const loaded=await api('/api/task-result/'+encodeURIComponent(id));
  const current=state?.tasks.find(item=>item.id===id);
  if(selected!==task.job_id||loaded.task_id!==id||loaded.updated!==updated||!current||current.updated!==updated)return;
  taskResults.set(key,loaded.result);
  taskSignature='';renderTasks();
 }catch(e){if(selected===task.job_id)notice(e.message,true);}
 finally{taskResultLoads.delete(key);}
}
function renderTasks(){
 if(!state)return;
 const tasks=state.tasks.filter(t=>t.job_id===selected&&isBackground(t.kind)&&(opportunityTab==='resume'?t.kind==='tailor_resume':opportunityTab==='interview'?t.kind.startsWith('interview_'):opportunityTab==='overview'?t.kind==='analyze_job':false));
 const sig=JSON.stringify(tasks);if(sig===taskSignature)return;
 const latestCompleted=tasks.find(t=>t.status==='done'&&t.result);
 for(const input of document.querySelectorAll('[data-draft]'))drafts.set(input.dataset.draft,input.value);
 const opened=new Map([...document.querySelectorAll('#task-list>details.task')].map(n=>[n.id,n.open]));taskSignature=sig;const box=$('task-list');box.replaceChildren();
 for(const t of tasks){
  const key=taskResultKey(t.id,t.updated),full=taskResults.get(key),preview=t.result||null;
  const card=el('details',undefined,'task');card.id='task-'+t.id;
  card.addEventListener('toggle',()=>{if(card.open&&t.status==='done'&&preview)loadTaskResult(t.id,t.updated);});
  card.open=opened.get(card.id)??(t===tasks[0]);
  const summary=el('summary');summary.append(el('strong',taskDisplayName(t)),el('small',({queued:'排队中',running:'正在处理',done:'已完成',failed:'处理失败',cancelled:'已取消'})[t.status]+' · '+weakDate(t.created)));card.append(summary);
  if(preview){
   if(preview.decision||preview.summary)card.append(el('p',preview.decision||preview.summary));
   if(full){
    if(t.kind==='tailor_resume'){
     const input=el('textarea');input.dataset.draft=t.id;input.setAttribute('aria-label','核对岗位版简历');input.value=drafts.get(t.id)??full.primary_output??full.markdown??'';input.oninput=()=>drafts.set(t.id,input.value);card.append(input);
     const save=el('button','保存这一版并导出 Word / PDF');save.onclick=async()=>{try{const v=await api('/api/resume-accept',{task_id:t.id,content:input.value});await loadVersions();await openResumeExport(v.id);notice('这一版已保存，请在本机预览回填信息并导出。');}catch(e){notice(e.message,true);}};card.append(save);
    }else {const output=window.JobAssistantReply.render(full.primary_output||full.summary||'');output.className='task-result';card.append(output);}
    if(t.kind.startsWith('interview_')){card.append(el('small','这是面试准备草稿：请核对数字、个人职责、工具和成果。模型可能补写未提供的细节，未经核实不要照读；历史建议也不等于真实经历。'));const b=el('button','复制这张卡');b.onclick=()=>copy(full.primary_output||'');card.append(b);if(full.questions?.length)card.append(el('p','下次可以补充：'+full.questions.join('；')));}
    const detail=el('details');detail.append(el('summary','专业分析与修改依据'),window.JobAssistantReply.render(full.markdown||''));card.append(detail);
   }else if(card.open)card.append(el('small','正在载入这份完整成果…'));
   const link=el('a','下载任务 Markdown');link.href='/api/export/'+t.id;link.download=true;card.append(link);
   const read=el('button',t.viewed?'设为待查看':'我已查看这份结果');read.className='secondary';read.onclick=async()=>{try{await api('/api/result-viewed',{task_id:t.id,result_updated:t.updated,viewed:!t.viewed});await refresh();notice(t.viewed?'已设为待查看。':'已标为查看，不会改变验收或求职进展。');}catch(e){notice(e.message,true);}};card.append(read);
   if(t.kind==='analyze_job'&&t===latestCompleted){const rerun=el('button','重新分析','secondary');rerun.onclick=()=>talk('analyze_job');card.append(rerun);}
   if(t.kind==='interview_prep'){card.append(progressButton('我收到面试邀请了','task',t.id,'interview',t.job_id));card.append(progressButton('这场面试已完成','task',t.id,'interview_done',t.job_id));}
   if(t.kind==='interview_review')card.append(progressButton('这场面试已完成','task',t.id,'interview_done',t.job_id));
  }else if(t.status==='failed'){card.append(el('p',t.error_text));const retry=el('button','重试');retry.onclick=()=>taskAction(t.id,'retry');card.append(retry);}
  if(['queued','running','failed'].includes(t.status)){const cancel=el('button','取消任务');cancel.onclick=()=>taskAction(t.id,'cancel');card.append(cancel);}
  if(t.metrics?.total_seconds){let cost=' · 输入 '+(t.metrics.prompt_chars||0)+' 字';if(t.metrics.input_tokens!==undefined)cost+=' / '+t.metrics.input_tokens+' tokens';if(t.metrics.output_tokens!==undefined)cost+=' · 输出 '+t.metrics.output_tokens+' tokens';card.append(el('small','耗时 '+t.metrics.total_seconds+' 秒 · 模型调用 '+t.metrics.model_seconds+' 秒'+cost));}
  const details=el('details');details.append(el('summary','查看脱敏发送内容'));const pre=el('pre','展开后载入本地预览');details.ontoggle=async()=>{if(details.open){try{pre.textContent=(await api('/api/task-preview',{task_id:t.id})).prompt;}catch(e){pre.textContent=e.message;}}};card.append(details);box.append(card);if(card.open&&t.status==='done'&&preview)loadTaskResult(t.id,t.updated);
 }
 if(!tasks.length)box.append(el('p',opportunityTab==='resume'?'还没有岗位简历。回到聊天点击优化简历，完成后在这里核对。':opportunityTab==='interview'?'填写上方面试信息，生成准备卡或复盘。':'需要更详细判断时，在聊天页点击“深入分析”。','empty'));
}
async function taskAction(id,verb){try{await api('/api/tasks/'+id+'/'+verb,{});await refresh();}catch(e){notice(e.message,true);}}
async function refresh(){state=await api('/api/state?summary=1');renderJobs();renderTasks();await reloadSettings();await loadHistory();await loadCompany();await loadJourney();renderWorkspaceStatus();if(typeof loadMockInterviews==='function')await loadMockInterviews();}
async function talk(kind,override){
  if(sending||(isBackground(kind)?backgroundPending:pending))return;const input=kind.startsWith('interview_')?$('interview-notes'):$('message');const text=override===undefined?input.value.trim():override;if(kind==='companion_chat'&&!text)return;sending=true;enable();
  try{const job=selected;const reference=kind==='companion_chat'&&referenceTaskId&&selectedArtifact()?.task_id===referenceTaskId?referenceTaskId:'';const identity=JSON.stringify([job,kind,text,reference]);if(request?.identity!==identity)request={identity,id:crypto.randomUUID()};const r=await api('/api/talk',{kind,text,job_id:job,request_id:request.id,reference_task_id:reference||undefined});if(selected===job){if(override===undefined)input.value='';renderReference();request=null;await refresh();renderWorkspaceStatus();}notice(isBackground(kind)?'后台任务已记下，完成后在工作台查看；我们可以继续聊天。':'收到，回复会留在这段对话里。');return r;}catch(e){notice(e.message,true);return null;}finally{sending=false;enable();}
}
async function onboardingAction(action,value={},force=true){const r=await api('/api/onboarding',{action,...value});settings=r;if(!['back','continue','connection-settings'].includes(action))fillSettings();renderOnboarding(settings.guide,force);return r;}
async function guideContinue(){if(settings?.guide?.active)await onboardingAction('continue',{},true);}
async function skipOnboarding(){
 await api('/api/onboarding',{action:'skip'});
 pairingRequested=false;pairingBaseline=null;sessionStorage.removeItem('job-assistant-pairing-revision');
 const p=new URLSearchParams(location.hash.slice(1));p.delete('pairing');p.delete('onboarding');
 await reloadSettings();const next=settings.ready?'settings':(settings.readiness?.page||'profile');p.set('page',next);history.replaceState(null,'','#'+p.toString());renderOnboarding(settings.guide,true);showPage(next,false);if(next==='profile')$('setup').open=true;else $('connections').open=true;
 notice('已退出首次引导，资料仍保留。'+(settings.readiness?.copy||'请完成本地档案后再开始分析岗位。'));
}
async function returnToBoss(){if(settings.extension_paired===false){pairingRequested=true;renderOnboarding(settings.guide,true);notice('先连接招聘侧栏，配对完成后再回 BOSS。');return;}window.open('https://www.zhipin.com/web/geek/job-recommend/','_blank','noopener,noreferrer');try{await guideContinue();await reloadSettings();notice('请在 BOSS 招聘页继续；如果浏览器拦截了新标签页，可点击下方链接。');}catch(e){notice(e.message,true);}}
async function finishOnboarding(){window.open('https://www.zhipin.com/web/geek/job-recommend/','_blank','noopener,noreferrer');await onboardingAction('complete',{},true);notice('首次引导完成，可以在 BOSS 招聘页继续看岗位。');}
function renderCommands(){const box=$('command-menu');if(!box)return;box.replaceChildren();
  box.append(el('p','引用已有专项成果（选择后会显示已选结果）','command-menu-heading'));
  for(const a of artifacts){const b=el('button',undefined,'command-artifact');b.type='button';b.setAttribute('role','option');b.append(el('strong',artifactLabel(a)+' · 引用'),el('small',artifactMeta(a)));b.onclick=()=>selectArtifact(a);box.append(b);}
  box.hidden=false;
}
$('message')?.addEventListener('input',()=>{if(['/','/引用'].includes($('message').value.trim()))renderCommands();else if($('command-menu'))$('command-menu').hidden=true;});
$('message')?.addEventListener('keydown',e=>{const box=$('command-menu');if(!box||box.hidden)return;if(e.key==='Escape'){box.hidden=true;e.preventDefault();}else if(e.key==='Enter'&&!e.ctrlKey&&!e.metaKey){const b=box.querySelector('button');if(b){b.click();e.preventDefault();}}});
form('identity-form',async()=>{const guideStep=settings?.guide?.step;await api('/api/companion',{persona:$('persona').value,buddy_name:$('buddy-name').value,user_name:$('user-name').value,stage:$('stage').value});resetPreview();await reloadSettings();if(guideStep==='persona')await onboardingAction('persona');notice('称呼记下了。接着保存档案并核对脱敏内容。');});
$('persona').onchange=rolePreview;
form('profile-form',async()=>{await api('/api/profile',profileValues());resetPreview();await refresh();await guideContinue();if(settings?.guide?.active){renderOnboarding(settings.guide,true);}else{showPage('profile');$('setup').open=true;}notice(settings.ready?'本地档案已保存，已有脱敏确认仍有效。':'本地档案已保存，请预览脱敏结果。');});
$('resume-import-confirm').onchange=()=>{$('resume-import-apply').disabled=!profileImport||!$('resume-import-confirm').checked;};
$('resume-import-apply').onclick=()=>{try{if(!profileImport||!$('resume-import-confirm').checked)throw Error('请先核对并确认读取范围');const editor=profileImport.editor;if(!$('profile-name').value.trim()&&editor.name)$('profile-name').value=editor.name;$('profile-preferences').value=mergeEditorValue($('profile-preferences').value,editor.preferences);$('profile-facts').value=mergeEditorValue($('profile-facts').value,editor.facts);resetPreview();$('resume-import-status').textContent='已加入编辑器，但还没有保存。只有空白和常见标点处理后完全相同的条目会自动去重；相似内容均已保留。请在下方对照检查，再保存本地档案。';$('resume-import-apply').disabled=true;clearProfileImportHash();$('profile-facts').focus();}catch(e){$('resume-import-status').textContent=e.message;}};
$('resume-import-dismiss').onclick=()=>{profileImport=null;profileImportId='';$('resume-import-preview').hidden=true;clearProfileImportHash();notice('这份本地草稿没有加入档案，原有资料保持不变。');};
for(const id of ['profile-name','profile-preferences','profile-facts','private-terms','user-name'])$(id).addEventListener('input',resetPreview);
$('use-template').textContent='使用空白模板，先看岗位';
action('use-template',async()=>{if($('profile-facts').value.trim())throw Error('已有经历内容，请直接编辑；空白模板不会覆盖你的草稿。');await api('/api/onboarding',{action:'blank-profile'});$('profile-facts').removeAttribute('required');$('profile-facts').value='';$('use-template').textContent='已使用空白模板 · 随时补充经历';resetPreview();await reloadSettings();notice('已进入空白档案模式。请核对脱敏预览，然后可以先分析岗位。');});
$('resume-file').onchange=async()=>{try{const f=$('resume-file').files[0];if(!f)return;if(f.size>5*1024*1024)throw Error('文件不能超过 5 MB');const base64=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=reject;r.readAsDataURL(f);});const r=await api('/api/documents',{name:f.name,base64});if(r.extracted)$('profile-facts').value+=($('profile-facts').value?'\n\n':'')+r.extracted;$('import-status').textContent=r.extracted?'已在本地提取，请核对后保存档案。':'未提取到文字：'+r.extraction_status+'。可粘贴简历文本。';resetPreview();}catch(e){notice(e.message,true);}};
action('privacy-preview',async()=>{if(JSON.stringify(profileValues())!==JSON.stringify({name:state.profile.name,preferences:state.profile.preferences,facts:state.profile.facts}))throw Error('经历有未保存修改，请先保存本地档案');await api('/api/companion',{private_terms:$('private-terms').value});const r=await api('/api/privacy-preview',{});previewToken=r.token;$('privacy-output').textContent=JSON.stringify(r.preview,null,2);$('privacy-note').textContent=r.note;$('privacy-confirm').checked=false;$('privacy-approve').disabled=true;await reloadSettings();});
$('privacy-confirm').onchange=()=>{$('privacy-approve').disabled=!previewToken||!$('privacy-confirm').checked;};
action('privacy-approve',async()=>{const guiding=settings?.guide?.active,fromChatFact=chatFactReturn;await api('/api/privacy-approve',{token:previewToken,confirmed:$('privacy-confirm').checked});chatFactReturn=false;await reloadSettings();if(guiding)await guideContinue();$('setup').open=false;if(guiding){renderOnboarding(settings.guide,true);notice(settings.extension_paired?'档案已确认。接下来切回 BOSS，打开一个感兴趣的岗位。':'档案已确认。先连接侧栏，再回 BOSS 看岗位。');}else if(fromChatFact){await refresh();showPage('chat');notice('这条经历已写入本机已确认事实，下一轮对话与分析会读取它。');}else{showPage('settings');$('connections').open=true;notice('档案已确认。可以继续使用搭子。');}});
function providerHelp(){const useAPI=$('provider').value==='api';$('api-fields').hidden=!useAPI;$('provider-help').textContent=useAPI?'填入服务商提供的地址、模型名称和 API 密钥。保存后发送一次测试，成功才继续。支持 Chat Completions 兼容接口。':'已通过 Codex 部署并登录？选择这一项，无需填写 API 密钥。这里会检查 CLI 登录凭据，实际任务再验证网络与额度。若提示未登录，请在终端运行 codex login。';}
$('provider').onchange=providerHelp;
let savingProvider=false;
form('provider-form',async()=>{if(savingProvider)return;savingProvider=true;$('save-provider').disabled=true;const guideStep=settings?.guide?.step;try{defaultConnectionTestState='unknown';await api('/api/companion',{provider:$('provider').value,base_url:$('base-url').value,api_model:$('api-model').value,api_key:$('api-key').value,json_mode:$('json-mode').checked,stream:$('stream-mode').checked,clear_api_key:$('clear-key').checked});$('api-key').value='';$('clear-key').checked=false;await reloadSettings();$('key-state').textContent=settings.has_api_key?'密钥已保存在本机':'未保存密钥';if(guideStep==='connection'){$('connection-status').textContent='正在测试真实聊天传输模式……';const r=await api('/api/connection-test',{});if(r.ok!==true)throw Error(r.message||'连接未通过，请检查接入方式后重试');$('connection-status').textContent=r.message;await reloadSettings();fillSettings();await onboardingAction('connection');notice('接入检查通过。现在选一个合拍的搭子。');}else notice('接入方式已保存。');}catch(e){$('connection-status').textContent=e.message;throw e;}finally{savingProvider=false;$('save-provider').disabled=false;}});
action('connection-remove-no',()=>{pendingConnectionRemoval=null;$('connection-remove-confirm').hidden=true;});
action('connection-remove-yes',async()=>{if(!pendingConnectionRemoval)return;const c=pendingConnectionRemoval;const task_models=Object.fromEntries(Object.entries(settings.task_models||{}).filter(([,assignment])=>assignment.connection_id!==c.id));await api('/api/companion',{connections:(settings.connections||[]).filter(item=>item.id!==c.id),task_models});pendingConnectionRemoval=null;$('connection-remove-confirm').hidden=true;if($('connection-id').value===c.id)$('connection-reset').click();await reloadSettings();fillSettings();notice('已移除连接，并清除了引用它的任务指派。');});
action('connection-reset',()=>{$('connection-id').value='';$('connection-name').value='';$('connection-url').value='';$('connection-model').value='';$('connection-key').value='';$('connection-key-state').textContent='';$('connection-model-status').textContent='';$('connection-model-list').replaceChildren(new Option('获取列表后选择',''));});
action('connection-save',async()=>{const id=$('connection-id').value||('conn_'+(crypto.randomUUID?.().replaceAll('-','')||Date.now().toString(36)));const conns=[...(settings.connections||[])];const item={id,name:$('connection-name').value,base_url:$('connection-url').value,api_model:$('connection-model').value,api_key:$('connection-key').value};const ix=conns.findIndex(c=>c.id===id);if(ix>=0)conns[ix]=item;else conns.push(item);await api('/api/companion',{connections:conns});$('connection-key').value='';await reloadSettings();fillSettings();$('connection-id').value=id;$('connection-name').value=item.name;$('connection-url').value=item.base_url;$('connection-model').value=item.api_model;$('connection-key-state').textContent=(settings.connections.find(c=>c.id===id)?.has_api_key?'密钥已保存在本机':'尚未保存密钥');notice('连接已保存在本机。');});
action('connection-fetch-models',async()=>{const id=$('connection-id').value;if(!id){$('connection-model-status').textContent='请先保存连接后再获取模型列表。';return;}const saved=(settings.connections||[]).find(c=>c.id===id);if(!saved||saved.base_url!==$('connection-url').value.replace(/\/$/,'')){$('connection-model-status').textContent='地址有变化，请先保存连接，再获取模型列表。';return;}try{$('connection-model-status').textContent='正在获取模型列表…';const r=await api('/api/models',{connection_id:id});const sel=$('connection-model-list');sel.replaceChildren(new Option('选择一个模型',''));for(const m of r.models)sel.append(new Option(m,m));$('connection-model-status').textContent=r.models.length?'已读取 '+r.models.length+' 个模型。也可以手动填写。':'服务商未返回模型；可以手动填写模型名。';}catch(e){$('connection-model-status').textContent=e.message+' 可以手动填写模型名。';}});
$('connection-model-list').addEventListener('change',()=>{if($('connection-model-list').value)$('connection-model').value=$('connection-model-list').value;});
action('task-model-save',async()=>{const task_models=collectTaskModels();for(const [intent,label] of Object.entries(modelIntents)){if(task_models[intent]&&!task_models[intent].model)throw Error(label+'需要填写模型名称');}if(taskModelsEqual(task_models,settings.task_models||{})){notice('没有新的任务模型指派变更。');return;}if(Object.keys(task_models).length&&!$('task-model-confirm').checked)throw Error('请先确认所选连接会接收对应任务的脱敏职业信息');await api('/api/companion',{task_models,task_models_confirmed:$('task-model-confirm').checked});$('task-model-confirm').checked=false;await reloadSettings();fillSettings();notice('任务模型指派已保存。');});
action('test-connection',async()=>{$('connection-status').textContent='正在测试真实聊天传输模式…';try{const r=await api('/api/connection-test',{});defaultConnectionTestState=r.ok===true?'passed':'failed';$('connection-status').textContent=r.message;await reloadSettings();fillSettings();}catch(e){defaultConnectionTestState='failed';$('connection-status').textContent=e.message;}});
$('search-provider').onchange=()=>{$('search-key-fields').hidden=$('search-provider').value!=='tavily';$('search-status').textContent='更改尚未保存。';};
action('save-search',async()=>{const provider=$('search-provider').value;if(provider==='tavily'&&!$('search-api-key').value.trim()&&!settings.has_search_api_key&&!$('clear-search-key').checked)throw Error('请填写 Tavily 搜索密钥，或选择免密钥来源');await api('/api/companion',{search_provider:provider,search_api_key:$('search-api-key').value,clear_search_api_key:$('clear-search-key').checked});$('search-api-key').value='';$('clear-search-key').checked=false;await reloadSettings();fillSettings();$('search-status').textContent='搜索接入已保存，尚未测试。';});
action('test-search',async()=>{if(($('search-provider').value!==settings.search_provider&&!(settings.search_provider===undefined&&$('search-provider').value==='public'))||$('search-api-key').value||$('clear-search-key').checked)throw Error('先保存搜索接入，再测试已保存的来源');const button=$('test-search');button.disabled=true;$('search-status').textContent='正在查询固定公开公司…';try{const r=await api('/api/search-test',{});$('search-status').textContent=r.message;if(r.ok)$('search-key-state').textContent=(settings.search_provider==='tavily'?'Tavily':'免密钥搜索')+' · 本次测试通过';}catch(e){$('search-status').textContent=e.message;}finally{button.disabled=false;}});
action('restart-onboarding',async()=>{await onboardingAction('restart');notice('首次引导已重新打开；已有档案和设置不会被删除。');});
let pairingCode='',pairingExpires=0;
let pairRequestId='';
async function loadPairRequest(id){
 pairRequestId=id||'';const card=$('pair-request-card'),fallback=$('pairing-default');
 if(!pairRequestId){card.hidden=true;fallback.hidden=false;return;}
 try{const r=await api('/api/pair-request-info',{request_id:pairRequestId});card.hidden=false;fallback.hidden=true;$('pair-request-copy').textContent='侧栏 '+r.extension_hint+' 正在申请连接。批准后，它能读取已保存岗位、相关聊天原话和建议成果，并按你的明确请求发起模型任务；不能读取模型密钥、原始简历附件或任意本机文件。';$('pair-request-confirm').checked=false;$('pair-request-confirm').closest('label').hidden=false;$('pair-request-approve').hidden=false;$('pair-request-approve').disabled=true;showPage('settings',false);$('connections').open=true;}catch(e){pairRequestId='';card.hidden=true;fallback.hidden=false;notice(e.message,true);}
}
$('pair-request-confirm').onchange=()=>$('pair-request-approve').disabled=!$('pair-request-confirm').checked;
action('pair-request-approve',async()=>{const r=await api('/api/pair-request-approve',{request_id:pairRequestId,confirmed:$('pair-request-confirm').checked});$('pair-request-copy').textContent='连接成功。现在可以回到 BOSS 侧栏，那里会自动继续。';$('pair-request-confirm').closest('label').hidden=true;$('pair-request-approve').hidden=true;pairingRequested=false;await reloadSettings();notice('侧栏已连接，可以返回 BOSS 继续。');});
action('extension-code',async()=>{const r=await api('/api/extension-code',{});pairingCode=r.code;pairingExpires=Date.now()+r.expires_in*1000;pairingRequested=true;pairingBaseline=String(settings?.extension_pairing_revision||0);sessionStorage.setItem('job-assistant-pairing-revision',pairingBaseline);const p=new URLSearchParams(location.hash.slice(1));p.set('pairing','1');history.replaceState(null,'','#'+p.toString());$('pair-code').textContent=pairingCode;$('copy-pair-code').hidden=false;renderOnboarding(settings.guide,true);});
action('copy-pair-code',async()=>{if(Date.now()>=pairingExpires)throw Error('配对码已过期，请重新生成');await navigator.clipboard.writeText(pairingCode);notice('已复制。粘贴到侧栏的配对码栏，再点击“连接”。');});
action('extension-revoke',async()=>{await api('/api/extension-revoke',{});pairingCode='';$('copy-pair-code').hidden=true;$('pair-code').textContent='连接已撤销。';await reloadSettings();});
action('general-chat',async()=>{selectJob('');showPage('chat');});
action('new-job',async()=>{selectJob('');showPage('opportunities');showOpportunity('materials');$('job-editor').open=true;$('job-title').focus();});
form('job-form',async()=>{const value={};for(const k of ['title','company','url','jd','conversation'])value[k]=$('job-'+k).value;if(selected)value.id=selected;const j=await api('/api/jobs',value);state=await api('/api/state?summary=1');selectJob(j.id);showPage('opportunities');showOpportunity('overview');$('job-editor').open=false;notice('岗位已确认，后续对话会记在这里。');});
form('chat-form',async()=>talk('companion_chat'));
document.querySelectorAll('[data-kind]').forEach(b=>b.onclick=()=>talk(b.dataset.kind));
$('deep-analysis').onclick=async()=>{try{const id=$('deep-analysis').dataset.taskId;if(id)openTask(id);else await talk('analyze_job');}catch(e){notice(e.message,true);}};action('refresh',refresh);
$('message').onkeydown=e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();talk('companion_chat');}};
function followHash(){const p=new URLSearchParams(location.hash.slice(1));if(p.get('pairing')==='1')pairingRequested=true;if(p.get('pair_request')){pairingRequested=true;loadPairRequest(p.get('pair_request'));return;}if(p.has('job'))selectJob(p.get('job'));if(p.get('fact_task')){prepareChatFact(p.get('fact_task')).catch(e=>notice(e.message,true));return;}if(p.get('resume_import')){showPage('profile',false);$('setup').open=true;loadProfileImport(p.get('resume_import')).catch(e=>notice(e.message,true));return;}if(settings.guide?.active||pairingRequested){renderOnboarding(settings.guide,true);return;}if(p.get('task')){openTask(p.get('task'));return;}const view=p.get('view');if(['interview','journey'].includes(view)){showPage('opportunities',false);showOpportunity(view==='journey'?'records':'interview',false);}else{showPage(p.get('page')||'chat',false);showOpportunity(p.get('tab')||'overview',false);}if(p.get('onboarding')==='1'){showPage('settings',false);$('connections').open=true;}else if(!settings.ready){showPage('profile',false);$('setup').open=true;}}
window.addEventListener('hashchange',followHash);
(async()=>{const accessParams=new URLSearchParams(location.hash.slice(1));const access=accessParams.get('access');let session;if(access){token=access;accessParams.delete('access');history.replaceState(null,'',location.pathname+location.search+(accessParams.size?'#'+accessParams.toString():''));session=await api('/api/session',{});}else session=await api('/api/session');token=session.token;$('runtime-badge').textContent='v'+session.version+' · '+(session.execution==='codex-worker'?'搭子已连接':'手动处理模式');state=await api('/api/state?summary=1');await reloadSettings();fillSettings();for(const k of ['name','preferences','facts'])$('profile-'+k).value=state.profile[k]||'';if(settings.guide_profile_skipped)$('profile-facts').removeAttribute('required');$('setup').open=!settings.ready;selectJob(state.jobs.some(j=>j.id===localStorage.getItem('job-assistant-target'))?localStorage.getItem('job-assistant-target'):'');followHash();await loadJourney();if(session.execution!=='codex-worker')notice('当前未启动自动处理，请用 launch.py 启动，或通过 Codex 手动领取任务。');let polling=false,lastPoll=0;setInterval(()=>{if(document.hidden)return;updateWaitLabels();const interval=pending||backgroundPending?1000:5000;if(polling||Date.now()-lastPoll<interval)return;polling=true;lastPoll=Date.now();refresh().catch(()=>{$('chat-status').textContent='与本机工作台连接中断。记录仍在本机；请从启动器重新打开工作台。';}).finally(()=>{polling=false;});},1000);})().catch(e=>notice(e.message,true));

let companyResearchPreview=null,companyResearchGeneration=0,companyResearchBinding=null;
const companySourceNames={public_web_page:'公开网页',public_search_excerpt:'搜索摘要',saved_company_material:'已保存公司资料',company_introduction:'公司介绍',introduction:'公司介绍',products:'产品与业务',recruitment:'招聘概况',peer_job:'同公司岗位'};
function researchSourceName(value){return companySourceNames[value]||'公开材料';}
function researchBinding(){const job=state?.jobs.find(j=>j.id===selected);return job?JSON.stringify([job.id,job.revision,job.company,job.url]):'';}
async function discardResearch(preview,jobId){if(preview?.preview_id&&jobId)try{await api('/api/company-research-discard',{job_id:jobId,preview_id:preview.preview_id});}catch(e){/* Expired previews already cannot be saved. */}}
function resetCompanyResearch(discard=false){
 if(discard)discardResearch(companyResearchPreview,companyResearchBinding?.jobId);
 companyResearchGeneration++;companyResearchPreview=null;companyResearchBinding=null;
 const area=$('company-research'),preview=$('company-research-preview'),formEl=$('company-research-form');
 if(area)area.hidden=true;if(preview)preview.hidden=true;if(formEl)formEl.hidden=false;
 if($('company-research-open'))$('company-research-open').hidden=!selected;
 if($('company-research-question'))$('company-research-question').value='';if($('company-research-url'))$('company-research-url').value='';
 if($('company-research-submit')){$('company-research-submit').disabled=false;$('company-research-submit').textContent='获取公开资料';}
 if($('company-research-confirm'))$('company-research-confirm').disabled=true;
 if($('company-research-sources'))$('company-research-sources').replaceChildren();
 if($('company-research-warnings'))$('company-research-warnings').textContent='';
 if($('company-research-status'))$('company-research-status').textContent='';
}
function renderCompanyResearchPreview(result){
 companyResearchPreview=result;
 const preview=$('company-research-preview'),formEl=$('company-research-form'),list=$('company-research-sources');
 if(!preview||!list)return;
 formEl.hidden=true;preview.hidden=false;list.replaceChildren();
 const newSources=(result.sources||[]).filter(source=>source.already_saved!==true).length,savedSources=(result.sources||[]).length-newSources;
 $('company-research-summary').textContent=(result.company_name||'当前公司')+' · '+(newSources?`新增 ${newSources} 条来源，尚未保存。请核对公司身份与原文。`:(savedSources?'没有新增来源，以下材料已保存在当前岗位。':'没有取得可用来源。可稍后重试或提供企业官网公开链接。'));
 for(const source of result.sources||[]){
  const card=el('article',undefined,'company-research-source');
  card.append(el('strong',source.title||source.url||'公开来源'),el('small',(source.already_saved?'已保存 · ':'')+researchSourceName(source.source_type)+' · 来源陈述，待核对'+(source.observed_at?' · '+weakDate(source.observed_at):'')));
  if(source.excerpt){const excerpt=el('details');excerpt.append(el('summary','查看来源内容'),el('p',source.excerpt));card.append(excerpt);}
  try{const u=new URL(source.url);if(u.protocol==='https:'&&!u.username&&!u.password){const link=el('a','打开原始来源');link.href=u.href;link.target='_blank';link.rel='noopener noreferrer';card.append(link);}}catch(e){}
  list.append(card);
 }
 $('company-research-warnings').textContent=(result.warnings||[]).join('；');
 $('company-research-confirm').disabled=!newSources||!result.preview_id;
 $('company-research-status').textContent=newSources?'新增来源仅保留在本次研究中；确认后才加入该岗位的公司材料。':'本轮没有待保存的新来源，已保存的材料可继续用于讨论。';
}
function setupCompanyResearch(){
 const open=$('company-research-open'),area=$('company-research'),formEl=$('company-research-form'),cancel=$('company-research-cancel'),discard=$('company-research-discard'),confirm=$('company-research-confirm');
 if(!open||open.dataset.ready)return;open.dataset.ready='1';
 open.onclick=()=>{if(!selected)return notice('先选择一个岗位，再研究它的公司。',true);area.hidden=false;open.hidden=true;$('company-research-question').focus();};
 const close=()=>resetCompanyResearch(true);cancel.onclick=close;discard.onclick=close;
 formEl.onsubmit=async e=>{
  e.preventDefault();if(!selected)return notice('请先选择一个岗位。',true);
  const question=$('company-research-question').value.trim();if(!question)return notice('写下你想了解的产品、业务或公司背景。',true);
  const sourceUrl=$('company-research-url').value.trim();const public_urls=sourceUrl?[sourceUrl]:undefined;
  const jobId=selected,binding=researchBinding(),generation=++companyResearchGeneration,button=$('company-research-submit');
  companyResearchBinding={jobId,binding};button.disabled=true;button.textContent='正在获取…';$('company-research-status').textContent='正在读取已保存材料并检索公开来源，通常需要几秒。你可以取消。';
  try{
   const result=await api('/api/company-research',{job_id:jobId,question,allow_network:true,public_urls});
   if(generation!==companyResearchGeneration||jobId!==selected||binding!==researchBinding()){await discardResearch(result,jobId);return;}
   renderCompanyResearchPreview(result);
  }catch(err){if(generation===companyResearchGeneration){notice(err.message,true);$('company-research-status').textContent='这次未取得预览，请检查网络后重试。';}}
  finally{if(generation===companyResearchGeneration){button.disabled=false;button.textContent='获取公开资料';}}
 };
 confirm.onclick=async()=>{
  if(!companyResearchPreview?.preview_id||!companyResearchBinding)return;
  const {jobId,binding}=companyResearchBinding;if(jobId!==selected||binding!==researchBinding()){resetCompanyResearch(true);return notice('岗位资料已变化，请重新研究后再核对保存。',true);}
  const generation=companyResearchGeneration;confirm.disabled=true;
  try{await api('/api/company-research-confirm',{job_id:jobId,preview_id:companyResearchPreview.preview_id,confirmed:true});if(generation!==companyResearchGeneration||selected!==jobId)return;companySignature='';resetCompanyResearch();await loadCompany();notice('已保存到该岗位的公司资料。后续对话和新任务可使用这些来源。');}
  catch(err){if(generation===companyResearchGeneration){notice(err.message,true);confirm.disabled=false;}}
 };
}
let companySignature='';
async function loadCompany(){
 setupCompanyResearch();
 if(companyResearchBinding&&companyResearchBinding.binding!==researchBinding())resetCompanyResearch(true);
 const id=selected;const r=await api('/api/company',{job_id:id});if(id!==selected)return;
 const signature=JSON.stringify([id,r]);if(signature===companySignature)return;companySignature=signature;
 const box=$('company-evidence');box.replaceChildren();const c=r.company;const summary=$('company-summary');
 $('company-research-open').hidden=!id||!$('company-research').hidden;
 if(!c){const job=state.jobs.find(j=>j.id===id);summary.textContent='公司与业务背景 · '+(job?.company||'未选择岗位');box.append(el('p',id?'还没有公司材料。可以直接研究这家公司，无需先去侧栏抓取。':'请先选择一个岗位。'));return;}
 summary.textContent='公司与业务背景 · '+c.name+' · '+c.evidence.length+' 条';
 box.append(el('p','已保存 '+c.evidence.length+' 条公开材料。新任务会选取相关材料；保存的正文或摘录可在这里查看。'));
 if(!c.evidence.length)box.append(el('p','公司已关联，还没有保存介绍或对照岗位。'));
 const kinds={introduction:'公司介绍',products:'产品与业务',recruitment:'招聘概况',peer_job:'同公司岗位参考',research:'公开研究资料'};
 for(const kind of Object.keys(kinds)){
  const entries=c.evidence.filter(e=>e.kind===kind);if(!entries.length)continue;const group=el('details',undefined,'company-group');group.append(el('summary',kinds[kind]+' · '+entries.length));
  for(const e of entries){
   const title=e.kind==='peer_job'?(e.title||'岗位参考'):e.kind==='recruitment'?'已加载 '+(e.jobs?.length||0)+' 个岗位卡片':e.kind==='research'?(e.title||'公开来源摘录'):kinds[e.kind];
   const d=el('details',undefined,'version company-material');d.append(el('summary',title));
   d.append(el('small',(e.label||(e.kind==='research'?researchSourceName(e.source_type):'招聘页表述'))+' · 资料 '+e.id.slice(0,8)+' · '+new Date(e.observed*1000).toLocaleString()+(e.partial?' · 内容可能折叠/截断':'')));
   if(e.text)d.append(el('pre',e.text));if(e.kind==='research')d.append(el('small',researchSourceName(e.source_type)+' · 来源陈述，待核对'));
   if(e.excerpt&&!e.text)d.append(el('pre',e.excerpt));
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
form('fact-form',async()=>{
 const fromChat=Boolean(chatFactTaskId);
 await api('/api/fact',{category:$('fact-category').value,content:$('fact-content').value,source:$('fact-source').value,confirmed:$('fact-confirm').checked,chat_task_id:chatFactTaskId||undefined});
 chatFactReturn=fromChat;clearChatFactDraft();resetPreview();await refresh();
 if(settings.ready){chatFactReturn=false;showPage(fromChat?'chat':'profile');notice('这条经历已在已确认档案中，未重复保存。');return;}
 await api('/api/companion',{private_terms:$('private-terms').value});
 const preview=await api('/api/privacy-preview',{});
 previewToken=preview.token;$('privacy-output').textContent=JSON.stringify(preview.preview,null,2);$('privacy-note').textContent=preview.note;
 $('setup').open=true;showPage('profile');
 notice('事实已存入本机。请核对脱敏预览并点击“确认档案”，之后的新对话和分析才会使用它。');
});
$('chat-fact-cancel').onclick=()=>{clearChatFactDraft();notice('这段聊天没有记入已确认经历。');};
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
