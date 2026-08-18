import { access, readFile } from 'node:fs/promises';
for (const file of ['dist/server/index.js','dist/.openai/hosting.json']) await access(file);
const worker = await import(new URL('../dist/server/index.js', import.meta.url));
if (!worker.default || typeof worker.default.fetch !== 'function') throw new Error('Worker default.fetch is missing.');
const html = await (await worker.default.fetch(new Request('https://example.test/dashboard'))).text();
for (const marker of ['Mobile Analytics','id="workspace"','data-route']) if (!html.includes(marker)) throw new Error(`Missing ${marker}`);
JSON.parse(await readFile(new URL('../dist/.openai/hosting.json', import.meta.url),'utf8'));
console.log('Artifact valid.');
