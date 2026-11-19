import { nodePresentation } from './network-node-state.js';
import { NetworkLoginPoll } from './network-login-poll.js';
import { openZeroTierDeviceReview } from './zerotier-device-ui.js';
// A write may have committed or cancelled a connection even when its result is unknown.
// Always invalidate reviewed hosts and await their refresh before reloading the catalog.
export async function settleNetworkOperation(work, affected, onAffected, load) {
  let completed=false;
  try { await work(); completed=true; } catch { /* result may be unknown */ }
  try { await onAffected(affected); } catch { completed=false; }
  await load(completed ? '操作已确认；请查看节点及连接状态。' : '操作结果未确认，受影响连接已停止；请先核对主机和网络配置的当前状态。');
  return completed;
}
// Network configuration is public metadata; provider identities remain native.
export function initNetworkUI({native, invoke, getHosts, onAffected, prepareStop=async()=>{}, pollOptions, beforeForgetZeroTier, showEmpty=()=>false}) {
  const panel=document.getElementById('network-panel'), open=document.getElementById('network-open');
  let deviceReviewDialog=null, forceManager=false;
  let renderedReview=null, renderEpoch=0;
  const expandedProfiles=new Set();
  let bindingRows=new Map();
  const bindingChanged='主机或网络配置已变化，未应用的网络绑定已丢弃；请重新选择并核对。';
  let catalog=null, editing=null, identityEditor=null, identityStates=new Map(), nodeStates=new Map(), busy=false, pendingStart=false, stopBusy=false, nodeEpoch=0, loadRevision=0;
  const poller=new NetworkLoginPoll(pollOptions);
  const managed=p=>['easytier','tailscale'].includes(p.provider);
  function retirePublication(){renderedReview=null;poller.stop();nodeEpoch++;loadRevision++;for(const node of nodeStates.values()){if(node){node.authUrl=null;node.reviewToken=null;}}}
  function clearSecrets() {panel.querySelectorAll('input[type=password]').forEach(input=>{input.value='';});}
  const identityReads=new Set();
  async function readIdentity(id) {
    const pending=Promise.resolve().then(()=>invoke('network_identity_status',{id}));identityReads.add(pending);
    try{return await pending;}finally{identityReads.delete(pending);}
  }
  async function beforeIdentityWrite(epoch) {
    while(identityReads.size)await Promise.allSettled([...identityReads]);
    if(epoch!==nodeEpoch || panel.hidden || document.hidden)throw Error('network_review_stale');
  }
  const el=(tag,text='',className='')=>{const n=document.createElement(tag);n.textContent=text;if(className)n.className=className;return n;};
  const button=(text,fn,allowDuringStart=false)=>{const b=el('button',text);b.type='button';b.disabled=stopBusy || (busy && !(allowDuringStart && pendingStart));b.onclick=fn;return b;};
  function stopButton(fn) {
    // A touch click can retarget after a rebuild; only its pressed review may stop.
    const b=button('停止节点',fn,true),frame=renderEpoch;let pressed=false,epoch;
    b.onpointerdown=()=>{pressed=true;epoch=nodeEpoch;};
    b.onclick=event=>{const current=!event?.detail || (pressed && renderedReview!==null && frame===renderEpoch && epoch===nodeEpoch);pressed=false;if(current)fn(event);};
    return b;
  }
  const label=(text,input)=>{const l=el('label',text);l.append(input);return l;};
  const field=(value='',placeholder='')=>{const n=document.createElement('input');n.value=value;n.placeholder=placeholder;n.autocomplete='off';return n;};
  const names=ids=>ids.map(id=>getHosts().find(h=>h.id===id)?.name || id).join('、') || '无';
  function bindingReview(hostId,profileId,reviewed=catalog) {
    const matches=getHosts().filter(host=>host.id===hostId),host=matches[0];
    if(!native || !reviewed || matches.length!==1 || host.enabled!==true || host.retired || host.keyDeletionPending || host.keyCleanupMode!=null || host.pairingStatus==='revoked')return null;
    const saved=reviewed.bindings.filter(binding=>binding.hostId===hostId);
    if(saved.length!==(host.networkProfileId?1:0) || (host.networkProfileId && saved[0]?.profileId!==host.networkProfileId))return null;
    const profile=profileId?reviewed.profiles.find(value=>value.id===profileId):null;
    if((profileId && !profile?.enabled) || (host.requiresNetworkBinding && (!profile || profile.provider!==host.provider)))return null;
    return JSON.stringify([host,reviewed]);
  }
  function discardChangedBindings(reviewed=catalog) {
    let discarded=false;
    for(const [hostId,row] of bindingRows)if(bindingReview(hostId,row.select.value || null,reviewed)!==row.review) {
      if((row.select.value || null)!==row.saved){row.select.value=row.saved || '';discarded=true;}
      bindingRows.delete(hostId);
    }
    return discarded;
  }
  const viewReview=(fresh,states,nodes)=>JSON.stringify([fresh,[...states],[...nodes],getHosts(),editing,identityEditor,busy,pendingStart,stopBusy,nodeEpoch]);
  async function load(message='',polling=false,permit=()=>true) {const revision=++loadRevision;const current=()=>revision===loadRevision && !panel.hidden && !document.hidden && permit();try {
    const fresh=await invoke('network_list');const states=new Map(), nodes=new Map();
    for(const profile of fresh.profiles) {if(!current())return false;if(managed(profile)) {
      if(busy || stopBusy)states.set(profile.id,identityStates.get(profile.id) ?? null);
      else try {const value=await readIdentity(profile.id);states.set(profile.id,value && typeof value.supported==='boolean' ? value : null);}catch {states.set(profile.id,null);}
    }}
    for(const profile of fresh.profiles) {if(!current())return false;if(managed(profile)) {try {
      let node=await invoke('network_node_status',{id:profile.id});
      if(!busy && !stopBusy && profile.provider==='tailscale' && node?.binding && ['needs-login','needs-machine-auth','running'].includes(node.state)) {
        const affected=fresh.bindings.filter(b=>b.profileId===profile.id).map(b=>b.hostId);
        if(!current())return false;try {node=await invoke('network_node_login_status',{id:profile.id,expectedCatalog:fresh.revision,expectedRevision:profile.revision,affected,binding:node.binding});} catch {node={...node,authUrl:null,reviewToken:null};}
      }
      // The native host only publishes paired, reviewed URL+token fields.
      if(node && !(typeof node.authUrl==='string' && typeof node.reviewToken==='string')){node={...node,authUrl:null,reviewToken:null};}
      nodes.set(profile.id,node);
    }catch {nodes.set(profile.id,null);}}}
    if(!current())return false;
    const pending=fresh.profiles.some(p=>p.provider==='tailscale' && ['starting','needs-login','needs-machine-auth'].includes(nodes.get(p.id)?.state));
    // Keep the active form and its reviewed catalog revision; polling still reads.
    if(editing || identityEditor) {const discarded=discardChangedBindings(fresh),status=panel.querySelector('[role=status]');if((message || discarded) && status)status.textContent=discarded?bindingChanged:message;}
    else {
      if(catalog && JSON.stringify(catalog)!==JSON.stringify(fresh))deviceReviewDialog?.invalidate();
      const status=panel.querySelector('[role=status]');
      const bindingsCurrent=[...bindingRows].every(([id,row])=>(row.select.value || null)===row.saved || bindingReview(id,row.select.value || null,fresh)===row.review);
      // Preserve both live nodes and their reviewed object references on identical reads.
      if(status && bindingsCurrent && renderedReview===viewReview(fresh,states,nodes)) {if(message)status.textContent=message;}
      else {catalog=fresh;identityStates=states;nodeStates=nodes;render(message);}
    }
    if(!polling && pending)poller.start(live=>load('',true,live));
    return pending;
  }catch {if(!current())return false;renderedReview=null;const discarded=discardChangedBindings(null);if(editing || identityEditor){const status=panel.querySelector('[role=status]');if(status)status.textContent=discarded?'网络配置读取失败，未应用的主机绑定已丢弃；请核对当前状态。':'网络配置读取失败，草稿仍保留；保存前请先核对当前状态。';return false;}catalog=null;identityStates.clear();nodeStates.clear();clearSecrets();panel.replaceChildren(el('p','网络配置读取失败，当前状态未知；请稍后核对。'));return false;}}
  async function operation(work,affected) {if(busy||stopBusy)return;retirePublication();const epoch=nodeEpoch;busy=true;try {await settleNetworkOperation(async()=>{await beforeIdentityWrite(epoch);await work();editing=null;},affected,onAffected,async message=>{busy=false;await load(message);});}finally{busy=false;}}
  async function identityOperation(profile,affected,action,mode,secret,expectedHandle=null) {
    if(busy||stopBusy)return;retirePublication();const epoch=nodeEpoch;busy=true;
    const args={id:profile.id,expectedCatalog:catalog.revision,expectedRevision:profile.revision,affected,action,mode,secret,expectedHandle};
    try {
      await settleNetworkOperation(async()=>{try {await beforeIdentityWrite(epoch);return await invoke('network_identity_write',args);} finally {args.secret='';secret='';}},affected,onAffected,async message=>{busy=false;await load(message);});
    } finally {busy=false;}
  }
  async function nodeOperation(profile,affected,action,expectedHandle,binding) {
    const stopping=action==='stop';
    if(stopping ? (stopBusy || (busy && !pendingStart) || !binding) : (busy || stopBusy))return;
    if(stopping)stopBusy=true;else {busy=true;pendingStart=true;}
    retirePublication();const operationEpoch=nodeEpoch;
    const args={id:profile.id,expectedCatalog:catalog.revision,expectedRevision:profile.revision,affected,expectedHandle,binding};
    const status=panel.querySelector('[role=status]');if(status)status.textContent=stopping?'正在停止本机节点；请等待结果。':action==='login'?'正在请求显式登录；不会自动打开网页。':'正在启动本机节点；尚未确认入网。';
    let completed=false;
    try {
      // Retire input without aborting the original SSH before native stop.
      if(stopping)await prepareStop(affected);else await onAffected(affected);
      if(!stopping)await beforeIdentityWrite(operationEpoch);
      const pending=invoke(`network_node_${action}`,args);
      if(!stopping)void load('节点请求已发送；可刷新状态并停止原节点。');
      await pending;completed=true;
    } catch { /* Native outcome may be unknown; never retry automatically. */ }
    finally {
      if(stopping)stopBusy=false;else {pendingStart=false;busy=false;}
      if(operationEpoch===nodeEpoch) await load(completed?'节点操作已确认；请核对当前节点状态。':'节点操作结果未确认；请核对当前状态，不会自动重试。');
      else if(!panel.hidden && !stopBusy)await load('请核对当前节点状态；不会自动重试。');
    }
  }
  async function openAuthorization(profile,affected,node) {
    if(busy||stopBusy || panel.hidden || document.hidden)return;
    const epoch=nodeEpoch, current=nodeStates.get(profile.id);
    if(current!==node || typeof node.authUrl!=='string' || typeof node.reviewToken!=='string')return;
    const args={id:profile.id,expectedCatalog:catalog.revision,expectedRevision:profile.revision,affected,binding:node.binding,expectedAuthUrl:node.authUrl,reviewToken:node.reviewToken};
    if(!confirm(`通过系统打开 ${profile.label} 的 Tailscale 授权页面？请核对浏览器或应用显示的设备和控制服务。`))return;
    busy=true;
    try {await beforeIdentityWrite(epoch);await invoke('network_node_open_auth',args);}
    catch {if(epoch===nodeEpoch)await load('授权入口已失效或打开结果未知；请核对当前节点状态，不会自动重试。');}
    finally {busy=false;}
  }
  function startNewProfile() {
    editing={id:'0'.repeat(32),label:'',provider:'tailscale',enabled:true,revision:1,settings:{controlUrl:'',hostname:''}};
    render();
  }
  function render(message='') {
    if(discardChangedBindings())message=bindingChanged;
    const previousBindings=bindingRows;bindingRows=new Map();
    if(!catalog){renderedReview=null;return;}renderedReview=viewReview(catalog,identityStates,nodeStates);renderEpoch++;clearSecrets();panel.replaceChildren();
    if(native && showEmpty() && !forceManager && !editing && !identityEditor && typeof catalog.revision==='string' && catalog.revision.length>0 &&
       Number.isInteger(catalog.preferences?.terminalFontSize) && catalog.preferences.terminalFontSize>=10 && catalog.preferences.terminalFontSize<=28 &&
       Array.isArray(catalog.profiles) && catalog.profiles.length===0 && Array.isArray(catalog.bindings) && catalog.bindings.length===0) {
      const card=el('section','','network-empty-card');card.id='network-empty-card';
      const icon=el('span','','network-empty-icon');icon.setAttribute('aria-hidden','true');
      const globe=document.createElementNS('http://www.w3.org/2000/svg','svg'),path=document.createElementNS('http://www.w3.org/2000/svg','path');
      globe.setAttribute('viewBox','0 0 24 24');path.setAttribute('d','M12 3 A9 9 0 1 0 12 21 A9 9 0 1 0 12 3 M3 12 H21 M12 3 C6 7 6 17 12 21 C18 17 18 7 12 3');globe.append(path);icon.append(globe);
      card.append(icon,el('h3','还没有网络配置'),el('p','配置 ZeroTier、Tailscale 或 EasyTier 后，在这里管理网络。'),button('添加网络配置',startNewProfile));
      panel.append(card,button('管理网络与共享设备',()=>{forceManager=true;render();}));
      return;
    }
    panel.append(el('h2','网络配置'),el('p','公开配置和本机网络身份分开保存；身份不随配置导出。节点状态不代表已入网。'));
    const status=el('p',message);status.setAttribute('role','status');panel.append(status);
    panel.append(button('审查 ZeroTier 共享设备',()=>{deviceReviewDialog=openZeroTierDeviceReview({invoke,beforeForget:beforeForgetZeroTier,onSettled:async ids=>{await onAffected(ids);await load();}});}));
    for(const profile of catalog.profiles) {
      const affected=catalog.bindings.filter(b=>b.profileId===profile.id).map(b=>b.hostId);
      const card=el('article','','saved-host-card network-profile-card');
      const providerName={tailscale:'Tailscale',easytier:'EasyTier',zerotier:'ZeroTier'}[profile.provider] || profile.provider;
      card.append(el('h3',`${profile.label} · ${providerName}`),el('p',profile.enabled?'配置已启用':'配置已停用'));
      card.append(el('p',`绑定主机：${affected.length ? names(affected) : '无'}`));
      const identity=identityStates.get(profile.id);
      const identityText=!managed(profile)?'本机身份：待接入':identity===null || identity===undefined?'本机身份状态未知，请核查设备':!identity.supported?'本平台本机身份待接入':!identity.available?'本机身份状态未知，请核查设备':identity.present?`本机身份已保存 · ${identity.mode==='DEVICE_STATE'?'设备状态（本机加密保存）':identity.mode==='PRIVATE'?'私有网络':'公开无秘密'}`:'本机身份尚未创建';
      const node=nodeStates.get(profile.id), nodeView=nodePresentation(profile,identity,node);card.append(el('p',nodeView.text));
      const management=el('details','','network-profile-management');management.open=expandedProfiles.has(profile.id);
      management.ontoggle=()=>{if(management.open)expandedProfiles.add(profile.id);else expandedProfiles.delete(profile.id);};
      const summary=el('summary','管理网络');
      summary.onclick=()=>{if(management.open)expandedProfiles.delete(profile.id);else expandedProfiles.add(profile.id);};
      management.append(summary,el('p',identityText));
      const actions=el('div','','saved-host-actions');actions.append(button('编辑',()=>{editing=profile;render();}),button(profile.enabled?'停用':'启用',()=>{if(!confirm(`将${profile.enabled?'停用':'启用'} ${profile.label}。受影响主机：${names(affected)}。继续？`))return;void operation(()=>invoke('network_save',{profile:{...profile,enabled:!profile.enabled},expectedCatalog:catalog.revision,expectedRevision:profile.revision,affected}),affected);}));
      if(nodeView.canStart && identity?.handle)actions.append(button('启动节点',()=>{if(!confirm(`启动 ${profile.label} 的本机节点？启动不代表入网或连接。`))return;void nodeOperation(profile,affected,'start',identity.handle,null);}));
      if(nodeView.canStop && node?.binding)actions.append(stopButton(()=>{if(!confirm(`停止 ${profile.label} 的本机节点？受影响主机：${names(affected)}。`))return;void nodeOperation(profile,affected,'stop',null,node.binding);}));
      if(nodeView.canLogin && node?.binding)actions.append(button('登录 Tailscale',()=>{if(confirm(`为 ${profile.label} 显式发起登录？不会自动打开网页。`))void nodeOperation(profile,affected,'login',identity.handle,node.binding);}));
      if(profile.provider==='tailscale' && ['needs-login','needs-machine-auth'].includes(node?.state) && node.authUrl && node.reviewToken)actions.append(button('打开授权页面',()=>void openAuthorization(profile,affected,node)));
      if(managed(profile))actions.append(button('刷新节点状态',()=>void load('已请求读取当前节点状态。'),true));
      if(managed(profile) && identity?.supported && identity.available) {
        if(identity.present && identity.handle)actions.append(button('删除本机身份',()=>{if(!confirm(`删除 ${profile.label} 的本机网络身份？受影响主机：${names(affected)}。此操作不会删除 SSH 配对密钥。`))return;void identityOperation(profile,affected,'delete','','',identity.handle);}));
        else if(!identity.present)actions.append(button('配置本机身份',()=>{if(profile.provider==='tailscale'){if(confirm(`为 ${profile.label} 创建本机加密设备状态？不包含 auth key，也不会自动登录。`))void identityOperation(profile,affected,'create','DEVICE_STATE','');}else{identityEditor=profile;editing=null;render();}}));
      }
      const deleteReason=affected.length ? `仍被主机引用：${names(affected)}。请先逐一更换或解除绑定。` : managed(profile) && (!identity || (identity.supported && (!identity.available || identity.present))) ? (identity?.present?'请先明确删除此设备上的网络身份。':'本机身份状态未确认，不能删除配置。') : '';
      const del=button('删除',()=>{if(deleteReason)return;if(confirm(`删除 ${profile.label}？`))void operation(()=>invoke('network_delete',{id:profile.id,expectedCatalog:catalog.revision,expectedRevision:profile.revision}),[]);});
      if(deleteReason){del.disabled=true;del.title=deleteReason;actions.append(el('p',deleteReason));}
      actions.append(del);management.append(actions);card.append(management);panel.append(card);
    }
    panel.append(button('新增网络配置',startNewProfile));
    if(editing) {
      const form=el('form','','network-editor');form.append(el('h3',catalog.profiles.some(p=>p.id===editing.id)?'编辑网络':'新增网络'));
      const name=field(editing.label,'配置名称');name.maxLength=96;name.required=true;form.append(label('名称',name));
      const provider=document.createElement('select');for(const p of ['tailscale','easytier','zerotier']){const o=el('option',p);o.value=p;provider.append(o);}provider.value=editing.provider;provider.disabled=catalog.profiles.some(p=>p.id===editing.id);form.append(label('服务商',provider));
      const settings=el('div');form.append(settings);let inputs={};
      function drawSettings() {settings.replaceChildren();inputs={};const initial=provider.value===editing.provider?editing.settings:{};
        const add=(key,title,placeholder='')=>{inputs[key]=field(initial[key] || '',placeholder);settings.append(label(title,inputs[key]));};
        if(provider.value==='tailscale'){add('controlUrl','控制地址（留空使用默认）','https://');add('hostname','设备名称（留空自动）');}
        if(provider.value==='easytier'){add('networkName','网络名称');const area=document.createElement('textarea');area.rows=3;area.value=(initial.peers || []).join('\n');area.placeholder='每行一个 tcp://、udp://、ws:// 或 wss:// 地址';inputs.peers=area;settings.append(label('公开节点地址',area));}
        if(provider.value==='zerotier')add('networkId','网络 ID（16 位小写十六进制）');
      }provider.onchange=drawSettings;drawSettings();
      const save=el('button','保存配置');save.type='submit';form.append(save,button('取消',()=>{editing=null;void load();}));
      form.onsubmit=e=>{e.preventDefault();const profile={...editing,label:name.value,provider:provider.value,settings:Object.fromEntries(Object.entries(inputs).map(([k,v])=>[k,k==='peers'?v.value.split('\n').map(s=>s.trim()).filter(Boolean):v.value]))};const exists=catalog.profiles.some(p=>p.id===editing.id);const affected=catalog.bindings.filter(b=>b.profileId===editing.id).map(b=>b.hostId);if(exists && !confirm(`保存将停止受影响连接：${names(affected)}。继续？`))return;void operation(()=>invoke('network_save',{profile,expectedCatalog:catalog.revision,expectedRevision:exists?editing.revision:null,affected}),affected);};panel.append(form);
    }
    if(identityEditor) {
      const p=identityEditor, affected=catalog.bindings.filter(b=>b.profileId===p.id).map(b=>b.hostId);const form=el('form','','network-editor');form.append(el('h3',`配置本机身份 · ${p.label}`),el('p',`本机保存不代表入网或连接；受影响主机：${names(affected)}。`));
      const select=document.createElement('select');for(const [value,title] of [['PRIVATE','私有网络（需要秘密）'],['PUBLIC_NO_SECRET','公开网络（无秘密）']]) {const option=el('option',title);option.value=value;select.append(option);}select.value='PRIVATE';form.append(label('网络模式',select));
      const secret=field('','输入本机网络秘密');secret.type='password';secret.autocomplete='off';secret.maxLength=1024;const secretLabel=label('网络秘密',secret);form.append(secretLabel);select.onchange=()=>{secret.value='';secret.disabled=select.value==='PUBLIC_NO_SECRET';};
      const save=el('button','保存本机身份');save.type='submit';form.append(save,button('取消',()=>{secret.value='';identityEditor=null;void load();}));
      form.onsubmit=e=>{e.preventDefault();if(busy||stopBusy)return;const mode=select.value, value=secret.value;const bytes=new TextEncoder().encode(value);const valid=bytes.length<=1024 && !value.includes('\0') && (mode==='PRIVATE'?bytes.length>0:mode==='PUBLIC_NO_SECRET'&&bytes.length===0);bytes.fill(0);if(!valid){secret.value='';status.textContent='私有网络需输入 1–1024 字节秘密；公开网络必须为空，不能包含 NUL。';return;}if(!confirm(`为 ${p.label} 保存本机网络身份？受影响主机：${names(affected)}。`)){secret.value='';return;}secret.value='';identityEditor=null;void identityOperation(p,affected,'create',mode,value);};panel.append(form);
    }
    const hostSection=el('section');hostSection.append(el('h3','主机网络绑定'));for(const host of getHosts().filter(h=>!h.retired)) {
      const previous=previousBindings.get(host.id);
      if(previous && (previous.select.value || null)!==previous.saved) {
        previous.select.disabled=busy || stopBusy;previous.apply.disabled=busy || stopBusy;
        bindingRows.set(host.id,previous);hostSection.append(previous.row);continue;
      }
      const row=el('div','','network-binding');row.append(el('strong',host.name));const select=document.createElement('select');const direct=el('option','系统连接（原有方式）');direct.value='';select.append(direct);for(const p of catalog.profiles){const o=el('option',`${p.label} · ${p.provider}${p.enabled?'':'（已停用）'}`);o.value=p.id;o.disabled=!p.enabled;select.append(o);}select.value=host.networkProfileId || '';
      const record={row,select,saved:host.networkProfileId || null,review:JSON.stringify([host,catalog])};
      const apply=button('应用',()=>{
        if(busy || stopBusy || bindingRows.get(host.id)!==record)return;
        const profileId=select.value || null;
        const current=()=>bindingRows.get(host.id)===record && (select.value || null)===profileId && bindingReview(host.id,profileId)===record.review;
        if(!current()){bindingRows.delete(host.id);renderedReview=null;void load(bindingChanged);return;}
        if(profileId===record.saved)return;
        const isDirect=!!record.saved && !profileId;
        const args={hostId:host.id,profileId,expectedCatalog:catalog.revision,confirmedDirect:isDirect};
        if(!confirm(isDirect?`解除 ${host.name} 的网络绑定并改为系统直连？这会停止该主机连接。`:`更改 ${host.name} 的网络绑定并停止其连接？`))return;
        if(!current()){bindingRows.delete(host.id);renderedReview=null;void load(bindingChanged);return;}
        void operation(()=>{if(!current())throw Error('network_bind_review_stale');bindingRows.delete(host.id);return invoke('network_bind',args);},[host.id]);
      });record.apply=apply;bindingRows.set(host.id,record);row.append(select,apply);hostSection.append(row);
    }panel.append(hostSection);
  }
  open.disabled=!native;open.onclick=()=>{deviceReviewDialog?.close();deviceReviewDialog=null;retirePublication();clearSecrets();bindingRows.clear();identityEditor=null;panel.hidden=!panel.hidden;if(!panel.hidden){forceManager=false;if(panel.querySelector('#network-empty-card'))panel.replaceChildren(el('p','正在读取网络配置…'));void load();}};
  const responsive=globalThis.window?.matchMedia?.('(min-width:600px)');
  responsive?.addEventListener?.('change',()=>{if(catalog && !panel.hidden && !document.hidden && !editing && !identityEditor)render();});
  document.addEventListener('visibilitychange',()=>{retirePublication();clearSecrets();bindingRows.clear();identityEditor=null;if(!document.hidden && !panel.hidden)void load('已返回应用；正在核对原配置与当前节点。');});
  window.addEventListener('pagehide',()=>{retirePublication();clearSecrets();bindingRows.clear();});
  return {refresh:()=>{if(!panel.hidden)void load();},reconcile:()=>{if(catalog && !panel.hidden && !document.hidden && !editing && !identityEditor)render();},close:()=>{deviceReviewDialog?.close();deviceReviewDialog=null;retirePublication();clearSecrets();bindingRows.clear();identityEditor=null;panel.hidden=true;}};
}
