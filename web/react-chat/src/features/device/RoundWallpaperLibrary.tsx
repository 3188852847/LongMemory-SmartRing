import {useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Alert, Button, Card, Descriptions, InputNumber, Select, Space, Tag} from 'antd';
import {ApiError, ChatApi, type RoundWallpaperDeployment, type RoundWallpaperDeviceStatus, type RoundWallpaperLibrary as Library, type RoundWallpaperUploadOptions} from '../../api';

const errorCopy:Record<string,string> = {
  wallpaper_upload_too_large:'源视频超过 768 MiB 上限。请先在本机裁短或压缩。',
  invalid_wallpaper_source_size:'源文件为空或超过大小上限。',
  wallpaper_source_outside_limits:'源视频的时长、分辨率或帧率超过当前安全边界。',
  wallpaper_clip_outside_source:'截取起点和长度超出了源视频。',
  ffprobe_failed:'无法识别这个文件中的视频流。', ffmpeg_failed:'FFmpeg 没有成功生成预览。',
  wallpaper_output_too_large:'生成结果超过 4 MiB，请降低帧率或颜色数。',
  ffmpeg_not_found:'没有找到 FFmpeg，请从启动面板重新启动并核对安装目录。',
  ffmpeg_directory_invalid:'FFmpeg 目录缺少 ffmpeg.exe 或 ffprobe.exe。',
  round_wallpaper_delivery_unavailable:'当前不是圆屏启动模式，壁纸投递端口没有开放。',
  device_offline:'圆屏当前离线，请先让设备进入已连接/聆听状态。',
  round_wallpaper_stage_failed:'圆屏没有完成下载或哈希核对；原壁纸未被切换。',
  device_timeout_outcome_unknown:'等待圆屏重启并回读活动壁纸超时；不要重复发布，设备可能已经完成切换。',
  round_wallpaper_readback_mismatch:'圆屏回执与本机素材不一致，已拒绝激活。',
  round_wallpaper_restart_not_acknowledged:'壁纸已选中，但圆屏没有确认重启；请手动重启后核对。',
};
function size(value:number) {return value>=1048576?`${(value/1048576).toFixed(1)} MiB`:`${Math.ceil(value/1024)} KiB`;}

export function RoundWallpaperLibrary({api,sessionReady}:{api:ChatApi;sessionReady:boolean}) {
  const queryClient=useQueryClient();
  const [file,setFile]=useState<File>();
  const [options,setOptions]=useState<RoundWallpaperUploadOptions>({start_seconds:60,duration_seconds:5,frame_rate:10,colors:96});
  const library=useQuery({queryKey:['round-wallpapers'],queryFn:()=>api.request<Library>('/api/round-wallpapers'),enabled:sessionReady});
  const device=useQuery({queryKey:['round-wallpapers','device'],queryFn:()=>api.request<RoundWallpaperDeviceStatus>('/api/round-wallpapers/device'),enabled:sessionReady&&Boolean(library.data?.device_delivery.enabled)});
  const upload=useMutation({mutationFn:()=>{if(!file)throw new ApiError('wallpaper_file_required',400);return api.uploadRoundWallpaper(file,options);},
    onSuccess:()=>{setFile(undefined);void queryClient.invalidateQueries({queryKey:['round-wallpapers']});}});
  const refreshDevice=()=>window.setTimeout(()=>void queryClient.invalidateQueries({queryKey:['round-wallpapers','device']}),5000);
  const publish=useMutation({mutationFn:(itemId:string)=>api.request<RoundWallpaperDeployment>(`/api/round-wallpapers/${itemId}/publish`,'POST'),onSuccess:refreshDevice});
  const rollback=useMutation({mutationFn:()=>api.request<RoundWallpaperDeployment>('/api/round-wallpapers/rollback','POST'),onSuccess:refreshDevice});
  const error=upload.error instanceof ApiError?(errorCopy[upload.error.code]??`导入失败：${upload.error.code}`):'导入失败，请核对本机媒体工具。';
  const deliveryError=publish.error instanceof ApiError||rollback.error instanceof ApiError
    ? errorCopy[(publish.error instanceof ApiError?publish.error:rollback.error as ApiError).code]??'圆屏没有完成壁纸操作；原壁纸仍可回退。'
    : '圆屏没有完成壁纸操作；原壁纸仍可回退。';
  const deviceReady=library.data?.device_delivery.enabled&&device.isSuccess;
  return <Card title="6. 动态壁纸素材库" extra={<Space><Tag color="cyan">local media</Tag><Button size="small" disabled={!deviceReady||!device.data.rollback_available} loading={rollback.isPending} onClick={()=>rollback.mutate()}>{device.data?.active_valid?'回退上一壁纸':'恢复保留的壁纸'}</Button></Space>}>
    <p className="subtle">上传原视频后，本机会验证内容并产生 360×360 GIF。活动壁纸会覆盖几何皮肤；切换为皮肤显示只停用活动指针，不会擦除这里的 A/B 壁纸槽。</p>
    {library.isError&&<Alert type="error" showIcon title="素材库不可用" description="请刷新页面；其他圆屏功能不受影响。"/>}
    {library.data&&!library.data.enabled&&<Alert type="warning" showIcon title="没有找到本机 FFmpeg" description="从启动面板重新启动后再试；控制台不会自动下载依赖。"/>}
    {library.data?.device_delivery.enabled&&device.isError&&<Alert type="warning" showIcon title="当前圆屏不支持运行时壁纸发布" description="设备离线或仍是旧固件时会看到此提示；不会写入 Flash。"/>}
    <div className="wallpaper-import-grid">
      <label className="wallpaper-file-field"><span>源视频</span><input aria-label="动态壁纸源视频" type="file" accept="video/*,.gif" onChange={event=>setFile(event.target.files?.[0])}/><small>{file?`${file.name} · ${size(file.size)}`:'单个文件不超过 768 MiB'}</small></label>
      <label><span>截取起点（秒）</span><InputNumber aria-label="截取起点" min={0} max={86400} step={1} value={options.start_seconds} onChange={value=>typeof value==='number'&&setOptions(current=>({...current,start_seconds:value}))}/></label>
      <label><span>时长</span><Select aria-label="壁纸时长" value={options.duration_seconds} options={[3,4,5].map(value=>({value,label:`${value} 秒`}))} onChange={value=>setOptions(current=>({...current,duration_seconds:value}))}/></label>
      <label><span>帧率</span><Select aria-label="壁纸帧率" value={options.frame_rate} options={[8,10,12].map(value=>({value,label:`${value} fps`}))} onChange={value=>setOptions(current=>({...current,frame_rate:value}))}/></label>
      <label><span>颜色数</span><Select aria-label="壁纸颜色数" value={options.colors} options={[64,96,128].map(value=>({value,label:String(value)}))} onChange={value=>setOptions(current=>({...current,colors:value}))}/></label>
    </div>
    <Space wrap className="wallpaper-actions"><Button type="primary" disabled={!file||!library.data?.enabled} loading={upload.isPending} onClick={()=>upload.mutate()}>导入并生成预览</Button><span className="subtle">{upload.isPending?'正在上传和转码，大文件需要等待…':'当前仅生成预览，不会改动真机。'}</span></Space>
    {upload.isError&&<Alert className="settings-model-alert" type="error" showIcon title="素材没有导入" description={error}/>}
    {upload.isSuccess&&<Alert className="settings-model-alert" type="success" showIcon title="素材已导入" description="预览已通过尺寸、时长和哈希校验；尚未发布到圆屏。"/>}
    {(publish.isError||rollback.isError)&&<Alert className="settings-model-alert" type="error" showIcon title="壁纸操作未完成" description={deliveryError}/>}
    {(publish.isSuccess||rollback.isSuccess)&&<Alert className="settings-model-alert" type="success" showIcon title="圆屏已核验并安排切换" description="设备正在重启；重连回读后才确认已生效，A/B 备用槽仍保留上一张已验证壁纸。"/>}
    <div className="wallpaper-library-list">{library.data?.items.length===0&&<p className="subtle">还没有本机动态壁纸素材。</p>}{library.data?.items.map(item=><article key={item.id} className="wallpaper-library-item">
      <img src={`/api/round-wallpapers/${item.id}/preview`} alt={`${item.source.display_name} 圆屏预览`}/><div><h3>{item.source.display_name}</h3><Descriptions size="small" column={1} items={[
        {key:'source',label:'源视频',children:`${item.source.width}×${item.source.height} · ${item.source.duration_seconds.toFixed(1)} 秒 · ${item.source.video_codec}`},
        {key:'clip',label:'预览裁切',children:`${item.clip.start_seconds} 秒起 · ${item.clip.duration_seconds} 秒 · ${item.clip.frame_rate} fps · ${item.clip.colors} 色`},
        {key:'size',label:'预览大小',children:size(item.preview.size_bytes)},{key:'hash',label:'素材指纹',children:<code>{item.preview.sha256.slice(0,16)}…</code>},{key:'state',label:'真机状态',children:device.data?.active_valid&&device.data.active_wallpaper_id===item.id&&device.data.active_sha256===item.preview.sha256?<Tag color="success">圆屏已回读</Tag>:<Tag>本机素材</Tag>},
      ]}/><Button type="primary" disabled={!deviceReady} loading={publish.isPending&&publish.variables===item.id} onClick={()=>publish.mutate(item.id)}>发布到圆屏（会重启）</Button></div></article>)}</div>
  </Card>;
}
