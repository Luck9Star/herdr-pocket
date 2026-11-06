// A write may have committed or cancelled a connection even when its result is unknown.
// Always invalidate reviewed hosts and await their refresh before reloading the catalog.
export async function settleNetworkOperation(work, affected, onAffected, load) {
  let completed=false;
  try { await work(); completed=true; } catch { /* result may be unknown */ }
  try { await onAffected(affected); } catch { completed=false; }
  await load(completed ? '保存完成；原生网络桥接尚不可用，绑定主机不会回退到系统连接。' : '操作结果未确认，受影响连接已停止；请先核对主机和网络配置的当前状态。');
  return completed;
}
// Network configuration is public metadata; provider identities remain native.
export function initNetworkUI({native, invoke, getHosts, onAffected}) {
  const panel=document.getElementById('network-panel'), open=document.getElementById('network-open');
  let catalog=null, editing=null, busy=false;
  const el=(tag,text='',className='')=>{const n=document.createElement(tag);n.textContent=text;if(className)n.className=className;return n;};
  const button=(text,fn)=>{const b=el('button',text);b.type='button';b.disabled=busy;b.onclick=fn;return b;};
  const label=(text,input)=>{const l=el('label',text);l.append(input);return l;};
  const field=(value='',placeholder='')=>{const n=document.createElement('input');n.value=value;n.placeholder=placeholder;n.autocomplete='off';return n;};
  const names=ids=>ids.map(id=>getHosts().find(h=>h.id===id)?.name || id).join('、') || '无';
  async function load(message='') {try {catalog=await invoke('network_list');render(message);}catch {catalog=null;panel.replaceChildren(el('p','网络配置读取失败，当前状态未知；请稍后核对。'));}}
  async function operation(work,affected) {if(busy)return;busy=true;try {await settleNetworkOperation(async()=>{await work();editing=null;},affected,onAffected,async message=>{busy=false;await load(message);});}finally{busy=false;}}
  function render(message='') {
    if(!catalog)return;panel.replaceChildren();panel.append(el('h2','网络配置'),el('p','管理公开配置；设备身份由原生网络组件单独管理，不在此采集或导出。当前三种桥接均不可用。'));
    const status=el('p',message);status.setAttribute('role','status');panel.append(status);
    for(const profile of catalog.profiles) {
      const affected=catalog.bindings.filter(b=>b.profileId===profile.id).map(b=>b.hostId);
      const card=el('article','','saved-host-card');card.append(el('h3',profile.label),el('p',`${profile.provider} · ${profile.enabled?'已启用':'已停用'} · 桥接不可用 · 受影响主机：${names(affected)}`));
      const actions=el('div','','saved-host-actions');actions.append(button('编辑',()=>{editing=profile;render();}),button(profile.enabled?'停用':'启用',()=>{if(!confirm(`将${profile.enabled?'停用':'启用'} ${profile.label}。受影响主机：${names(affected)}。继续？`))return;void operation(()=>invoke('network_save',{profile:{...profile,enabled:!profile.enabled},expectedCatalog:catalog.revision,expectedRevision:profile.revision,affected}),affected);}));
      const del=button('删除',()=>{if(affected.length){status.textContent=`仍被主机引用：${names(affected)}。请先逐一更换或解除绑定。`;return;}if(confirm(`删除 ${profile.label}？`))void operation(()=>invoke('network_delete',{id:profile.id,expectedCatalog:catalog.revision,expectedRevision:profile.revision}),[]);});actions.append(del);card.append(actions);panel.append(card);
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
    const hostSection=el('section');hostSection.append(el('h3','主机网络绑定'));for(const host of getHosts().filter(h=>!h.retired)) {
      const row=el('div','','network-binding');row.append(el('strong',host.name));const select=document.createElement('select');const direct=el('option','系统连接（原有方式）');direct.value='';select.append(direct);for(const p of catalog.profiles){const o=el('option',`${p.label} · ${p.provider}${p.enabled?'':'（已停用）'}`);o.value=p.id;o.disabled=!p.enabled;select.append(o);}select.value=host.networkProfileId || '';row.append(select,button('应用',()=>{const profileId=select.value || null;if(profileId===(host.networkProfileId || null))return;const isDirect=!!host.networkProfileId && !profileId;if(!confirm(isDirect?`解除 ${host.name} 的网络绑定并改为系统直连？这会停止该主机连接。`:`更改 ${host.name} 的网络绑定并停止其连接？`))return;void operation(()=>invoke('network_bind',{hostId:host.id,profileId,expectedCatalog:catalog.revision,confirmedDirect:isDirect}),[host.id]);}));hostSection.append(row);
    }panel.append(hostSection);
  }
  open.disabled=!native;open.onclick=()=>{panel.hidden=!panel.hidden;if(!panel.hidden)void load();};
  return {refresh:()=>{if(!panel.hidden)void load();},close:()=>{panel.hidden=true;}};
}
