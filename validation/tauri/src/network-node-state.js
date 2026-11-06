// Engine/Running states report the provider's local state, never SSH readiness.
export function nodePresentation(profile, identity, node) {
  const ts=profile.provider==='tailscale';
  const no={canStart:false,canStop:false,canLogin:false};
  if (!ts && profile.provider !== 'easytier') return { ...no,text:'节点服务待接入' };
  if (node?.state === 'starting') return { ...no,text:'节点启动中；不代表已入网', canStop:true };
  if (node?.state === 'closing') return { ...no,text:'节点正在停止；可核查后显式再停止', canStop:true };
  if (!ts && node?.state === 'engine-started') return { ...no,text:'本机引擎已启动；入网及 SSH 尚未确认', canStop:true };
  // Even if vault status is unavailable, retain the exact active node stop action.
  if(ts && ['needs-login','needs-machine-auth','running'].includes(node?.state)) {
    const valid=identity?.supported && identity.available && identity.present && identity.mode==='DEVICE_STATE' && identity.handle===node.binding?.identityRef;
    if(node.state==='needs-login')return {...no,text:'Tailscale 需要显式登录；尚未确认入网',canStop:true,canLogin:!!valid&&profile.enabled};
    if(node.state==='needs-machine-auth')return {...no,text:'Tailscale 等待管理员批准设备；可刷新状态',canStop:true};
    return {...no,text:'Tailscale 报告 Running；实际链路与 SSH 尚待核验',canStop:true};
  }
  if (!identity) return { ...no,text:'本机身份状态未知' };
  if (!identity.supported || !identity.available) return { ...no,text:'本机身份服务不可用' };
  if (!identity.present) return { ...no,text:'先配置本机网络身份' };
  if (!ts && identity.mode === 'PUBLIC_NO_SECRET') return { ...no,text:'公开无秘密模式暂不支持启动' };
  if (identity.mode !== (ts?'DEVICE_STATE':'PRIVATE')) return { ...no,text:'本机身份状态未知' };
  if (!node || node.state === 'unknown') return { ...no,text:'节点状态未确认' };
  if (node.state === 'unavailable') return { ...no,text:'节点服务待接入' };
  if (node.state === 'stopped') return { ...no,text:profile.enabled?'节点已停止':'配置已停用', canStart:profile.enabled };
  return { ...no,text:'节点状态未确认' };
}
