import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';

execFileSync(process.execPath,['scripts/build.js']);
const worker=(await import('../dist/server/index.js?test='+Date.now())).default;

test('serves every product route',async()=>{for(const route of ['/','/dashboard','/scrapers','/scrapers/gsmarena','/admin','/database','/realtime']){const response=await worker.fetch(new Request('https://example.test'+route));assert.equal(response.status,200);assert.match(response.headers.get('content-type'),/text\/html/);}});
test('serves approved static assets',async()=>{for(const route of ['/static/css/app.css','/static/js/data.js','/static/js/app.js','/assets/brand-mark.png'])assert.equal((await worker.fetch(new Request('https://example.test'+route))).status,200);});
test('returns a real 404',async()=>assert.equal((await worker.fetch(new Request('https://example.test/unknown'))).status,404));
test('frontend output contains no framework markers',async()=>{const html=await (await worker.fetch(new Request('https://example.test/'))).text();assert.doesNotMatch(html,/react|typescript|__next/i);});
