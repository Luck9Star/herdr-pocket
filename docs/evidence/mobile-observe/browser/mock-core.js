// Isolated UI staging only. Never shipped in app builds; no SSH or credentials.
export class Channel { onmessage=()=>{}; }
export const isTauri=()=>true;
let active=null, generation=0;
const bytes=text=>[...new TextEncoder().encode(text)];
function emitFrame(a,full) { if(active!==a)return; a.seq++; a.channel.onmessage({kind:'frame',generation:a.generation,frame:{seq:a.seq,full,bytes:bytes(full?'\x1b[2J\x1b[HUI FIXTURE · NOT SSH\r\n已选择 '+a.pane+'\r\n等待合成更新…':'\x1b[5;1H\x1b[2Ksynthetic update '+a.seq+' · 中文 é')}}); }
export async function invoke(command,args={}) {
 if(command==='remote_observe') return new Promise((resolve,reject)=>{
  const a={generation:++generation,client:args.clientGeneration,channel:args.onEvent,seq:0,reject,timer:null};active=a;
  a.channel.onmessage({kind:'dashboard',generation:a.generation,panes:[{paneId:'w1:p1',terminalId:'term_a1'},{paneId:'w1:p2',terminalId:'term_b2'}]});
 });
 if(command==='remote_select'){const a=active;if(!a||args.generation!==a.generation)throw Error('cancelled');a.pane=args.paneId;emitFrame(a,true);return;}
 if(command==='remote_ack'){const a=active;if(a&&args.generation===a.generation&&args.seq===a.seq)a.timer=setTimeout(()=>emitFrame(a,false),700);return;}
 if(command==='remote_cancel'){const a=active;if(a&&args.clientGeneration===a.client){clearTimeout(a.timer);active=null;a.reject('cancelled');}return;}
 throw Error('UI staging does not implement '+command);
}
