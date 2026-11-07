// A shared device belongs to the provider, never to an individual profile.
const uuid = value => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value);
const creationPhases = new Set(['record-present','record-pending','finishing']);
const deletionPhases = new Set(['record-present','record-removed','finishing']);
const exactKeys = (value, keys) => value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === keys.length && keys.every(k=>Object.hasOwn(value,k));
const validDevice = d => exactKeys(d,['handle','instanceId']) && uuid(d.handle) && uuid(d.instanceId);
export function validDeviceStatus(s) {
  if (!exactKeys(s,['available','device','pendingCreation','pendingDeletion']) || typeof s.available !== 'boolean') return false;
  const pending = (p, phases) => p === null || (exactKeys(p,['handle','phase']) && uuid(p.handle) && phases.has(p.phase));
  if (!(s.device === null || validDevice(s.device)) || !pending(s.pendingCreation,creationPhases) || !pending(s.pendingDeletion,deletionPhases)) return false;
  if ([s.device,s.pendingCreation,s.pendingDeletion].filter(Boolean).length > 1) return false;
  return s.available || (!s.device && !s.pendingCreation && !s.pendingDeletion);
}
export function deviceReview(catalog, hosts) {
  if (!catalog || (typeof catalog.revision !== 'string' && typeof catalog.revision !== 'number') || !Array.isArray(catalog.profiles) || !Array.isArray(catalog.bindings) || !Array.isArray(hosts)) throw Error('invalid catalog');
  if (catalog.revision === '' || (typeof catalog.revision === 'number' && !Number.isSafeInteger(catalog.revision))) throw Error('invalid revision');
  if (catalog.profiles.some(p => !p || typeof p.id !== 'string' || typeof p.label !== 'string' || typeof p.provider !== 'string') || catalog.bindings.some(b => !b || typeof b.profileId !== 'string' || typeof b.hostId !== 'string')) throw Error('invalid catalog');
  const profiles = catalog.profiles.filter(p => p.provider === 'zerotier');
  if (new Set(catalog.profiles.map(p=>p.id)).size !== catalog.profiles.length) throw Error('duplicate profile');
  const ids = new Set(profiles.map(p=>p.id));
  if (hosts.some(h=>!h || typeof h.id !== 'string')) throw Error('invalid hosts');
  const hostIds = [...new Set([...catalog.bindings.filter(b=>ids.has(b.profileId)).map(b=>b.hostId), ...hosts.filter(h=>h.provider==='zerotier' || ids.has(h.networkProfileId)).map(h=>h.id)])].sort();
  return {catalogRevision:catalog.revision, profileIds:[...ids].sort(), hostIds, profileNames:profiles.map(p=>`${p.label}（${p.id}）`), hostNames:hostIds.map(id=>`${hosts.find(h=>h.id===id)?.name || '未知主机'}（${id}）`), contents:canonical({catalog,hosts})};
}
// Compare complete public catalog and host content, even if a producer reuses a revision.
const canonical = value => JSON.stringify(value, function(k,v) { return v && typeof v==='object' && !Array.isArray(v) ? Object.fromEntries(Object.keys(v).sort().map(key=>[key,v[key]])) : v; });
const fingerprint = canonical;

let activeDialog=null, writeInFlight=null;
export function openZeroTierDeviceReview({invoke, beforeForget, onSettled=()=>{}}) {
  activeDialog?.close();
  let epoch=0, busy=false, closed=false, review=null, state=null, choice=null;
  const prior=document.activeElement, dialog=document.createElement('dialog');
  dialog.setAttribute('aria-labelledby','zerotier-device-title');
  const el=(tag,text='')=>{const n=document.createElement(tag);n.textContent=text;return n;};
  const restoreFocus=()=>{const target=prior?.isConnected===false ? document.getElementById?.('network-open') : prior;target?.focus?.();};
  const close=()=>{if(closed)return;closed=true;epoch++;cleanup();dialog.close();dialog.remove();if(activeDialog===controller)activeDialog=null;restoreFocus();};
  const invalidate=()=>{epoch++;choice=null;review=null;state=null;if(!closed)render('审查已失效，请重新读取。');};
  const visibility=()=>{if(document.hidden)invalidate();};
  const pagehide=()=>invalidate();
  const blur=()=>invalidate();
  const cleanup=()=>{document.removeEventListener('visibilitychange',visibility);window.removeEventListener('pagehide',pagehide);window.removeEventListener('blur',blur);};
  dialog.addEventListener('close',()=>{if(closed)return;closed=true;epoch++;cleanup();dialog.remove();if(activeDialog===controller)activeDialog=null;restoreFocus();});
  dialog.addEventListener('cancel',e=>{e.preventDefault();close();cleanup();});
  document.addEventListener('visibilitychange',visibility);window.addEventListener('pagehide',pagehide);window.addEventListener('blur',blur);
  function button(label,fn,disabled=false){const b=el('button',label);b.type='button';b.disabled=!!disabled;b.onclick=fn;return b;}
  async function read(message='', confirmedBy=null) {
    const current=++epoch;choice=null;review=null;state=null;render('正在读取设备和网络目录…');
    try {
      // Host-list failures must never become the empty cached list from home.
      // Device availability is independent of the public impact review.
      const [catalog,hosts,status]=await Promise.allSettled([invoke('network_list'),invoke('host_list'),invoke('zerotier_device_status')]);
      if(closed || current!==epoch || document.hidden)return;
      if(catalog.status!=='fulfilled' || hosts.status!=='fulfilled')throw Error('unknown impact');
      review=deviceReview(catalog.value,hosts.value);
      if(status.status!=='fulfilled' || !validDeviceStatus(status.value) || !status.value.available) {
        render('设备状态未知或共享设备能力不可用；受影响范围已列出，不能执行设备操作。');return;
      }
      state=status.value;render(confirmedBy && !confirmedBy(state) ? '操作结果未确认；请核对当前状态，不会自动重试。' : message);
    } catch {if(!closed && current===epoch)render('网络目录或主机清单不可用，受影响范围未知；不能执行设备操作。');}
  }
  function render(message='') {
    if(closed)return;const focused=dialog.contains(document.activeElement), focusedText=focused ? document.activeElement.textContent : null;dialog.replaceChildren();const title=el('h2','ZeroTier 共享设备');title.id='zerotier-device-title';title.tabIndex=-1;dialog.append(title,el('p','此设备身份由所有 ZeroTier 网络配置共享；设备存在不代表已入网或可连接。'));
    const status=el('p',message);status.setAttribute('role','status');status.setAttribute('aria-live','polite');dialog.append(status);
    if(review) {
      dialog.append(el('p',`受影响网络：${review.profileNames.join('、') || '无'}`),el('p',`受影响主机：${review.hostNames.join('、') || '无'}`));
    }
    if(review && state) {
      if(state.device)dialog.append(el('p',`身份记录编号：${state.device.handle}`));
      else dialog.append(el('p','当前没有已确认的共享设备。'));
      if(state.pendingCreation)dialog.append(el('p',`待定创建：${state.pendingCreation.handle} · ${state.pendingCreation.phase}`));
      if(state.pendingDeletion)dialog.append(el('p',`待定删除：${state.pendingDeletion.handle} · ${state.pendingDeletion.phase}；可审查后继续处理。`));
      const actions=el('div');actions.className='row';
      const select=(action,label,disabled=false)=>actions.append(button(label,()=>{choice=action;render('请核对上方全部受影响网络和主机，再确认操作。');},busy||writeInFlight||disabled));
      if(!state.pendingDeletion && !state.pendingCreation && !state.device)select('create','创建共享设备');
      if(!state.pendingDeletion && !state.pendingCreation && state.device)select('forget','删除共享设备',typeof beforeForget!=='function');
      if(state.pendingCreation && !state.pendingDeletion) {if(['record-present','finishing'].includes(state.pendingCreation.phase))select('recoverPendingCreation','恢复待定创建');if(['record-pending','finishing'].includes(state.pendingCreation.phase))select('discardPendingCreation','放弃待定创建');if(state.pendingCreation.phase==='finishing')dialog.append(el('p','恢复只接纳已安装记录；放弃仅清理未安装记录。若状态不符会拒绝，请重新读取状态。'));}
      if(state.pendingDeletion)select('recoverPendingDeletion','恢复待定删除');
      if(state.device && typeof beforeForget!=='function')dialog.append(el('p','当前版本暂不支持移除此设备身份。'));
      dialog.append(actions);
      if(choice){const desc={create:'创建共享设备',forget:'删除共享设备',recoverPendingCreation:'恢复待定创建',discardPendingCreation:'放弃待定创建',recoverPendingDeletion:'恢复待定删除'};dialog.append(el('p',`确认${desc[choice]}？此操作影响上面列出的全部网络和主机。`),button('确认操作',()=>void write(),busy),button('取消操作',()=>{choice=null;render();},busy));}
    }
    const actions=el('div');actions.className='row dialog-actions';actions.append(button('刷新状态',()=>void read(),false),button('关闭',close));dialog.append(actions);
    if(focused && !document.hidden && dialog.open) {const target=[...dialog.querySelectorAll('button')].find(b=>b.textContent===focusedText && !b.disabled);(target || title).focus();}
  }
  async function write() {
    if(busy || writeInFlight || !choice || !review || !state || document.hidden)return;
    const action=choice, reviewed=review, original=state, current=epoch;choice=null;busy=true;const writeToken={};writeInFlight=writeToken;render('正在核对审查内容…');
    try {
      const [catalog,hosts,status]=await Promise.all([invoke('network_list'),invoke('host_list'),invoke('zerotier_device_status')]);
      if(closed || current!==epoch || document.hidden || !validDeviceStatus(status) || !status.available || fingerprint(deviceReview(catalog,hosts))!==fingerprint(reviewed) || fingerprint(status)!==fingerprint(original)) throw Error('stale');
      const args={action,catalogRevision:reviewed.catalogRevision,profileIds:reviewed.profileIds,hostIds:reviewed.hostIds,handle:action==='forget'?original.device.handle:action==='create'?null:action==='recoverPendingDeletion'?original.pendingDeletion.handle:original.pendingCreation.handle,instanceId:action==='forget'?original.device.instanceId:null,expectedPhase:action==='create'||action==='forget'?null:action==='recoverPendingDeletion'?original.pendingDeletion.phase:original.pendingCreation.phase};
      if(action==='forget') {if(typeof beforeForget!=='function')throw Error('no stop');const {expectedPhase,...forgetReview}=args;if(await beforeForget(forgetReview) !== true)throw Error('stop unconfirmed');if(closed || current!==epoch || document.hidden)throw Error('stale');
        const [again,againHosts,device]=await Promise.all([invoke('network_list'),invoke('host_list'),invoke('zerotier_device_status')]);
        if(closed || current!==epoch || document.hidden || fingerprint(deviceReview(again,againHosts))!==fingerprint(reviewed) || fingerprint(device)!==fingerprint(original))throw Error('stale');
      }
      let result;
      try { result=await invoke('zerotier_device_write',args); } finally { await onSettled(reviewed.hostIds); }
      if (['create','recoverPendingCreation'].includes(action) ? !validDevice(result) : result !== null) throw Error('unconfirmed result');
      if (action==='recoverPendingCreation' && result.handle!==original.pendingCreation.handle) throw Error('wrong recovered identity');
      const confirmedBy = status => {
        if (action==='create' || action==='recoverPendingCreation') return status.device?.handle===result.handle && status.device?.instanceId===result.instanceId && !status.pendingCreation && !status.pendingDeletion;
        if (action==='forget') return !status.device && !status.pendingDeletion && !status.pendingCreation;
        if (action==='discardPendingCreation') return !status.device && !status.pendingCreation && !status.pendingDeletion;
        return !status.device && !status.pendingCreation && !status.pendingDeletion;
      };
      busy=false;if(writeInFlight===writeToken)writeInFlight=null;if(!closed && current===epoch)await read('操作已确认；请核对当前设备状态。',confirmedBy);
    } catch {busy=false;if(writeInFlight===writeToken)writeInFlight=null;if(!closed && current===epoch)await read('操作未确认或审查已失效；请核对当前状态，不会自动重试。');}
    finally {if(writeInFlight===writeToken)writeInFlight=null;if(!writeInFlight && activeDialog && activeDialog!==controller)void activeDialog.refresh();}
  }
  const controller={close,refresh:()=>void read(),invalidate};activeDialog=controller;
  document.body.append(dialog);render();dialog.showModal();dialog.querySelector('h2')?.focus();void read();return controller;
}
