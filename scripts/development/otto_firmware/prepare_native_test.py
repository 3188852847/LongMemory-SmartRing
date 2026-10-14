"""Stage exact decoder with read/seek assertions in a fresh ASCII host test dir."""
from pathlib import Path
import argparse, shutil, json, hashlib
def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--upstream',type=Path,required=True)
    a=p.parse_args(); a.output.mkdir(exist_ok=False)
    repo=Path(__file__).resolve().parents[3]
    fixtures=repo/'tests/unit/firmware/gif_host'
    for file in fixtures.iterdir(): shutil.copy2(file,a.output/file.name)
    decoder=a.source/'main/display/lvgl_display/gif'
    shutil.copy2(decoder/'gifdec.h',a.output/'gifdec.h')
    text=(decoder/'gifdec.c').read_text(encoding='utf-8')
    text=text.replace('#include <esp_log.h>','#include <esp_log.h>\n#include <assert.h>\nextern size_t input_length;')
    old='        memcpy(buf, &gif->data[gif->f_rw_p], len);'
    assert text.count(old)==1
    text=text.replace(old,'        assert(gif->f_rw_p <= input_length && len <= input_length - gif->f_rw_p);\n'+old)
    old='        return gif->f_rw_p;'
    assert text.count(old)==1
    text=text.replace(old,'        assert(gif->f_rw_p <= input_length);\n'+old)
    (a.output/'gifdec.c').write_text(text,encoding='utf-8')
    shutil.copy2(Path(__file__).with_name('otto_state.h'),a.output/'otto_state.h')
    shutil.copy2(repo/'tests/unit/firmware/otto_state_test.cc',a.output/'otto_state_test.cc')
    for file in (a.upstream/'gifs').glob('*.gif'): shutil.copy2(file,a.output/file.name)
    print('Host test staged; exact gifdec algorithm with added input-bound assertions.')
if __name__=='__main__':main()
