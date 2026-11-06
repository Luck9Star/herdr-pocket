// Continue the recorded partial execution after Penpot rejected a self-navigation.
if(penpot.currentFile?.id!=='b55064db-d93d-80f9-8008-ddd22e6d398f'||penpot.currentPage?.id!=='7a22df08-251d-8016-8008-de03541c11da')throw Error('Wrong file/page');
const old={};for(const b of penpot.root.children.filter(s=>s.type==='board'))old[b.name.slice(0,3)]=b;
const expected={S21:['b9d502c0-514c-80a9-8008-e6e948847ee0',7],S22:['b9d502c0-514c-80a9-8008-e6e948cbab81',2],S23:['b9d502c0-514c-80a9-8008-e6e948f6e88f',2],S24:['b9d502c0-514c-80a9-8008-e6e9491d8ef0',2],S25:['b9d502c0-514c-80a9-8008-e6e94944d7ce',2],S26:['b9d502c0-514c-80a9-8008-e6e9496936f8',2]};
for(const [k,[id,n]] of Object.entries(expected))if(old[k]?.id!==id||old[k].children.length!==n)throw Error('Unexpected partial '+k);
const title=penpotUtils.findShapeById('61ebadac-98b5-8013-8008-e6e7925618da');const body=old.S19.children.find(s=>s.type==='text'&&s.characters.startsWith('新增：Lab-Node-02'));const confirm=old.S19.children.filter(s=>s.name.includes('演示：确认审查'));if(title?.characters!=='逐项审查示例'||!body||confirm.length!==2)throw Error('Unexpected S19');
const C={card:'#FFFFFF',ink:'#0F172A',sub:'#475569',muted:'#64748B',brand:'#4F46E5',soft:'#EEF2FF',success:'#047857',successBg:'#ECFDF5',warn:'#92400E',warnBg:'#FEF3C7'};const font=penpot.fonts.findByName('Inter');
function rect(b,x,y,w,h,c){let s=penpot.createRectangle();s.resize(w,h);s.fills=[{fillColor:c,fillOpacity:1}];s.borderRadius=10;b.appendChild(s);s.x=b.x+x;s.y=b.y+y;return s;}
function txt(b,x,y,w,h,v,size=14,color=C.ink,weight=400){let s=penpot.createText(v);s.name=v.split('\n')[0].slice(0,50);s.resize(w,h);font?.applyToText(s);s.fontSize=String(size);s.fontWeight=String(weight);s.lineHeight='1.45';s.fills=[{fillColor:color,fillOpacity:1}];b.appendChild(s);s.x=b.x+x;s.y=b.y+y;return s;}
function button(b,x,y,w,label,dest,kind='plain'){let r=rect(b,x,y,w,44,kind==='selected'?C.soft:kind==='primary'?C.brand:C.card);r.name='action · '+label;let t=txt(b,x+10,y+11,w-20,24,label,14,kind==='primary'?C.card:kind==='selected'?C.brand:C.ink,600);t.align='center';if(dest){for(const s of [r,t])s.addInteraction('click',{type:'navigate-to',destination:dest});}}
function panel(b,y,h,title,body,bg=C.card,color=C.ink){rect(b,24,y,342,h,bg);txt(b,40,y+16,310,26,title,16,color,600);txt(b,40,y+50,310,h-58,body,14,C.sub);}
const choices=['新增','保留','替换'],sel=[old.S21,old.S22,old.S23];
for(let i=0;i<3;i++){let b=sel[i];if(i>0)panel(b,140,120,'测试主机 · 请选择处理方式','这只是原型：没有读取文件、写入配置或连接主机。',C.warnBg,C.warn);for(let j=0;j<3;j++){if(i===0&&j===0)continue;button(b,24,280+j*56,342,(j===i?'● ':'○ ')+choices[j],j===i?null:sel[j],j===i?'selected':'plain');}let note=i===2?'替换会影响已保存连接；旧身份停用并保留供核查。':i===0?'新增资料需独立配对，不复制秘密。':'保留现有资料，不覆盖信任。';txt(b,24,460,342,55,note,13,C.sub);button(b,24,548,342,'确认所选处理',[old.S25,old.S26,old.S24][i],'primary');button(b,24,608,342,'取消，不提交',old.S01);}
panel(old.S24,140,205,'演示结果 · 不执行导入','新资料待独立配对与主动连接验证。\n旧身份停用并保留，可供撤销核查或明确清理。\n相关自动重试停止，不自动连接。',C.successBg,C.success);
panel(old.S25,140,205,'演示结果 · 不执行导入','新资料待独立配对与主动连接验证；不会复制设备身份或秘密。',C.successBg,C.success);
panel(old.S26,140,205,'演示结果 · 不执行导入','原资料及信任保留，未替换或自动连接。',C.successBg,C.success);
for(const b of [old.S24,old.S25,old.S26]){button(b,24,548,342,'返回主机看板',old.S01,'primary');button(b,24,608,342,'返回冲突审查',old.S19);txt(b,24,744,342,50,'此页为交互原型，不代表导入已执行。',12,C.muted);}
title.hidden=true;body.hidden=true;for(const s of confirm){s.hidden=true;for(const i of s.interactions)i.remove();}for(let j=0;j<3;j++)button(old.S19,40,350+j*50,310,'○ '+choices[j],sel[j]);
return {completed:Object.keys(expected).map(k=>({id:old[k].id,name:old[k].name})),modified:old.S19.id};
