import { previewConnectionProfile } from './connection-profile.js';
import { NativeCameraReturn } from './native-camera-return.js';

// This controller only reads public text/camera data and fills a reviewed local
// form. It has no storage, key creation, network, or identity recovery capability.
export function initConnectionProfileUI({native,invoke,state,apply,preview=previewConnectionProfile,now=()=>performance.now(),scanTtl=60000}) {
  const $=id=>document.getElementById(id);let revision=0,ticket=null,scanBusy=false;
  const available=()=>state().available && !document.hidden;
  const identity=()=>JSON.stringify(state());
  const camera=new NativeCameraReturn({purpose:'connection-profile',snapshot:()=>JSON.stringify([revision,state()]),allowed:()=>state().available,now,ttl:scanTtl,onExpire:()=>invalidate('本次扫描已过期；请重新扫描或手动粘贴。')});
  function clearPreview() {
    ticket=null;$('connection-profile-details').hidden=true;$('connection-profile-details').textContent='';
    $('connection-profile-fingerprint').hidden=true;$('connection-profile-fingerprint').textContent='';
  }
  function render() {
    if(camera.attempt && !camera.current()) {
      camera.discard();revision++;clearPreview();
      $('connection-profile-status').textContent='本次扫描已过期或目标已变化；请重新扫描或手动粘贴。';
    }
    $('connection-profile-scan').disabled=!native || scanBusy || !available();
    $('connection-profile-preview').disabled=!available();
    $('connection-profile-preview').textContent=camera.held ? '重新查看本次扫描结果' : '预览连接资料与指纹';
    $('connection-profile-apply').disabled=!ticket || !available() || ticket.identity!==identity();
  }
  function invalidate(message='') {
    camera.discard();revision++;clearPreview();
    $('connection-profile-status').textContent=message;render();
  }
  const current=(start,key)=>revision===start && available() && key===identity();
  async function inspect(raw,start,key) {
    try {
      const result=await preview(raw);
      if(!current(start,key))return;
      ticket={...result,identity:key};$('connection-profile-details').textContent=result.text;
      $('connection-profile-details').hidden=false;
      $('connection-profile-fingerprint').textContent=`主机公钥指纹（本地计算）：${result.fingerprint}`;$('connection-profile-fingerprint').hidden=false;
      $('connection-profile-status').textContent='仅公开连接资料；请核对全部字段与独立来源。指纹由本地计算，尚未验证主机。';
    } catch {if(current(start,key))$('connection-profile-status').textContent='连接资料格式无效或超出 2048 UTF-8 字节；未填入任何字段。';}
    render();
  }
  $('connection-profile-raw').addEventListener('input',()=>invalidate('资料已修改；请重新预览。'));
  $('remote-form').addEventListener('input',event=>{if(event.target.id!=='connection-profile-raw')invalidate('表单已修改；先前预览已作废，请独立核对当前字段。网络声明保持不变。');});
  $('connection-profile-preview').onclick=async()=>{
    // A scanner Activity may resolve before or after visibility is restored.
    // Its bounded in-memory result needs a fresh foreground user action.
    render();if(!available())return;
    const held=camera.take(document.hidden);
    invalidate();if(held!==null)$('connection-profile-raw').value=held;
    const start=revision,key=identity();await inspect($('connection-profile-raw').value,start,key);
  };
  $('connection-profile-scan').onclick=async()=>{
    if(!native || scanBusy || !available())return;
    invalidate();
    const start=revision,key=identity(),attempt=camera.start();if(!attempt)return;
    scanBusy=true;render();
    try {
      const raw=await invoke('pair_scan_response');
      const outcome=camera.receive(attempt,raw,document.hidden);if(!outcome)return;
      if(outcome==='held') {
        $('connection-profile-status').textContent='本次相机已返回；回到前台后点“重新查看本次扫描结果”。尚未填入或审查任何目标字段。';
      } else {$('connection-profile-raw').value=raw;await inspect(raw,start,key);}
    } catch {if(camera.current(attempt)){camera.discard();$('connection-profile-status').textContent='扫描未完成、被取消或相机权限不可用；可手动粘贴公开连接资料并预览。';}}
    finally {scanBusy=false;render();}
  };
  $('connection-profile-apply').onclick=()=>{
    if(!ticket || !available() || ticket.identity!==identity()) {invalidate('目标或身份已变化；请在无设备身份的新主机表单重新预览。');return;}
    const profile=ticket.profile;invalidate();apply(profile);
    $('connection-profile-status').textContent=`已填入新主机表单（声明网络：${profile.provider}）；未保存、未创建设备、未连接。请独立核对目标，再勾选审查并创建设备。`;
    render();
  };
  $('connection-profile-cancel').onclick=()=>invalidate('已取消预览；可手动填写或重新粘贴资料。');
  document.addEventListener('visibilitychange',()=>{
    if(document.hidden) {
      if(camera.background()) {
        // A background event revokes existing previews without changing the
        // target snapshot owned by this single native camera return.
        clearPreview();
        $('connection-profile-status').textContent='相机读取中；仅本次短时返回可重新查看，未保留任何审查。';render();
      } else invalidate('应用进入后台；连接资料预览已作废。');
    } else {camera.foreground();render();}
  });
  window.addEventListener('pagehide',()=>invalidate());
  render();return {invalidate,render};
}
