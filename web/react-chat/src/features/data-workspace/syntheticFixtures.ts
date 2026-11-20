/** 仅供合成验收：固定样例不读取个人库，不提供任何设备或模型写入口。 */
export function syntheticResponse(path:string, populated:boolean):unknown {
  const url=new URL(path,'http://synthetic.invalid');
  switch(url.pathname) {
    case '/api/session':return {csrf:'synthetic-only'};
    case '/api/memory-engine/identity':return {schema_version:1,configured:true,method:'hy_memory_pro_chat',representation:'method_defined',legacy_sqlite:false,state:'available'};
    case '/api/observability':return {schema_version:1,scope:'current_process',capacity:100,persistence:'disabled',
      requests:[],device_playback:'unconfirmed',coverage:['http_request'],uncovered:['asr','tts','device_playback','background_completion'],logs:[]};
    case '/api/device':return {ready:populated,connection_count:populated?1:0,reason:populated?null:'device_offline',read_volume_supported:populated,set_volume_supported:populated,read_status_supported:false,set_brightness_supported:false,set_theme_supported:false,stop_speech_supported:false,allowed_volume:{minimum:5,maximum:100}};
    default:throw new Error(`Unmapped synthetic endpoint: ${url.pathname}`);
  }
}
