chrome.sidePanel.setPanelBehavior({openPanelOnActionClick:true}).catch(()=>{});
const paths=new Set(['/capture','/task','/result','/status','/confirm','/history','/talk','/company-save','/company-read','/company-bind','/resume-import','/restore','/cancel','/retry','/sync','/onboarding-complete','/jobs','/select','/links','/link-context','/link-save','/link-unbind']);
function trusted(sender){return sender.id===chrome.runtime.id && sender.url===chrome.runtime.getURL('panel.html');}
async function callBridge(path,value,port,token){
  if(!Number.isInteger(port)||port<1024||port>65535)throw Error('本地端口必须为 1024—65535');
  const response=await fetch(`http://127.0.0.1:${port}/bridge${path}`,{method:'POST',headers:{'Content-Type':'application/json',...(token?{'X-Bridge-Token':token}:{})},body:JSON.stringify(value),signal:AbortSignal.timeout(12000)});
  const result=await response.json();if(!response.ok){const error=Error(result.error || `本地服务错误 ${response.status}`);error.status=response.status;throw error;}return result;
}
async function discover(port){return callBridge('/discover',{},port);}
function expectedVersion(){return chrome.runtime.getManifest?.().version_name||'';}
function requireCompatible(result){const expected=expectedVersion();if(!expected||result?.version!==expected)throw Error(`侧栏版本 ${expected||'未知'} 与本机工作台版本 ${result?.version||'未知'} 不一致，请更新同一版本后重新连接`);return result;}
function bytesHex(bytes){return Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');}
function equalHex(a,b){if(typeof a!=='string'||typeof b!=='string'||!/^[0-9a-f]{64}$/.test(a)||!/^[0-9a-f]{64}$/.test(b))return false;let difference=0;for(let i=0;i<64;i++)difference|=a.charCodeAt(i)^b.charCodeAt(i);return difference===0;}
async function verifyPairedServer(port,token){
  if(typeof token!=='string'||!token||!globalThis.crypto?.subtle)throw Error('无法验证本机服务，请重新配对');
  const nonceBytes=new Uint8Array(32);globalThis.crypto.getRandomValues(nonceBytes);const nonce=bytesHex(nonceBytes);
  const result=await callBridge('/challenge',{nonce},port);
  const expected=expectedVersion();if(!expected||result?.version!==expected)throw Error(`本机工作台版本 ${result?.version||'未知'} 与侧栏版本 ${expected||'未知'} 不一致，请重新配对`);
  if(result.nonce!==nonce||typeof result.proof!=='string')throw Error('本机服务验证失败，请重新配对');
  const encoder=new TextEncoder();
  const key=await globalThis.crypto.subtle.importKey('raw',encoder.encode(token),{name:'HMAC',hash:'SHA-256'},false,['sign']);
  const signature=new Uint8Array(await globalThis.crypto.subtle.sign('HMAC',key,encoder.encode(nonce)));
  if(!equalHex(bytesHex(signature),result.proof))throw Error('本机服务验证失败，请重新配对');
  return result;
}
async function openWorkbench(url){
  const saved=await chrome.storage.session.get('workbenchTabId');
  const tabId=saved.workbenchTabId;
  if(Number.isInteger(tabId)){
    try{
      const tab=await chrome.tabs.update(tabId,{url,active:true});
      if(Number.isInteger(tab?.windowId)&&chrome.windows?.update)await chrome.windows.update(tab.windowId,{focused:true});
      return {tab_id:tabId,reused:true};
    }catch{}
  }
  const tab=await chrome.tabs.create({url,active:true});
  if(Number.isInteger(tab?.id))await chrome.storage.session.set({workbenchTabId:tab.id});
  return {tab_id:tab?.id,reused:false};
}
if(chrome.tabs?.onRemoved?.addListener)chrome.tabs.onRemoved.addListener(async tabId=>{
  const saved=await chrome.storage.session.get('workbenchTabId');
  if(saved.workbenchTabId===tabId)await chrome.storage.session.remove('workbenchTabId');
});
chrome.runtime.onMessage.addListener((m,sender,respond)=>{
  if(!trusted(sender))return false;
  (async()=>{
    if(m.type==='JA_PAIR'){
      requireCompatible(await discover(m.port));
      const result=await callBridge('/pair',{code:m.code},m.port);
      await chrome.storage.session.set({connection:{port:m.port,token:result.token,version:result.version||expectedVersion()}});
      await chrome.storage.session.remove('pairing');
      return {connected:true};
    }
    if(m.type==='JA_DISCOVER'){
      const {connection,pairing}=await chrome.storage.session.get(['connection','pairing']);
      const pinned=connection||pairing;
      if(pinned){
        const port=pinned.port;
        try{if(connection)await verifyPairedServer(port,connection.token);const result=await discover(port);return {found:true,port,version:result.version,pairing:result.pairing,
          compatible:result.version===expectedVersion(),paired:!!connection,needsRepair:!!connection&&result.version!==expectedVersion(),expected:expectedVersion()};}
        catch{return {found:false,port,paired:!!connection,pendingPair:!!pairing,needsRepair:!!connection,expected:expectedVersion()};}
      }
      const ports=Array.isArray(m.ports)?m.ports:[8421];
      const expected=expectedVersion();
      let fallback=null;
      for(const port of ports){try{const result=await discover(port);const found={found:true,port,version:result.version,pairing:result.pairing,compatible:!!expected&&result.version===expected,expected};if(found.compatible)return found;if(!fallback)fallback=found;}catch{}}
      return fallback||{found:false,expected};
    }
    if(m.type==='JA_PAIR_REQUEST'){
      requireCompatible(await discover(m.port));
      const request=await callBridge('/pair-request',{},m.port);
      await chrome.storage.session.set({pairing:{port:m.port,requestId:request.request_id}});
      return {requested:true,port:m.port,request_id:request.request_id,expires_in:request.expires_in};
    }
    if(m.type==='JA_PAIR_STATUS'){
      const {pairing}=await chrome.storage.session.get('pairing');if(!pairing)return {status:'missing'};
      const result=await callBridge('/pair-status',{request_id:pairing.requestId},pairing.port);
      if(result.status==='approved'){
        requireCompatible(result);
        await chrome.storage.session.set({connection:{port:pairing.port,token:result.token,version:result.version}});
        await chrome.storage.session.remove('pairing');
        return {status:'approved',connected:true,port:pairing.port,version:result.version};
      }
      return {status:result.status,port:pairing.port,expires_in:result.expires_in};
    }
    if(m.type==='JA_DISCONNECT'){const {connection}=await chrome.storage.session.get('connection');try{if(connection){await verifyPairedServer(connection.port,connection.token);await callBridge('/disconnect',{},connection.port,connection.token);}}finally{await chrome.storage.session.remove('connection');}return {connected:false};}
    if(m.type==='JA_CONNECTION'){const {connection,pairing}=await chrome.storage.session.get(['connection','pairing']);return {connected:!!connection,port:connection?.port||pairing?.port,pairing:!!pairing};}
    if(m.type==='JA_OPEN_WORKBENCH'){
      const url=String(m.url||'');
      const parsed=new URL(url);
      if(parsed.protocol!=='http:'||parsed.hostname!=='127.0.0.1')throw Error('工作台地址无效');
      const port=Number(parsed.port||80);if(!Number.isInteger(port)||port<1024||port>65535)throw Error('工作台端口无效');
      return openWorkbench(parsed.toString());
    }
    if(m.type==='JA_OPEN_URL'){
      const url=String(m.url||'');const parsed=new URL(url);const host=parsed.hostname.toLowerCase();
      if(parsed.protocol!=='https:'||parsed.username||parsed.password||!['','443'].includes(parsed.port)||!(host==='zhipin.com'||host==='www.zhipin.com'||host==='zhaopin.com'||host.endsWith('.zhaopin.com')||host==='58.com'||host.endsWith('.58.com')))throw Error('招聘网页链接无效');
      const tab=await chrome.tabs.create({url:parsed.toString(),active:true});return {tab_id:tab?.id};
    }
    if(m.type==='JA_API' && paths.has(m.path)){
      const {connection}=await chrome.storage.session.get('connection');if(!connection)throw Error('先在侧栏输入本地工作台配对码');
      if(connection.version!==expectedVersion())throw Error(`侧栏版本 ${expectedVersion()||'未知'} 与已配对工作台版本不一致，请重新配对`);
      // Prove the pinned endpoint holds the paired token before sending that
      // token or any user/page data. A paired connection never falls back.
      await verifyPairedServer(connection.port,connection.token);
      return callBridge(m.path,m.value || {},connection.port,connection.token);
    }
    throw Error('未知扩展动作');
  })().then(value=>respond({ok:true,value}),e=>respond({ok:false,error:e.message}));
  return true;
});
