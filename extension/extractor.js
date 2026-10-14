/* Pure read-only DOM adapter. No private API, network interception, cookies or clicks. */
(function(root){
  function visible(node){
    if(!node || !node.isConnected || node.closest('[hidden],[aria-hidden="true"]'))return false;
    for(let p=node;p;p=p.parentElement){const style=p.ownerDocument.defaultView.getComputedStyle(p);if(style.display==='none'||style.visibility==='hidden')return false;}
    return node.getClientRects().length>0;
  }
  function nodes(scope,selector){return Array.from(scope.querySelectorAll(selector)).filter(visible);}
  function text(node){
    // Text walker avoids hidden anti-copy nodes without importing their text into the prompt.
    if(!node)return '';
    const chunks=[];const walker=node.ownerDocument.createTreeWalker(node,4);
    for(let item=walker.nextNode();item;item=walker.nextNode()){
      let parent=item.parentElement, ok=true;
      while(parent){const style=parent.ownerDocument.defaultView.getComputedStyle(parent);if(parent.matches('script,style,[hidden],[aria-hidden="true"]')||style.display==='none'||style.visibility==='hidden'){ok=false;break;}if(parent===node)break;parent=parent.parentElement;}
      if(ok && item.textContent.trim())chunks.push(item.textContent.trim());
    }
    return chunks.join('\n').replace(/\u00a0/g,' ').trim();
  }
  function oneText(scope,selectors){for(const selector of selectors){const found=nodes(scope,selector);if(found.length===1 && text(found[0]))return text(found[0]);}const doc=scope.ownerDocument||scope;if(selectors.some(s=>s.includes('company'))&&genericSite(doc.location?.href)==='zhaopin'&&/\/jobdetail\//.test(doc.location.pathname)){const m=(doc.title||'').match(/招聘_(.+?)招聘\s*-\s*智联招聘/);if(m?.[1])return m[1].trim();}return '';}
  const headingText=n=>text(n).replace(/[\s:：]/g,'');
  function companyIdentity(href){try{const u=new URL(href);if(u.protocol!=='https:')return null;if(['www.zhipin.com','zhipin.com'].includes(u.hostname)){const m=u.pathname.match(/^\/gongsi\/(?:job\/(?:\d+\/)?)?([A-Za-z0-9_~\-]{4,200})\.html$/);return m?{source_site:'boss',company_key:m[1],company_url:'https://www.zhipin.com/gongsi/'+m[1]+'.html'}:null;}if(['www.zhaopin.com','zhaopin.com'].includes(u.hostname)){const m=u.pathname.match(/^\/companydetail\/([^/]+)\.(?:htm|html)$/i)||u.pathname.match(/^\/companydetail\/jobs-([^/]+)\/?$/i);if(!m||m[1].length>180)return null;const raw=m[1];return {source_site:'zhaopin',company_key:'zhaopin:'+raw,company_url:'https://www.zhaopin.com/companydetail/'+raw+'.htm'};}return null;}catch{return null;}}
  function genericSite(href){try{const u=new URL(href);if(u.protocol!=='https:')return null;const h=u.hostname.toLowerCase();if(h==='zhaopin.com'||h.endsWith('.zhaopin.com'))return 'zhaopin';if(h==='58.com'||h.endsWith('.58.com'))return '58';return null;}catch{return null;}}
  function genericIdentity(href){const site=genericSite(href);if(!site)return null;const u=new URL(href);const path=u.pathname;let raw='';if(site==='zhaopin'){const detail=path.match(/\/jobdetail\/([A-Za-z0-9._~-]{4,200})\.(?:html?|htm)$/i);if(detail)raw=detail[1];else{const position=path.match(/\/(?:position|job)\/([A-Za-z0-9._~-]{4,200})(?:\/|\.(?:html?|htm)|$)/i);if(!position)return null;raw=position[1];}}else{const legacy=path.match(/\/zp[^/]+\/([A-Za-z0-9_-]{8,200})\.(?:shtml?|html?)$/i);if(legacy)raw=legacy[1];else{if(!/(job|zhaopin|detail)[\/_-]/i.test(path))return null;raw=path.split('/').filter(Boolean).at(-1)||'';}}raw=raw.replace(/\.(?:html?|shtml?)$/i,'').replace(/[^A-Za-z0-9._~-]/g,'_');if(raw.length<4)return null;return {site,job_key:raw.slice(0,200),url:u.origin+u.pathname};}
  function uniqueCompany(scope,site){
    const links=nodes(scope,'a').filter(a=>{try{const u=new URL(a.href);return site==='58'?u.hostname==='qy.58.com'&&/^\/\d+\/?$/.test(u.pathname):(u.hostname==='zhaopin.com'||u.hostname.endsWith('.zhaopin.com'))&&/^\/companydetail\/(?!jobs-).+\.htm(?:l)?$/.test(u.pathname);}catch{return false;}});
    const values=[...new Set(links.map(text).filter(v=>v.length>=2&&v.length<=300&&!/^\d+$|个在招职位/.test(v)))];
    return values.length===1?values[0]:'';
  }
  function companyReference(scope,site){
    if(site!=='zhaopin')return null;
    const links=nodes(scope,'a[href*="/companydetail/"]').map(a=>({identity:companyIdentity(a.href),name:text(a)})).filter(x=>x.identity?.source_site===site&&x.name.length>=2&&x.name.length<=300);
    const ids=[...new Set(links.map(x=>x.identity.company_key))],names=[...new Set(links.map(x=>x.name))];
    if(ids.length!==1||names.length!==1)return null;
    return {...links[0].identity,name:names[0]};
  }
  function genericJob(doc,href){
    const site=genericSite(href);let id=genericIdentity(href),title='',company='',body='',companyRef=null;
    const roots=nodes(doc,'.job-detail-modules__detail');
    const pos=nodes(doc,'.pos_info');
    if(site==='zhaopin'&&roots.length){
      if(roots.length!==1)return {status:'ambiguous',reason:'存在多个智联岗位详情，等待页面稳定'};
      const scope=roots[0];
      const links=[...new Map(nodes(scope,'a').map(a=>genericIdentity(a.href)).filter(x=>x?.site===site).map(x=>[x.job_key,x])).values()];
      if(links.length>1||(id&&links.length===1&&id.job_key!==links[0].job_key))return {status:'ambiguous',reason:'岗位链接冲突，未采集'};
      id=id||links[0];
      const summaries=nodes(scope,'.job-detail-modules__summary-wrap');
      if(summaries.length===1){
        title=oneText(summaries[0],['.job-detail-summary__title-text']);
        companyRef=companyReference(summaries[0],site)||companyReference(scope,site);
        company=companyRef?.name||uniqueCompany(summaries[0],site)||uniqueCompany(scope,site);
      }
      const cards=nodes(scope,'.job-detail-card').filter(c=>nodes(c,'h3').some(h=>headingText(h)==='职位描述'));
      if(cards.length===1){const bodies=nodes(cards[0],'.job-detail-card__body');if(bodies.length===1)body=text(bodies[0]);}
    }else if(site==='58'&&pos.length){
      if(pos.length!==1)return {status:'ambiguous',reason:'存在多个58岗位详情，等待页面稳定'};
      title=oneText(pos[0],['.pos_name']);
      company=uniqueCompany(doc,site);
      const bodies=nodes(doc,'.pos_description .posDes');if(bodies.length===1)body=text(bodies[0]);
    }else{
      // Older simple layouts: require explicit headings and identity, never scan
      // nearby recruiter text or pick the largest container on the entire page.
      let scope=doc;
      const heads=nodes(doc,'h2,h3,h4,dt').filter(h=>/^(职位描述|岗位职责|工作内容|岗位详情|职位详情)$/.test(headingText(h)));
      if(heads.length===1){
        if(!id&&site==='zhaopin'){
          for(let p=heads[0].parentElement;p&&p!==doc.body;p=p.parentElement){
            const links=[...new Map(nodes(p,'a').map(a=>genericIdentity(a.href)).filter(x=>x?.site===site).map(x=>[x.job_key,x])).values()];
            if(links.length>1)break;
            if(links.length===1){id=links[0];scope=p;break;}
          }
        }
        for(let n=heads[0].nextElementSibling;n;n=n.nextElementSibling){
          if(n.matches('h1,h2,h3,h4,dt'))break;
          if(visible(n)&&text(n).length>=40){body=text(n);break;}
        }
      }
      title=oneText(scope,['.job-name','.job-title','.position-name','.position-title','h1']);
      if(!title){const hs=nodes(scope,'h2').filter(h=>!heads.includes(h));if(hs.length===1)title=text(hs[0]);}
      company=oneText(scope,['.company-name','.corp-name'])||uniqueCompany(scope,site);
    }
    if(!id)return {status:'unavailable',reason:'未定位到智联或58的唯一岗位详情'};
    if(!title||!company||body.length<40||body.length>50000)return {status:'incomplete',reason:'岗位标题、公司或职位正文未完整定位，未采集'};
    const capture={...id,title:title.slice(0,200),company:company.slice(0,300),jd:body,method:'dom',source_site:site};
    if(companyRef)Object.assign(capture,{company_key:companyRef.company_key,company_url:companyRef.company_url});
    return {status:'ready',capture,adapter:site+'-dom-v2'};
  }
  function identity(href){try{const u=new URL(href);if(!['www.zhipin.com','zhipin.com'].includes(u.hostname)||u.protocol!=='https:')return null;const m=u.pathname.match(/^\/job_detail\/([A-Za-z0-9_-]{4,200})\.html$/);return m?{job_key:m[1],url:`https://www.zhipin.com/job_detail/${m[1]}.html`}:null;}catch{return null;}}
  function matchingCard(doc,id,scope){
    // Resolve a card by its actual detail link, never by its position or the first title.
    const links=nodes(doc,'a[href*="/job_detail/"]').filter(a=>!scope.contains(a) && identity(a.href)?.job_key===id.job_key && text(a) && !/查看更多|查看详情/.test(text(a)));
    const titles=[...new Set(links.map(text))];
    if(titles.length!==1)return null;
    let company='';
    for(const link of links){
      for(let p=link.parentElement;p && p!==doc.body;p=p.parentElement){
        if(p.contains(scope))break;
        const ids=new Set(nodes(p,'a[href*="/job_detail/"]').map(a=>identity(a.href)?.job_key).filter(Boolean));
        if(ids.size!==1)break;
        const companies=nodes(p,'a[href*="/gongsi/"]').map(text).filter(Boolean);
        if(companies.length===1){company=companies[0];break;}
      }
      if(company)break;
    }
    return {title:titles[0],company};
  }
  function selectedCard(doc,id,scope){
    const cards=nodes(doc,'.job-card-wrapper,.job-card-box,.job-list-box li,.job-list-container li,.job-list-container [class*="job-card"]');
    const matches=[];
    for(const card of cards){
      if(card.contains(scope))continue;
      const ids=[...new Set(nodes(card,'a[href*="/job_detail/"]').map(a=>identity(a.href)?.job_key).filter(Boolean))];
      if(ids.length!==1 || ids[0]!==id.job_key)continue;
      const title=oneText(card,['.job-name','.job-title','a[href*="/job_detail/"]']);
      const company=oneText(card,['.company-name','a[href*="/gongsi/"]']);
      const chosen=card.matches('.selected,.active,.cur,.current,[aria-selected="true"]') || !!card.querySelector('.selected,.active,.cur,.current,[aria-selected="true"]');
      matches.push({title,company,chosen});
    }
    const preferred=matches.filter(x=>x.chosen);
    const pool=preferred.length===1?preferred:matches;
    return pool.length===1 && pool[0].title?pool[0]:null;
  }
  function detailTitleNear(heading,scope){
    const candidates=[];
    const box=scope.closest('.job-detail-box') || scope.querySelector('.job-detail-box');
    const header=box?.querySelector('.job-detail-header') || scope.querySelector('.job-detail-header');
    if(header)candidates.push(oneText(header,['.job-name','.job-title','h1','h2','h3']));
    const body=heading.parentElement;
    if(body){
      candidates.push(oneText(body,['.job-name','.job-title']));
      const prev=body.previousElementSibling;if(prev)candidates.push(oneText(prev,['.job-name','.job-title','h1','h2','h3']),text(prev));
    }
    return candidates.filter(t=>t && t!=='职位描述').sort((a,b)=>a.length-b.length)[0] || '';
  }
  function uniqueDescription(candidates){
    const unique=[];
    for(const node of candidates){
      const value=text(node).replace(/\s+/g,' ').trim();
      if(!value)continue;
      const duplicate=unique.find(item=>{
        const prior=text(item).replace(/\s+/g,' ').trim();
        return item.contains(node)&&prior.includes(value)||node.contains(item)&&value.includes(prior);
      });
      if(!duplicate)unique.push(node);
      else if(node.contains(duplicate)&&!duplicate.contains(node))unique[unique.indexOf(duplicate)]=node;
    }
    return unique.length===1?unique[0]:null;
  }
  function directDescription(doc){
    // Independent 2026 pages do not always put .job-detail-section under
    // .job-detail. Treat the section class as authoritative and keep the
    // salary/company blocks out of the candidate set.
    const all=nodes(doc,'.job-sec-text,.job-detail-description,p.desc')
      .filter(n=>text(n).length>=40)
      .filter(n=>!n.closest('.salary-info,.company-info-box'));
    const structural=all.filter(n=>n.closest('.job-detail-section'));
    const structuralBody=uniqueDescription(structural);
    if(structuralBody)return {body:structuralBody,heading:null,scope:structuralBody.parentElement};
    if(structural.length)return {ambiguous:true};
    const uniqueBody=uniqueDescription(all);
    if(uniqueBody)return {body:uniqueBody,heading:null,scope:uniqueBody.parentElement};
    const ambiguous=all.length>1;
    const headings=nodes(doc,'h1,h2,h3,h4,[role="heading"],.title').filter(n=>headingText(n)==='职位描述');
    if(headings.length!==1)return null;
    const heading=headings[0];
    // Prefer a legacy text block in the same card/body as the semantic heading.
    for(let p=heading.parentElement;p && p!==doc.body;p=p.parentElement){
      const blocks=nodes(p,'.job-sec-text,.job-detail-description,p.desc').filter(n=>text(n).length>=40);
      if(blocks.length===1)return {body:blocks[0],heading,scope:p};
      if(blocks.length>1){
        const after=blocks.filter(n=>heading.compareDocumentPosition(n)&4);
        if(after.length===1)return {body:after[0],heading,scope:p};
      }
      if(p.matches('.job-detail,.job-detail-box,.job-detail-body,section,article'))break;
    }
    // Some independent pages put the text as the immediate sibling without the old class.
    for(let n=heading.nextElementSibling;n;n=n.nextElementSibling){
      if(!visible(n))continue;if(n.matches('h1,h2,h3,h4'))break;
      if(text(n).length>=40)return {body:n,heading,scope:heading.parentElement};
    }
    return ambiguous?{ambiguous:true}:null;
  }
  function directCompany(doc){
    const selectors=['.job-detail .company-info-box a[href*="/gongsi/"]','.company-info-box a[href*="/gongsi/"]','.sider-company .company-info a','.company-info .company-name','.company-name','a[href*="/gongsi/"]'];
    // Resolve each scoped tier before considering wider page links. Footer
    // recommendations must never make a known employer name ambiguous.
    for(const selector of selectors){
      const names=[...new Set(nodes(doc,selector).map(text).filter(t=>t&&t.length<=300&&!/查看|公司介绍|公司主页|全部职位/.test(t)))];
      if(names.length===1)return names[0];
    }
    return '';
  }
  function semanticDetail(doc,direct=null){
    // The 2026 split list view exposes a 职位描述 heading and a 查看更多信息 link,
    // but not the old job-detail / job-sec-text classes. Anchor only to this section.
    const headings=nodes(doc,'h1,h2,h3,h4,[role="heading"]').filter(n=>headingText(n)==='职位描述');
    if(headings.length!==1)return null;
    const heading=headings[0];let scope=null, id=direct;
    if(direct){scope=heading.parentElement;}
    for(let p=heading.parentElement;!scope && p && p!==doc.body;p=p.parentElement){
      const more=nodes(p,'a[href*="/job_detail/"]').filter(a=>/^(查看更多信息|查看职位详情|查看完整职位)$/.test(text(a)));
      const ids=[...new Map(more.map(a=>identity(a.href)).filter(Boolean).map(i=>[i.job_key,i])).values()];
      if(ids.length>1)return null;
      if(ids.length===1){scope=p;id=ids[0];break;}
    }
    if(!scope || !id)return null;
    let card=direct?{title:oneText(doc,['.job-banner .name h1','.job-banner h1','h1']),company:directCompany(doc)}:(selectedCard(doc,id,scope)||matchingCard(doc,id,scope));
    const companyPage=companyIdentity(doc.location?.href||'');
    if(companyPage&&card&&!card.company)card.company=oneText(doc,['.company-banner h1','.company-info h1','h1']).replace(/招聘$/,'');
    if(direct && !card.company){
      const links=nodes(doc,'a[href*="/gongsi/"]');
      const names=[...new Set(links.map(text).filter(t=>t && !/查看|公司介绍|公司主页/.test(t)))];
      if(names.length===1)card.company=names[0];
    }
    if(!card?.title)return {status:'incomplete',reason:'已找到职位描述，但没有匹配到同一岗位卡片，请稍候或打开完整详情'};
    // Exact visible title inside detail must agree with the link's matching card.
    const detailBox=scope.closest('.job-detail-box') || scope.querySelector('.job-detail-box');
    const detailHeader=detailBox?.querySelector('.job-detail-header') || scope.querySelector('.job-detail-header') || null;
    const renderedTitle=detailTitleNear(heading,scope);
    // The ID relationship is authoritative. A non-empty, materially different title
    // is a switch-in-progress signal; truncated list titles are accepted.
    if(renderedTitle&&!direct){
      const compact=s=>s.replace(/[\s.…\.。·（）()\-—_]/g,'').toLowerCase();
      const a=compact(renderedTitle),b=compact(card.title);
      if(a && b && !a.includes(b) && !b.includes(a))return {status:'incomplete',reason:'详情标题与选中岗位正在同步，等待切换完成'};
      if(a.length>=b.length && renderedTitle.length<=200 && !renderedTitle.includes('\n'))card.title=renderedTitle;
    }
    let body=nodes(scope,'p.desc,.job-sec-text,.job-detail-description').filter(n=>text(n).length>=40&&!n.closest('.salary-info,.company-info-box'))[0] || null;
    for(let start=heading;start && start!==scope && !body;start=start.parentElement){
      for(let next=start.nextElementSibling;next;next=next.nextElementSibling){
        if(!visible(next))continue;
        if(next.matches('h1,h2,h3,h4') || nodes(next,'a[href*="/job_detail/"],a[href*="/gongsi/"]').length)break;
        const txt=text(next);
        if(txt.length>=40 && /职责|要求|负责|工作内容|岗位描述/.test(txt)){body=next;break;}
        if(txt.length>20000)break;
      }
    }
    if(!body)return {status:'incomplete',reason:'已定位岗位，但职责正文仍在加载，请稍候'};
    let company=card.company;
    // If the list truncates the company, resolve a detail-side recruiter line only
    // when its prefix agrees; never copy the recruiter's personal name.
    if(!company || /\.\.\.|…/.test(company)){
      const prefix=company.replace(/\.\.\.|…/g,'').trim();
      const names=nodes(scope,'div,span,p').map(text).filter(t=>t.length<120 && /^[^\n]+\s[·•]\s[^\n]+$/.test(t)).map(t=>t.split(/[·•]/)[0].trim()).filter(t=>!prefix || t.startsWith(prefix));
      const unique=[...new Set(names)];if(unique.length===1)company=unique[0];
    }
    if(!company)return {status:'incomplete',reason:'已识别正文，未找到同一岗位公司名，请打开完整详情'};
    let jd=text(body);
    // Custom salary fonts expose private-use glyphs, not digits. Do not invent a mapping.
    if(/[\uE000-\uF8FF]/.test(jd))return {status:'incomplete',reason:'正文含无法可靠解码的字体字符，请使用选中文字预览核对'};
    const conditions=detailHeader && !detailHeader.contains(body) && text(detailHeader).length<500 ? text(detailHeader) : '';
    const safeConditions=conditions && !/[\uE000-\uF8FF]/.test(conditions) ? conditions : '';
    const recruiter=oneText(scope,['.job-boss-info .name','.boss-info .name','.job-boss .name'])
      .replace(/\s+(?:在线|离线)\s*$/,'').trim();
    return {status:'ready',capture:{...id,title:card.title.slice(0,200),company:company.slice(0,300),jd:[safeConditions,jd].filter(Boolean).join('\n').slice(0,50000),method:'dom',...(recruiter&&recruiter.length<=100?{recruiter_name:recruiter}:{})},adapter:direct?'boss-detail-semantic':'boss-split-semantic'};
  }
  const resumeLabels={advantage:'个人优势',expectations:'期望职位',work:'工作经历',projects:'项目经历',education:'教育经历',certificates:'资格证书',custom:'自定义添加'};
  const zhaopinResumeLabels=new Set(['个人优势','求职意向','工作／实习经历','工作/实习经历','工作经历','实习经历','教育经历','项目经历','培训经历','语言能力','专业技能','获得证书','证书']);
  const zhaopinResumeFields={advantage:['个人优势'],expectations:['求职意向'],work:['工作／实习经历','工作/实习经历','工作经历','实习经历'],projects:['项目经历'],education:['教育经历'],certificates:['获得证书','证书'],custom:['培训经历','语言能力','专业技能']};
  const allResumeHeadingLabels=new Set([...Object.values(resumeLabels),...zhaopinResumeLabels]);
  function resumeLabel(value){return String(value||'').replace(/[\s:：]/g,'').replace(/[／]/g,'/');}
  function zhaopinResumeNodes(doc,label){
    const wanted=resumeLabel(label),found=[],walker=doc.createTreeWalker(doc.body,4);
    for(let item=walker.nextNode();item;item=walker.nextNode()){
      if(resumeLabel(item.textContent)!==wanted)continue;
      let node=item.parentElement;if(!node||zhaopinResumeExcluded(node)||!visible(node))continue;
      // Prefer the largest exact-text wrapper (usually the title div), without
      // climbing into a section whose body happens to contain only the label.
      while(node.parentElement&&node.parentElement!==doc.body&&resumeLabel(text(node.parentElement))===wanted)node=node.parentElement;
      if(!found.includes(node))found.push(node);
    }
    return found;
  }
  function zhaopinResumeStructure(doc,href){
    try{const u=new URL(href);if(u.protocol!=='https:'||u.hostname!=='i.zhaopin.com'||u.pathname!=='/resume')return null;}catch{return null;}
    const result=[],walker=doc.createTreeWalker(doc.body,4);
    for(let item=walker.nextNode();item;item=walker.nextNode()){
      const label=item.textContent.replace(/\u00a0/g,' ').replace(/\s+/g,' ').trim();
      if(!zhaopinResumeLabels.has(label))continue;
      const node=item.parentElement;if(!node||!visible(node))continue;
      const chain=[];
      for(let p=node,depth=0;p&&p!==doc.body&&depth<5;p=p.parentElement,depth++){
        chain.push({tag:p.tagName,classes:[...p.classList].slice(0,8),role:p.getAttribute('role')||'',children:[...p.children].slice(0,10).map(c=>({tag:c.tagName,classes:[...c.classList].slice(0,6)})),chars:text(p).length});
        if(p.matches('main,section,article,[role="main"]'))break;
      }
      result.push({label,chain});if(result.length>=30)break;
    }
    return result;
  }
  function resumeSite(href){try{const u=new URL(href);if(u.protocol!=='https:')return '';if(['www.zhipin.com','zhipin.com'].includes(u.hostname)&&u.pathname.replace(/\/$/,'')==='/web/geek/resume')return 'boss';if(u.hostname==='i.zhaopin.com'&&u.pathname.replace(/\/$/,'')==='/resume')return 'zhaopin';return '';}catch{return '';}}
  function resumePage(href){return !!resumeSite(href);}
  function resumeExcluded(node){return !!node.closest('aside,footer,.resume-nav,.resume-sidebar,.side-bar,.attachment,.resume-attachment,.resume-diagnosis,.diagnosis,.privacy-setting,.resume-privacy,[class*="attachment"],[class*="diagnosis"],[class*="privacy"]');}
  function zhaopinResumeExcluded(node){
    // On Zhaopin, the real resume sections use diagnosis-scroll classes.
    // The jobs-bar is the duplicate section navigation, not resume content.
    return !!node.closest('aside,footer,[class*="jobs-bar"],.resume-nav,.resume-sidebar,.side-bar,.attachment,.resume-attachment,.resume-diagnosis,.diagnosis,.privacy-setting,.resume-privacy,[class*="attachment"],[class*="privacy"]');
  }
  function resumeHeadings(doc,label){return nodes(doc,'h1,h2,h3,h4,[role="heading"]').filter(n=>headingText(n)===label.replace(/[\s:：]/g,'')&&!resumeExcluded(n));}
  function resumeScope(doc,heading){
    const labels=allResumeHeadingLabels;let best=null;
    for(let p=heading.parentElement,depth=0;p&&p!==doc.body&&depth<6;p=p.parentElement,depth++){
      if(resumeExcluded(p))break;
      const content=text(p);const inside=nodes(p,'h1,h2,h3,h4,[role="heading"]').filter(n=>labels.has(resumeLabel(text(n)))).length;
      if(inside===1&&content.length>text(heading).length&&content.length<60000){best=p;if(p.matches('section,article,li,[class*="resume-item"],[class*="resume-section"],[class*="resume-module"]')||p.querySelector('ul,ol'))break;}
      if(inside>1)break;
    }
    return best;
  }
  function cleanResumeText(value,label){
    value=value.replace(/\u00a0/g,' ').trim();
    if(value.startsWith(label))value=value.slice(label.length).trim();
    return value.replace(/^(编辑|添加|修改)\s*/,'').trim();
  }
  function cleanZhaopinResumeText(value,label){
    const lines=value.replace(/\u00a0/g,' ').split(/\n+/)
      .map(line=>line.replace(/[\uE000-\uF8FF]/g,'').trim());
    if(resumeLabel(lines[0])===resumeLabel(label))lines.shift();
    return lines
      .filter(line=>line&&!/^(?:必填|编辑|修改|展开|收起|查看全部|添加.{0,16})$/.test(line))
      .join('\n').trim();
  }
  function resumeSection(doc,key){
    const label=resumeLabels[key];const heads=resumeHeadings(doc,label);
    if(heads.length!==1)return {status:'unavailable',items:[]};
    const heading=heads[0],scope=resumeScope(doc,heading);
    if(!scope)return {status:'empty',items:[]};
    let candidates=nodes(scope,'li').filter(n=>!n.parentElement?.closest('li')&&!resumeExcluded(n));
    if(!candidates.length)candidates=[...scope.children].filter(n=>n!==heading&&!n.contains(heading)&&visible(n)&&!resumeExcluded(n));
    let items=candidates.map(n=>cleanResumeText(text(n),label)).filter(Boolean);
    if(!items.length){const fallback=cleanResumeText(text(scope),label);if(fallback)items=[fallback];}
    items=[...new Set(items)]
      .filter(value=>value.length<=12000&&!/\*{3,}/.test(value))
      .filter(value=>key!=='custom'||!/展示你的|自定义添加/.test(value))
      .slice(0,50);
    return items.length?{status:'present',items}:{status:'empty',items:[]};
  }
  function zhaopinResumeSection(doc,key){
    const labels=zhaopinResumeFields[key]||[],found=[],seenHead=new Set();
    for(const label of labels){
      const heads=zhaopinResumeNodes(doc,label);
      if(heads.length>1)return {status:'unavailable',items:[]};
      if(heads.length&&!seenHead.has(heads[0])){found.push({label,heading:heads[0]});seenHead.add(heads[0]);}
    }
    if(!found.length)return {status:'unavailable',items:[]};
    const allHeads=[];for(const label of zhaopinResumeLabels)for(const head of zhaopinResumeNodes(doc,label))if(!allHeads.includes(head))allHeads.push(head);
    const items=[];let sawScope=false;
    for(const item of found){
      let scope=null;
      for(let p=item.heading.parentElement,depth=0;p&&p!==doc.body&&depth<8;p=p.parentElement,depth++){
        if(zhaopinResumeExcluded(p))break;
        const recognized=allHeads.filter(h=>p.contains(h)).length;
        const value=text(p);
        if(recognized===1&&value.length>text(item.heading).length&&value.length<60000){scope=p;if(p.matches('section,article,li,[class*="resume-item"],[class*="resume-section"],[class*="resume-module"]')||p.querySelector('ul,ol'))break;}
        if(recognized>1)break;
      }
      if(!scope)continue;sawScope=true;
      const itemSelector=key==='work'?'.job-exp-pre-item':key==='expectations'?'.wanna-title__job-container':'';
      let candidates=itemSelector?nodes(scope,itemSelector).filter(n=>!zhaopinResumeExcluded(n)):[];
      if(!candidates.length)candidates=nodes(scope,'li').filter(n=>!n.parentElement?.closest('li')&&!zhaopinResumeExcluded(n));
      if(!candidates.length)candidates=[...scope.children].filter(n=>!n.contains(item.heading)&&visible(n)&&!zhaopinResumeExcluded(n));
      let values=candidates.map(n=>cleanZhaopinResumeText(text(n),item.label)).filter(Boolean);
      if(!values.length){const fallback=cleanZhaopinResumeText(text(scope),item.label);if(fallback)values=[fallback];}
      for(const value of values){if(value.length<=12000&&!/\*{3,}/.test(value)&&!items.includes(value))items.push(value);}
    }
    if(items.length)return {status:'present',items:items.slice(0,50)};
    return sawScope?{status:'empty',items:[]}:{status:'unavailable',items:[]};
  }
  function resumeName(doc){
    const title=resumeHeadings(doc,'我的在线简历')[0];const end=resumeHeadings(doc,resumeLabels.advantage)[0];
    if(!title)return '';
    const candidates=nodes(doc,'[class*="name"],h1,strong').filter(n=>{
      if(resumeExcluded(n)||n===title||n.contains(title))return false;
      const after=!!(title.compareDocumentPosition(n)&4);const before=!end||!!(n.compareDocumentPosition(end)&4);
      const value=text(n);return after&&before&&value.length>=2&&value.length<=40&&!value.includes('\n')&&!/[\d*@]/.test(value)&&!Object.values(resumeLabels).includes(value);
    });
    return candidates.length?text(candidates[0]).slice(0,100):'';
  }
  function extractResume(doc,href){
    const site=resumeSite(href);if(!site)return {status:'unsupported',reason:'请打开 BOSS 或智联的本人在线简历页面'};
    const sections={};for(const key of Object.keys(resumeLabels))sections[key]=site==='boss'?resumeSection(doc,key):zhaopinResumeSection(doc,key);
    if(!Object.values(sections).some(section=>section.status==='present'))return {status:'incomplete',reason:site==='zhaopin'?'智联在线简历栏目未能唯一定位或尚未加载完成，请确认当前选中的在线简历后重试':'在线简历栏目还没有加载完成'};
    const source_url=site==='boss'?'https://www.zhipin.com/web/geek/resume':'https://i.zhaopin.com/resume';
    return {status:'ready',resume:{schema:site==='boss'?'job-assistant.boss-resume.v1':'job-assistant.zhaopin-resume.v1',source_url,name:site==='boss'?resumeName(doc):'',sections},note:'仅在本次点击后读取当前在线简历栏目；未读取附件、头像、诊断、隐私设置或掩码联系方式。'};
  }
  function extractJob(doc,href){
    const current=new URL(href);
    if(genericSite(href))return genericJob(doc,href);
    if(!['www.zhipin.com','zhipin.com'].includes(current.hostname))return {status:'unsupported',reason:'请切到 BOSS 职位详情页'};
    if(/\/chat|\/geek\/chat/.test(current.pathname))return {status:'chat',reason:'聊天页：先固定对应岗位，再选中消息并点击读取选中文字'};
    const direct=identity(href);
    if(direct){
      const section=directDescription(doc);
      if(section?.ambiguous)return {status:'ambiguous',reason:'检测到多段不同的职位正文，请核对当前岗位详情'};
      if(section){
        const embedded=nodes(section.scope,'a[href*="/job_detail/"]').map(a=>identity(a.href)).filter(Boolean);
        if(embedded.some(x=>x.job_key!==direct.job_key))return {status:'incomplete',reason:'页面链接和详情尚未一致，等待岗位切换完成'};
        const title=oneText(doc,['.job-banner .name h1','.job-banner h1','.job-primary .name h1','.job-primary h1','h1']);
        let company=directCompany(doc);
        const jd=text(section.body);
        if(title && company && jd.length>=40){
          const salary=oneText(doc,['.job-banner .salary','.job-primary .salary','.salary']);
          const safeSalary=/[\uE000-\uF8FF]/.test(salary)?'页面薪资使用自定义字体，请在网页核对':salary;
          return {status:'ready',capture:{...direct,title:title.slice(0,200),company:company.slice(0,300),jd:[safeSalary&&`薪资：${safeSalary}`,jd].filter(Boolean).join('\n').slice(0,50000),method:'dom'},adapter:'boss-detail-heading'};
        }
        return {status:'incomplete',reason:!title?'已识别职位正文，岗位标题尚未加载':'已识别职位正文，公司名称尚未唯一定位'};
      }
      const panes=nodes(doc,'.job-detail');
      return {status:panes.length>1?'ambiguous':'incomplete',reason:'职位正文暂未唯一定位，已排除公司介绍和薪资块'};
    }
    // Fail closed if several visible job detail panes exist. Never read the listing as a JD.
    const selectors=['.job-detail-box','.job-detail-container','.job-detail'];
    let scope=null;
    for(const selector of selectors){const found=nodes(doc,selector).filter(n=>nodes(n,'.job-sec-text,.job-detail-description').length);if(found.length>1)return {status:'ambiguous',reason:'检测到多个职位详情，请打开单独的职位页'};if(found.length===1){scope=found[0];break;}}
    if(!scope && direct)scope=doc;
    if(!scope)return semanticDetail(doc) || {status:'unavailable',reason:'未定位到唯一职位描述与详情链接。请点开岗位，或使用“读取选中 JD”'};
    const descriptions=nodes(scope,'.job-sec-text,.job-detail-description');
    if(descriptions.length!==1)return semanticDetail(doc,direct) || {status:'unavailable',reason:'职位正文缺失或不唯一，请打开完整职位详情'};
    const jd=text(descriptions[0]);
    const header=direct?doc:scope;
    const title=oneText(header,['.job-banner .name h1','.job-name h2','.job-name h1','.job-title','h1']);
    const company=oneText(header,['.company-info .company-name','.company-name','.sider-company .company-info a','.company-name a']);
    let id=direct;
    if(!id){
      const ids=nodes(scope,'a[href*="/job_detail/"]').map(a=>identity(a.href)).filter(Boolean);
      const unique=[...new Map(ids.map(item=>[item.job_key,item])).values()];
      if(unique.length===1)id=unique[0];
    }
    if(!id)return {status:'unavailable',reason:'详情中没有唯一岗位链接，请打开独立职位页再识别'};
    const explicit=nodes(scope,'a[href*="/job_detail/"]').map(a=>identity(a.href)).filter(Boolean);
    if(direct && scope!==doc && explicit.some(x=>x.job_key!==direct.job_key))return {status:'incomplete',reason:'页面链接和详情尚未一致，等待岗位切换完成'};
    if(!title || !company || jd.length<40)return semanticDetail(doc,direct) || {status:'incomplete',reason:'岗位名称、公司或 JD 尚未完整加载；等待后可点击重新识别'};
    const salary=oneText(header,['.job-banner .salary','.salary']);
    const conditions=oneText(header,['.job-banner .job-primary .info-primary > p','.job-banner .text']);
    const safeSalary=/[\uE000-\uF8FF]/.test(salary)?'页面薪资使用自定义字体，请在网页核对':salary;
    const safeConditions=/[\uE000-\uF8FF]/.test(conditions)?'':conditions;
    return {status:'ready',capture:{...id,title:title.slice(0,200),company:company.slice(0,300),jd:([safeSalary&&`薪资：${safeSalary}`,safeConditions,jd].filter(Boolean).join('\n')).slice(0,50000),method:'dom'}};
  }
  function diagnose(doc,href){
    const shape=(n,depth=0)=>({tag:n.tagName,classes:[...n.classList],chars:text(n).length,...(depth<3?{children:[...n.children].filter(visible).slice(0,12).map(c=>shape(c,depth+1))}:{})});
    const siteStructure=genericSite(href)?nodes(doc,'.pos_info,.job-detail-modules__summary-wrap,h1').map(n=>shape(n)):[];
    const counts={};for(const s of ['.job-detail-box','.job-detail-container','.job-detail','.job-sec-text','.job-detail-description','p.desc','h1','h3','a[href*="/gongsi/"]','iframe'])counts[s]=doc.querySelectorAll(s).length;
    const headings=nodes(doc,'h1,h2,h3,h4,[role="heading"]').filter(n=>headingText(n)==='职位描述');
    const chain=n=>{const result=[];for(let p=n;p&&result.length<7;p=p.parentElement)result.push({tag:p.tagName,classes:[...p.classList],children:[...p.children].slice(0,12).map(c=>({tag:c.tagName,classes:[...c.classList]}))});return result;};
    const r=extract(doc,href);
    const blockMeta=nodes(doc,'.job-sec-text,.job-detail-description,p.desc').map((n,index)=>{
      const preceding=[];let p=n.previousElementSibling;while(p&&preceding.length<4){if(/^H[1-4]$/.test(p.tagName)||p.matches('.title'))preceding.push({tag:p.tagName,classes:[...p.classList],chars:text(p).length});p=p.previousElementSibling;}
      return {index,classes:[...n.classList],chars:text(n).length,parent:{tag:n.parentElement?.tagName,classes:[...(n.parentElement?.classList||[])]},preceding};
    });
    const candidates={title_selectors:['.job-banner .name h1','.job-banner h1','.job-primary .name h1','.job-primary h1','h1'].map(s=>({selector:s,count:nodes(doc,s).length})),company_links:nodes(doc,'a[href*="/gongsi/"]').map(n=>({classes:[...n.classList],chars:text(n).length})).slice(0,20)};
    const resumeOnly=!!resumeSite(href);
    return {adapter_version:'0.6.0-diagnostic',site_structure:siteStructure,resume_structure:zhaopinResumeStructure(doc,href),path:new URL(href).pathname.replace(/\/job_detail\/[^/]+/,'/job_detail/<id>').replace(/\/gongsi\/.+/,'/gongsi/<id>'),status:resumeOnly?'unavailable':r.status,reason:resumeOnly?'在线简历诊断只报告结构，不读取正文':r.reason||'',counts,description_containers:headings.map(chain),text_blocks:blockMeta,candidates,company_sections:r.company_capture?.sections.map(s=>({kind:s.kind,chars:s.text.length}))||[],note:'仅标签/类名/字符数/数量，不含简历正文、招聘者姓名、用户资料、Cookie 或 URL 参数'};
  }
  function pageIdentity(doc,href){
    const direct=identity(href);if(direct)return {job_key:direct.job_key,source:'url'};
    const foreign=genericIdentity(href);if(foreign?.site==='zhaopin'&&/^\/jobdetail\//i.test(new URL(href).pathname))return {job_key:foreign.job_key,source_site:'zhaopin',url:foreign.url,source:'url'};
    const unique=items=>[...new Set(items.filter(Boolean))];
    // Only actual job cards count as selection evidence. A hovered label,
    // expanded section or active button in the detail pane is not a job switch.
    const cards=nodes(doc,'.job-card-wrapper,.job-card-box,.job-list-box li,.job-list-container li');
    const selected=unique(cards.filter(c=>!c.closest('.job-detail-box,.job-detail-container,.job-detail') && c.matches('.selected,.active,.cur,.current,[aria-selected="true"]')).flatMap(c=>nodes(c,'a[href*="/job_detail/"]').map(a=>identity(a.href)?.job_key)));
    const detail=unique(nodes(doc,'.job-detail-box .more-job-btn,.job-detail-container .more-job-btn,.job-detail-body a[href*="/job_detail/"]').map(a=>identity(a.href)?.job_key));
    if(selected.length>1||detail.length>1)return {job_key:null,conflict:true,source:'multiple'};
    if(selected.length===1)return {job_key:selected[0],conflict:detail.length===1&&selected[0]!==detail[0],source:'selected-card'};
    return {job_key:detail[0]||null,source:detail.length?'detail-link':'unknown'};
  }
  function employer(doc,href,job){
    const page=companyIdentity(href);
    if(page)return {...page,name:oneText(doc,['.company-banner h1','.company-info h1','h1']).replace(/\s*收藏\s*/g,'').replace(/招聘$/,'').trim()};
    if(job?.source_site==='zhaopin'&&job.company_key&&job.company_url)return {...companyIdentity(job.company_url),name:job.company};
    const selectors=['.company-info-box a[href*="/gongsi/"]','.sider-company a[href*="/gongsi/"]','.company-info a[href*="/gongsi/"]','.job-detail-modules__summary-wrap a[href*="/companydetail/"]','.job-detail-modules__detail a[href*="/companydetail/"]'];
    for(const selector of selectors){
      const links=nodes(doc,selector).map(n=>({n,id:companyIdentity(n.href)})).filter(x=>x.id);
      const ids=[...new Set(links.map(x=>x.id.company_key))];
      if(ids.length===1)return {...links[0].id,name:job?.company||text(links[0].n)||directCompany(doc)};
    }
    if(job){
      const cards=nodes(doc,'.job-card-wrapper,.job-card-box,.job-list-container li,.job-list-box li');
      for(const c of cards){
        const ids=[...new Set(nodes(c,'a[href*="/job_detail/"]').map(a=>identity(a.href)?.job_key).filter(Boolean))];
        if(ids.length!==1||ids[0]!==job.job_key)continue;
        const companies=nodes(c,'a[href*="/gongsi/"]').map(a=>companyIdentity(a.href)).filter(Boolean);
        if(new Set(companies.map(c=>c.company_key)).size===1)return {...companies[0],name:job.company};
      }
    }
    return null;
  }
  function companySections(doc,isCompany){
    const result=[];
    const add=(kind,n,label='企业自述',partialHint=false)=>{const value=text(n);if(value.length>=20&&value.length<60000&&!result.some(s=>s.text===value))result.push({kind,text:value.slice(0,20000),partial:partialHint||n.scrollHeight>n.clientHeight+8||!!n.closest('.fold-text'),label});};
    nodes(doc,'.company-info-box .job-sec-text').forEach(n=>add('introduction',n));
    if(isCompany){
      if(genericSite(doc.location?.href)==='zhaopin'){
        // Zhaopin renders the title and text in sibling regions of one card,
        // not as adjacent heading/content siblings.
        for(const card of nodes(doc,'.seo-card')){
          if(card.closest('.recommend-box,.recommend-list,.hot-job-list,[class*="recommend"],[class*="guess"]'))continue;
          const title=nodes(card,'.seo-card__title');if(title.length!==1)continue;
          const label=headingText(title[0]);const kind=/^(公司简介|公司介绍)$/.test(label)?'introduction':/^(产品介绍|公司产品|产品信息|产品与服务|产品服务|公司业务|业务介绍|主营业务)$/.test(label)?'products':null;
          if(!kind)continue;
          let bodies=nodes(card,'.seo-card__content .introduction__text,.seo-card__content .seo-card__text');
          if(!bodies.length)bodies=nodes(card,'.seo-card__content');
          if(!bodies.length)continue;
          const body=bodies.find(n=>text(n).length>=20);if(!body)continue;
          const cardText=text(card),generated=/AI.{0,12}生成|由.{0,20}AI.{0,12}生成|仅供参考/.test(cardText);
          const toggle=nodes(card,'.seo-card__toggle').some(n=>!n.classList.contains('seo-card__toggle--expanded'));
          add(kind,body,generated?'平台AI生成，仅供参考':'智联公司页介绍，未经独立核实',toggle||card.classList.contains('seo-card--collapsed'));
        }
      }
      const heads=nodes(doc,'h2,h3,h4,[role="heading"]');
      for(const h of heads){
        const label=headingText(h);const kind=/^(公司简介|公司介绍)$/.test(label)?'introduction':/^(产品介绍|公司产品|产品信息|产品与服务|产品服务|公司业务|业务介绍|主营业务)$/.test(label)?'products':null;
        if(!kind)continue;
        // Read siblings up to the next heading; never capture whole-page text,
        // management biographies, recruiter lists or recommendations.
        for(let n=h.nextElementSibling;n;n=n.nextElementSibling){
          if(n.matches('h1,h2,h3,h4')||n.querySelector('h1,h2,h3'))break;
          if(n.matches('.company-boss,.boss-list,.manager-list'))break;
          if(text(n).length>=20){add(kind,n);break;}
        }
      }
      nodes(doc,'.company-intro .text,.company-intro .fold-text,.company-introduction .text,.company-desc .text').forEach(n=>add('introduction',n));
    }
    return result.slice(0,8);
  }
  function companyPageData(doc,href,info){
    const page=companyIdentity(href),sections=companySections(doc,!!page);
    const jobs=[],seen=new Set();
    if(page&&page.source_site==='boss'){
      // Only the company's main job list; "精选职位" outside it is excluded.
      for(const c of nodes(doc,'.job-list-container li,.job-list-box li,.job-list li,.job-card-wrapper')){
        if(c.closest('.recommend-box,.recommend-list,.hot-job-list'))continue;
        const links=nodes(c,'a[href*="/job_detail/"]');
        const ids=[...new Set(links.map(a=>identity(a.href)?.job_key).filter(Boolean))];
        if(ids.length!==1||seen.has(ids[0])||nodes(c,'a[href*="/gongsi/"]').some(a=>companyIdentity(a.href)?.company_key!==info.company_key))continue;
        const a=links.find(a=>identity(a.href));const title=oneText(c,['.job-name','.job-title'])||text(a);
        if(!title||title.length>240)continue;
        seen.add(ids[0]);jobs.push({...identity(a.href),title,salary:oneText(c,['.salary','.red']),conditions:oneText(c,['.job-area','.job-info','.job-limit'])});
        if(jobs.length>=30)break;
      }
    }
    if(page&&page.source_site==='zhaopin'&&/^\/companydetail\/jobs-[^/]+\/?$/i.test(new URL(href).pathname)){
      const links=nodes(doc,'a[href*="/jobdetail/"]');
      for(const a of links){
        const id=genericIdentity(a.href);if(!id||id.site!=='zhaopin'||seen.has(id.job_key))continue;
        const card=a.closest('.job-onlinelist__jobs__item,.job-card,.job-card-item,.job-list-item,.job-list__item,.position-list-item,.job-item,article,li,div[class*="job-card"],div[class*="job-item"],div[class*="position-card"],div[class*="job-list-item"]');
        if(!card||!visible(card)||card.closest('.recommend-box,.recommend-list,.hot-job-list,[class*="recommend"],[class*="guess"]'))continue;
        if(card.matches('.job-onlinelist__jobs__item')&&!card.closest('.job-onlinelist'))continue;
        const cardLinks=nodes(card,'a[href*="/jobdetail/"]').map(x=>genericIdentity(x.href)).filter(x=>x?.site==='zhaopin');
        const ids=[...new Set(cardLinks.map(x=>x.job_key))];if(ids.length!==1||ids[0]!==id.job_key)continue;
        const companyLinks=nodes(card,'a[href*="/companydetail/"]').map(x=>companyIdentity(x.href)).filter(Boolean);
        if(companyLinks.some(x=>x.company_key!==info.company_key))continue;
        const title=oneText(card,['.job-name','.job-title','.position-name','.position-title','[class*="job-name"]','[class*="position-name"]'])||text(a);
        if(!title||title.length>240)continue;
        seen.add(id.job_key);jobs.push({...id,title,salary:oneText(card,['.job-onlinelist__jobs__info__salary','.salary','[class*="salary"]']),conditions:oneText(card,['.job-onlinelist__jobs__welfare','.job-area','.job-info','.job-limit','[class*="job-info"]','[class*="require"]'])});
        if(jobs.length>=30)break;
      }
    }
    const categories=page?nodes(doc,'a[href*="/gongsi/job/"]').filter(a=>companyIdentity(a.href)?.company_key===info.company_key).map(text).filter(s=>s.length<45&&/[（(]\d+[）)]/.test(s)):[];
    const filters=page?nodes(doc,'.filter-select-box,.job-filter,.filter-box').map(text).filter(s=>s.length<1000).join('\n').slice(0,1500):'';
    return {...info,source_url:new URL(href).origin+new URL(href).pathname,sections,jobs,categories:[...new Set(categories)].slice(0,20),filters,coverage:'仅当前页面已加载内容；职位卡片不等于完整JD，分类数字不等于已采集数量'};
  }
  function chatContext(doc,href){
    const page=new URL(href);
    if(!['www.zhipin.com','zhipin.com'].includes(page.hostname)||page.pathname.replace(/\/$/,'')!=='/web/geek/chat')return {status:'unsupported'};
    // BOSS keeps one URL for every contact. Read only the visible header and
    // position strip of the selected conversation, never message text.
    const markers=nodes(doc,'a,button,span,div').filter(n=>text(n).replace(/\s/g,'')==='查看职位');
    const candidates=[];
    const parseHeader=raw=>{
      const clean=raw.replace(/(?:\s+(?:更多|在线|离线))+\s*$/,'').replace(/[|｜]/g,' ').trim();
      if(!clean||clean.length>140||/(?:全部|未读|新招呼|仅沟通|查看职位)/.test(clean)||/\d{1,2}:\d{2}|(?:已读|送达)/.test(clean))return null;
      const parts=clean.split(/\s+/).filter(Boolean);
      if(parts.length<3||parts.length>4)return null;
      const role=parts.at(-1);
      if(!/(?:HR|招聘|人事|经理|主管|总监|负责人|校长|老板|猎头|顾问)/i.test(role)||role.length>16)return null;
      const recruiter_name=parts[0],company=parts.slice(1,-1).join(' ');
      return recruiter_name.length>=2&&recruiter_name.length<=100&&company.length>=2&&company.length<=300?{recruiter_name,company}:null;
    };
    function collect(marker){
      for(let card=marker,depth=0;card&&depth<5;card=card.parentElement,depth++){
        const summary=text(card).replace(/\s+/g,' ').trim();
        if(summary.length<=4||summary.length>180||!/(?:查看职位|\d+[\d.,]*\s*[-–—~至]\s*\d+[\d.,]*\s*[Kk万])/.test(summary))continue;
        const job_title=summary.split(/(?:\d+[\d.,]*\s*[-–—~至]\s*\d+[\d.,]*\s*[Kk万]|查看职位)/)[0].trim();
        if(job_title.length<2||job_title.length>100||/(?:更多|全部|未读|新招呼|仅沟通|已读|送达)/.test(job_title)||parseHeader(job_title))continue;
        const previous=card.previousElementSibling;
        // The header must be the strip's immediate sibling. Searching inside
        // earlier containers can borrow an unrelated contact from the left list.
        const fields=previous?parseHeader(text(previous)):null;
        if(fields){
          const links=[...new Map(nodes(card,'a[href*="/job_detail/"]').map(a=>identity(a.href)).filter(Boolean).map(id=>[id.job_key,id])).values()];
          if(links.length>1)return;
          candidates.push({...fields,job_title,...(links.length===1?{job_url:links[0].url}:{})});break;
        }
      }
    }
    for(const marker of markers)collect(marker.parentElement);
    // The current BOSS strip can omit the “查看职位” control. A salary-bearing
    // strip directly beneath the selected conversation header is enough; a
    // salary mentioned in a chat message has no adjacent recruiter header.
    if(!candidates.length){
      for(const strip of nodes(doc,'div,section,article,header').filter(n=>{
        const value=text(n).replace(/\s+/g,' ').trim();
        return value.length>=5&&value.length<=140&&/\d+[\d.,]*\s*[-–—~至]\s*\d+[\d.,]*\s*[Kk万]/.test(value);
      }))collect(strip);
    }
    const unique=[...new Map(candidates.map(x=>[JSON.stringify(x),x])).values()];
    if(unique.length!==1)return {status:'incomplete',reason:'当前 HR 会话的招聘者、企业或岗位未能唯一核验；请等待页面加载或打开岗位 JD'};
    return {status:'ready',chat:{url:page.origin+page.pathname,...unique[0]}};
  }
  function extract(doc,href){
    const resumeSource=resumeSite(href);if(resumeSource)return {status:'resume',reason:'这是本人在线简历页。只有点击“读取在线简历”后才会读取正文。',page_type:resumeSource+'-resume'};
    const r=extractJob(doc,href),info=employer(doc,href,r.capture);
    if(info?.name){
      if(r.capture)Object.assign(r.capture,{company_key:info.company_key,company_url:info.company_url});
      r.company_capture=companyPageData(doc,href,info);
      if(r.capture&&!companyIdentity(href))r.company_capture.source_url=r.capture.url;
      if(companyIdentity(href)&&r.status!=='ready'){r.status='company';r.reason='正在浏览公司公开介绍或招聘信息';}
    }
    return r;
  }
  const api={extract,extractResume,resumePage,identity,genericIdentity,genericSite,diagnose,pageIdentity,companyIdentity,chatContext};
  if(typeof module!=='undefined' && module.exports)module.exports=api;
  root.JobAssistantExtractor=api;
})(globalThis);
