import { nodePresentation } from './network-node-state.js';
import { NetworkLoginPoll } from './network-login-poll.js';
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
export function initNetworkUI({native, invoke, getHosts, onAffected, pollOptions}) {
  const panel=document.getElementById('network-panel'), open=document.getElementById('network-open');
  let catalog=null, editing=null, identityEditor=null, identityStates=new Map(), nodeStates=new Map(), busy=false, pendingStart=false, stopBusy=false, nodeEpoch=0, loadRevision=0;
  const poller=new NetworkLoginPoll(pollOptions);
  const managed=p=>['easytier','tailscale'].includes(p.provider);
  function retirePublication(){poller.stop();nodeEpoch++;loadRevision++;for(const node of nodeStates.values()){if(node){node.authUrl=null;node.reviewToken=null;}}}
  function clearSecrets() {panel.querySelectorAll('input[type=password]').forEach(input=>{input.value='';});}
  const el=(tag,text='',className='')=>{const n=document.createElement(tag);n.textContent=text;if(className)n.className=className;return n;};
  const button=(text,fn,allowDuringStart=false)=>{const b=el('button',text);b.type='button';b.disabled=stopBusy || (busy && !(allowDuringStart && pendingStart));b.onclick=fn;return b;};
  const label=(text,input)=>{const l=el('label',text);l.append(input);return l;};
  const field=(value='',placeholder='')=>{const n=document.createElement('input');n.value=value;n.placeholder=placeholder;n.autocomplete='off';return n;};
  const names=ids=>ids.map(id=>getHosts().find(h=>h.id===id)?.name || id).join('、') || '无';
  async function load(message='',polling=false,permit=()=>true) {const revision=++loadRevision;const current=()=>revision===loadRevision && !panel.hidden && !document.hidden && permit();try {
    const fresh=await invoke('network_list');const states=new Map(), nodes=new Map();
    for(const profile of fresh.profiles) {if(!current())return false;if(managed(profile)) {try {const value=await invoke('network_identity_status',{id:profile.id});states.set(profile.id,value && typeof value.supported==='boolean' ? value : null);}catch {states.set(profile.id,null);}}}
    for(const profile of fresh.profiles) {if(!current())return false;if(managed(profile)) {try {
      let node=await invoke('network_node_status',{id:profile.id});
      if(profile.provider==='tailscale' && node?.binding && ['needs-login','needs-machine-auth','running'].includes(node.state)) {
        const affected=fresh.bindings.filter(b=>b.profileId===profile.id).map(b=>b.hostId);
        if(!current())return false;try {node=await invoke('network_node_login_status',{id:profile.id,expectedCatalog:fresh.revision,expectedRevision:profile.revision,affected,binding:node.binding});} catch {node={...node,authUrl:null,reviewToken:null};}
      }
      // The native host only publishes paired, reviewed URL+token fields.
      if(node && !(typeof node.authUrl==='string' && typeof node.reviewToken==='string')){node={...node,authUrl:null,reviewToken:null};}
      nodes.set(profile.id,node);
    }catch {nodes.set(profile.id,null);}}}
    if(!current())return false;
    catalog=fresh;identityStates=states;nodeStates=nodes;render(message);
    const pending=fresh.profiles.some(p=>p.provider==='tailscale' && ['starting','needs-login','needs-machine-auth'].includes(nodes.get(p.id)?.state));
    if(!polling && pending)poller.start(live=>load('',true,live));
    return pending;
  }catch {if(!current())return false;catalog=null;identityStates.clear();nodeStates.clear();clearSecrets();panel.replaceChildren(el('p','网络配置读取失败，当前状态未知；请稍后核对。'));return false;}}
  async function operation(work,affected) {if(busy||stopBusy)return;retirePublication();busy=true;try {await settleNetworkOperation(async()=>{await work();editing=null;},affected,onAffected,async message=>{busy=false;await load(message);});}finally{busy=false;}}
  async function identityOperation(profile,affected,action,mode,secret,expectedHandle=null) {
    if(busy||stopBusy)return;retirePublication();busy=true;
    const args={id:profile.id,expectedCatalog:catalog.revision,expectedRevision:profile.revision,affected,action,mode,secret,expectedHandle};
    try {
      await settleNetworkOperation(async()=>{try {return await invoke('network_identity_write',args);} finally {args.secret='';secret='';}},affected,onAffected,async message=>{busy=false;await load(message);});
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
      // Revoke the reviewed view before starting or stopping the native node.
      await onAffected(affected);
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
    try {await invoke('network_node_open_auth',args);}
    catch {if(epoch===nodeEpoch)await load('授权入口已失效或打开结果未知；请核对当前节点状态，不会自动重试。');}
    finally {busy=false;}
  }
  function render(message='') {
    if(!catalog)return;clearSecrets();panel.replaceChildren();panel.append(el('h2','网络配置'),el('p','公开配置和本机网络身份分开保存；身份不随配置导出。节点状态不代表已入网。'));
    const status=el('p',message);status.setAttribute('role','status');panel.append(status);
    for(const profile of catalog.profiles) {
      const affected=catalog.bindings.filter(b=>b.profileId===profile.id).map(b=>b.hostId);
      const card=el('article','','saved-host-card');card.append(el('h3',profile.label),el('p',`${profile.provider} · ${profile.enabled?'已启用':'已停用'} · 受影响主机：${names(affected)}`));
      const identity=identityStates.get(profile.id);
      const identityText=!managed(profile)?'本机身份：待接入':identity===null || identity===undefined?'本机身份状态未知，请核查设备':!identity.supported?'本平台本机身份待接入':!identity.available?'本机身份状态未知，请核查设备':identity.present?`本机身份已保存 · ${identity.mode==='DEVICE_STATE'?'设备状态（本机加密保存）':identity.mode==='PRIVATE'?'私有网络':'公开无秘密'}`:'本机身份尚未创建';
      card.append(el('p',identityText));
      const node=nodeStates.get(profile.id), nodeView=nodePresentation(profile,identity,node);card.append(el('p',nodeView.text));
      const actions=el('div','','saved-host-actions');actions.append(button('编辑',()=>{editing=profile;render();}),button(profile.enabled?'停用':'启用',()=>{if(!confirm(`将${profile.enabled?'停用':'启用'} ${profile.label}。受影响主机：${names(affected)}。继续？`))return;void operation(()=>invoke('network_save',{profile:{...profile,enabled:!profile.enabled},expectedCatalog:catalog.revision,expectedRevision:profile.revision,affected}),affected);}));
      if(nodeView.canStart && identity?.handle)actions.append(button('启动节点',()=>{if(!confirm(`启动 ${profile.label} 的本机节点？启动不代表入网或连接。`))return;void nodeOperation(profile,affected,'start',identity.handle,null);}));
      if(nodeView.canStop && node?.binding)actions.append(button('停止节点',()=>{if(!confirm(`停止 ${profile.label} 的本机节点？受影响主机：${names(affected)}。`))return;void nodeOperation(profile,affected,'stop',null,node.binding);},true));
      if(nodeView.canLogin && node?.binding)actions.append(button('登录 Tailscale',()=>{if(confirm(`为 ${profile.label} 显式发起登录？不会自动打开网页。`))void nodeOperation(profile,affected,'login',identity.handle,node.binding);}));
      if(profile.provider==='tailscale' && ['needs-login','needs-machine-auth'].includes(node?.state) && node.authUrl && node.reviewToken)actions.append(button('打开授权页面',()=>void openAuthorization(profile,affected,node)));
      if(managed(profile))actions.append(button('刷新节点状态',()=>void load('已请求读取当前节点状态。'),true));
      if(managed(profile) && identity?.supported && identity.available) {
        if(identity.present && identity.handle)actions.append(button('删除本机身份',()=>{if(!confirm(`删除 ${profile.label} 的本机网络身份？受影响主机：${names(affected)}。此操作不会删除 SSH 配对密钥。`))return;void identityOperation(profile,affected,'delete','','',identity.handle);}));
        else if(!identity.present)actions.append(button('配置本机身份',()=>{if(profile.provider==='tailscale'){if(confirm(`为 ${profile.label} 创建本机加密设备状态？不包含 auth key，也不会自动登录。`))void identityOperation(profile,affected,'create','DEVICE_STATE','');}else{identityEditor=profile;editing=null;render();}}));
      }
      const del=button('删除',()=>{if(affected.length){status.textContent=`仍被主机引用：${names(affected)}。请先逐一更换或解除绑定。`;return;}if(managed(profile) && (!identity || (identity.supported && (!identity.available || identity.present)))){status.textContent=identity?.present?'请先明确删除此设备上的网络身份。':'本机身份状态未确认，不能删除配置。';return;}if(confirm(`删除 ${profile.label}？`))void operation(()=>invoke('network_delete',{id:profile.id,expectedCatalog:catalog.revision,expectedRevision:profile.revision}),[]);});actions.append(del);card.append(actions);panel.append(card);
    }
    panel.append(button('新增网络配置',()=>{editing={id:'0'.repeat(32),label:'',provider:'tailscale',enabled:true,revision:1,settings:{controlUrl:'',hostname:''}};render();}));
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
      const save=el('button','保存配置');save.type='submit';form.append(save,button('取消',()=>{editing=null;render();}));
      form.onsubmit=e=>{e.preventDefault();const profile={...editing,label:name.value,provider:provider.value,settings:Object.fromEntries(Object.entries(inputs).map(([k,v])=>[k,k==='peers'?v.value.split('\n').map(s=>s.trim()).filter(Boolean):v.value]))};const exists=catalog.profiles.some(p=>p.id===editing.id);const affected=catalog.bindings.filter(b=>b.profileId===editing.id).map(b=>b.hostId);if(exists && !confirm(`保存将停止受影响连接：${names(affected)}。继续？`))return;void operation(()=>invoke('network_save',{profile,expectedCatalog:catalog.revision,expectedRevision:exists?editing.revision:null,affected}),affected);};panel.append(form);
    }
    if(identityEditor) {
      const p=identityEditor, affected=catalog.bindings.filter(b=>b.profileId===p.id).map(b=>b.hostId);const form=el('form','','network-editor');form.append(el('h3',`配置本机身份 · ${p.label}`),el('p',`本机保存不代表入网或连接；受影响主机：${names(affected)}。`));
      const select=document.createElement('select');for(const [value,title] of [['PRIVATE','私有网络（需要秘密）'],['PUBLIC_NO_SECRET','公开网络（无秘密）']]) {const option=el('option',title);option.value=value;select.append(option);}select.value='PRIVATE';form.append(label('网络模式',select));
      const secret=field('','输入本机网络秘密');secret.type='password';secret.autocomplete='off';secret.maxLength=1024;const secretLabel=label('网络秘密',secret);form.append(secretLabel);select.onchange=()=>{secret.value='';secret.disabled=select.value==='PUBLIC_NO_SECRET';};
      const save=el('button','保存本机身份');save.type='submit';form.append(save,button('取消',()=>{secret.value='';identityEditor=null;render();}));
      form.onsubmit=e=>{e.preventDefault();if(busy||stopBusy)return;const mode=select.value, value=secret.value;const bytes=new TextEncoder().encode(value);const valid=bytes.length<=1024 && !value.includes('\0') && (mode==='PRIVATE'?bytes.length>0:mode==='PUBLIC_NO_SECRET'&&bytes.length===0);bytes.fill(0);if(!valid){secret.value='';status.textContent='私有网络需输入 1–1024 字节秘密；公开网络必须为空，不能包含 NUL。';return;}if(!confirm(`为 ${p.label} 保存本机网络身份？受影响主机：${names(affected)}。`)){secret.value='';return;}secret.value='';identityEditor=null;void identityOperation(p,affected,'create',mode,value);};panel.append(form);
    }
    const hostSection=el('section');hostSection.append(el('h3','主机网络绑定'));for(const host of getHosts().filter(h=>!h.retired)) {
      const row=el('div','','network-binding');row.append(el('strong',host.name));const select=document.createElement('select');const direct=el('option','系统连接（原有方式）');direct.value='';select.append(direct);for(const p of catalog.profiles){const o=el('option',`${p.label} · ${p.provider}${p.enabled?'':'（已停用）'}`);o.value=p.id;o.disabled=!p.enabled;select.append(o);}select.value=host.networkProfileId || '';row.append(select,button('应用',()=>{const profileId=select.value || null;if(profileId===(host.networkProfileId || null))return;const isDirect=!!host.networkProfileId && !profileId;if(!confirm(isDirect?`解除 ${host.name} 的网络绑定并改为系统直连？这会停止该主机连接。`:`更改 ${host.name} 的网络绑定并停止其连接？`))return;void operation(()=>invoke('network_bind',{hostId:host.id,profileId,expectedCatalog:catalog.revision,confirmedDirect:isDirect}),[host.id]);}));hostSection.append(row);
    }panel.append(hostSection);
  }
  open.disabled=!native;open.onclick=()=>{retirePublication();clearSecrets();identityEditor=null;panel.hidden=!panel.hidden;if(!panel.hidden)void load();};
  document.addEventListener('visibilitychange',()=>{retirePublication();clearSecrets();identityEditor=null;if(!document.hidden && !panel.hidden)void load('已返回应用；正在核对原配置与当前节点。');});
  window.addEventListener('pagehide',()=>{retirePublication();clearSecrets();});
  return {refresh:()=>{if(!panel.hidden)void load();},close:()=>{retirePublication();clearSecrets();identityEditor=null;panel.hidden=true;}};
}
