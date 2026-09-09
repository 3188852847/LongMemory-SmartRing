import {useRef, useState} from 'react';
import {Button} from 'antd';
import {ChatApi} from './api';
import {settingsFailure} from './settingsFailure';

interface Preview {token: string; revision: number; config_matches: boolean; server: string}
export function DeviceRoleSync({api, disabled}: {api: ChatApi; disabled: boolean}) {
  const [preview, setPreview] = useState<Preview>();
  const [notice, setNotice] = useState('尚未检查小智配置。保存网页角色不会自动同步。');
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  async function check() {
    if (lock.current) return; lock.current = true; setBusy(true); setPreview(undefined);
    try {
      const result = await api.request<Preview>('/api/assistant-role/device'); setPreview(result);
      setNotice(result.config_matches ? '磁盘配置已匹配当前角色；运行中的小智是否加载尚未验证。' : '配置尚未匹配。确认同步只改角色提示词，不改音色、网络或模型。');
    } catch (error) {setNotice(settingsFailure(error, 'read'));}
    finally {lock.current = false; setBusy(false);}
  }
  async function sync() {
    if (lock.current || !preview || !confirm(`将已保存的角色版本 ${preview.revision} 写入 ${preview.server} 的配置？\n原配置备份留在小智私有目录，含原有凭据。之后需重启小智；不会自动重启或打断聊天。`)) return;
    lock.current = true; setBusy(true);
    try {
      const result = await api.request<{revision:number; backup?:string}>('/api/assistant-role/device', 'POST', {token:preview.token});
      setNotice(`版本 ${result.revision} 已写入配置并回读核对。请在启动面板停止后重新启动文字＋圆屏服务，再唤醒圆屏。运行生效仍未验证。${result.backup ? '原配置已备份。' : ''}`);
    } catch (error) {setNotice(settingsFailure(error, 'write'));}
    finally {setPreview(undefined); lock.current = false; setBusy(false);}
  }
  return <section aria-label="圆屏角色同步"><h3>圆屏角色同步</h3><p>仅同步已经保存的版本，不同步编辑框草稿。</p>
    <Button disabled={disabled || busy} onClick={() => void check()}>检查小智配置</Button>{' '}
    <Button disabled={disabled || busy || !preview || preview.config_matches} onClick={() => void sync()}>确认同步已保存角色</Button>
    <p role="status">{notice}</p></section>;
}
