"""Kaukosäätimen mobiilisivu (selain ja Android-sovellus käyttävät samaa sivua)."""

PAGE = r"""<!DOCTYPE html>
<html lang="fi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">
<meta name="theme-color" content="#000000">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<title>Mediasoitin</title>
<style>
:root{--a:#D35400;--t:#E6E6E6;--m:#8C8C8C;--s:#121212;--b:#1e1e1e}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{height:100%}
body{margin:0;background:#000;color:var(--t);font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
 user-select:none;-webkit-user-select:none;overscroll-behavior:none}
#app{display:flex;flex-direction:column;height:100%}
header{display:flex;align-items:center;justify-content:space-between;padding:12px 16px 6px;color:var(--m);
 font-size:12px;letter-spacing:1px;text-transform:uppercase}
header button{all:unset;color:var(--m);font-size:12px;padding:4px 8px}
main{flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch}
.page{display:none;padding-bottom:16px}.page.on{display:block}
nav{display:flex;border-top:1px solid var(--b);background:#050505;padding-bottom:env(safe-area-inset-bottom)}
nav button{all:unset;flex:1;text-align:center;padding:10px 0 12px;color:var(--m);font-size:11px}
nav button svg{display:block;margin:0 auto 3px;width:24px;height:24px;fill:currentColor}
nav button.on{color:var(--a)}
#cover{width:min(64vw,300px);aspect-ratio:1;margin:8px auto 0;border-radius:14px;background:#141414 center/cover no-repeat;
 display:flex;align-items:center;justify-content:center;font-size:64px;color:var(--a)}
#title{font-size:21px;font-weight:700;text-align:center;margin:16px 16px 4px;line-height:1.25}
#artist{color:var(--a);text-align:center;font-size:16px;min-height:20px;margin:0 16px}
.time{display:flex;justify-content:space-between;color:var(--m);font-size:13px;margin:16px 22px 4px;font-variant-numeric:tabular-nums}
input[type=range]{-webkit-appearance:none;appearance:none;width:calc(100% - 44px);margin:0 22px;height:6px;border-radius:3px;background:#2a2a2a;outline:none}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:24px;height:24px;border-radius:50%;background:var(--a)}
input[type=range]::-moz-range-thumb{width:24px;height:24px;border-radius:50%;background:var(--a);border:0}
.row{display:flex;justify-content:center;align-items:center;gap:10px;margin:16px 8px;flex-wrap:wrap}
.transport{display:flex;justify-content:center;align-items:center;gap:min(2.5vw,12px);margin:16px 8px;flex-wrap:nowrap}
.transport .btn{width:min(14vw,60px);height:min(14vw,60px);flex:0 0 auto}
.transport .btn svg{width:min(6.5vw,26px);height:min(6.5vw,26px)}
.transport #play{width:min(20vw,84px);height:min(20vw,84px)}
.transport #play svg{width:min(9vw,36px);height:min(9vw,36px)}
.btn{background:var(--s);color:var(--t);border:0;border-radius:50%;width:60px;height:60px;display:flex;
 align-items:center;justify-content:center;touch-action:manipulation;font-size:15px}
.btn:active{background:#2a2a2a}
.btn svg{width:26px;height:26px;fill:currentColor}
#play{width:84px;height:84px;background:var(--a);color:#fff}
#play svg{width:36px;height:36px}
.pill{width:auto;height:44px;border-radius:22px;padding:0 14px;white-space:nowrap;font-size:14px}
.vol{display:flex;align-items:center;gap:10px;margin:6px 22px}
.vol input{margin:0;width:100%}
.item{padding:14px 18px;border-bottom:1px solid #161616;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.item.cur{color:var(--a);font-weight:700}
.item:active{background:#111}
.empty{color:var(--m);text-align:center;padding:40px 20px;line-height:1.5}
#pad{margin:12px;height:52vh;border-radius:16px;background:#0d0d0d;border:1px solid var(--b);display:flex;
 align-items:center;justify-content:center;color:#333;font-size:14px;touch-action:none;text-align:center;padding:20px}
.keys{display:flex;gap:8px;margin:0 12px;flex-wrap:wrap}
.keys .btn{flex:1;border-radius:12px;height:50px;min-width:70px}
.type{display:flex;gap:8px;margin:12px}
.type input{flex:1;background:#0d0d0d;border:1px solid var(--b);color:var(--t);border-radius:12px;padding:12px;font-size:16px}
.type .btn{border-radius:12px;width:auto;padding:0 18px;height:auto;background:var(--a);color:#fff}
#off{display:none;position:fixed;inset:0;background:rgba(0,0,0,.88);align-items:center;justify-content:center;
 text-align:center;padding:30px;color:var(--m);line-height:1.5;z-index:9}
</style></head><body>
<div id="app">
<header><span>Mediasoitin</span><button id="forget" style="display:none" onclick="Android.forget()">Vaihda tietokone</button></header>
<main>
 <section class="page on" id="p-play">
  <div id="cover">♪</div>
  <div id="title">–</div>
  <div id="artist"></div>
  <div class="time"><span id="pos">0:00</span><span id="dur">0:00</span></div>
  <input type="range" id="seek" min="0" max="1000" value="0">
  <div class="transport">
   <button class="btn" onclick="cmd('seek',-10)"><svg viewBox="0 0 24 24"><path d="M11 18V6l-8.5 6 8.5 6zm.5-6 8.5 6V6l-8.5 6z"/></svg></button>
   <button class="btn" onclick="cmd('prev')"><svg viewBox="0 0 24 24"><path d="M6 6h2v12H6zm3.5 6 8.5 6V6z"/></svg></button>
   <button class="btn" id="play" onclick="cmd('toggle')"><svg id="pi" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg></button>
   <button class="btn" onclick="cmd('next')"><svg viewBox="0 0 24 24"><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z"/></svg></button>
   <button class="btn" onclick="cmd('seek',10)"><svg viewBox="0 0 24 24"><path d="M4 18l8.5-6L4 6v12zm9-12v12l8.5-6L13 6z"/></svg></button>
  </div>
  <div class="vol"><button class="btn pill" onclick="cmd('mute')" id="mute">🔊</button>
   <input type="range" id="vol" min="0" max="100" value="100"></div>
  <div class="row">
   <button class="btn pill" onclick="cmd('fullscreen')">⛶ Koko näyttö</button>
   <button class="btn pill" onclick="cmd('stop')">■ Pysäytä</button>
   <button class="btn pill" id="nextep" style="display:none" onclick="cmd('next_episode')">⏭ Seuraava jakso</button>
  </div>
 </section>
 <section class="page" id="p-list"><div id="list"></div></section>
 <section class="page" id="p-radio"><div id="radio"></div></section>
 <section class="page" id="p-pad">
  <div id="pad">Liikuta sormea: hiiri<br>Napauta: klikkaus · Kahdella sormella: rullaus<br>Kahden sormen napautus: oikea klikkaus</div>
  <div class="keys">
   <button class="btn" onclick="cmd('mouse_click','left')">Vasen</button>
   <button class="btn" onclick="cmd('mouse_click','right')">Oikea</button>
   <button class="btn" onclick="cmd('key','esc')">Esc</button>
   <button class="btn" onclick="cmd('key','backspace')">⌫</button>
   <button class="btn" onclick="cmd('key','enter')">Enter</button>
  </div>
  <div class="type"><input id="txt" placeholder="Kirjoita tietokoneelle…" autocomplete="off">
   <button class="btn" onclick="sendText()">Lähetä</button></div>
 </section>
</main>
<nav>
 <button class="on" data-p="p-play"><svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>Toisto</button>
 <button data-p="p-list"><svg viewBox="0 0 24 24"><path d="M3 6h13v2H3zm0 5h13v2H3zm0 5h9v2H3zm15-5v8.2A3 3 0 1 0 20 22V13h2v-2z"/></svg>Soittolista</button>
 <button data-p="p-radio"><svg viewBox="0 0 24 24"><path d="M4 8h16a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1zm3 9a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zm6-4v2h6v-2zm-6.6-6.1L16.7 3l.7 1.9L8.6 8z"/></svg>Radio</button>
 <button data-p="p-pad"><svg viewBox="0 0 24 24"><path d="M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zm0 2v9h14V5zm0 11v3h6.5v-3zm8 0v3H19v-3z"/></svg>Hiiri</button>
</nav>
</div>
<div id="off">Yhteys soittimeen katkesi.<br><br>Onko soitin auki ja puhelin samassa wifissä?</div>
<script>
const P=new URLSearchParams(location.search),K=P.get('k');
const $=id=>document.getElementById(id);
let st={},dragging=false,volDrag=false,lastCover=null,fails=0;
if(window.Android){$('forget').style.display='block'}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{
 document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('on',x===b));
 document.querySelectorAll('.page').forEach(p=>p.classList.toggle('on',p.id===b.dataset.p));
 $('txt').blur()});
function fmt(s){if(s==null||s<0)return'0:00';s=Math.floor(s);const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60;
 return h?`${h}:${String(m).padStart(2,'0')}:${String(x).padStart(2,'0')}`:`${m}:${String(x).padStart(2,'0')}`}
async function cmd(c,v){try{await fetch('/api/cmd?k='+K,{method:'POST',body:JSON.stringify({cmd:c,value:v})});
 if(!c.startsWith('mouse'))setTimeout(poll,150)}catch(e){}}
function sendText(){const t=$('txt').value;if(t){cmd('type',t);$('txt').value=''}}
$('txt').addEventListener('keydown',e=>{if(e.key==='Enter'){sendText();cmd('key','enter')}});
function list(el,items,cur,fn,empty){const sig=JSON.stringify([items,cur]);if(el.dataset.sig===sig)return;el.dataset.sig=sig;
 el.innerHTML='';if(!items.length){el.innerHTML='<div class="empty">'+empty+'</div>';return}
 items.forEach((n,i)=>{const d=document.createElement('div');d.className='item'+(i===cur?' cur':'');
  d.textContent=n;d.onclick=()=>fn(i);el.appendChild(d)})}
async function poll(){
 try{const r=await fetch('/api/state?k='+K,{cache:'no-store'});if(r.status===403){location.reload();return}
  st=await r.json();fails=0;$('off').style.display='none'}
 catch(e){if(++fails>2)$('off').style.display='flex';return}
 document.documentElement.style.setProperty('--a',st.accent||'#D35400');
 $('title').textContent=st.title||'Ei toistoa';$('artist').textContent=st.artist||'';
 $('pos').textContent=fmt(st.pos);$('dur').textContent=fmt(st.dur);
 if(!dragging)$('seek').value=st.dur?Math.round(1000*st.pos/st.dur):0;
 if(!volDrag)$('vol').value=st.volume??100;
 $('mute').textContent=st.mute?'🔇':'🔊';
 $('nextep').style.display=st.has_next_episode?'flex':'none';
 $('pi').innerHTML=st.paused?'<path d="M8 5v14l11-7z"/>':'<path d="M6 5h4v14H6zm8 0h4v14h-4z"/>';
 const coverSig=(st.cover_id||'')+'|'+(st.video?1:0);
 if(coverSig!==lastCover){lastCover=coverSig;
  if(st.cover_id){$('cover').style.backgroundImage=`url(/api/cover?k=${K}&v=${st.cover_id})`;$('cover').textContent=''}
  else{$('cover').style.backgroundImage='';$('cover').textContent=st.video?'▶':'♪'}}
 list($('list'),(st.playlist||[]).map((n,i)=>(i+1)+'. '+n),st.current,i=>cmd('play_index',i),'Soittolista on tyhjä.');
 list($('radio'),(st.radio||[]).map(n=>'★  '+n),-1,i=>cmd('play_radio',i),
  'Ei suosikkiradioita.<br>Lisää asemia suosikeiksi soittimen Radio-välilehdellä (hiiren oikea → Lisää suosikiksi).');
}
$('seek').addEventListener('input',()=>{dragging=true;$('pos').textContent=fmt(st.dur*$('seek').value/1000)});
$('seek').addEventListener('change',()=>{cmd('seek_abs',st.dur*$('seek').value/1000);dragging=false});
let vt=0;$('vol').addEventListener('input',()=>{volDrag=true;const n=Date.now();if(n-vt>80){vt=n;cmd('volume',+$('vol').value)}});
$('vol').addEventListener('change',()=>{cmd('volume',+$('vol').value);volDrag=false});
// --- kosketuslevy
const pad=$('pad');let last=null,moved=0,t0=0,fingers=0,acc=[0,0],sacc=0,flushT=null;
function flush(){flushT=null;if(acc[0]||acc[1]){cmd('mouse_move',[Math.round(acc[0]),Math.round(acc[1])]);acc=[0,0]}
 if(Math.abs(sacc)>=1){cmd('mouse_scroll',Math.round(sacc));sacc=0}}
function queue(){if(!flushT)flushT=setTimeout(flush,35)}
pad.addEventListener('touchstart',e=>{e.preventDefault();fingers=Math.max(fingers,e.touches.length);
 const t=e.touches[0];last=[t.clientX,t.clientY,e.touches.length>1?e.touches[1].clientY:null];if(e.touches.length===1){moved=0;t0=Date.now()}},{passive:false});
pad.addEventListener('touchmove',e=>{e.preventDefault();const t=e.touches[0];if(!last)return;
 const dx=t.clientX-last[0],dy=t.clientY-last[1];moved+=Math.abs(dx)+Math.abs(dy);
 if(e.touches.length>1){sacc+=-dy*4}else{const sp=Math.hypot(dx,dy),g=1.2+Math.min(sp/12,2.2);acc[0]+=dx*g;acc[1]+=dy*g}
 last=[t.clientX,t.clientY];queue()},{passive:false});
pad.addEventListener('touchend',e=>{e.preventDefault();if(e.touches.length===0){
 if(moved<10&&Date.now()-t0<300){cmd('mouse_click',fingers>1?'right':'left')}fingers=0;last=null}
 else{const t=e.touches[0];last=[t.clientX,t.clientY]}},{passive:false});
setInterval(()=>{if(!document.hidden)poll()},1000);poll();
</script></body></html>"""
