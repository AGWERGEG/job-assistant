chrome.sidePanel.setPanelBehavior({openPanelOnActionClick:true}).catch(()=>{});
const paths=new Set(['/capture','/task','/result','/status','/confirm','/history','/talk','/company-save','/company-read','/restore','/cancel','/retry','/sync','/onboarding-complete']);
function trusted(sender){return sender.id===chrome.runtime.id && sender.url===chrome.runtime.getURL('panel.html');}
async function callBridge(path,value,port,token){
  if(!Number.isInteger(port)||port<1024||port>65535)throw Error('本地端口必须为 1024—65535');
  const response=await fetch(`http://127.0.0.1:${port}/bridge${path}`,{method:'POST',headers:{'Content-Type':'application/json',...(token?{'X-Bridge-Token':token}:{})},body:JSON.stringify(value),signal:AbortSignal.timeout(12000)});
  const result=await response.json();if(!response.ok)throw Error(result.error || `本地服务错误 ${response.status}`);return result;
}
chrome.runtime.onMessage.addListener((m,sender,respond)=>{
  if(!trusted(sender))return false;
  (async()=>{
    if(m.type==='JA_PAIR'){
      const result=await callBridge('/pair',{code:m.code},m.port);
      await chrome.storage.session.set({connection:{port:m.port,token:result.token}});
      return {connected:true};
    }
    if(m.type==='JA_DISCONNECT'){const {connection}=await chrome.storage.session.get('connection');try{if(connection)await callBridge('/disconnect',{},connection.port,connection.token);}finally{await chrome.storage.session.remove('connection');}return {connected:false};}
    if(m.type==='JA_CONNECTION'){const {connection}=await chrome.storage.session.get('connection');return {connected:!!connection,port:connection?.port};}
    if(m.type==='JA_API' && paths.has(m.path)){
      const {connection}=await chrome.storage.session.get('connection');if(!connection)throw Error('先在侧栏输入本地工作台配对码');
      return callBridge(m.path,m.value || {},connection.port,connection.token);
    }
    throw Error('未知扩展动作');
  })().then(value=>respond({ok:true,value}),e=>respond({ok:false,error:e.message}));
  return true;
});
