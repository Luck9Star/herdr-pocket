// Add only previously absent click actions to the existing S03 hide key.
if(penpot.currentFile?.id!=='b55064db-d93d-80f9-8008-ddd22e6d398f' || penpot.currentPage?.id!=='7a22df08-251d-8016-8008-de03541c11da')throw Error('Wrong file/page');
const destination=penpotUtils.findShapeById('ff7bd149-6597-80a5-8008-e8acfe51be24');
const key=penpotUtils.findShapeById('e6d238f0-ac08-8028-8008-de07ebe3655d');
const label=penpotUtils.findShapeById('e6d238f0-ac08-8028-8008-de07ebe487e1');
if(!destination || destination.name!=='S43 · 键盘收起 · 输入已锁定' || !key || !label || key.interactions.length || label.interactions.length || label.characters!=='收起键盘')throw Error('Unexpected existing interaction');
key.addInteraction('click',{type:'navigate-to',destination});label.addInteraction('click',{type:'navigate-to',destination});
return {addedTo:[key.id,label.id],destination:destination.id};
