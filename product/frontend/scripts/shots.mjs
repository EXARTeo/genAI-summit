// Visual QA: start the app in mock mode on a free port and screenshot every route
// in dark + light at desktop (1440x900) and mobile (390x844) into .shots/ (git-ignored).
// Usage: npm run shots [-- --only=audit] [-- --theme=dark] [-- --size=desktop]
import { mkdir, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';
import { createServer } from 'vite';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outDir = path.join(root, '.shots');
const args = Object.fromEntries(
  process.argv
    .slice(2)
    .filter((a) => a.startsWith('--'))
    .map((a) => a.slice(2).split('=')),
);

const SIZES = {
  desktop: { width: 1440, height: 900 },
  mobile: { width: 390, height: 844 },
};
const THEMES = ['dark', 'light'];

/** name, path, optional action run before the screenshot. */
const SHOTS = [
  ['home', '/'],
  ['systems', '/systems'],
  ['system-overview', '/systems/SYS-001'],
  ['system-folder', '/systems/SYS-001/folder'],
  ['system-plugins', '/systems/SYS-001/plugins'],
  ['system-rules', '/systems/SYS-001/rules'],
  ['system-lessons', '/systems/SYS-001/lessons'],
  ['audits', '/audits'],
  ['audit-profile', '/audits/aud-sys001-r2?step=profile_model'],
  ['audit-datasets', '/audits/aud-sys001-r2?step=analyse_datasets'],
  ['audit-findings', '/audits/aud-sys001-r2?step=analyse'],
  ['audit-report', '/audits/aud-sys001-r2?step=report'],
  ['audit-waiting', '/audits/aud-sys001-r3'],
  ['audit-running', '/audits/aud-sys002-r1'],
  ['approvals', '/approvals'],
  [
    'approval-drawer',
    '/approvals',
    async (page) => {
      await page
        .getByRole('button', { name: /review/i })
        .first()
        .click();
      await page.waitForTimeout(900);
    },
  ],
  [
    'memory-sheet',
    '/audits/aud-sys001-r2?step=analyse',
    async (page) => {
      await page
        .getByRole('button', { name: /MEM-0042/ })
        .first()
        .click();
      await page.waitForTimeout(700);
    },
  ],
  ['regulation', '/regulation'],
  ['regulation-sources', '/regulation?tab=sources'],
  ['chat', '/chat'],
  ['settings', '/settings'],
  ['settings-rules', '/settings?tab=rules'],
  ['not-found', '/nope'],
];

async function main() {
  const server = await createServer({
    root,
    mode: 'mocks',
    logLevel: 'error',
    server: { port: 0, host: '127.0.0.1', strictPort: false },
  });
  await server.listen();
  const addr = server.httpServer.address();
  const base = `http://127.0.0.1:${addr.port}`;
  console.log(`vite (mocks) on ${base}`);

  if (!args.only) await rm(outDir, { recursive: true, force: true });
  await mkdir(outDir, { recursive: true });

  let browser;
  try {
    browser = await chromium.launch();
  } catch {
    browser = await chromium.launch({ channel: 'msedge' });
  }

  const shots = SHOTS.filter(([name]) => !args.only || name.includes(args.only));
  const themes = args.theme ? [args.theme] : THEMES;
  const sizes = args.size ? [args.size] : Object.keys(SIZES);
  let n = 0;
  try {
    for (const theme of themes) {
      for (const size of sizes) {
        const ctx = await browser.newContext({
          viewport: SIZES[size],
          deviceScaleFactor: 1,
          reducedMotion: 'no-preference',
          colorScheme: theme,
        });
        await ctx.addInitScript((t) => localStorage.setItem('aac.theme', t), theme);
        const page = await ctx.newPage();
        page.on('pageerror', (e) => console.error(`  pageerror: ${e.message}`));
        for (const [name, url, action] of shots) {
          await page.goto(base + url, { waitUntil: 'networkidle' });
          await page.waitForTimeout(1400);
          if (action) {
            try {
              await action(page);
            } catch (e) {
              console.error(`  ${name}: action failed (${e.message.split('\n')[0]})`);
            }
          }
          const file = path.join(outDir, `${name}--${theme}--${size}.png`);
          await page.screenshot({ path: file, fullPage: Boolean(args.full) });
          n++;
        }
        await ctx.close();
      }
    }
  } finally {
    await browser.close();
    await server.close();
  }
  console.log(`${n} screenshots in ${path.relative(process.cwd(), outDir) || outDir}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
