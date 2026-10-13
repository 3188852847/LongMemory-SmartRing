import {Alert, Button, Modal} from 'antd';
import {useState} from 'react';

const commands = [
  ['明确记住', '请记住：我叫小林', '保存原句 L0，并生成一条规范化 L1'],
  ['本轮不生成 L1', '不要记住：我今天想喝茉莉花茶', '仍保留原始对话 L0'],
  ['纠正错误', '不是豆包，是年糕', '唯一命中旧事实后，用新事实取代'],
  ['记录变化', '我以前喜欢喝咖啡，现在不喝咖啡了', '保留旧事实的历史有效期'],
  ['查看来源', '你怎么知道豆包？', '回读形成 L1 的用户原话'],
  ['请求删除', '请忘掉豆包', '只回读候选，不会立刻删除'],
  ['确认删除', '确认删除这条记忆', '必须紧接上一句，并且仍只删除 L1'],
] as const;

export function MemoryCommandHelp() {
  const [open, setOpen] = useState(false);
  return <>
    <Button onClick={() => setOpen(true)}>记忆命令</Button>
    <Modal title="可直接使用的记忆命令" open={open} footer={null} onCancel={() => setOpen(false)} width={720}>
      <Alert showIcon type="info" title="固定句式用于降低误改风险"
        description="这些命令会返回真实应用层回执。普通聊天仍由当前提取策略决定是否形成长期记忆。"/>
      <div className="memory-command-help-list">
        {commands.map(([name, example, effect]) => <section key={name}>
          <strong>{name}</strong><code>{example}</code><span>{effect}</span>
        </section>)}
      </div>
      <p>“请记住”只接受以“我 / 我的”开头的完整陈述；问题和主体不明片段不会强写。删除 L1 不等于删除 L0、备份或日志。</p>
    </Modal>
  </>;
}
