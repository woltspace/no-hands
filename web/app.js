'use strict';
let csrf = '', previousQR = false, pending = false;
const el = id => document.getElementById(id);

async function json(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw Error(data.error || 'Unable to reach the setup app.');
  return data;
}

function error(message) {
  el('error').textContent = message;
  el('error').hidden = !message;
}

async function checks() {
  try {
    const data = await json('/api/checks');
    el('checks').replaceChildren(...data.checks.map(check => {
      const item = document.createElement('li');
      item.className = check.ok ? 'ok' : 'pending';
      item.textContent = (check.ok ? '✓ ' : '○ ') + check.name + (check.ok ? ' ready' : ': ' + check.help);
      return item;
    }));
  } catch (e) { error(e.message); }
}

async function refresh() {
  try {
    const state = await json('/api/status');
    csrf = state.csrf;
    el('setup').textContent = state.configured
      ? 'Your Wolt has prepared this Mac.'
      : 'Ask your Wolt to install and configure No-hands using the guide in this repository.';
    el('provider').textContent = 'Speech: ' + (state.provider === 'openai' ? 'OpenAI' : 'local server');
    el('operation').textContent = state.operation;
    el('start').disabled = !state.configured || !!state.operation || pending;
    el('start').hidden = state.running;
    el('stop').hidden = !state.running;
    el('stop').disabled = !!state.operation || state.active_call || pending;
    el('qr').disabled = !state.ready || !!state.operation || pending;
    el('hide-qr').hidden = !state.qr;
    el('hide-qr').disabled = !!state.operation || pending;
    el('qrbox').hidden = !state.qr;
    if (state.qr && !previousQR) el('qrimage').src = '/qr.png';
    if (!state.qr) el('qrimage').removeAttribute('src');
    previousQR = state.qr;
    el('ready').textContent = state.ready ? 'Ready to call' : 'Almost ready';
    el('dial').textContent = state.ready
      ? 'Dial 101 for normal mode or 102 for car mode to talk to ' + state.wolt + '. ' + (state.active_call
        ? 'A call is connected.'
        : 'Then say hello. Phone registration and the audio path are confirmed by your first call.')
      : 'Start the phone above. We’ll check the services before you call.';
    if (state.error) error(state.error);
  } catch (e) {
    error('The app is unavailable. Ask your Wolt to start No-hands from the lodge.');
    el('ready').textContent = 'Connection lost';
    el('start').disabled = true;
    el('qr').disabled = true;
    el('qrbox').hidden = true;
  }
}

for (const name of ['start', 'stop', 'qr', 'hide-qr']) {
  el(name).onclick = async () => {
    pending = true;
    error('');
    try {
      await json('/api/' + name, {method: 'POST', headers: {'X-No-Hands': csrf}});
    } catch (e) { error(e.message); }
    finally { pending = false; await refresh(); }
  };
}
el('refresh').onclick = async () => { error(''); await checks(); await refresh(); };
checks();
refresh();
setInterval(refresh, 2000);
