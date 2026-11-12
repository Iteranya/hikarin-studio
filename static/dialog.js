// Baby modal: one shared overlay, tiny promise API.
// uiAlert(message) -> resolves when closed.
// uiConfirm(message) -> resolves true/false.
// uiPrompt(message, defaultValue?) -> resolves string, or null if cancelled.
// No window.alert / window.confirm / window.prompt — those freeze the browser.

let shell = null;

function ensureShell() {
  if (shell) return shell;
  shell = document.createElement('div');
  shell.id = 'ui-dialog-backdrop';
  shell.innerHTML = `
    <div class="ui-dialog" role="dialog" aria-modal="true" aria-labelledby="ui-dialog-title">
      <div class="ui-dialog-title" id="ui-dialog-title">Hikarin Studio</div>
      <div class="ui-dialog-body" id="ui-dialog-body"></div>
      <input class="ui-dialog-input" id="ui-dialog-input" hidden autocomplete="off" spellcheck="false">
      <div class="ui-dialog-actions">
        <button class="btn ui-dialog-cancel" id="ui-dialog-cancel">Cancel</button>
        <button class="btn primary ui-dialog-ok" id="ui-dialog-ok">OK</button>
      </div>
    </div>`;
  document.body.appendChild(shell);
  return shell;
}

function ensureStyle() {
  if (ensureStyle.done) return;
  const style = document.createElement('style');
  style.textContent = `
    #ui-dialog-backdrop { position: fixed; inset: 0; z-index: 9999; display: flex; align-items: center; justify-content: center; background: rgba(8, 10, 14, .62); backdrop-filter: blur(2px); }
    #ui-dialog-backdrop[hidden] { display: none; }
    .ui-dialog { min-width: 320px; max-width: min(480px, 92vw); background: var(--card, #12151b); border: 1px solid var(--border, #262a33); border-radius: 12px; box-shadow: 0 18px 48px rgba(0,0,0,.5); padding: 14px; display: flex; flex-direction: column; gap: 10px; }
    .ui-dialog-title { font-size: 13px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: var(--muted-foreground, #8b93a7); }
    .ui-dialog-body { font-size: 14px; line-height: 1.45; color: var(--foreground, #e8eaf0); white-space: pre-wrap; }
    .ui-dialog-input { width: 100%; box-sizing: border-box; background: var(--background, #0b0e13); border: 1px solid var(--border, #262a33); border-radius: 8px; padding: 8px 10px; color: var(--foreground, #e8eaf0); font-size: 14px; }
    .ui-dialog-actions { display: flex; gap: 8px; justify-content: flex-end; }
  `;
  document.head.appendChild(style);
  ensureStyle.done = true;
}

export function uiAlert(message, title = 'Hikarin Studio') {
  return showDialog({ title, message, input: false, buttons: ['ok'] }).then(() => {});
}
export function uiConfirm(message, title = 'Really?') {
  return showDialog({ title, message, input: false, buttons: ['cancel', 'ok'] }).then((v) => v === 'ok');
}
export function uiPrompt(message, defaultValue = '', title = 'Hikarin Studio') {
  return showDialog({ title, message, input: true, value: defaultValue, buttons: ['cancel', 'ok'] });
}

function showDialog({ title, message, input, value, buttons }) {
  ensureStyle();
  const sh = ensureShell();
  const body = sh.querySelector('#ui-dialog-body');
  const inputEl = sh.querySelector('#ui-dialog-input');
  const okBtn = sh.querySelector('#ui-dialog-ok');
  const cancelBtn = sh.querySelector('#ui-dialog-cancel');
  sh.querySelector('#ui-dialog-title').textContent = title;
  body.textContent = message;
  inputEl.hidden = !input;
  inputEl.value = input ? (value ?? '') : '';
  cancelBtn.hidden = !buttons.includes('cancel');
  okBtn.textContent = buttons.includes('cancel') ? 'Save' : 'OK';
  sh.hidden = false;
  return new Promise((resolve) => {
    const done = (val) => {
      sh.hidden = true;
      okBtn.onclick = null; cancelBtn.onclick = null; sh.onclick = null;
      inputEl.onkeydown = null;
      resolve(val);
    };
    okBtn.onclick = () => done(input ? inputEl.value : 'ok');
    cancelBtn.onclick = () => done(input ? null : 'cancel');
    sh.onclick = (e) => { if (e.target === sh) done(input ? null : 'cancel'); };
    inputEl.onkeydown = (e) => {
      if (e.key === 'Enter') done(inputEl.value);
      else if (e.key === 'Escape') done(null);
    };
    if (input) setTimeout(() => { inputEl.focus(); inputEl.select(); }, 30);
    else setTimeout(() => okBtn.focus(), 30);
  });
}
