"""Re-stage actual display/GIF code using M's public host scaffolding; no device."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from otto_review_bridge import method


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--scaffolding', type=Path, required=True)
    parser.add_argument('--fixed-gifs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    controller = args.output/'controller/gif'
    controller.mkdir(parents=True)
    board = args.source/'main/boards/viewe-smartring-plus/viewe-smartring-plus.cc'
    display = args.source/'main/display/lvgl_display'
    text = board.read_text(encoding='utf-8')
    raw_text = (display/'lvgl_image.cc').read_text(encoding='utf-8')
    template = (args.scaffolding/'bridge_test.cc.in').read_text(encoding='utf-8')
    pieces = {
        '%RAW_IMAGE%': method(raw_text, 'LvglRawImage::LvglRawImage(void* data, size_t size)') + '\n' +
                       method(raw_text, 'bool LvglRawImage::IsGif() const'),
        '%CLEAR%': method(text, 'void ClearGif()'),
        '%SHOW%': method(text, 'bool ShowOtto(const char* emotion)'),
        '%WALLPAPER%': method(text, 'void TryLoadWallpaper()'),
        '%STATUS%': method(text, 'void SetStatus(const char* status) override'),
        '%SYSTEM%': method(text, 'void SetEmotion(const char* emotion) override'),
        '%SERVER%': method(text, 'void SetServerEmotion(const char* emotion) override'),
        '%VIEW%': method(text, 'bool SetFaceView(const std::string& view)'),
    }
    # 实际显示仲裁/生命周期全保留；只截去本次无关的几何脸绘制。
    apply = method(text, 'void ApplyFace(const char* emotion)')
    pieces['%APPLY%'] = apply[:apply.index('        const char* value = emotion')] + '\n        visible=wallpaper_ready_?active_gif_:"geometry";\n    }'
    for token, value in pieces.items():
        assert template.count(token) == 1
        template = template.replace(token, value)
    # 补充反复切换和错误尺寸壁纸：检查真实隐藏标志/图片引用/唯一计时器。
    extra = r'''
    Load();files["round_wallpaper.gif"]=wallpaper;
    {
        DisplayFixture d;
        for(int i=0;i<30;i++) {
            assert(d.SetFaceView("wallpaper")&&d.active_gif_=="wallpaper");
            assert(!lv_obj_has_flag(d.wallpaper_image_,LV_OBJ_FLAG_HIDDEN));
            assert(d.wallpaper_image_->src==d.wallpaper_gif_->image_dsc()&&timers.size()==1);
            assert(d.SetFaceView("otto")&&d.active_face_=="neutral");
            assert(!lv_obj_has_flag(d.wallpaper_image_,LV_OBJ_FLAG_HIDDEN));
            assert(d.wallpaper_image_->src==d.wallpaper_gif_->image_dsc()&&timers.size()==1);
        }
        files["round_wallpaper.gif"]=neutral; // 240x240并非原壁纸要求的360x360。
        assert(!d.SetFaceView("wallpaper")&&!d.wallpaper_view_&&d.active_face_=="neutral");
        assert(!lv_obj_has_flag(d.wallpaper_image_,LV_OBJ_FLAG_HIDDEN));
    }
    assert(timers.empty()&&tracked_live()==0);
'''
    assert template.count('    std::cout<<') == 1
    template = template.replace('    std::cout<<', extra + '\n    std::cout<<')
    (args.output/'bridge_test.cc').write_text(template, encoding='utf-8')
    for name in ['lvgl.h', 'esp_log.h', 'decode_test.c']:
        shutil.copyfile(args.scaffolding/name, args.output/name)
    for name in ['gifdec.h', 'lvgl_gif.h', 'lvgl_gif.cc']:
        shutil.copyfile(display/'gif'/name, controller/name)
    shutil.copyfile(display/'lvgl_image.h', args.output/'controller/lvgl_image.h')
    shutil.copyfile(board.with_name('otto_state.h'), args.output/'otto_state.h')
    shutil.copyfile(display/'gif/gifdec.h', args.output/'gifdec.h')
    decoder = (display/'gif/gifdec.c').read_text(encoding='utf-8')
    decoder = decoder.replace('#include <esp_log.h>', '#include <esp_log.h>\n#include <assert.h>\nextern size_t input_length;')
    target = '        memcpy(buf, &gif->data[gif->f_rw_p], len);'
    assert decoder.count(target) == 1
    decoder = decoder.replace(target, '        assert(gif->f_rw_p <= input_length && len <= input_length - gif->f_rw_p);\n' + target)
    target = '        return gif->f_rw_p;'
    assert decoder.count(target) == 1
    decoder = decoder.replace(target, '        assert(gif->f_rw_p <= input_length);\n' + target)
    (args.output/'gifdec.c').write_text(decoder, encoding='utf-8')
    gifs = {'neutral.gif': 'edcb042a7ff48dcc0da0d7bafa7a08171e41ad9efe29d2bc5d552f0ed8b27eb7',
            'happy.gif': '9d2c6701d7a7a81208a00cf4c76ec1ca64f1f6ddc4a884b94aa489cc71c120a3'}
    for name, expected in gifs.items():
        data = (args.fixed_gifs/name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected
        (args.output/name).write_bytes(data)
    inputs = [board, board.with_name('otto_state.h'), args.source/'main/application.cc',
              args.source/'main/display/display.h', display/'lvgl_image.cc', display/'lvgl_image.h',
              display/'gif/lvgl_gif.cc', display/'gif/lvgl_gif.h', display/'gif/gifdec.c']
    record = {str(path.relative_to(args.source)): hashlib.sha256(path.read_text(encoding='utf-8').encode()).hexdigest()
              for path in inputs}
    assert record[str(board.relative_to(args.source))] == hashlib.sha256(text.encode()).hexdigest()
    (args.output/'source-fingerprints.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')
    # 不执行21图解码/100次循环的旧main；该C对象仅提供分配跟踪函数。
    output = str(args.output)
    commands = ["$ErrorActionPreference='Stop'", ". 'D:\\01-开发环境\\03-C-C++\\scripts\\Enter-Cpp.ps1'",
                f"Push-Location -LiteralPath '{output}'", 'try {',
                '& cl.exe /nologo /c /utf-8 /TC /Dmain=decoder_unused_main /I. gifdec.c decode_test.c',
                "if ($LASTEXITCODE -ne 0) { throw 'Decoder host compile failed' }",
                '& cl.exe /nologo /std:c++17 /EHsc /utf-8 /I. bridge_test.cc controller/gif/lvgl_gif.cc gifdec.obj decode_test.obj /Fe:review_display.exe',
                "if ($LASTEXITCODE -ne 0) { throw 'Display host compile failed' }",
                '& .\\review_display.exe', "if ($LASTEXITCODE -ne 0) { throw 'Display host checks failed' }",
                '} finally { Pop-Location }']
    (args.output/'run.ps1').write_text('\n'.join(commands)+'\n', encoding='utf-8-sig')
    print(json.dumps(record, indent=2))
    print(str(args.output/'run.ps1'))


if __name__ == '__main__':
    main()
