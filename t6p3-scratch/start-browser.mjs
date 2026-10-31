import { launch } from './cdp.mjs';
const b = await launch();
console.log('CHROME_UP port=' + b.port);
// не убиваме процеса — браузърът живее между тестовите стъпки
setInterval(() => {}, 60000);
