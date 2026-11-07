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
.seg{display:flex;margin:10px 12px;background:#111;border-radius:12px;padding:3px}
.seg button{all:unset;flex:1;text-align:center;padding:9px;border-radius:9px;color:var(--m);font-size:14px}
.seg button.on{background:#262626;color:var(--t)}
.crumb{display:flex;align-items:center;gap:8px;margin:4px 12px 6px}
.crumb .t{flex:1;font-weight:700;font-size:16px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.crumb button{all:unset;background:#161616;border-radius:10px;padding:8px 12px;font-size:14px;color:var(--t)}
.crumb button.play{background:var(--a);color:#fff}
.search{display:block;width:calc(100% - 24px);margin:6px 12px;background:#0d0d0d;border:1px solid var(--b);color:var(--t);
 border-radius:12px;padding:11px 12px;font-size:16px;box-sizing:border-box}
.it{display:flex;align-items:center;gap:12px;padding:12px 16px;border-bottom:1px solid #141414}
.it:active{background:#111}
.it .ic{width:26px;text-align:center;font-size:18px;flex:0 0 auto}
.it .nm{flex:1;min-width:0}
.it .nm div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.it .nm small{color:var(--m);font-size:12px}
.it .side{color:var(--m);font-size:13px;flex:0 0 auto}
.star{all:unset;font-size:22px;padding:4px 6px;color:var(--m)}
.star.on{color:var(--a)}
.subh{color:var(--m);font-size:12px;letter-spacing:1px;text-transform:uppercase;margin:14px 16px 4px}
#p-stream.on{display:flex;flex-direction:column;height:100%;min-height:470px;padding-bottom:18px}
#scard{width:min(64vw,300px);flex:0 1 300px;min-height:70px;margin:8px auto 0;border-radius:14px;background:#141414;
 display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;color:var(--a)}
#scard svg{height:42%;max-height:110px;width:auto;fill:currentColor}
#p-stream #title{margin-top:14px}
body.top #toast{bottom:auto;top:52px}
#scard div{color:var(--m);font-size:13px;text-align:center;padding:0 14px;line-height:1.4}
.hint{color:var(--m);font-size:12px;text-align:center;margin:4px 16px 0;line-height:1.45}
.spacer{flex:1 1 0;min-height:6px}
#p-stream .transport{gap:min(7vw,30px);margin-top:20px}
#p-stream #sback,#p-stream #sfwd{width:min(18vw,72px);height:min(18vw,72px)}
#p-stream #sback svg,#p-stream #sfwd svg{width:min(8vw,32px);height:min(8vw,32px)}
.svol{display:flex;justify-content:center;align-items:center;gap:14px;margin:6px 22px}
.svol .btn{font-size:26px}
.seg.small{margin:10px auto 0;width:min(78vw,320px)}
.seg.small button{padding:6px;font-size:12px}
#toast{position:fixed;left:50%;bottom:86px;transform:translateX(-50%);background:#222;color:#fff;padding:10px 16px;
 border-radius:20px;font-size:14px;opacity:0;transition:opacity .2s;pointer-events:none;z-index:8;
 max-width:88vw;width:max-content;text-align:center;line-height:1.35}
#off{display:none;position:fixed;inset:0;background:rgba(0,0,0,.88);align-items:center;justify-content:center;
 text-align:center;padding:30px;color:var(--m);line-height:1.5;z-index:9}
</style></head><body>
<div id="app">
<header><span>Mediasoitin</span><button id="forget" style="display:none" onclick="Android.forget()">Vaihda tietokone</button></header>
<main id="main">
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
  <div id="rhistBox" style="display:none"><div class="subh">Äsken soi</div><div id="rhist"></div></div>
  <div class="row">
   <button class="btn pill" onclick="cmd('fullscreen')">⛶ Koko näyttö</button>
   <button class="btn pill" onclick="cmd('stop')">■ Pysäytä</button>
   <button class="btn pill" id="nextep" style="display:none" onclick="cmd('next_episode')">⏭ Seuraava jakso</button>
   <button class="btn pill" id="skipintro" style="display:none;background:var(--a);color:#fff" onclick="cmd('skip_intro')">⏭ Ohita alkutunnari</button>
  </div>
 </section>
 <section class="page" id="p-list"><div id="list"></div></section>
 <section class="page" id="p-browse">
  <div class="seg"><button id="segF" class="on" onclick="setMode('f')">Kansiot</button><button id="segL" onclick="setMode('l')">Kirjasto</button></div>
  <div class="crumb"><button id="bUp" onclick="up()">‹ Takaisin</button><div class="t" id="bTitle">Tietokone</div>
   <button class="play" id="bPlay" onclick="playHere()">▶ Toista</button></div>
  <input id="bFilter" class="search" placeholder="Suodata…" autocomplete="off">
  <div id="bList"></div>
 </section>
 <section class="page" id="p-radio">
  <input id="rq" class="search" placeholder="Hae asemaa (esim. Yle, Nova, jazz)…" autocomplete="off" enterkeyhint="search">
  <div class="subh">Suosikit</div><div id="radio"></div>
  <div class="subh" id="rhead">Suomalaiset asemat</div><div id="rres"></div>
 </section>
 <section class="page" id="p-stream">
  <div id="scard"><svg viewBox="0 0 24 24"><path d="M21 3H3a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h5v2h8v-2h5a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zm0 14H3V5h18zM10 7.5v7l5.5-3.5z"/></svg>
   <div>Netflix · YouTube · Disney+<br>Viaplay · muut selaimessa</div></div>
  <div id="title">Suoratoisto</div>
  <div class="hint">Kelaus: YouTube 5 s, Netflix ja Disney+ 10 s.<br>Pidä nuolta pohjassa, niin kelaus jatkuu.</div>
  <div class="seg small"><button id="ppMedia" onclick="setPP('media')">Tauko: medianäppäin</button><button id="ppSpace" onclick="setPP('space')">Tauko: välilyönti</button></div>
  <div class="spacer"></div>
  <div class="row"><button class="btn pill" onclick="st_('fullscreen')">⛶ Koko näyttö</button></div>
  <div class="svol">
   <button class="btn" id="svd">−</button>
   <button class="btn" onclick="st_('mute')" style="font-size:20px">🔇</button>
   <button class="btn" id="svu">+</button>
  </div>
  <div class="transport">
   <button class="btn" id="sback"><svg viewBox="0 0 24 24"><path d="M11 18V6l-8.5 6 8.5 6zm.5-6 8.5 6V6l-8.5 6z"/></svg></button>
   <button class="btn" id="spp" onclick="sPlay()" style="width:min(22vw,92px);height:min(22vw,92px);background:var(--a);color:#fff"><svg viewBox="0 0 24 24" style="width:min(10vw,40px);height:min(10vw,40px)"><path d="M3 5v14l9-7zM14 5h3v14h-3zm5 0h3v14h-3z"/></svg></button>
   <button class="btn" id="sfwd"><svg viewBox="0 0 24 24"><path d="M4 18l8.5-6L4 6v12zm9-12v12l8.5-6L13 6z"/></svg></button>
  </div>
 </section>
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
 <button data-p="p-browse"><svg viewBox="0 0 24 24"><path d="M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8z"/></svg>Selaa</button>
 <button data-p="p-radio"><svg viewBox="0 0 24 24"><path d="M4 8h16a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1zm3 9a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zm6-4v2h6v-2zm-6.6-6.1L16.7 3l.7 1.9L8.6 8z"/></svg>Radio</button>
 <button data-p="p-stream"><svg viewBox="0 0 24 24"><path d="M21 3H3a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h5v2h8v-2h5a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zm0 14H3V5h18zM10 7.5v7l5.5-3.5z"/></svg>Suoratoisto</button>
 <button data-p="p-pad"><svg viewBox="0 0 24 24"><path d="M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zm0 2v9h14V5zm0 11v3h6.5v-3zm8 0v3H19v-3z"/></svg>Hiiri</button>
</nav>
</div>
<div id="toast"></div>
<div id="off">Yhteys soittimeen katkesi.<br><br>Onko soitin käynnissä (myös taustalla) ja puhelin samassa wifissä?</div>
<script>
const P=new URLSearchParams(location.search),K=P.get('k');
const $=id=>document.getElementById(id);
let st={},dragging=false,volDrag=false,lastCover=null,fails=0;
if(window.Android){$('forget').style.display='block'}
function tab(id){document.body.classList.toggle('top',id==='p-stream');document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('on',x.dataset.p===id));
 document.querySelectorAll('.page').forEach(p=>p.classList.toggle('on',p.id===id));$('txt').blur();
 if(id==='p-browse'&&!B.loaded)load('');if(id==='p-radio'&&!R.loaded)radioSearch('')}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>tab(b.dataset.p));
let toastT=0;function toast(t,ms){const e=$('toast');e.textContent=t;e.style.opacity=1;clearTimeout(toastT);toastT=setTimeout(()=>e.style.opacity=0,ms||1600)}
function esc(t){return String(t).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
async function api(path){const r=await fetch(path+(path.includes('?')?'&':'?')+'k='+K,{cache:'no-store'});return r.json()}
// ---- selaus
const B={mode:'f',loaded:false,path:'',parent:null,items:[],lib:null,artist:null,album:null};
const ICON={dir:'📁',drive:'💽',disc:'💿',video:'🎬',audio:'🎵',list:'📃'};
function setMode(m){B.mode=m;$('segF').classList.toggle('on',m==='f');$('segL').classList.toggle('on',m==='l');
 $('bFilter').value='';if(m==='f')load(B.path);else libLoad()}
function row(icon,name,sub,side,onTap,onHold){const d=document.createElement('div');d.className='it';
 d.innerHTML=`<div class="ic">${icon}</div><div class="nm"><div>${esc(name)}</div>${sub?`<small>${esc(sub)}</small>`:''}</div>${side?`<div class="side">${esc(side)}</div>`:''}`;
 d.onclick=onTap;if(onHold)d.oncontextmenu=e=>{e.preventDefault();onHold()};return d}
function render(){const L=$('bList'),f=$('bFilter').value.trim().toLowerCase();L.innerHTML='';
 const items=B.items.filter(x=>!f||x.label.toLowerCase().includes(f));
 if(!items.length){L.innerHTML='<div class="empty">'+(B.mode==='l'&&!B.lib?.artists?.length?'Kirjasto on tyhjä.<br>Lisää musiikkikansio soittimen Kirjasto-välilehdellä.':'Ei sisältöä.')+'</div>';return}
 items.forEach(x=>L.appendChild(row(x.icon,x.label,x.sub,x.side,x.tap,x.hold)))}
async function load(path){B.loaded=true;B.mode='f';$('bTitle').textContent='Ladataan…';
 let d;try{d=await api('/api/browse?path='+encodeURIComponent(path))}catch(e){toast('Ei yhteyttä');return}
 if(d.error){toast(d.error);return}
 B.path=d.path;B.parent=d.parent;$('bTitle').textContent=d.title;$('bUp').style.visibility=d.parent===null?'hidden':'visible';
 $('bPlay').style.display=d.path?'block':'none';$('bFilter').value='';
 B.items=d.items.map(x=>({icon:ICON[x.type]||'📄',label:x.name,
  tap:()=>{if(x.type==='dir'||(x.type==='drive'))load(x.path);else if(x.type==='disc'){cmd('play_path',{path:x.path});tab('p-play')}
   else{cmd('play_path',{path:x.path});toast('Toistetaan');tab('p-play')}},
  hold:x.type==='dir'||x.type==='drive'?null:()=>{cmd('queue_path',{path:x.path});toast('Lisätty soittolistaan')}}));
 render();$('main').scrollTop=0}
async function libLoad(){B.loaded=true;if(!B.lib){$('bTitle').textContent='Ladataan…';try{B.lib=await api('/api/library')}catch(e){toast('Ei yhteyttä');return}}
 B.artist=null;B.album=null;libRender()}
function libRender(){$('bFilter').value='';const A=B.lib.artists||[];
 if(!B.artist){$('bTitle').textContent='Artistit';$('bUp').style.visibility='hidden';$('bPlay').style.display='none';
  B.items=A.map(a=>({icon:'👤',label:a.name,side:a.albums.length+' alb.',tap:()=>{B.artist=a;libRender()}}))}
 else if(!B.album){const a=B.artist;$('bTitle').textContent=a.name;$('bUp').style.visibility='visible';$('bPlay').style.display='none';
  B.items=a.albums.map(al=>({icon:'💿',label:al.name,sub:[al.year,al.count+' kappaletta'].filter(Boolean).join(' · '),tap:()=>openAlbum(a.name,al.name)}))}
 render();$('main').scrollTop=0}
async function openAlbum(artist,album){let d;try{d=await api('/api/album?artist='+encodeURIComponent(artist)+'&album='+encodeURIComponent(album))}catch(e){return}
 B.album=d;$('bTitle').textContent=album;$('bUp').style.visibility='visible';$('bPlay').style.display='block';
 const paths=d.tracks.map(t=>t.path);
 B.items=d.tracks.map((t,i)=>({icon:'🎵',label:(t.track?t.track+'. ':'')+t.title,side:t.dur,
  tap:()=>{cmd('play_paths',{paths,index:i});toast('Toistetaan');tab('p-play')},hold:()=>{cmd('queue_path',{path:t.path});toast('Lisätty soittolistaan')}}));
 render();$('main').scrollTop=0}
function up(){if(B.mode==='f'){if(B.parent!==null)load(B.parent)}else{if(B.album){B.album=null;libRender()}else if(B.artist){B.artist=null;libRender()}}}
function playHere(){if(B.mode==='f'){if(B.path){cmd('play_path',{path:B.path});toast('Toistetaan kansio');tab('p-play')}}
 else if(B.album){cmd('play_paths',{paths:B.album.tracks.map(t=>t.path),index:0});toast('Toistetaan albumi');tab('p-play')}}
$('bFilter').addEventListener('input',render);
// ---- radio
const R={loaded:false,results:[]};let rT=0;
function isFav(url){return (st.radio_favs||[]).some(f=>f.url===url)}
function starBtn(stn){const b=document.createElement('button');b.className='star'+(isFav(stn.url)?' on':'');b.textContent=isFav(stn.url)?'★':'☆';
 b.onclick=e=>{e.stopPropagation();const was=isFav(stn.url);cmd('radio_fav',stn);toast(was?'Poistettu suosikeista':'Lisätty suosikkeihin');
  b.classList.toggle('on',!was);b.textContent=was?'☆':'★'};return b}
function renderRadio(){const F=$('radio');F.innerHTML='';const favs=st.radio_favs||[];
 if(!favs.length)F.innerHTML='<div class="empty" style="padding:14px">Ei suosikkeja vielä. Lisää ☆-tähdellä.</div>';
 favs.forEach(f=>{const d=row('📻',f.name,'',null,()=>{cmd('radio_play',f);toast('Kuunnellaan '+f.name);tab('p-play')});d.appendChild(starBtn(f));F.appendChild(d)});
 const Rr=$('rres');Rr.innerHTML='';R.results.forEach(s=>{const d=row('📻',s.name,[s.info,s.country&&s.country!=='FI'?s.country:''].filter(Boolean).join(' · '),null,
  ()=>{cmd('radio_play',s);toast('Kuunnellaan '+s.name);tab('p-play')});d.appendChild(starBtn(s));Rr.appendChild(d)})}
async function radioSearch(q){R.loaded=true;$('rhead').textContent=q?'Hakutulokset: '+q:'Suomalaiset asemat';
 $('rres').innerHTML='<div class="empty" style="padding:14px">Haetaan…</div>';
 let d;try{d=await api('/api/radio?q='+encodeURIComponent(q))}catch(e){d={error:'Ei yhteyttä'}}
 if(d.error){$('rres').innerHTML='<div class="empty" style="padding:14px">'+esc(d.error)+'</div>';return}
 R.results=d;renderRadio()}
$('rq').addEventListener('input',()=>{clearTimeout(rT);const q=$('rq').value.trim();rT=setTimeout(()=>radioSearch(q.length>=2?q:''),600)});
$('rq').addEventListener('keydown',e=>{if(e.key==='Enter'){clearTimeout(rT);radioSearch($('rq').value.trim());$('rq').blur()}});
function fmt(s){if(s==null||s<0)return'0:00';s=Math.floor(s);const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60;
 return h?`${h}:${String(m).padStart(2,'0')}:${String(x).padStart(2,'0')}`:`${m}:${String(x).padStart(2,'0')}`}
async function cmd(c,v){try{await fetch('/api/cmd?k='+K,{method:'POST',body:JSON.stringify({cmd:c,value:v})});
 if(!c.startsWith('mouse'))setTimeout(poll,c==='stream'?300:150)}catch(e){}}
// ---- suoratoisto (selaimen ohjaus)
function st_(a){cmd('stream',a)}
let PP='media';try{PP=localStorage.getItem('ppMode')||'media'}catch(e){}
function setPP(m){PP=m;try{localStorage.setItem('ppMode',m)}catch(e){}
 $('ppMedia').classList.toggle('on',m==='media');$('ppSpace').classList.toggle('on',m==='space')}
setPP(PP);
function sPlay(){st_(PP==='space'?'space':'playpause')}
function repeat(el,fn){let t1=0,t2=0;const stop=()=>{clearTimeout(t1);clearInterval(t2)};
 el.addEventListener('pointerdown',e=>{e.preventDefault();stop();fn();t1=setTimeout(()=>{t2=setInterval(fn,330)},550)});
 ['pointerup','pointerleave','pointercancel'].forEach(n=>el.addEventListener(n,stop));
 el.addEventListener('contextmenu',e=>e.preventDefault())}
repeat($('sback'),()=>st_('back'));repeat($('sfwd'),()=>st_('fwd'));
repeat($('svd'),()=>st_('vol_down'));repeat($('svu'),()=>st_('vol_up'));
let noticeId=null,firstPoll=true;
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
 if(noticeId!==null&&st.notice_id!==noticeId&&st.notice)toast(st.notice,3500);noticeId=st.notice_id||0;
 // Soitin taustalla eikä toista mitään -> avataan suoraan suoratoiston ohjaus.
 if(firstPoll){firstPoll=false;if(st.hidden&&st.title==='Ei toistoa')tab('p-stream')}
 $('title').textContent=st.title||'Ei toistoa';$('artist').textContent=st.artist||'';
 $('pos').textContent=fmt(st.pos);$('dur').textContent=fmt(st.dur);
 if(!dragging)$('seek').value=st.dur?Math.round(1000*st.pos/st.dur):0;
 if(!volDrag)$('vol').value=st.volume??100;
 $('mute').textContent=st.mute?'🔇':'🔊';
 $('nextep').style.display=st.has_next_episode?'flex':'none';
 $('skipintro').style.display=st.intro_active?'flex':'none';
 $('pi').innerHTML=st.paused?'<path d="M8 5v14l11-7z"/>':'<path d="M6 5h4v14H6zm8 0h4v14h-4z"/>';
 const coverSig=(st.cover_id||'')+'|'+(st.video?1:0);
 if(coverSig!==lastCover){lastCover=coverSig;
  if(st.cover_id){$('cover').style.backgroundImage=`url(/api/cover?k=${K}&v=${st.cover_id})`;$('cover').textContent=''}
  else{$('cover').style.backgroundImage='';$('cover').textContent=st.video?'▶':'♪'}}
 list($('list'),(st.playlist||[]).map((n,i)=>(i+1)+'. '+n),st.current,i=>cmd('play_index',i),'Soittolista on tyhjä.');
 const hist=st.radio_history||[];$('rhistBox').style.display=hist.length?'block':'none';
 const hs=JSON.stringify(hist);if($('rhist').dataset.sig!==hs){$('rhist').dataset.sig=hs;$('rhist').innerHTML=
  hist.map((h,i)=>`<div class="item${i===0?' cur':''}" style="padding:10px 18px">${esc(h)}</div>`).join('')}
 const favSig=JSON.stringify(st.radio_favs||[]);if(R.favSig!==favSig){R.favSig=favSig;renderRadio()}
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
