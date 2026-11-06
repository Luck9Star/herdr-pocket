// A running engine only means the local engine started; it does not prove a join or SSH.
export function nodePresentation(profile, identity, node) {
  if (profile.provider !== 'easytier') return { text:'节点服务待接入', canStart:false, canStop:false };
  if (node?.state === 'engine-started') return { text:'本机引擎已启动；入网及 SSH 尚未确认', canStart:false, canStop:true };
  if (node?.state === 'starting') return { text:'节点启动中；不代表已入网', canStart:false, canStop:true };
  if (node?.state === 'closing') return { text:'节点正在停止；可核查后显式再停止', canStart:false, canStop:true };
  if (!identity) return { text:'本机身份状态未知', canStart:false, canStop:false };
  if (!identity.supported || !identity.available) return { text:'本机身份服务不可用', canStart:false, canStop:false };
  if (!identity.present) return { text:'先配置本机网络身份', canStart:false, canStop:false };
  if (identity.mode === 'PUBLIC_NO_SECRET') return { text:'公开无秘密模式暂不支持启动', canStart:false, canStop:false };
  if (identity.mode !== 'PRIVATE') return { text:'本机身份状态未知', canStart:false, canStop:false };
  if (!node || node.state === 'unknown') return { text:'节点状态未确认', canStart:false, canStop:false };
  if (node.state === 'unavailable') return { text:'节点服务待接入', canStart:false, canStop:false };
  if (node.state === 'stopped') return { text:profile.enabled?'节点已停止':'配置已停用', canStart:profile.enabled, canStop:false };
  return { text:'节点状态未确认', canStart:false, canStop:false };
}
