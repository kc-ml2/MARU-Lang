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
  :root { color-scheme: light; }   /* 다크 모드에서 UA 기본색이 뒤집혀 흰 글씨가 되는 것 방지 */
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
           background: #fff; color: #1a1a1a; border-radius: 6px; cursor: pointer; }
  button:hover { background: #f0f2f5; }
  button.primary { background: #2557d6; color: #fff; border-color: #2557d6; }
  .missing { margin-top: 16px; padding: 10px 12px; background: #fff8e6;
             border: 1px solid #f2e2b3; border-radius: 8px; font-size: 13px; }
  .toolbar { position: fixed; bottom: 0; left: 0; right: 0; background: #fff;
             border-top: 1px solid #e3e6ea; padding: 10px 20px; display: none; gap: 8px; }
  body.awaiting .toolbar { display: flex; }
  #anchor { position: fixed; inset: 0; background: rgba(0,0,0,.35); display: none;
            align-items: center; justify-content: center; }
  #anchor .card { background: #fff; color: #1a1a1a; border-radius: 10px; padding: 18px 20px; min-width: 360px; }
  #anchor button { display: block; width: 100%; text-align: left; margin: 6px 0; }
  .inline { margin-top: 8px; display: flex; gap: 6px; }
  .inline textarea { flex: 1; font: inherit; padding: 6px; border: 1px solid #cfd4da; border-radius: 6px; }
  .addrow { margin: 4px 0 2px; display: none; }
  body.awaiting .addrow { display: block; }
  .addrow > button { color: #2557d6; border-style: dashed; }
  #tray { position: fixed; bottom: 52px; left: 0; right: 0; background: #fff;
          border-top: 1px solid #e3e6ea; padding: 8px 20px; display: none;
          max-height: 40vh; overflow: auto; box-shadow: 0 -2px 8px rgba(0,0,0,.06); }
  #tray .tray-h { font-size: 12px; font-weight: 700; color: #555; margin-bottom: 6px; }
  #tray .tray-item { display: flex; gap: 8px; align-items: center; font-size: 13px; padding: 2px 0; }
  #tray .tray-item button { padding: 0 6px; }
  #tray .tray-bar { display: flex; gap: 8px; margin-top: 8px; }
  #parties { position: fixed; inset: 0; background: rgba(0,0,0,.35); display: none;
             align-items: center; justify-content: center; }
  #parties .card { background: #fff; color: #1a1a1a; border-radius: 10px; padding: 18px 20px;
                   min-width: 380px; max-width: 480px; max-height: 80vh; overflow: auto; }
  #parties .pty { border: 1px solid #e3e6ea; border-radius: 8px; padding: 10px 12px; margin: 10px 0; }
  #parties label { display: block; font-size: 12px; color: #555; margin: 6px 0 2px; }
  #parties input { width: 100%; box-sizing: border-box; font: inherit; padding: 6px;
                   border: 1px solid #cfd4da; border-radius: 6px; }
</style></head>
<body>
<header>
  <h1 id="title">MARU 문서 편집</h1>
  <span id="status">연결 중…</span>
</header>
<div id="err"></div>
<main id="doc"><p style="color:#888">문서를 기다리는 중…</p></main>
<div id="tray"></div>
<div class="toolbar">
  <button onclick="addBlock()">+ 블록 추가</button>
  <button id="stagebtn" onclick="toggleStaging()">묶어 편집: 꺼짐</button>
  <span style="flex:1"></span>
  <button class="primary" onclick="finalizeDoc()">확정</button>
</div>
<div id="anchor"><div class="card">
  <h3 style="margin-top:0">기준 문서를 선택하세요</h3>
  <div id="anchor-list"></div>
  <button onclick="send({skip:true})">건너뛰기 (표준 없이)</button>
</div></div>
<div id="parties"><div class="card">
  <h3 style="margin-top:0">계약 당사자 정보를 입력하세요</h3>
  <p style="margin:0 0 6px; color:#888; font-size:13px">문서를 편집하기 전에 갑·을 정보를 먼저 채워주세요.</p>
  <div id="parties-list"></div>
  <div style="display:flex; gap:8px; margin-top:12px">
    <button class="primary" style="flex:1" onclick="submitParties()">저장하고 계속</button>
    <button onclick="partiesDismissed=true; closeParties();">나중에</button>
  </div>
</div></div>

<script>
const WS = "ws://127.0.0.1:__WS_PORT__";
let canvas = null, awaiting = null, ws = null, partiesDismissed = false;
let staging = false, pending = [];   // 묶어 편집: 대기 중인 op들 (일괄 batch 전송)

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
function send(obj){ ws.send(JSON.stringify(obj)); awaiting=null; document.body.classList.remove('awaiting'); setStatus('처리 중…','busy'); showErr(null); closeAnchor(); closeParties(); }

function onInterrupt(c){
  showErr(c && c.error);
  if (c && c.type === 'awaiting_anchor_choice') { openAnchor(c.candidates||[]); return; }
  if (c && c.canvas) { canvas = c.canvas; render(); }
  awaiting = c; document.body.classList.add('awaiting'); setStatus('편집 대기');
  // Contract parties still blank → collect them first, before free editing.
  if (c && (c.missing_parties||[]).length && !partiesDismissed) openParties();
}

function render(){
  if(!canvas) return;
  document.getElementById('title').textContent = canvas.title || 'MARU 문서 편집';
  const doc = document.getElementById('doc'); doc.innerHTML='';
  if (canvas.title){ const t=document.createElement('div'); t.className='doc-title'; t.textContent=canvas.title; doc.appendChild(t); }
  const parties = ((canvas.metadata||{}).parties)||[];
  if (parties.length){ const p=document.createElement('div'); p.className='parties';
    p.textContent = parties.map(x=>[x.label, x.name || '(미입력)'].join(': ')).join('  ·  ');
    if (incompleteParties().length){ const e=btn('당사자 정보 입력', openParties); e.style.marginLeft='8px'; p.appendChild(e); }
    doc.appendChild(p); }
  (canvas.sections||[]).forEach(sec => {
    const sd=document.createElement('div'); sd.className='section';
    const art=((sec.metadata||{}).article_no)||''; const head=[art, sec.title].filter(Boolean).join(' ');
    if(head){ const h=document.createElement('h2'); h.textContent=head; sd.appendChild(h); }
    (sec.blocks||[]).forEach((b, i) => sd.appendChild(blockEl(sec, b, i)));
    sd.appendChild(addRow(sec));   // 엑셀 새 행처럼 섹션 맨 아래 인라인 추가
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
  acts.appendChild(btn('삭제', ()=>act({op:'delete', block_id:b.block_id}, '삭제: '+b.block_id)));
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
  const go=btn('적용', ()=>{ act({op:'edit', block_id:b.block_id, feedback:ta.value}, '수정: '+b.block_id); box.remove(); });
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
  act({op:'add', content:text}, '블록 추가(문서 끝)');
}
function addRow(sec){
  const wrap=document.createElement('div'); wrap.className='addrow';
  wrap.appendChild(btn('＋ 블록 추가', ()=>{
    if(wrap.querySelector('.inline')) return;
    const box=document.createElement('div'); box.className='inline';
    const ta=document.createElement('textarea'); ta.rows=2;
    ta.placeholder='이 섹션에 추가할 블록 내용 (비우면 AI가 생성)';
    const go=btn('저장', ()=>{ act({op:'add', section_id:sec.section_id, content:ta.value}, '추가 @ '+(sec.title||sec.section_id)); box.remove(); });
    go.className='primary';
    const cancel=btn('취소', ()=>box.remove());
    box.append(ta, go, cancel); wrap.appendChild(box); ta.focus();
  }));
  return wrap;
}

// 묶어 편집: staging이면 op을 대기열에 쌓고, 아니면 즉시 전송.
function act(op, label){
  if(staging){ pending.push({op, label}); renderTray(); }
  else send(op);
}
function toggleStaging(){
  staging=!staging;
  const b=document.getElementById('stagebtn');
  b.textContent='묶어 편집: '+(staging?'켜짐':'꺼짐');
  b.classList.toggle('primary', staging);
}
function renderTray(){
  const tray=document.getElementById('tray');
  tray.innerHTML='';
  if(!pending.length){ tray.style.display='none'; return; }
  tray.style.display='block';
  const h=document.createElement('div'); h.className='tray-h';
  h.textContent=`대기 중인 수정 (${pending.length})`; tray.appendChild(h);
  pending.forEach((p, i)=>{ const r=document.createElement('div'); r.className='tray-item';
    r.appendChild(btn('✕', ()=>{ pending.splice(i,1); renderTray(); }));
    const t=document.createElement('span'); t.textContent=p.label; r.appendChild(t);
    tray.appendChild(r); });
  const bar=document.createElement('div'); bar.className='tray-bar';
  const apply=btn(`일괄 적용(${pending.length})`, applyBatch); apply.className='primary';
  bar.append(apply, btn('비우기', ()=>{ pending=[]; renderTray(); }));
  tray.appendChild(bar);
}
function applyBatch(){
  if(!pending.length) return;
  const ops=pending.map(p=>p.op); pending=[]; renderTray();
  send({op:'batch', ops});
}
function finalizeDoc(){
  if(pending.length && !confirm('대기 중인 수정 '+pending.length+'건이 적용되지 않았습니다. 그래도 확정할까요?')) return;
  send({op:'finalize'});
}
function openAnchor(cands){
  const list=document.getElementById('anchor-list'); list.innerHTML='';
  cands.forEach((c,i)=>{ const b=document.createElement('button');
    b.innerHTML=`<b>${c.name}</b> <span style="color:#888">관련도 ${c.score}</span>`;
    b.onclick=()=>send({index:i}); list.appendChild(b); });
  document.getElementById('anchor').style.display='flex'; setStatus('기준 문서 선택');
}
function closeAnchor(){ document.getElementById('anchor').style.display='none'; }

function incompleteParties(){
  return (((canvas||{}).metadata||{}).parties||[]).filter(p => !((p.name||'').trim()));
}
function ptyField(key, label, val){
  const w=document.createElement('div');
  const l=document.createElement('label'); l.textContent=label;
  const i=document.createElement('input'); i.dataset.key=key; i.value=val||'';
  w.append(l, i); return w;
}
function openParties(){
  const list=document.getElementById('parties-list'); list.innerHTML='';
  const incomplete=incompleteParties();
  const targets=incomplete.length ? incomplete : (((canvas||{}).metadata||{}).parties||[]);
  targets.forEach(p => {
    const box=document.createElement('div'); box.className='pty'; box.dataset.label=p.label||'';
    const role=p.role ? ` <span style="color:#888;font-weight:400">(${p.role})</span>` : '';
    box.innerHTML = `<b>${p.label||'당사자'}${role}</b>`;
    box.appendChild(ptyField('name', '상호/성명', p.name));
    box.appendChild(ptyField('representative', '대표자', p.representative));
    box.appendChild(ptyField('address', '주소', p.address));
    list.appendChild(box);
  });
  document.getElementById('parties').style.display='flex'; setStatus('당사자 정보 입력');
}
function submitParties(){
  const parties=[...document.querySelectorAll('#parties-list .pty')].map(box => {
    const out={label: box.dataset.label};
    box.querySelectorAll('input').forEach(i => { out[i.dataset.key]=i.value.trim(); });
    return out;
  });
  send({op:'set_parties', parties});
}
function closeParties(){ document.getElementById('parties').style.display='none'; }
connect();
</script>
</body></html>
"""
