import {useState} from 'react';
import {Alert, Button, Card} from 'antd';
import './experimentPreparation.css';

export const offlinePreparation = '.\\.venv\\Scripts\\python.exe -m longmemory.evaluation.comparison.runner --provider fake --split dev';
export const retrievalPreparation = `$sourceReport = 'experiments/runs/comparison-请替换为上一步输出的实际编号/report.json'
$bgeSnapshot = 'local/runtime/models/bge-small-zh-v1.5/7999e1d3359715c523056ef9478215996d62a620'
.\\.venv\\Scripts\\python.exe -m longmemory.evaluation.comparison.retrieval --source-report $sourceReport --model-dir $bgeSnapshot --split dev`;

function Command({text}:{text:string}) {
  const [notice,setNotice] = useState('');
  return <><pre className="experiment-preparation-command"><code>{text}</code></pre><Button onClick={()=>{
    void navigator.clipboard?.writeText(text).then(()=>setNotice('已复制；尚未执行。'),()=>setNotice('未能复制，请选中上方命令手动复制。'));
    if (!navigator.clipboard) setNotice('当前浏览器不支持复制，请选中上方命令。');
  }}>复制命令</Button><p role="status">{notice}</p></>;
}

/** 帮助只给真实入口；网页不会代为运行终端命令或下载依赖。 */
export function ExperimentPreparation({onArchive,onRun}:{onArchive:()=>void;onRun:()=>void}) {
  return <section className="experiment-preparation" aria-label="准备实验档案">
    <h2 id="experiment-preparation-heading" tabIndex={-1}>准备实验档案</h2>
    <Alert showIcon type="info" title="先准备合成档案，再决定是否运行回答对照" description="以下在项目根目录的 PowerShell 中执行，使用已经准备好的项目 Python 环境。命令不会由网页执行；环境或模型缺失时先由所有者准备，不自动下载。"/>
    <Card title="1 · 离线体验：建立冻结的合成历史">
      <p>先用 Fake（本地规则模拟器）检查来源、持久化与报告流程。它只使用版本化合成开发题，不读个人库，也不调用真实模型。</p>
      <Command text={offlinePreparation}/>
      <p>终端将输出新建的 <code>experiments/runs/comparison-&lt;唯一编号&gt;/report.json</code>。先核对实际完成状态和逐题错误，再回档案页刷新。Fake 的分数只用于工程检查，不能当记忆效果。</p>
      <Button onClick={onArchive}>回到档案并刷新</Button>
    </Card>
    <Card title="2 · 准备网页运行所需的冻结检索档案">
      <p>第一步的比较档案可以直接浏览，但不能冒充网页所需的检索档案。已有固定 BGE 快照与 semantic 依赖时，将下方来源编号替换为第一步真实输出，再执行本地检索。</p>
      <Command text={retrievalPreparation}/>
      <p>此入口读取冻结事实并本地编码，不重提取、不回答。缺失/不匹配的快照、来源或 schema（数据结构版本）会拒绝运行；不要改旧档案凑通过，也不要下载后跳过指纹校验。</p>
      <p>新结果为 <code>experiments/runs/retrieval-&lt;唯一编号&gt;/report.json</code>，只有兼容且完成的开发集档案会出现在运行来源中。命令均追加新目录，不覆盖原档案。</p>
      <Button onClick={onRun}>前往运行实验核对能力</Button>
    </Card>
    <Card title="3 · 预检、运行、逐题复核">
      <p>在“运行实验”选择实际检索档案，先预检预算、再明确确认。只读服务不能启动。Fake 不联网；真实模型另需所有者配置与网络条件，不因出现选项就代表连接验证成功。</p>
      <p>查看结果时区分召回是否充分、实际交给模型的内容、回答和人工判断；失败/未完成不能计为通过。人工标签由实际复核者填写。</p>
      <details><summary>仓库指南与实现入口</summary><p><code>docs/research/method-comparison.md</code> · 历史比较；<code>docs/research/semantic-retrieval.md</code> · 冻结检索；<code>docs/deployment/experiment-console.md</code> · 网页预算与复核。以上为仓库文件，可在编辑器打开。</p><p>命令分别调用 <code>longmemory.evaluation.comparison.runner</code> 与 <code>longmemory.evaluation.comparison.retrieval</code>。本页不读取已有个人实验产物，不宣称这些步骤已在你的数据上运行。</p></details>
    </Card>
  </section>;
}
