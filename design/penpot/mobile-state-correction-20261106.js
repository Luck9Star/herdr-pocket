// Guarded correction: align the hidden and recovered demo target.
if(penpot.currentFile?.id!=='b55064db-d93d-80f9-8008-ddd22e6d398f'||penpot.currentPage?.id!=='7a22df08-251d-8016-8008-de03541c11da')throw Error('Wrong file/page');
const changes=[
['61ebadac-98b5-8013-8008-e6e7921633ba','workstation-01 / pane-demo / term-demo\n最后画面：16:40:10\n隐藏不停止远端任务；草稿按目标保留。','B / Lab-Node-02 / test-session / agent-c\n最后画面：16:40:10\n隐藏不停止远端任务；草稿按目标保留。'],
['61ebadac-98b5-8013-8008-e6e7925618da','逐项选择并确认','逐项审查示例']
];
for(const [id,before] of changes){const s=penpotUtils.findShapeById(id);if(!s||s.type!=='text'||s.characters!==before)throw Error('Unexpected text '+id);}
for(const [id,,after] of changes)penpotUtils.findShapeById(id).characters=after;
return changes.map(([id,,after])=>({id,after}));
