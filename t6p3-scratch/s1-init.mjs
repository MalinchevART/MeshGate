import { newTab, close } from './cdp.mjs';

const tab = await newTab();

// WS брояч — И преди зареждане на страницата
await tab.addInitScript(`
  (() => {
    const Orig = window.WebSocket;
    window.__ws = { count: 0, urls: [] };
    window.WebSocket = class extends Orig {
      constructor(...a) {
        super(...a);
        window.__ws.count++;
        window.__ws.urls.push(String(a[0]));
      }
    };
  })();
`);

// маркер: ако страницата се презареди, __marker изчезва
await tab.addInitScript(`window.__marker = 'no-reload-' + Date.now();`);

await tab.goto('http://localhost/');
await tab.sleep(1500);

const st1 = await tab.evaluate(`({
  url: location.href,
  marker: window.__marker || null,
  hasLogin: !!document.querySelector('input[placeholder="потребител"]'),
  ws: window.__ws || null,
})`);
console.log('след зареждане:', JSON.stringify(st1, null, 1));

// вход през формата (нативен setter за React)
await tab.evaluate(`
  (() => {
    const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    const u = document.querySelector('input[placeholder="потребител"]');
    const p = document.querySelector('input[placeholder="парола"]');
    set.call(u, 'admin'); u.dispatchEvent(new Event('input', {bubbles:true}));
    set.call(p, 'P@sswordG@te'); p.dispatchEvent(new Event('input', {bubbles:true}));
  })();
`);
await tab.sleep(600);
await tab.evaluate(`document.querySelector('form.login button:not([disabled])').click(); 'clicked'`);
await tab.sleep(2500);

// Onboarding модал? → „Пропусни"
const ob = await tab.evaluate(`!!document.querySelector('.modal-back')`);
if (ob) {
  await tab.evaluate(`
    [...document.querySelectorAll('.modal-back button')].find(b => b.textContent.includes('Пропусни'))?.click(); 'skip-onboarding';
  `);
  await tab.sleep(800);
}

const st2 = await tab.evaluate(`({
  url: location.href,
  marker: window.__marker || null,
  ws: window.__ws,
  alarmChip: (() => {
    const b = document.querySelector('.mg-alarm');
    if (!b) return null;
    return { text: b.innerText.trim(), classes: b.querySelector('.chip, [class*=chip]')?.className || b.innerHTML.slice(0,200) };
  })(),
  monitorBadge: (() => {
    const btns = [...document.querySelectorAll('.side-btn')];
    const m = btns.find(b => b.textContent.includes('Мониторинг'));
    return m ? { badge: m.querySelector('.side-badge')?.textContent ?? null } : null;
  })(),
  live: (() => {
    const el = document.querySelector('.topbar-live .mg-live');
    return el ? { cls: el.className, text: el.innerText.trim() } : null;
  })(),
  topbarUser: document.querySelector('.topbar-user')?.textContent,
  brand: document.querySelector('.brand-word')?.textContent,
  rolePill: document.querySelector('.brand .pill')?.textContent,
})`);
console.log('след вход:', JSON.stringify(st2, null, 1));
await tab.screenshot('s1-after-login.png');
console.log('TAB_ID=' + tab.targetId);
