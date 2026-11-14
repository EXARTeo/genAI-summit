// Bundle the seeded system folders (product/mlflow-seed/cases/SYS-*) into one JSON
// fixture for mock mode, so the demo UI shows the same dossiers the backend seeds.
// The answer keys (_answer-key/) are never bundled.
//
//   npm run fixtures
import { mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = fileURLToPath(new URL('.', import.meta.url));
const casesDir = resolve(here, '../../mlflow-seed/cases');
const out = resolve(here, '../src/shared/lib/mocks/fixtures/seed-cases.json');
const SKIP = new Set(['_answer-key', '__pycache__']);

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    if (SKIP.has(name)) return [];
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

const systems = {};
for (const id of readdirSync(casesDir)
  .filter((n) => /^SYS-/.test(n))
  .sort()) {
  const root = join(casesDir, id);
  systems[id] = Object.fromEntries(
    walk(root)
      .map((p) => [relative(root, p).split('\\').join('/'), readFileSync(p, 'utf8').replace(/\r\n/g, '\n')])
      .sort(([a], [b]) => a.localeCompare(b)),
  );
}
mkdirSync(resolve(out, '..'), { recursive: true });
writeFileSync(out, JSON.stringify(systems, null, 1) + '\n');
console.log(`wrote ${out} (${Object.keys(systems).length} systems)`);
