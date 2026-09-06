import {useQuery, useQueryClient} from '@tanstack/react-query';
import {Alert, Button, Card, Select, Space} from 'antd';
import {ChatApi, type Config} from './api';
import {AppShell, ConsoleNav} from './AppShell';
import {RoleEditor} from './RoleEditor';
import {VoiceSettings} from './VoiceSettings';
import {useAppearance} from './AppearanceProvider';

const api = new ChatApi();

/** 将助手角色、声音和浏览器外观汇集到一个入口；三类设置仍保持不同生效边界。 */
export function SettingsApp() {
  const queryClient = useQueryClient();
  const {prefs, update, reset} = useAppearance();
  const session = useQuery({queryKey:['settings-session'], queryFn:async () => {await api.bootstrap(); return true;}, staleTime:Infinity});
  const config = useQuery({queryKey:['chat-config'], queryFn:() => api.request<Config>('/api/chat-config'), enabled:session.isSuccess});
  const enabled = session.isSuccess && config.data?.enabled === true;
  const sidebar = <ConsoleNav active="settings" legacyPath="/chat"/>;

  return <AppShell subtitle="角色、声音与阅读体验" className="settings-shell" sidebar={sidebar}>
    <header><div><h1>个性化设置</h1><p className="subtle">这里设置助手如何表达和播放，不等于 L3 用户画像，也不会修改你的事实记忆。</p></div></header>
    {(session.isError || config.isError) && <Alert type="error" showIcon title="设置服务当前不可用" description="请确认统一启动的文字服务仍在运行，再刷新本页。"/>}
    <div className="settings-grid">
      <Card title="助手角色" extra={<span className="setting-scope">网页＋可选圆屏同步</span>}>
        <p>编辑角色名称与系统提示词。网页从下一轮开始使用；圆屏必须在弹窗里单独预检和同步。</p>
        <RoleEditor api={api} disabled={!enabled} onSaved={() => {void queryClient.invalidateQueries({queryKey:['chat-config']});}}/>
      </Card>
      <Card title="声音" extra={<span className="setting-scope">小智 TTS</span>}>
        <p>查看当前 EdgeTTS 或 VoxCPM2 后端。Edge 音色可试听和保存；VoxCPM2 参数仍由独立适配层管理。</p>
        <VoiceSettings api={api} disabled={!enabled}/>
      </Card>
      <Card title="外观与阅读" extra={<span className="setting-scope">当前浏览器</span>}>
        <p>只保存主题和字号枚举，不保存聊天正文或个人记忆。</p>
        <Space orientation="vertical" style={{width:'100%'}}>
          <label>主题</label><Select className="wide" aria-label="主题" value={prefs.theme} onChange={theme => update({...prefs, theme})} options={[{value:'system',label:'跟随系统'},{value:'light',label:'浅色'},{value:'dark',label:'深色'}]}/>
          <label>字号</label><Select className="wide" aria-label="字号" value={prefs.size} onChange={size => update({...prefs, size})} options={[{value:'normal',label:'标准'},{value:'large',label:'大'},{value:'larger',label:'更大'}]}/>
          <Button onClick={() => reset()}>恢复默认</Button>
        </Space>
      </Card>
    </div>
    {!enabled && !session.isError && !config.isError && <p role="status">正在读取设置能力；未启用文字服务时角色和声音设置不可操作。</p>}
  </AppShell>;
}
