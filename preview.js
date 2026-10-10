const previews=[...document.querySelectorAll('.solver-preview')];
let paused=matchMedia('(prefers-reduced-motion: reduce)').matches;
const initialized=new Set(),visible=new Set();
const send=(frame,cmd,value)=>frame.contentWindow?.postMessage({lacamCmd:{cmd,value}},location.origin);
const button=document.getElementById('motion-toggle');
function update(){button.textContent=paused?'Play planning previews':'Pause planning previews';button.setAttribute('aria-pressed',String(paused));for(const f of previews)send(f,paused||!visible.has(f)?'pause':'play');}
window.addEventListener('message',event=>{if(event.origin!==location.origin)return;const f=previews.find(x=>x.contentWindow===event.source);if(!f||!event.data?.lacamState)return;const state=event.data.lacamState;if(!initialized.has(f)){initialized.add(f);send(f,'seek',Math.floor(state.T*.35));send(f,'speed',f.src.includes('/construction/')?48:24);update();}else if(!paused&&visible.has(f)&&state.simT>=state.T_END){send(f,'reset');}});
const observer=new IntersectionObserver(entries=>{for(const e of entries){if(e.isIntersecting)visible.add(e.target);else visible.delete(e.target)}update();},{threshold:.05});previews.forEach(f=>observer.observe(f));button.addEventListener('click',()=>{paused=!paused;update()});update();
