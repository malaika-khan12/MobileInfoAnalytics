import { createServer } from 'node:http';
import './build.js';

const worker=(await import('../dist/server/index.js?dev='+Date.now())).default;
const args=process.argv.slice(2);
const value=(flag,fallback)=>{const i=args.indexOf(flag);return i>=0?args[i+1]:fallback;};
const host=value('--host','0.0.0.0');
const port=Number(value('--port','4173'));

createServer(async(req,res)=>{
  const response=await worker.fetch(new Request(`http://${req.headers.host}${req.url}`,{method:req.method,headers:req.headers}));
  res.writeHead(response.status,Object.fromEntries(response.headers));
  res.end(Buffer.from(await response.arrayBuffer()));
}).listen(port,host,()=>console.log(`Mobile Analytics ready on ${host}:${port}`));
