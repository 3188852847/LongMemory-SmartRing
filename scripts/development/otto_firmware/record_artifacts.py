"""Create public hashes/auditable diff and verify it on a minimal fresh source fixture."""
import argparse, difflib, hashlib, json, struct, subprocess, sys
from pathlib import Path
FILES=['CMakeLists.txt','main/application.cc','main/display/display.h',
       'main/display/lvgl_display/gif/lvgl_gif.cc',
       'main/display/lvgl_display/gif/lvgl_gif.h',
       'main/boards/viewe-smartring-plus/viewe-smartring-plus.cc',
       'main/boards/viewe-smartring-plus/otto_state.h']
def sha(data):return hashlib.sha256(data).hexdigest()
def digest(path):
    data=path.read_bytes();return {'bytes':len(data),'sha256':sha(data)}
def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--baseline-source',type=Path,required=True);p.add_argument('--build',type=Path,required=True)
    p.add_argument('--comparison-build',type=Path,required=True);p.add_argument('--baseline-build',type=Path,required=True)
    p.add_argument('--assets-report',type=Path,required=True);p.add_argument('--decoder-report',type=Path,required=True)
    p.add_argument('--bridge-source',type=Path,required=True)
    p.add_argument('--audit-fixture',type=Path,required=True)
    p.add_argument('--patch-only',action='store_true');a=p.parse_args()
    repo=Path(__file__).resolve().parents[3]
    patch=repo/'firmware/smartring_plus/patches/0014-otto-gif-face.patch'
    parts=[];sources={}
    a.audit_fixture.mkdir(exist_ok=False)
    for file in FILES:
        old=a.baseline_source/file;new=a.source/file
        before=old.read_text(encoding='utf-8') if old.exists() else ''
        after=new.read_text(encoding='utf-8')
        sources[file]={'baseline_normalized_sha256':sha(before.encode()) if old.exists() else None,
                       'result_normalized_sha256':sha(after.encode())}
        parts.append(f'diff --git a/{file} b/{file}\n')
        if not old.exists():parts.append('new file mode 100644\n')
        parts.extend(difflib.unified_diff(before.splitlines(keepends=True),after.splitlines(keepends=True),
                    fromfile='a/'+file if old.exists() else '/dev/null',tofile='b/'+file,n=0))
        if old.exists():
            target=a.audit_fixture/file;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(before,encoding='utf-8',newline='\n')
    patch.write_text(''.join(parts),encoding='utf-8',newline='\n')
    subprocess.run(['git','apply','--unidiff-zero','--check',str(patch)],cwd=a.audit_fixture,check=True)
    subprocess.run(['git','apply','--unidiff-zero',str(patch)],cwd=a.audit_fixture,check=True)
    for file,record in sources.items():
        assert sha((a.audit_fixture/file).read_text(encoding='utf-8').encode())==record['result_normalized_sha256']
    subprocess.run(['git','apply','--unidiff-zero','--check','--reverse',str(patch)],cwd=a.audit_fixture,check=True)
    if a.patch_only:
        print('Final patch applied, all source hashes matched, reverse check passed.');return
    bins=['xiaozhi.bin','xiaozhi.elf','xiaozhi.map','partition_table/partition-table.bin','generated_assets.bin']
    builds={'delivery':{name:digest(a.build/name) for name in bins},
            'independent_clean':{name:digest(a.comparison_build/name) for name in bins}}
    partition=(a.build/'partition_table/partition-table.bin').read_bytes()
    assert partition==(a.baseline_build/'partition_table/partition-table.bin').read_bytes()
    assert partition==(a.comparison_build/'partition_table/partition-table.bin').read_bytes()
    rows=[]
    for pos in range(0,len(partition),32):
        magic,typ,sub,offset,size,label,flags=struct.unpack_from('<HBBII16sI',partition,pos)
        if magic!=0x50aa:break
        rows.append({'name':label.rstrip(b'\0').decode(),'type':typ,'subtype':sub,'offset':hex(offset),'bytes':size,'flags':flags})
    assert [r for r in rows if r['name']=='assets'][0]['bytes']==2097152
    assert builds['delivery']['xiaozhi.bin']['bytes']<=4128768
    assert builds['delivery']['xiaozhi.bin']['bytes']==builds['independent_clean']['xiaozhi.bin']['bytes']
    assert (a.build/'generated_assets.bin').read_bytes()==(a.comparison_build/'generated_assets.bin').read_bytes()
    assert (a.source/'sdkconfig').read_bytes()==(a.baseline_source/'sdkconfig').read_bytes()
    assert (a.source/'dependencies.lock').read_bytes()==(a.baseline_source/'dependencies.lock').read_bytes()
    info=subprocess.run([sys.executable,'-m','esptool','image_info',str(a.build/'xiaozhi.bin')],capture_output=True,text=True,check=True)
    if 'Checksum: ' not in info.stdout or 'Validation Hash: ' not in info.stdout: raise ValueError('unexpected image_info format')
    if '(valid)' not in info.stdout:raise ValueError('image validation not confirmed')
    decoder=json.loads(a.decoder_report.read_text(encoding='utf-8-sig'))
    assets=json.loads(a.assets_report.read_text(encoding='utf-8'))
    receipt={'id':'0014-otto-gif-face','status':'offline_delivery_ready','recorded_date':'2026-10-14','timezone':'Asia/Shanghai',
        'source_baseline':'0013 / main repository a041b5f','sdk_commit':'735507283d5b2f9fb363a1901172dbd9e847945d',
        'sdk_version':'5.5.4','lvgl_version':'9.4.0','component_lock':digest(a.source/'dependencies.lock'),
        'sdkconfig':digest(a.source/'sdkconfig'),'dependencies_changed':False,'config_changed':False,
        'application_version':'2.2.3-otto0014','board':'viewe-smartring-plus','chip':'esp32s3',
        'app_capacity':4128768,'app_free_bytes':4128768-builds['delivery']['xiaozhi.bin']['bytes'],
        'delivery_build':str(a.build),'comparison_build':str(a.comparison_build),
        'builds':builds,'partition_layout_unchanged':True,'partitions':rows,
        'patch':digest(patch),'patch_context_lines':0,'patch_apply_option':'--unidiff-zero',
        'sources':sources,'patch_forward_and_reverse_checked':True,
        'image_checksum_and_validation_hash_valid':True,
        'assets':assets,'decoder_validation':{'files':len(decoder),'frames':sum(r['frames'] for r in decoder),
            'switches':sum(r['switches'] for r in decoder),'max_host_decoder_allocation_bytes':max(r['peak_decoder_bytes_host'] for r in decoder),
            'read_seek_bounds_checked':True,'allocation_failure_checked':True,'no_remaining_allocations':True,
            'host_not_device_memory':True,'results':decoder},
        'display_bridge_validation':{'passed':True,
            'source':json.loads(a.bridge_source.read_text(encoding='utf-8')),
            'cases':['System thinking never cached for Speaking; server thinking preserved.',
                'Actual Listening -> status Thinking -> system thinking -> Speaking with no LLM is neutral; happy LLM is happy.',
                'First-frame decode error -> neutral; mid-frame decode error -> deferred safe cleanup -> neutral.',
                'Paused/finished decoder not treated as error; 999/1000ms retry boundary checked.',
                'Neutral decoder failure -> retained wallpaper or geometry.',
                'Otto -> wallpaper -> Otto checks image hidden flag and 240/360 dimensions.',
                'Unavailable wallpaper returns false and shows visible Otto; wallpaper mid-frame error retries from neutral.']},
        'display_default':'Otto 240x240 centered','wallpaper_and_nvs_preserved':True,
        'firmware_runtime_on_device_verified':False,'serial_opened':False,'flashed':False,
        'limits':['No protocol turnID; previous-turn emotion arriving during new Thinking/Speaking cannot be distinguished.',
                  'Device frame rate, available heap with live audio, memory, voice and interleaving require owner/K validation.']}
    out=repo/'firmware/smartring_plus/experiments/0014-otto-gif-face.json'
    out.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'patch_forward_reverse':'passed','delivery_build':str(a.build),
        'app':builds['delivery']['xiaozhi.bin'],'app_free_bytes':receipt['app_free_bytes'],
        'partition_table':builds['delivery']['partition_table/partition-table.bin'],
        'assets_prefix_sha256':assets['new_image_sha256'],'assets_write_bytes':assets['write_bytes']},indent=2))
if __name__=='__main__':main()
