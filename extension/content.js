(() => {
  let previous='', stableSince=Date.now(), previousJob='', identitySince=Date.now();
  let dirty=true, clickedKey=null, clickedAt=0;
  document.addEventListener('click',event=>{
    const card=event.target.closest?.('.job-card-wrapper,.job-card-box,.job-list-box li,.job-list-container li');
    if(!card||card.closest('.job-detail-box,.job-detail-container,.job-detail'))return;
    const ids=[...new Set([...card.querySelectorAll('a[href*="/job_detail/"]')].map(a=>JobAssistantExtractor.identity(a.href)?.job_key).filter(Boolean))];
    if(ids.length===1){clickedKey=ids[0];clickedAt=Date.now();dirty=true;}
  },true);
  // Observe only to invalidate reads; inference and API calls happen in the open side panel.
  new MutationObserver(()=>{dirty=true;}).observe(document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['class','style','hidden','aria-hidden','href']});
  let cached=null, lastURL='';
  chrome.runtime.onMessage.addListener((message,sender,respond)=>{
    if(sender.id!==chrome.runtime.id)return;
    if(message.type==='JA_SNAPSHOT'){
      if(dirty || location.href!==lastURL || !cached){
        cached=JobAssistantExtractor.extract(document,location.href);dirty=false;lastURL=location.href;
      }
      const signature=JSON.stringify(cached);
      if(signature!==previous){previous=signature;stableSince=Date.now();}
      let hint=JobAssistantExtractor.pageIdentity(document,location.href);
      if(clickedKey && Date.now()-clickedAt<5000 && hint.source!=='url' && cached.capture?.job_key!==clickedKey){
        hint={job_key:clickedKey,source:'clicked-card',conflict:true};
      }
      const job=cached.capture?.job_key||hint.job_key||'';
      if(job!==previousJob){previousJob=job;identitySince=Date.now();}
      if(hint.conflict||(hint.job_key&&cached.capture&&hint.job_key!==cached.capture.job_key)){
        respond({status:'incomplete',reason:'正在切换岗位，等待详情与选中卡片同步',stable_ms:0,identity_stable_ms:0,identity:hint,company_capture:cached.company_capture});return;
      }
      respond({...cached,stable_ms:Date.now()-stableSince,identity_stable_ms:Date.now()-identitySince,identity:hint});
    }else if(message.type==='JA_DIAGNOSTICS'){
      respond(JobAssistantExtractor.diagnose(document,location.href));
    }else if(message.type==='JA_SELECTION'){
      // Selection is returned only on an explicit side-panel click. No background chat scraping.
      respond({text:(window.getSelection()?.toString() || '').trim().slice(0,12000),url:location.href});
    }
  });
})();
