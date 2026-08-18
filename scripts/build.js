import { readFile, mkdir, rm, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const read = path => readFile(resolve(root, path), path.match(/\.(png|gif|ico)$/) ? null : 'utf8');
const escapeTemplate = value => value.replaceAll('\\', '\\\\').replaceAll('`', '\\`').replaceAll('${', '\\${');

let html = await read('frontend/templates/index.html');
html = html
  .replaceAll("{{ url_for('static', filename='css/app.css') }}", '/static/css/app.css')
  .replaceAll("{{ url_for('static', filename='js/data.js') }}", '/static/js/data.js')
  .replaceAll("{{ url_for('static', filename='js/app.js') }}", '/static/js/app.js');

const [css, data, app, mark, favicon, loading, manifest] = await Promise.all([
  read('frontend/static/css/app.css'), read('frontend/static/js/data.js'), read('frontend/static/js/app.js'),
  read('frontend/assets/brand-mark.png'), read('frontend/assets/favicon.ico'), read('frontend/assets/loading.gif'),
  read('.openai/hosting.json')
]);
const binary = buffer => Buffer.from(buffer).toString('base64');
const worker = `const assets = new Map([
  ['/static/css/app.css',{type:'text/css; charset=utf-8',body:\`${escapeTemplate(css)}\`}],
  ['/static/js/data.js',{type:'text/javascript; charset=utf-8',body:\`${escapeTemplate(data)}\`}],
  ['/static/js/app.js',{type:'text/javascript; charset=utf-8',body:\`${escapeTemplate(app)}\`}],
  ['/assets/brand-mark.png',{type:'image/png',base64:'${binary(mark)}'}],
  ['/assets/favicon.ico',{type:'image/x-icon',base64:'${binary(favicon)}'}],
  ['/assets/loading.gif',{type:'image/gif',base64:'${binary(loading)}'}]
]);
const html = \`${escapeTemplate(html)}\`;
const allowed = new Set(['/','/dashboard','/scrapers','/admin','/database','/realtime']);
function decode(value){const bytes=Uint8Array.from(atob(value),c=>c.charCodeAt(0));return bytes;}
export default {async fetch(request){const url=new URL(request.url);const asset=assets.get(url.pathname);if(asset)return new Response(asset.base64?decode(asset.base64):asset.body,{headers:{'content-type':asset.type,'cache-control':'public, max-age=3600','x-content-type-options':'nosniff'}});if(allowed.has(url.pathname)||url.pathname.startsWith('/scrapers/'))return new Response(html,{headers:{'content-type':'text/html; charset=utf-8','cache-control':'no-cache','x-content-type-options':'nosniff','referrer-policy':'strict-origin-when-cross-origin'}});return new Response('Not found',{status:404,headers:{'content-type':'text/plain; charset=utf-8'}});}};
`;

await rm(resolve(root, 'dist'), {recursive:true, force:true});
await mkdir(resolve(root, 'dist/server'), {recursive:true});
await mkdir(resolve(root, 'dist/.openai'), {recursive:true});
await writeFile(resolve(root, 'dist/server/index.js'), worker);
await writeFile(resolve(root, 'dist/.openai/hosting.json'), manifest);
console.log('Built plain HTML/CSS/JavaScript frontend for Sites.');
