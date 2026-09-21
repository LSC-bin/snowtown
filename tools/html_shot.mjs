// HTML 파일을 스크린샷으로 변환 (UI 검증용)
import { chromium } from '/home/leeseokchan/hermes agent/councel_project/counseling-tracker/node_modules/playwright-core/index.mjs';

const EXE = '/home/leeseokchan/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome';
const [src, out, w, h] = [process.argv[2], process.argv[3], Number(process.argv[4] ?? 1000), Number(process.argv[5] ?? 620)];

const browser = await chromium.launch({ executablePath: EXE, headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: w, height: h } });
await page.goto('file://' + src, { waitUntil: 'load' });
await page.waitForTimeout(500);
await page.screenshot({ path: out });
console.log('saved', out);
await browser.close();