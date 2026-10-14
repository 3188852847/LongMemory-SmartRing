/* 独立绑定浏览器生命周期，便于用合成事件核对不会意外恢复播放。 */
(function(root){
  function attach(document, preference, pause){
    const visibility=()=>{if(document.hidden)pause();};
    const motion=event=>{if(event.matches)pause();};
    document.addEventListener('visibilitychange',visibility);
    preference.addEventListener('change',motion);
    if(preference.matches)pause();
    return ()=>{document.removeEventListener('visibilitychange',visibility);preference.removeEventListener('change',motion);};
  }
  if(typeof module!=='undefined')module.exports={attach};else root.OttoLifecycle={attach};
})(typeof window!=='undefined'?window:globalThis);
