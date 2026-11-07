import {observationError} from './observation-error.js';
const definitions=[['network','网络路径'],['hostKey','SSH 主机指纹'],['authentication','SSH 公钥认证'],['dashboard','会话看板'],['terminal','终端首帧']];
const stages=Object.freeze({connecting:'正在连接 SSH，等待主机身份核验…','host-key-verified':'预期主机公钥已匹配，正在进行公钥认证…',authenticated:'公钥认证已完成，正在读取会话看板…'});
const clean=value=>typeof value==='string'?value.replace(/[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]/g,'').slice(0,128):'';
const validPair=pair=>pair && typeof pair.paneId==='string' && /^[A-Za-z0-9:_-]{1,128}$/.test(pair.paneId) && typeof pair.terminalId==='string' && /^term_[0-9a-f]{1,123}$/.test(pair.terminalId);
const same=(a,b)=>!!a && !!b && a.paneId===b.paneId && a.terminalId===b.terminalId;
export const connectionStageText=stage=>typeof stage==='string' && Object.hasOwn(stages,stage)?stages[stage]:null;
// The key contains public identity only. Credentials and terminal contents are
// never retained or rendered by the diagnostic model.
export function connectionDiagnosticIdentity({hostId=null,target={},deviceFingerprint=null,networkProfileId=null,networkRevision=null}={}) {
 return JSON.stringify([hostId,['host','port','username','expectedHostKey','socketPath','herdrPath','session'].map(key=>target[key] ?? null),deviceFingerprint,networkProfileId,networkRevision]);
}
export class ConnectionDiagnostics {
 constructor({identity,host='当前主机',session='',network=false,device=false,now=Date.now()}){
  this.identity=identity;this.host=clean(host);this.session=clean(session);this.network=!!network;this.device=!!device;this.startedAt=now;this.active=true;this.closed=false;this.paused=false;this.failure='';this.target=null;
  this.rows=Object.fromEntries(definitions.map(([id])=>[id,{state:'unknown',message:'尚未确认'}]));
  this.rows.network={state:'pending',message:`${this.network?'已选择绑定的网络路径':'已选择系统连接路径'}；尚未确认可达`};
 }
 stage(value){if(!this.active || !connectionStageText(value))return false;
  if(value==='host-key-verified'){this.rows.network={state:'verified',message:'所选路径已完成 SSH 握手'};this.rows.hostKey={state:'verified',message:'预期主机公钥已匹配'};}
  if(value==='authenticated')this.rows.authentication={state:'verified',message:this.device?'本机设备公钥认证已完成':'临时公钥认证已完成'};
  return true;
 }
 dashboard(board){if(!this.active || !board?.selectable || !['fresh','unavailable'].includes(board.phase) || !Array.isArray(board.panes))return false;this.rows.dashboard={state:'verified',message:board.phase==='unavailable'?'会话快照已核验；持续更新不可用':'会话快照已核验'};return true;}
 bind(pair){if(!this.active || !validPair(pair) || this.target && !same(this.target,pair))return false;if(this.target && this.rows.terminal.state==='verified')return true;this.target=Object.freeze({paneId:pair.paneId,terminalId:pair.terminalId});this.rows.terminal={state:'pending',message:'原 pane 与 terminal 已绑定；等待完整画面绘制'};return true;}
 full(pair){if(!this.active || !same(this.target,pair))return false;this.rows.terminal={state:'verified',message:'原目标完整画面已绘制'};return true;}
 pause(){if(this.closed)return;this.active=false;this.paused=true;}
 resume(){if(this.closed)return;this.active=true;this.paused=false;}
 finish(error=null){if(this.closed)return false;this.active=false;this.closed=true;this.paused=false;
  if(error && error!=='cancelled'){
   this.failure=observationError(error);
   const row=error==='host_key_mismatch'?'hostKey':error==='authentication_failed'?'authentication':['connection_failed','provider_unavailable','overlay_provider_unavailable','mobile_node_not_started','network_identity_missing','network_profile_disabled','network_identity_changed','mobile_node_binding_mismatch','overlay_stale_revision'].includes(error)?'network':['socket_unavailable','session_mismatch','unsupported_protocol'].includes(error)?'dashboard':['pane_missing','resume_target_changed','observe_failed'].includes(error)?'terminal':null;
   if(row)this.rows[row]={state:'failed',message:this.failure};
  }
  return true;
 }
}
export function createConnectionDiagnosticsView(){
 const element=document.createElement('details');element.className='connection-diagnostics';element.setAttribute('data-connection-diagnostics','true');
 const heading=document.createElement('summary');heading.textContent='最近一次连接诊断';element.append(heading);
 const context=document.createElement('p'),result=document.createElement('p'),list=document.createElement('ol');element.append(context,result,list);
 const rows=definitions.map(([id,label])=>{const row=document.createElement('li');row.dataset.connectionStage=id;list.append(row);return {id,label,row};});
 const update=record=>{
  element.hidden=!record;if(!record)return;
  context.textContent=`${record.host} · 会话 ${record.session || '未指定'} · ${new Date(record.startedAt).toLocaleString()}${record.target?` · ${record.target.paneId} · ${record.target.terminalId}`:''}`;
  result.textContent=record.failure?`本次尝试未完成：${record.failure}`:record.paused?'本次观察已暂停；以下为该次连接已确认的事实。':record.closed?'本次尝试已结束；以下记录不代表当前仍然在线。':'本次尝试进行中；未知阶段不表示通过。';
  element.dataset.attemptState=record.paused?'paused':record.closed?'ended':'active';
  for(const {id,label,row} of rows){const value=record.rows[id];row.dataset.stageState=value.state;row.textContent=`${label} · ${value.state==='verified'?'已确认':value.state==='failed'?'失败':value.state==='pending'?'等待确认':'尚未确认'}：${value.message}`;}
 };
 update(null);return {element,update};
}
