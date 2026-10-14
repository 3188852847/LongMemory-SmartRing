"""Stage actual board bridge methods and actual LvglGif with LVGL/partition host stubs."""
from pathlib import Path
import argparse, hashlib, json, shutil
def method(text, signature):
    start=text.index(signature);brace=text.index('{',start);depth=1;end=brace+1
    while depth:
        if text[end]=='{':depth+=1
        elif text[end]=='}':depth-=1
        end+=1
    return text[start:end]
def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    repo=Path(__file__).resolve().parents[3]
    display=a.source/'main/display/lvgl_display'
    dest=a.output/'controller/gif';dest.mkdir(parents=True,exist_ok=False)
    for name in ('lvgl_gif.cc','lvgl_gif.h','gifdec.h'):shutil.copy2(display/'gif'/name,dest/name)
    shutil.copy2(display/'lvgl_image.h',dest.parent/'lvgl_image.h')
    board=(a.source/'main/boards/viewe-smartring-plus/viewe-smartring-plus.cc').read_text(encoding='utf-8')
    raw=(display/'lvgl_image.cc').read_text(encoding='utf-8')
    raw=raw[raw.index('LvglRawImage::LvglRawImage'):raw.index('LvglCBinImage::LvglCBinImage')]
    selected={'CLEAR':'    void ClearGif(', 'SHOW':'    bool ShowOtto(', 'WALLPAPER':'    void TryLoadWallpaper(',
        'STATUS':'    void SetStatus(', 'SYSTEM':'    void SetEmotion(', 'SERVER':'    void SetServerEmotion(',
        'VIEW':'    bool SetFaceView('}
    replacements={key:method(board,sig) for key,sig in selected.items()}
    apply=method(board,'    void ApplyFace(')
    apply=apply[:apply.index('        const char* value =')]+'        visible=wallpaper_ready_?active_gif_:"geometry";\n    }'
    replacements.update(APPLY=apply,RAW_IMAGE=raw)
    template=(repo/'tests/unit/firmware/gif_host/bridge_test.cc.in').read_text(encoding='utf-8')
    for key,value in replacements.items():
        assert template.count('%'+key+'%')==1;template=template.replace('%'+key+'%',value)
    (a.output/'bridge_test.cc').write_text(template,encoding='utf-8',newline='\n')
    record={'source':'actual final otto0014 methods, no reimplementation of event or decoder arbitration',
        'snippets_sha256':{key:hashlib.sha256(val.encode()).hexdigest() for key,val in replacements.items()},
        'excluded':'geometric fallback painting, actual LVGL rendering and hardware are stubbed; GIF algorithm/controller are real'}
    (a.output/'bridge-source.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    print('Actual display/controller bridge staged.')
if __name__=='__main__':main()
