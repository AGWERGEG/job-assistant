/* Exported prompts and returned practice results stay local until user shares a file. */
let mockPreview=null,mockJob='',mockPackage=null,mockSignature='',mockBusy=false;
const practice=document.createElement('section');practice.id='mock-interview-panel';practice.className='panel';
practice.append(el('h2','去其他 AI 练一次面试'),el('p','导出已脱敏提示词，在其他 AI 中逐题练习。结束时取回 JSON，预览后存回这个岗位。无需调用当前模型。'));
const exportButton=el('button','生成模拟面试提示词');exportButton.id='mock-export';practice.append(exportButton);
const exportDetails=el('details');exportDetails.append(el('summary','检查将带给外部 AI 的提示词'));
const prompt=el('textarea');prompt.id='mock-prompt';prompt.readOnly=true;prompt.rows=12;prompt.setAttribute('aria-label','已脱敏模拟面试提示词');exportDetails.append(prompt);
const approveLabel=el('label');const approve=el('input');approve.type='checkbox';approve.id='mock-export-confirm';approveLabel.append(approve,document.createTextNode('我已核对脱敏内容，准备手动交给其他 AI'));exportDetails.append(approveLabel);
const download=el('button','下载提示词 .md');download.disabled=true;exportDetails.append(download);practice.append(exportDetails);
const importDetails=el('details');importDetails.append(el('summary','导入练习结果'));
importDetails.append(el('p','只粘贴 AI 最后返回的 JSON 代码块，或选择 UTF-8 的 .json / .txt 文件。练习编号必须属于当前岗位。'));
const file=el('input');file.type='file';file.accept='.json,.txt';file.setAttribute('aria-label','模拟面试结果文件');importDetails.append(file);
const content=el('textarea');content.id='mock-result-input';content.rows=7;content.setAttribute('aria-label','模拟面试结果 JSON');importDetails.append(content);
const previewButton=el('button','预览并检查返回格式');previewButton.id='mock-preview';importDetails.append(previewButton);
const previewBox=el('pre');previewBox.id='mock-result-preview';previewBox.style.whiteSpace='pre-wrap';previewBox.style.overflowWrap='anywhere';importDetails.append(previewBox);
const confirmLabel=el('label');const confirm=el('input');confirm.type='checkbox';confirm.id='mock-import-confirm';confirmLabel.append(confirm,document.createTextNode('已核对目标岗位和练习结果，仅保存为模拟面试记录'));importDetails.append(confirmLabel);
const save=el('button','确认导入');save.id='mock-import';save.disabled=true;importDetails.append(save);practice.append(importDetails);
const feedback=el('p');feedback.id='mock-feedback';feedback.setAttribute('role','status');practice.append(feedback);
const records=el('div');records.id='mock-records';practice.append(records);
document.getElementById('opportunity-interview').prepend(practice);

function resetMockPreview(){mockPreview=null;previewBox.textContent='';confirm.checked=false;save.disabled=true;}
function mockText(result){
 return [result.summary,...[['优点','strengths'],['待改进','improvements'],['下一步','next_steps']].map(([label,key])=>label+'\n'+(result[key]||[]).join('\n')),
 ...(result.turns||[]).map((t,i)=>'第 '+(i+1)+' 轮\n问题：'+t.question+'\n回答：'+(t.answer||'未回答')+'\n反馈：'+t.feedback)].join('\n\n');
}
async function loadMockInterviews(){
 const id=selected;exportButton.disabled=!id||!settings?.ready||mockBusy;previewButton.disabled=!id||mockBusy;
 if(id!==mockJob){mockJob=id;mockPackage=null;prompt.value='';approve.checked=false;download.disabled=true;content.value='';file.value='';resetMockPreview();feedback.textContent='';mockSignature='';exportDetails.open=false;importDetails.open=false;}
 const response=await api('/api/mock-interview/records',{job_id:id});if(selected!==id)return;
 const sig=JSON.stringify(response);if(sig===mockSignature)return;mockSignature=sig;records.replaceChildren();
 for(const r of response.records||[]){const row=el('details');row.className='version';row.append(el('summary','外部 AI 模拟面试 · '+new Date(r.created*1000).toLocaleString()));
  row.append(el('small',(r.stale?'对应旧版档案或岗位。':'')+'练习反馈，不是已确认个人事实；不计入真实面试进展。'));const text=el('pre',mockText(r.result));text.style.whiteSpace='pre-wrap';text.style.overflowWrap='anywhere';row.append(text);records.append(row);}
}
exportButton.onclick=async()=>{if(mockBusy)return;const id=selected;mockBusy=true;exportButton.disabled=true;try{
 const result=await api('/api/mock-interview/export',{job_id:id});if(selected!==id)return;
 mockPackage=result;prompt.value=result.prompt;approve.checked=false;download.disabled=true;exportDetails.open=true;feedback.textContent=result.note;
 }catch(e){feedback.textContent=e.message;}finally{mockBusy=false;loadMockInterviews().catch(()=>{});}};
approve.onchange=()=>{download.disabled=!approve.checked||!mockPackage||mockPackage.job_id!==selected;};
download.onclick=()=>{if(!approve.checked||!mockPackage||mockPackage.job_id!==selected)return;
 const url=URL.createObjectURL(new Blob([mockPackage.prompt],{type:'text/markdown;charset=utf-8'}));const a=el('a');a.href=url;a.download=mockPackage.filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
 feedback.textContent='提示词已下载。把它交给其他 AI，练习结束后将 JSON 带回来。';};
content.oninput=resetMockPreview;
file.onchange=async()=>{const f=file.files[0];if(!f)return;const id=selected;resetMockPreview();try{
 if(f.size>300000)throw Error('结果文件最大 300 KB');const text=await f.text();if(id!==selected)return;content.value=text;feedback.textContent='文件已载入，请点击预览。';
 }catch(e){feedback.textContent=e.message;}};
previewButton.onclick=async()=>{const id=selected;resetMockPreview();try{
 const r=await api('/api/mock-interview/preview',{job_id:id,content:content.value});if(id!==selected)return;mockPreview={...r,source:content.value};
 previewBox.textContent='保存到：'+r.target+'\n'+(r.stale?'注意：档案或岗位已更新，本结果对应导出时资料。\n':'')+r.note+'\n\n'+mockText(r.result);
 feedback.textContent='格式检查通过，请核对预览后确认导入。';
 }catch(e){feedback.textContent=e.message;}};
confirm.onchange=()=>{save.disabled=!confirm.checked||!mockPreview||mockPreview.job_id!==selected;};
save.onclick=async()=>{if(mockBusy||!confirm.checked||!mockPreview||mockPreview.source!==content.value||mockPreview.job_id!==selected)return;
 const p=mockPreview;mockBusy=true;save.disabled=true;try{
 const r=await api('/api/mock-interview/import',{job_id:p.job_id,content:p.source,preview_token:p.preview_token,confirmed:true});
 if(p.job_id!==selected)return;resetMockPreview();feedback.textContent=r.duplicate?'这份结果已导入，没有重复保存。':'已保存模拟面试记录。可在下方展开复盘。';await loadMockInterviews();
 }catch(e){feedback.textContent=e.message;}finally{mockBusy=false;confirm.onchange();}};
