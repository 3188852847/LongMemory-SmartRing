import {useQuery, useQueryClient} from '@tanstack/react-query';
import {Alert, Button, Card, Select, Space, Tabs} from 'antd';
import {useSearchParams} from 'react-router-dom';
import {ChatApi, type Config} from './api';
import {AppShell, ConsoleNav} from './AppShell';
import {RoleEditor} from './RoleEditor';
import {VoiceSettings} from './VoiceSettings';
import {ProactiveSettings} from './ProactiveSettings';
import {useAppearance} from './AppearanceProvider';
import {PageHeader} from './PageHeader';
import {ModelConnectionSettings} from './ModelConnectionSettings';
import {MemoryBackendSettings} from './MemoryBackendSettings';
import {PersonalizationOverview} from './PersonalizationOverview';
import {TTSBenchmarkPanel} from './TTSBenchmarkPanel';
import {VADSettings} from './VADSettings';

const api = new ChatApi();

/** 将模型、助手角色、声音和浏览器外观汇集到一个入口；设置仍保持不同生效边界。 */
export function SettingsApp() {
  const [searchParams,setSearchParams]=useSearchParams();
  const queryClient = useQueryClient();
  const {prefs, update, reset} = useAppearance();
  const session = useQuery({queryKey:['settings-session'], queryFn:async () => {await api.bootstrap(); return true;}, staleTime:Infinity});
  const config = useQuery({queryKey:['chat-config'], queryFn:() => api.request<Config>('/api/chat-config'), enabled:session.isSuccess});
  const enabled = session.isSuccess && config.data?.enabled === true;
  const requestedTab=searchParams.get('tab');
  const activeTab=['model','memory-backend','role','voice','appearance','proactive'].includes(requestedTab??'')?requestedTab!:'role';
  const selectTab=(tab:string)=>{const next=new URLSearchParams(searchParams);if(tab==='role')next.delete('tab');else next.set('tab',tab);setSearchParams(next,{replace:true});};
  const sidebar = <ConsoleNav active="settings" legacyPath="/chat"/>;

  return <AppShell subtitle="角色、声音与阅读体验" className="settings-shell" sidebar={sidebar}>
    <PageHeader eyebrow="控制与观察" title="设置中心" description="调整助手的表达、声音、页面外观和主动联系边界；这些设置不会修改你的事实记忆。"/>
    {(session.isError || config.isError) && <Alert type="error" showIcon title="设置服务当前不可用" description="请确认统一启动的文字服务仍在运行，再刷新本页。"/>}
    <section className="settings-overview" aria-label="当前设置摘要">
      <div><small>设置服务</small><strong className={enabled ? 'is-positive' : ''}>{enabled ? '可用' : '连接中'}</strong></div>
      <div><small>当前助手</small><strong>{config.data?.role ?? '—'}</strong></div>
      <div><small>当前模型</small><strong>{config.data?.model ?? '—'}</strong></div>
      <div><small>模型通道</small><strong>{config.data?.provider ?? '—'}</strong></div>
    </section>
    <PersonalizationOverview api={api} ready={enabled} prefs={prefs} onSelectTab={selectTab}/>
    <Tabs className="settings-tabs" activeKey={activeTab} onChange={selectTab} items={[
      {key:'model', label:'模型与服务', children:<Card title="模型与服务" extra={<span className="setting-scope">当前服务进程</span>}>
        <p>核对当前进程，并管理学校/官方两个本机配置档。页面永远不读取或显示已有 API Key，切换在重启后生效。</p>
        <ModelConnectionSettings api={api} config={config.data} disabled={!enabled}
          onHealth={health => queryClient.setQueryData<Config>(['chat-config'], current => current ? {...current, model_health:health} : current)}/>
      </Card>},
      {key:'memory-backend', label:'记忆后端', children:<Card title="圆屏记忆后端" extra={<span className="setting-scope">下次统一启动</span>}>
        <p>在保持圆屏、模型、角色和声音不变的情况下切换长期记忆实现，用于日常体验和受控对照。</p>
        <MemoryBackendSettings api={api} disabled={!enabled}/>
      </Card>},
      {key:'role', label:'助手角色', children:<Card title="助手角色" extra={<span className="setting-scope">网页＋可选圆屏同步</span>}>
        <p>编辑角色名称与系统提示词。网页从下一轮开始使用；圆屏必须在弹窗里单独预检和同步。</p>
        <RoleEditor api={api} disabled={!enabled} onSaved={() => {void queryClient.invalidateQueries({queryKey:['chat-config']});}}/>
      </Card>},
      {key:'voice', label:'声音', children:<Card title="声音" extra={<span className="setting-scope">小智 TTS</span>}>
        <p>查看并试听当前 TTS，调整已接入的语音参数，以及选择圆屏拾音灵敏度。TTS 输出与 VAD 输入互不替代。</p>
        <VoiceSettings api={api} disabled={!enabled}/>
        <VADSettings api={api} disabled={!enabled}/>
        <TTSBenchmarkPanel api={api} enabled={enabled}/>
      </Card>},
      {key:'appearance', label:'外观与阅读', children:<Card title="外观与阅读" extra={<span className="setting-scope">当前浏览器</span>}>
        <p>只保存主题、字号、阅读密度、聊天宽度和动画偏好，不保存聊天正文或个人记忆。</p>
        <Space orientation="vertical" style={{width:'100%'}}>
          <label>主题</label><Select className="wide" aria-label="主题" value={prefs.theme} onChange={theme => update({...prefs, theme})} options={[{value:'future',label:'未来控制台（推荐）'},{value:'system',label:'跟随系统'},{value:'light',label:'平静浅色'},{value:'dark',label:'经典深色'}]}/>
          <label>字号</label><Select className="wide" aria-label="字号" value={prefs.size} onChange={size => update({...prefs, size})} options={[{value:'normal',label:'标准'},{value:'large',label:'大'},{value:'larger',label:'更大'}]}/>
          <label>阅读密度</label><Select className="wide" aria-label="阅读密度" value={prefs.density} onChange={density => update({...prefs, density})} options={[{value:'comfortable',label:'舒展（推荐）'},{value:'compact',label:'紧凑'}]}/>
          <label>聊天内容宽度</label><Select className="wide" aria-label="聊天内容宽度" value={prefs.chatWidth} onChange={chatWidth => update({...prefs, chatWidth})} options={[{value:'focused',label:'聚焦阅读（推荐）'},{value:'wide',label:'充分利用宽屏'}]}/>
          <label>界面动画</label><Select className="wide" aria-label="界面动画" value={prefs.motion} onChange={motion => update({...prefs, motion})} options={[{value:'system',label:'跟随系统'},{value:'reduce',label:'减少动画'},{value:'full',label:'完整动画'}]}/>
          <Button onClick={() => reset()}>恢复默认</Button>
        </Space>
      </Card>},
      {key:'proactive', label:'主动交流', children:<Card title="主动交流" extra={<span className="setting-scope">持久许可边界</span>}>
        <p>设置系统什么时候可以联系你，管理显式定时和习惯策略，并查看每次运行为什么发送或被拦截。</p>
        <ProactiveSettings api={api} ready={session.isSuccess}/>
      </Card>},
    ]}/>
    {!enabled && !session.isError && !config.isError && <p role="status">正在读取设置能力；未启用文字服务时角色和声音设置不可操作。</p>}
  </AppShell>;
}
