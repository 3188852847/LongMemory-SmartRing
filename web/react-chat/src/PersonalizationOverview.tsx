import {useQuery} from '@tanstack/react-query';
import {Button, Tag} from 'antd';
import type {ChatApi, ProactivePolicy, RoundSkins} from './api';
import type {AppearancePreferences} from './AppearanceProvider';
import {readRolePreferences} from './rolePreferences';

interface RoleSummary {
  current:{revision:number;name:string;prompt:string;saved_at:string|null};
  web:'next_turn'|'fake_no_persona';
  device:'check_required'|'not_synced';
}

interface VoiceSummary {
  backend:'edge'|'voxcpm2'|'unsupported';
  voice:string|null;
  service_ready?:boolean|null;
  profile?:{reference:string|null;style:string;quality:'fast'|'balanced'|'quality'};
  references?:Array<{id:string|null;label:string}>;
}

const themeLabels:Record<AppearancePreferences['theme'],string> = {
  future:'未来控制台', system:'跟随系统', light:'平静浅色', dark:'经典深色',
};
const interactionLabels = {
  listen_first:'先倾听', ask_before_advice:'先询问再建议', direct:'直接讨论办法',
};
const qualityLabels = {fast:'快速', balanced:'均衡', quality:'质量'};

function unavailable(query:{isError:boolean}) { return query.isError ? '读取失败' : '读取中'; }

/**
 * 把分散的个性化配置放进同一张“事实表”。这里刻意不自动读取真机：
 * 真机读取会占用设备控制通道，而且预览选择不等于已经下发到设备。
 */
export function PersonalizationOverview({api, ready, prefs, onSelectTab}:{
  api:ChatApi; ready:boolean; prefs:AppearancePreferences; onSelectTab:(tab:string)=>void;
}) {
  const role = useQuery({queryKey:['assistant-role'], queryFn:()=>api.request<RoleSummary>('/api/assistant-role'), enabled:ready});
  const skins = useQuery({queryKey:['round-skins'], queryFn:()=>api.request<RoundSkins>('/api/round-skins'), enabled:ready});
  const proactive = useQuery({queryKey:['proactive-policy'], queryFn:()=>api.request<ProactivePolicy>('/api/proactive-policy'), enabled:ready});
  const voice = useQuery({
    queryKey:['personalization-voice'], queryFn:()=>api.request<VoiceSummary>('/api/voice-settings'),
    enabled:false, retry:false,
  });

  const rolePreferences = role.data ? readRolePreferences(role.data.current.prompt) : null;
  const selectedSkin = skins.data?.skins.find(item => item.id === skins.data?.selected_skin);
  const reference = voice.data?.profile?.reference;
  const referenceLabel = voice.data?.references?.find(item => item.id === reference)?.label ?? reference;
  const voiceValue = !voice.data ? (voice.isError ? '读取失败' : '尚未读取')
    : voice.data.backend === 'voxcpm2'
      ? `VoxCPM2 · ${referenceLabel ?? '模型默认声线'} · ${qualityLabels[voice.data.profile?.quality ?? 'balanced']}`
      : voice.data.backend === 'edge' ? `Edge · ${voice.data.voice ?? '默认音色'}` : '当前后端不支持设置';

  const rows = [
    {key:'appearance', title:'控制台外观', value:`${themeLabels[prefs.theme]} · ${prefs.density === 'compact' ? '紧凑' : '舒展'}`, scope:'当前浏览器', timing:'立即生效', action:'appearance'},
    {key:'role', title:'助手角色', value:role.data ? `${role.data.current.name} · 修订 ${role.data.current.revision}` : unavailable(role), scope:'网页对话', timing:'下一轮生效', action:'role'},
    {key:'interaction', title:'表达与互动', value:rolePreferences?.enabled ? interactionLabels[rolePreferences.preferences.interactionStyle] : '使用角色提示词默认规则', scope:'网页；圆屏需同步角色', timing:'下一轮／同步后', action:'role'},
    {key:'voice', title:'声音方案', value:voiceValue, scope:'网页朗读＋圆屏 TTS', timing:voice.data?.backend === 'voxcpm2' ? '下次合成' : '重启语音服务后', action:'voice'},
    {key:'skin', title:'圆屏状态皮肤', value:selectedSkin?.name ?? (skins.data ? skins.data.selected_skin : unavailable(skins)), scope:'当前只是预览选择', timing:'真机需单独应用', action:'display'},
    {key:'wallpaper', title:'动态壁纸', value:'真机状态未自动读取', scope:'智能圆屏', timing:'在圆屏外观页发布', action:'display'},
    {key:'proactive', title:'主动交流', value:proactive.data ? (proactive.data.enabled ? '已允许' : '已关闭') : unavailable(proactive), scope:'持久策略', timing:'保存后生效', action:'proactive'},
  ];

  return <section className="personalization-overview" aria-labelledby="personalization-overview-title">
    <div className="personalization-overview-heading">
      <div><small>PERSONALIZATION MAP</small><h2 id="personalization-overview-title">个性化状态总览</h2></div>
      <p>“网页已选中”不等于“圆屏已同步”。真机相关项目只在明确操作后下发。</p>
    </div>
    <div className="personalization-grid">
      {rows.map(row => <article className="personalization-row" key={row.key}>
        <div><small>{row.title}</small><strong>{row.value}</strong></div>
        <div className="personalization-boundary"><Tag>{row.scope}</Tag><span>{row.timing}</span></div>
        {row.action === 'display'
          ? <Button href="/display-preview" size="small">打开圆屏外观</Button>
          : <Button size="small" onClick={() => onSelectTab(row.action)}>设置</Button>}
      </article>)}
    </div>
    <div className="personalization-voice-read">
      <span>声音状态需要检查小智本地配置，因此不在打开页面时自动运行。</span>
      <Button size="small" loading={voice.isFetching} onClick={() => void voice.refetch()}>读取声音状态</Button>
    </div>
  </section>;
}
