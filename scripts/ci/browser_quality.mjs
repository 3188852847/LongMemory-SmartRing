// 收集与执行使用同一默认配置；每份合成 spec 必须恰好属于一个项目。
import {mkdirSync,readdirSync,readFileSync,writeFileSync} from 'node:fs';
import {dirname,relative,resolve} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';

export function collectionEntries(report) {
  const entries=[];
  function visit(suites,parents=[]) {
    for(const suite of suites) {
      for(const spec of suite.specs??[])for(const test of spec.tests??[]) {
        entries.push({file:spec.file.replaceAll('\\','/'),title:[...parents,suite.title,spec.title].join(' > '),project:test.projectName});
      }
      visit(suite.suites??[],[...parents,suite.title]);
    }
  }
  visit(report.suites??[]);
  return entries;
}

export function verifyCollection(report,files) {
  if(report.errors?.length)throw new Error('浏览器收集有错误');
  const entries=collectionEntries(report),seen=new Set();
  for(const entry of entries) {
    if(!files.includes(entry.file))throw new Error(`未声明的合成文件：${entry.file}`);
    const key=entry.file+'\0'+entry.title;
    if(seen.has(key))throw new Error(`跨项目重复收集：${entry.file} ${entry.title}`);
    seen.add(key);
  }
  for(const file of files)if(!entries.some(entry=>entry.file===file))throw new Error(`遗漏合成文件：${file}`);
  if(!entries.length)throw new Error('合成浏览器收集为空');
  for(const project of report.config.projects)if(project.retries!==0)throw new Error('浏览器项目必须零重试');
  return entries;
}

function main() {
  const repository=resolve(dirname(fileURLToPath(import.meta.url)),'../..');
  const frontend=resolve(repository,'web/react-chat'),specRoot=resolve(frontend,'e2e');
  const evidence=resolve(repository,`data/test-tmp/ci/browser/run-${Date.now()}-${process.pid}`);
  mkdirSync(evidence,{recursive:true});
  const cli=resolve(frontend,'node_modules/@playwright/test/cli.js');
  function specs(directory) {
    return readdirSync(directory,{withFileTypes:true}).flatMap(entry=>{
      const file=resolve(directory,entry.name);
      return entry.isDirectory()?specs(file):entry.isFile()&&entry.name.endsWith('.spec.ts')?[relative(specRoot,file).replaceAll('\\','/')]:[];
    }).sort();
  }
  const guard=spawnSync(process.execPath,['--test',resolve(repository,'scripts/ci/test_browser_quality.mjs')],{cwd:frontend,stdio:'inherit'});
  if(guard.status!==0)throw new Error('浏览器收集护栏自测失败');
  const listing=spawnSync(process.execPath,[cli,'test','--list','--reporter=json'],{cwd:frontend,encoding:'utf8',maxBuffer:16*1024*1024});
  writeFileSync(resolve(evidence,'collection.json'),listing.stdout??'');
  if(listing.stderr)process.stderr.write(listing.stderr);
  if(listing.status!==0)throw new Error('浏览器收集失败');
  const scheduled=verifyCollection(JSON.parse(listing.stdout),specs(specRoot));
  writeFileSync(resolve(evidence,'scheduled.json'),JSON.stringify(scheduled,null,2)+'\n');
  console.log(`合成浏览器：${scheduled.length} 项，${specs(specRoot).length} 份 spec；真实 SDK e2e-live 未执行，需显式隔离资源。`);
  const result=spawnSync(process.execPath,[cli,'test','--reporter=list,json','--output',resolve(evidence,'test-results')],{
    cwd:frontend,stdio:'inherit',env:{...process.env,PLAYWRIGHT_JSON_OUTPUT_FILE:resolve(evidence,'results.json')},
  });
  if(!readFileSync(resolve(evidence,'results.json'),'utf8'))throw new Error('缺少浏览器结果');
  const report=JSON.parse(readFileSync(resolve(evidence,'results.json'),'utf8'));
  const executed=verifyCollection(report,specs(specRoot));
  const key=entry=>JSON.stringify(entry);
  if(JSON.stringify(scheduled.map(key).sort())!==JSON.stringify(executed.map(key).sort()))throw new Error('实际运行收集与预检不一致');
  console.log(JSON.stringify({evidence,scheduled:scheduled.length,...report.stats}));
  if(result.status!==0)throw new Error(`浏览器回归失败，退出码 ${result.status}`);
}

if(process.argv[1]&&import.meta.url===pathToFileURL(resolve(process.argv[1])).href) {
  try {main();}catch(error){console.error(error.message);process.exitCode=1;}
}
