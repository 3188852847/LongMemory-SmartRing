import {useQuery} from '@tanstack/react-query';
import {Button} from '../../components/Button';
import {ChatApi} from '../../api';

const plugin = 'http://127.0.0.1:16185/#/plugin-view/astrbot_plugin_private_companion/';
type Status = {state: 'not_configured' | 'unavailable' | 'setup' | 'ready'; private_targets?: number};

export function CompanionHome({api, active}: {api: ChatApi; active: boolean}) {
  const status = useQuery({queryKey:['companion-status'], enabled:active,
    queryFn:() => api.request<Status>('/api/companion/status'), refetchInterval:active ? 15000 : false, retry:false});
  const data = status.data;
  return <section>
    <p role="status">{data?.state === 'ready' ? `已连接陪伴小屋，已绑定 ${data.private_targets} 个私聊窗口。`
      : data?.state === 'setup' ? '小屋已连接，等待完成私聊绑定和角色设置。'
      : data?.state === 'not_configured' ? '这台电脑还没有配置陪伴小屋。'
      : status.isError || data?.state === 'unavailable' ? '暂时读不到小屋状态。可以打开本机小屋检查连接。' : '正在读取小屋状态…'}</p>
    <Button href={plugin + '陪伴小屋'} target="_blank" rel="noreferrer" variant="primary" label="打开陪伴小屋"/>
    <p>日程、主动联系、一起陪伴、游戏、创作、图片、识屏、现实设备与直播，都在小屋里管理。</p>
    <p>首次使用 QQ 时，私聊机器人发送「我会永远陪着你 大肥鱼」，然后在小屋的“开始使用”里确认自己的窗口。</p>
  </section>;
}
