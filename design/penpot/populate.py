"""Populate once after build-core.js; requires the locally connected Penpot MCP."""
import json, subprocess
from pathlib import Path
root=Path(__file__).resolve().parent
screens=json.loads((root/'screens.json').read_text())
for start in range(0,len(screens),6):
    chunk=screens[start:start+6]
    code="if(penpot.currentFile.id!=='b55064db-d93d-80f9-8008-ddd22e6d398f')throw new Error('Wrong file');const data="+json.dumps(chunk,ensure_ascii=False)+"; return data.map((s,i)=>{if(storage.hp.boards[s.id])throw new Error('Already populated: '+s.id); const b=storage.hp.board(s,"+str(start)+"+i);return {id:s.id,board:b.id};});"
    result=subprocess.run(['mcporter','call','http://localhost:4401/mcp.execute_code','--allow-http','--args',json.dumps({'code':code}),'--output','json'],capture_output=True,text=True,check=True)
    parsed=json.loads(result.stdout)
    if 'result' not in parsed:raise RuntimeError(result.stdout)
    print(json.dumps(parsed['result'],ensure_ascii=False),flush=True)
