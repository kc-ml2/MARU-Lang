"""Local browser bridge for the interactive document (doc) graph.

`maru run` is a WebSocket *client* — in attach mode the upstream server may not
even be ours. So instead of serving UI from the server, the REPL itself starts a
tiny local WebSocket bridge (no extra deps: reuses `websockets`) and opens a
self-contained HTML canvas app in the browser. The REPL relays a doc turn's
`canvas`/`interrupt` events to the browser and reads back the user's edit
commands, which it forwards upstream as `resume`.

    upstream ws  ──canvas/interrupt──►  REPL  ──►  local bridge ws  ──►  browser
    upstream ws  ◄───── resume ───────  REPL  ◄──  local bridge ws  ◄──  browser
"""
import asyncio
import json
import tempfile
import webbrowser
from pathlib import Path

import websockets


class DocBridge:
    """A localhost WebSocket bridge between the REPL and a browser canvas app."""

    def __init__(self):
        self._server = None
        self._clients: set = set()
        self._resume_q: asyncio.Queue = asyncio.Queue()
        self._last_canvas: dict | None = None
        self._pending_interrupt: dict | None = None
        self._html_path: str | None = None
        self.port: int | None = None

    async def start(self) -> None:
        if self._server is not None:
            return
        # Ephemeral localhost port; the OS picks a free one.
        self._server = await websockets.serve(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        self._write_html()

    async def _handle(self, ws, *args) -> None:
        """One connected browser tab. Sends current state, then reads commands."""
        self._clients.add(ws)
        try:
            if self._last_canvas is not None:
                await ws.send(json.dumps({"type": "canvas", "canvas": self._last_canvas}))
            if self._pending_interrupt is not None:
                await ws.send(json.dumps(self._pending_interrupt))
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                # Browser → a resume command (edit op dict or anchor choice).
                await self._resume_q.put(msg)
        except Exception:
            pass
        finally:
            self._clients.discard(ws)

    async def _broadcast(self, obj: dict) -> None:
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send(json.dumps(obj))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def send_canvas(self, canvas: dict) -> None:
        self._last_canvas = canvas
        await self._broadcast({"type": "canvas", "canvas": canvas})

    async def send_interrupt(self, content) -> None:
        self._pending_interrupt = {"type": "interrupt", "content": content}
        # A fresh interrupt supersedes any stale queued resume.
        while not self._resume_q.empty():
            self._resume_q.get_nowait()
        await self._broadcast(self._pending_interrupt)

    async def send_complete(self) -> None:
        self._pending_interrupt = None
        await self._broadcast({"type": "complete"})

    async def send_error(self, message: str) -> None:
        self._pending_interrupt = None
        await self._broadcast({"type": "error", "content": message})

    async def await_resume(self):
        """Block until the browser sends the next resume command."""
        content = await self._resume_q.get()
        self._pending_interrupt = None
        return content

    def has_clients(self) -> bool:
        return bool(self._clients)

    def open_browser(self) -> None:
        if self._html_path:
            webbrowser.open(f"file://{self._html_path}")

    def _write_html(self) -> None:
        html = CANVAS_HTML.replace("__WS_PORT__", str(self.port))
        path = Path(tempfile.gettempdir()) / "maru_canvas.html"
        path.write_text(html, encoding="utf-8")
        self._html_path = str(path)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass
            self._server = None


CANVAS_HTML = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>MARU 문서 편집</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, -apple-system, "Apple SD Gothic Neo", sans-serif;
         margin: 0; background: #f6f7f9; color: #1a1a1a; }
  header { position: sticky; top: 0; background: #fff; border-bottom: 1px solid #e3e6ea;
           padding: 12px 20px; display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 16px; margin: 0; flex: 1; }
  #status { font-size: 12px; padding: 3px 8px; border-radius: 10px; background: #eef; }
  #status.busy { background: #fee9c8; } #status.done { background: #d6f5d6; }
  #err { display: none; background: #fdecea; color: #b3261e; padding: 8px 20px; font-size: 13px; }
  main { max-width: 860px; margin: 16px auto; padding: 0 16px 80px; }
  .doc-title { font-size: 22px; font-weight: 700; margin: 8px 0 4px; }
  .parties { color: #555; font-size: 13px; margin-bottom: 16px; }
  .section { margin: 18px 0; }
  .section > h2 { font-size: 15px; color: #2557d6; margin: 0 0 8px; }
  .block { background: #fff; border: 1px solid #e3e6ea; border-radius: 8px;
           padding: 10px 12px; margin: 8px 0; }
  .block .meta { font-size: 11px; color: #8a8f98; margin-bottom: 4px; display: flex; gap: 8px; }
  .block .text { white-space: pre-wrap; line-height: 1.5; }
  .block .acts { margin-top: 8px; display: none; gap: 6px; flex-wrap: wrap; }
  body.awaiting .block .acts { display: flex; }
  button { font: inherit; font-size: 12px; padding: 4px 10px; border: 1px solid #cfd4da;
           background: #fff; border-radius: 6px; cursor: pointer; }
  button:hover { background: #f0f2f5; }
  button.primary { background: #2557d6; color: #fff; border-color: #2557d6; }
  .missing { margin-top: 16px; padding: 10px 12px; background: #fff8e6;
             border: 1px solid #f2e2b3; border-radius: 8px; font-size: 13px; }
  .toolbar { position: fixed; bottom: 0; left: 0; right: 0; background: #fff;
             border-top: 1px solid #e3e6ea; padding: 10px 20px; display: none; gap: 8px; }
  body.awaiting .toolbar { display: flex; }
  #anchor { position: fixed; inset: 0; background: rgba(0,0,0,.35); display: none;
            align-items: center; justify-content: center; }
  #anchor .card { background: #fff; border-radius: 10px; padding: 18px 20px; min-width: 360px; }
  #anchor button { display: block; width: 100%; text-align: left; margin: 6px 0; }
  .inline { margin-top: 8px; display: flex; gap: 6px; }
  .inline textarea { flex: 1; font: inherit; padding: 6px; border: 1px solid #cfd4da; border-radius: 6px; }
</style></head>
<body>
<header>
  <h1 id="title">MARU 문서 편집</h1>
  <span id="status">연결 중…</span>
</header>
<div id="err"></div>
<main id="doc"><p style="color:#888">문서를 기다리는 중…</p></main>
<div class="toolbar">
  <button onclick="addBlock()">+ 블록 추가</button>
  <span style="flex:1"></span>
  <button class="primary" onclick="send({op:'finalize'})">확정</button>
</div>
<div id="anchor"><div class="card">
  <h3 style="margin-top:0">기준 문서를 선택하세요</h3>
  <div id="anchor-list"></div>
  <button onclick="send({skip:true})">건너뛰기 (표준 없이)</button>
</div></div>

<script>
const WS = "ws://127.0.0.1:__WS_PORT__";
let canvas = null, awaiting = null, ws = null;

function setStatus(t, cls){ const s=document.getElementById('status'); s.textContent=t; s.className=cls||''; }
function showErr(m){ const e=document.getElementById('err'); if(m){e.style.display='block';e.textContent='⚠ '+m;} else {e.style.display='none';} }

function connect(){
  ws = new WebSocket(WS);
  ws.onopen = () => setStatus('연결됨');
  ws.onclose = () => { setStatus('연결 끊김', 'busy'); setTimeout(connect, 1000); };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === 'canvas') { canvas = msg.canvas; render(); }
    else if (msg.type === 'interrupt') { onInterrupt(msg.content); }
    else if (msg.type === 'complete') { awaiting=null; document.body.classList.remove('awaiting'); setStatus('완료', 'done'); showErr(null); }
    else if (msg.type === 'error') { setStatus('오류', 'busy'); showErr(msg.content); }
  };
}
function send(obj){ ws.send(JSON.stringify(obj)); awaiting=null; document.body.classList.remove('awaiting'); setStatus('처리 중…','busy'); showErr(null); closeAnchor(); }

function onInterrupt(c){
  showErr(c && c.error);
  if (c && c.type === 'awaiting_anchor_choice') { openAnchor(c.candidates||[]); return; }
  if (c && c.canvas) { canvas = c.canvas; render(); }
  awaiting = c; document.body.classList.add('awaiting'); setStatus('편집 대기');
}

function render(){
  if(!canvas) return;
  document.getElementById('title').textContent = canvas.title || 'MARU 문서 편집';
  const doc = document.getElementById('doc'); doc.innerHTML='';
  if (canvas.title){ const t=document.createElement('div'); t.className='doc-title'; t.textContent=canvas.title; doc.appendChild(t); }
  const parties = ((canvas.metadata||{}).parties)||[];
  if (parties.length){ const p=document.createElement('div'); p.className='parties';
    p.textContent = parties.map(x=>[x.label,x.name].filter(Boolean).join(': ')).join('  ·  '); doc.appendChild(p); }
  (canvas.sections||[]).forEach(sec => {
    const sd=document.createElement('div'); sd.className='section';
    const art=((sec.metadata||{}).article_no)||''; const head=[art, sec.title].filter(Boolean).join(' ');
    if(head){ const h=document.createElement('h2'); h.textContent=head; sd.appendChild(h); }
    (sec.blocks||[]).forEach((b, i) => sd.appendChild(blockEl(sec, b, i)));
    doc.appendChild(sd);
  });
  const missing=(canvas.missing_terms||[]);
  if(missing.length){ const m=document.createElement('div'); m.className='missing';
    m.textContent='미정 항목: '+missing.map(x=>x.label||'?').join(', '); doc.appendChild(m); }
}

function blockEl(sec, b, idx){
  const el=document.createElement('div'); el.className='block';
  const refs=(b.source_refs||[]).length;
  const meta=document.createElement('div'); meta.className='meta';
  meta.innerHTML = `<b>${b.block_id}</b><span>${b.block_type||''}</span>` + (refs?`<span>출처 ${refs}</span>`:'');
  const text=document.createElement('div'); text.className='text'; text.textContent=b.text||'';
  const acts=document.createElement('div'); acts.className='acts';
  acts.appendChild(btn('수정', ()=>editBlock(el, b)));
  acts.appendChild(btn('삭제', ()=>send({op:'delete', block_id:b.block_id})));
  acts.appendChild(btn('↑', ()=>move(sec, idx, -1)));
  acts.appendChild(btn('↓', ()=>move(sec, idx, +1)));
  el.append(meta, text, acts);
  return el;
}
function btn(t, fn){ const b=document.createElement('button'); b.textContent=t; b.onclick=fn; return b; }

function editBlock(el, b){
  if (el.querySelector('.inline')) return;
  const box=document.createElement('div'); box.className='inline';
  const ta=document.createElement('textarea'); ta.rows=2; ta.placeholder='이 블록을 어떻게 고칠까요? (피드백)';
  const go=btn('적용', ()=>send({op:'edit', block_id:b.block_id, feedback:ta.value}));
  go.className='primary';
  box.append(ta, go); el.appendChild(box); ta.focus();
}
function move(sec, idx, delta){
  const ids=(sec.blocks||[]).map(x=>x.block_id); const j=idx+delta;
  if(j<0||j>=ids.length) return;
  [ids[idx], ids[j]]=[ids[j], ids[idx]];
  send({op:'reorder', section_id:sec.section_id, order:ids});
}
function addBlock(){
  const text=prompt('추가할 블록 내용 (비우면 AI가 피드백으로 생성):','');
  if(text===null) return;
  send({op:'add', content:text});
}
function openAnchor(cands){
  const list=document.getElementById('anchor-list'); list.innerHTML='';
  cands.forEach((c,i)=>{ const b=document.createElement('button');
    b.innerHTML=`<b>${c.name}</b> <span style="color:#888">관련도 ${c.score}</span>`;
    b.onclick=()=>send({index:i}); list.appendChild(b); });
  document.getElementById('anchor').style.display='flex'; setStatus('기준 문서 선택');
}
function closeAnchor(){ document.getElementById('anchor').style.display='none'; }
connect();
</script>
</body></html>
"""
