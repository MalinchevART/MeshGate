/* CDP драйвер за Chrome headless (Node 24: вградени fetch + WebSocket).
   Използва се само за тестовете на Т6 — не е част от кода на MeshGate. */
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PORT = 9333;

export async function launch(extraArgs = []) {
  const userDataDir = join(tmpdir(), `t6p3-chrome-${Date.now()}`);
  mkdtempSync(userDataDir, { recursive: true });
  const args = [
    '--headless=new', `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${userDataDir}`, '--no-first-run', '--no-default-browser-check',
    '--disable-gpu', '--window-size=1440,900', ...extraArgs, 'about:blank',
  ];
  const proc = spawn(CHROME, args, { stdio: 'ignore', detached: false });
  // изчакай devtools endpoint-а
  let version = null;
  for (let i = 0; i < 60; i++) {
    try {
      version = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json();
      break;
    } catch { await new Promise(r => setTimeout(r, 250)); }
  }
  if (!version) throw new Error('Chrome не пусна DevTools endpoint');
  return { proc, port: PORT, userDataDir, wsUrlBase: version.webSocketDebuggerUrl };
}

export class Tab {
  constructor(ws) {
    this.ws = ws;
    this.id = 1;
    this.pending = new Map();
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(msg.error.message + ' ' + JSON.stringify(msg.error.data || '')));
        else resolve(msg.result);
      }
    });
  }
  send(method, params = {}, sessionId) {
    const id = this.id++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params, sessionId }));
    });
  }
  async enable() {
    await this.send('Page.enable');
    await this.send('Runtime.enable');
    await this.send('Log.enable');
  }
  async addInitScript(source) {
    return this.send('Page.addScriptToEvaluateOnNewDocument', { source });
  }
  async goto(url) {
    const res = await this.send('Page.navigate', { url });
    if (res.errorText) throw new Error('navigate: ' + res.errorText);
    // изчакай load event
    await this.waitEvent('Page.loadEventFired', 15000).catch(() => {});
    await this.sleep(300);
  }
  waitEvent(name, timeout = 10000) {
    return new Promise((resolve, reject) => {
      const to = setTimeout(() => { cleanup(); reject(new Error('timeout waitEvent ' + name)); }, timeout);
      const h = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.method === name) { cleanup(); resolve(msg.params); }
      };
      const cleanup = () => { clearTimeout(to); this.ws.removeEventListener('message', h); };
      this.ws.addEventListener('message', h);
    });
  }
  async evaluate(expr, awaitPromise = false) {
    const r = await this.send('Runtime.evaluate', {
      expression: expr, returnByValue: true, awaitPromise,
    });
    if (r.exceptionDetails) throw new Error('page eval: ' + JSON.stringify(r.exceptionDetails.exception?.description || r.exceptionDetails.text));
    return r.result?.value;
  }
  async screenshot(path) {
    const r = await this.send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(path, Buffer.from(r.data, 'base64'));
    return path;
  }
  async setViewport(width, height, mobile = false) {
    await this.send('Emulation.setDeviceMetricsOverride', {
      width, height, deviceScaleFactor: 1, mobile,
    });
  }
  async press(key, code, modifiers = 0) {
    await this.send('Input.dispatchKeyEvent', { type: 'keyDown', key, code, windowsVirtualKeyCode: code === 'Escape' ? 27 : key === 'Tab' ? 9 : 0, modifiers });
    await this.send('Input.dispatchKeyEvent', { type: 'keyUp', key, code, windowsVirtualKeyCode: code === 'Escape' ? 27 : key === 'Tab' ? 9 : 0, modifiers });
  }
  sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
}

export async function newTab(wsUrlBase) {
  // вземи target list, създай нов tab през /json/new
  const t = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json();
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  const tab = new Tab(ws);
  tab.targetId = t.id;
  await tab.enable();
  return tab;
}

export async function close(tab) {
  try { await fetch(`http://127.0.0.1:${PORT}/json/close/${tab.targetId}`, { method: 'PUT' }); } catch {}
}

export function kill(browser) {
  try { browser.proc.kill(); } catch {}
  try { rmSync(browser.userDataDir, { recursive: true, force: true }); } catch {}
}
