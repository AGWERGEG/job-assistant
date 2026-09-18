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
  function oneText(scope,selectors){for(const selector of selectors){const found=nodes(scope,selector);if(found.length===1 && text(found[0]))return text(found[0]);}return '';}
  const headingText=n=>text(n).replace(/[\s:：]/g,'');
  function companyIdentity(href){try{const u=new URL(href);if(u.protocol!=='https:'||!['www.zhipin.com','zhipin.com'].includes(u.hostname))return null;const m=u.pathname.match(/^\/gongsi\/(?:job\/(?:\d+\/)?)?([A-Za-z0-9_~\-]{4,200})\.html$/);return m?{company_key:m[1],company_url:'https://www.zhipin.com/gongsi/'+m[1]+'.html'}:null;}catch{return null;}}
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
  function directDescription(doc){
    // Independent 2026 pages do not always put .job-detail-section under
    // .job-detail. Treat the section class as authoritative and keep the
    // salary/company blocks out of the candidate set.
    const all=nodes(doc,'.job-sec-text,.job-detail-description,p.desc')
      .filter(n=>text(n).length>=40)
      .filter(n=>!n.closest('.salary-info,.company-info-box'));
    const structural=all.filter(n=>n.closest('.job-detail-section'));
    if(structural.length===1)return {body:structural[0],heading:null,scope:structural[0].parentElement};
    if(structural.length>1){
      const ranked=structural.map(n=>({n,len:text(n).length})).sort((a,b)=>b.len-a.len);
      if(!ranked[1] || ranked[0].len>=ranked[1].len*1.5)return {body:ranked[0].n,heading:null,scope:ranked[0].n.parentElement};
      return null;
    }
    if(all.length===1)return {body:all[0],heading:null,scope:all[0].parentElement};
    if(all.length>1){
      const ranked=all.map(n=>({n,len:text(n).length})).sort((a,b)=>b.len-a.len);
      if(!ranked[1] || ranked[0].len>=ranked[1].len*1.5)return {body:ranked[0].n,heading:null,scope:ranked[0].n.parentElement};
    }
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
    return null;
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
    return {status:'ready',capture:{...id,title:card.title.slice(0,200),company:company.slice(0,300),jd:[safeConditions,jd].filter(Boolean).join('\n').slice(0,50000),method:'dom'},adapter:direct?'boss-detail-semantic':'boss-split-semantic'};
  }
  function extractJob(doc,href){
    const current=new URL(href);
    if(!['www.zhipin.com','zhipin.com'].includes(current.hostname))return {status:'unsupported',reason:'请切到 BOSS 职位详情页'};
    if(/\/chat|\/geek\/chat/.test(current.pathname))return {status:'chat',reason:'聊天页：先固定对应岗位，再选中消息并点击读取选中文字'};
    const direct=identity(href);
    if(direct){
      const section=directDescription(doc);
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
    const counts={};for(const s of ['.job-detail-box','.job-detail-container','.job-detail','.job-sec-text','.job-detail-description','p.desc','h1','h3','a[href*="/gongsi/"]','iframe'])counts[s]=doc.querySelectorAll(s).length;
    const headings=nodes(doc,'h1,h2,h3,h4,[role="heading"]').filter(n=>headingText(n)==='职位描述');
    const chain=n=>{const result=[];for(let p=n;p&&result.length<7;p=p.parentElement)result.push({tag:p.tagName,classes:[...p.classList],children:[...p.children].slice(0,12).map(c=>({tag:c.tagName,classes:[...c.classList]}))});return result;};
    const r=extract(doc,href);
    const blockMeta=nodes(doc,'.job-sec-text,.job-detail-description,p.desc').map((n,index)=>{
      const preceding=[];let p=n.previousElementSibling;while(p&&preceding.length<4){if(/^H[1-4]$/.test(p.tagName)||p.matches('.title'))preceding.push({tag:p.tagName,classes:[...p.classList],chars:text(p).length});p=p.previousElementSibling;}
      return {index,classes:[...n.classList],chars:text(n).length,parent:{tag:n.parentElement?.tagName,classes:[...(n.parentElement?.classList||[])]},preceding};
    });
    const candidates={title_selectors:['.job-banner .name h1','.job-banner h1','.job-primary .name h1','.job-primary h1','h1'].map(s=>({selector:s,count:nodes(doc,s).length})),company_links:nodes(doc,'a[href*="/gongsi/"]').map(n=>({classes:[...n.classList],chars:text(n).length})).slice(0,20)};
    return {adapter_version:'0.6.0-diagnostic',path:new URL(href).pathname.replace(/\/job_detail\/[^/]+/,'/job_detail/<id>').replace(/\/gongsi\/.+/,'/gongsi/<id>'),status:r.status,reason:r.reason||'',counts,description_containers:headings.map(chain),text_blocks:blockMeta,candidates,company_sections:r.company_capture?.sections.map(s=>({kind:s.kind,chars:s.text.length}))||[],note:'仅标签/类名/字符数/数量，不含正文、招聘者姓名、用户资料、Cookie 或 URL 参数'};
  }
  function pageIdentity(doc,href){
    const direct=identity(href);if(direct)return {job_key:direct.job_key,source:'url'};
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
    const selectors=['.company-info-box a[href*="/gongsi/"]','.sider-company a[href*="/gongsi/"]','.company-info a[href*="/gongsi/"]'];
    for(const selector of selectors){
      const links=nodes(doc,selector).map(n=>({n,id:companyIdentity(n.href)})).filter(x=>x.id);
      const ids=[...new Set(links.map(x=>x.id.company_key))];
      if(ids.length===1)return {...links[0].id,name:job?.company||directCompany(doc)};
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
    const add=(kind,n)=>{const value=text(n);if(value.length>=20&&value.length<60000&&!result.some(s=>s.text===value))result.push({kind,text:value.slice(0,20000),partial:n.scrollHeight>n.clientHeight+8||!!n.closest('.fold-text'),label:'企业自述'});};
    nodes(doc,'.company-info-box .job-sec-text').forEach(n=>add('introduction',n));
    if(isCompany){
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
    if(page){
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
    const categories=page?nodes(doc,'a[href*="/gongsi/job/"]').filter(a=>companyIdentity(a.href)?.company_key===info.company_key).map(text).filter(s=>s.length<45&&/[（(]\d+[）)]/.test(s)):[];
    const filters=page?nodes(doc,'.filter-select-box,.job-filter,.filter-box').map(text).filter(s=>s.length<1000).join('\n').slice(0,1500):'';
    return {...info,source_url:new URL(href).origin+new URL(href).pathname,sections,jobs,categories:[...new Set(categories)].slice(0,20),filters,coverage:'仅当前页面已加载内容；职位卡片不等于完整JD，分类数字不等于已采集数量'};
  }
  function extract(doc,href){
    const r=extractJob(doc,href),info=employer(doc,href,r.capture);
    if(info?.name){
      if(r.capture)Object.assign(r.capture,{company_key:info.company_key,company_url:info.company_url});
      r.company_capture=companyPageData(doc,href,info);
      if(r.capture&&!companyIdentity(href))r.company_capture.source_url=r.capture.url;
      if(companyIdentity(href)&&r.status!=='ready'){r.status='company';r.reason='正在浏览公司公开介绍或招聘信息';}
    }
    return r;
  }
  const api={extract,identity,diagnose,pageIdentity,companyIdentity};
  if(typeof module!=='undefined' && module.exports)module.exports=api;
  root.JobAssistantExtractor=api;
})(globalThis);
