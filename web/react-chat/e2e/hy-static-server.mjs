// 仅服务 Y 的独占生产构建。API 全由浏览器测试拦截，不装配运行时/数据库。
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {resolve,sep,extname} from 'node:path';
const root=resolve(process.env.HY_UI_BUILD_DIR??'');
const port=Number(process.env.HY_UI_PORT);
if(!process.env.HY_UI_BUILD_DIR||!port||[8767,8000,8003].includes(port))throw new Error('explicit synthetic build and random port required');
createServer(async(req,res)=>{
  const url=new URL(req.url,'http://127.0.0.1');
  if(url.pathname.startsWith('/api/')){res.writeHead(501);res.end('synthetic API interception required');return;}
  const relative=url.pathname.startsWith('/react-chat/assets/')?decodeURIComponent(url.pathname.slice('/react-chat/'.length)):'index.html';
  const path=resolve(root,relative);
  if(!path.startsWith(root+sep)){res.writeHead(404);res.end();return;}
  try{const data=await readFile(path);res.writeHead(200,{'Content-Type':({'.js':'text/javascript','.css':'text/css','.html':'text/html'})[extname(path)]??'application/octet-stream','Cache-Control':'no-store'});res.end(data);}catch{res.writeHead(404);res.end();}
}).listen(port,'127.0.0.1');
