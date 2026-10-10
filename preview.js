const previews = [...document.querySelectorAll('.solver-preview')];
const deferredFrames = [...document.querySelectorAll('iframe[data-src]')];
const initialized = new Set(), visible = new Set();
let paused = matchMedia('(prefers-reduced-motion: reduce)').matches;
const button = document.getElementById('motion-toggle');
const send = (frame, cmd, value) => {
  if (frame.hasAttribute('src')) frame.contentWindow?.postMessage({lacamCmd: {cmd, value}}, location.origin);
};
const showFrame = frame => {
  frame.classList.add('preview-ready');
  frame.parentElement.querySelector('.preview-poster')?.remove();
};
function update() {
  button.textContent = paused ? 'Play planning previews' : 'Pause planning previews';
  button.setAttribute('aria-pressed', String(paused));
  for (const frame of previews) send(frame, paused || !visible.has(frame) || document.hidden ? 'pause' : 'play');
}
window.addEventListener('message', event => {
  if (event.origin !== location.origin) return;
  const frame = previews.find(item => item.contentWindow === event.source);
  if (!frame || !event.data?.lacamState) return;
  const state = event.data.lacamState;
  if (!initialized.has(frame)) {
    initialized.add(frame);
    showFrame(frame);
    send(frame, 'seek', Math.floor(state.T * .35));
    send(frame, 'speed', frame.src.includes('/construction/') ? 48 : 24);
    update();
  } else if (!paused && visible.has(frame) && !document.hidden && state.simT >= state.T_END) {
    send(frame, 'reset');
  }
});
function loadFrame(frame) {
  const source = frame.dataset.src;
  if (!source) return;
  frame.src = source;
  frame.removeAttribute('data-src');
}
// Native loading="lazy" can fetch frames far below the fold. Start these only
// when visible, so first-screen images do not compete with Three.js and video.
const observer = new IntersectionObserver(entries => {
  for (const entry of entries) {
    const frame = entry.target;
    if (entry.isIntersecting) {
      visible.add(frame);
      loadFrame(frame);
    } else {
      visible.delete(frame);
    }
  }
  update();
}, {threshold: .01});
for (const frame of deferredFrames) observer.observe(frame);
button.addEventListener('click', () => {paused = !paused; update();});
document.addEventListener('visibilitychange', update);
update();
