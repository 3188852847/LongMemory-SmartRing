import {Alert, Button, Input, Modal} from 'antd';
import {useState} from 'react';
import {ChatApi} from './api';

type ExplicitMemoryResult = {
  kind: 'include'; status: string; notice: string;
  target_memory_ids: string[]; l0_message_id: string;
};

/** 明确声明入口复用“请记住”契约，不让页面直接拼装数据库记录。 */
export function ManualMemoryAdd({api, disabled, onSaved}: {
  api: ChatApi; disabled: boolean; onSaved: (memoryId?: string) => Promise<void> | void;
}) {
  const [open, setOpen] = useState(false);
  const [content, setContent] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');

  async function save() {
    const value = content.trim();
    if (!value || busy) return;
    setBusy(true); setNotice('');
    try {
      const result = await api.request<ExplicitMemoryResult>(
        '/api/memory-commands/include', 'POST', {content: value},
      );
      setNotice(result.notice);
      if (result.status === 'applied') {
        setContent('');
        await onSaved(result.target_memory_ids[0]);
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '没有写入，请重新检查。');
    } finally {
      setBusy(false);
    }
  }

  return <>
    <Button disabled={disabled} onClick={() => {setOpen(true); setNotice('');}}>明确添加</Button>
    <Modal title="明确添加一条 L1" open={open} okText="保存为长期事实" cancelText="关闭"
      confirmLoading={busy} okButtonProps={{disabled: !content.trim()}}
      onCancel={() => {if (!busy) {setOpen(false); setContent(''); setNotice('');}}}
      onOk={() => void save()}>
      <Alert showIcon type="info" title="这里只添加关于你自己的完整事实"
        description="请输入以“我”或“我的”开头的陈述。系统会保留这次操作为 L0 来源，再生成或去重一条 L1；不会调用模型猜测。"/>
      <Input.TextArea aria-label="要明确记住的事实" rows={4} maxLength={1000} showCount
        value={content} onChange={event => setContent(event.target.value)}
        placeholder="例如：我平时喜欢喝茉莉花茶。"/>
      {notice && <p role="status">{notice}</p>}
    </Modal>
  </>;
}
