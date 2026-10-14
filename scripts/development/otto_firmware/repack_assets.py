"""Lossless append of fixed Otto resources to the vendor mmap table, offline only."""
import argparse
import hashlib
import json
import struct
from pathlib import Path

CAPACITY = 2097152
ENTRY = struct.Struct('<32sIIHH')
def sha(data): return hashlib.sha256(data).hexdigest()
def parse(image, accept_unindexed_tail=False):
    if len(image) < 12: raise ValueError('short header')
    count, checksum, length = struct.unpack_from('<III', image)
    end = 12 + length
    if count == 0 or count > 4096 or end > len(image) or length < count * ENTRY.size:
        raise ValueError('invalid bounds')
    body = image[12:end]
    if sum(body) & 65535 != checksum: raise ValueError('checksum mismatch')
    payload = body[count * ENTRY.size:]
    entries, names, spans = [], set(), []
    for i in range(count):
        name, size, offset, width, height = ENTRY.unpack_from(body, i * ENTRY.size)
        if b'\0' not in name: raise ValueError('unterminated name')
        name = name.split(b'\0', 1)[0].decode('utf-8')
        if not name or name in names: raise ValueError('duplicate/empty name')
        names.add(name)
        if offset + 2 + size > len(payload) or payload[offset:offset+2] != b'ZZ':
            raise ValueError('invalid asset bounds or magic')
        if any(offset < b and offset + size + 2 > a for a,b in spans):
            raise ValueError('overlapping resources')
        spans.append((offset, offset + size + 2))
        entries.append((name,size,offset,width,height,payload[offset+2:offset+2+size]))
    # 非表内、非擦除的尾部不擅自丢弃。原数据区域的全部字节（含间隙）整体保留。
    if not accept_unindexed_tail and any(b != 255 for b in image[end:]):
        raise ValueError('non-erased unindexed tail; manual review required')
    return entries, payload, end

def repack(original, gif_root, manifest, tail_review=None):
    if tail_review is not None:
        if len(original) != CAPACITY or tail_review.get('original_image_sha256') != sha(original):
            raise ValueError('tail review image fingerprint mismatch')
        if not tail_review.get('no_reachable_tail_consumers') or not tail_review.get('code_evidence'):
            raise ValueError('tail review lacks consumer evidence')
    entries, payload, original_used = parse(original, tail_review is not None)
    if tail_review is not None and tail_review.get('original_used_bytes') != original_used:
        raise ValueError('tail review used-length mismatch')
    fixed = json.loads(manifest.read_text(encoding='utf-8'))
    assert fixed['commit'] == '970cf66906d7c30059faa2704e7002f06b8c3619'
    added = []
    payload = bytearray(payload)
    for item in fixed['files']:
        path = item['path']; data = (gif_root / path).read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if blob != item['git_blob_sha1'] or len(data) != item['bytes']:
            raise ValueError('upstream fingerprint mismatch: ' + path)
        if not path.endswith('.gif'): continue
        if data[:6] != b'GIF89a' or struct.unpack_from('<HH', data, 6) != (240,240):
            raise ValueError('unexpected GIF dimensions/header')
        name = 'otto_' + Path(path).name
        if name in {e[0] for e in entries} or len(name.encode()) >= 32:
            raise ValueError('resource name conflict')
        entries.append((name,len(data),len(payload),240,240,data))
        payload += b'ZZ' + data
        added.append({'name':name,'bytes':len(data),'sha256':sha(data),'git_blob_sha1':blob})
    if len(added) != 21: raise ValueError('expected all 21 Otto GIFs')
    table = b''.join(ENTRY.pack(n.encode(),s,o,w,h) for n,s,o,w,h,d in entries)
    body = table + payload
    used = 12 + len(body)
    if used > CAPACITY: raise ValueError(f'capacity blocked: {used} > {CAPACITY}')
    base = original + b'\xff' * (CAPACITY-len(original))
    if len(base) != CAPACITY: raise ValueError('original exceeds partition capacity')
    image = struct.pack('<III',len(entries),sum(body)&65535,len(body)) + body
    erase_end = (used + 4095) // 4096 * 4096
    # 末扇区必须带回原字节；后续扇区不写。新 used 之后整段原尾原样保留。
    image += base[used:erase_end]
    final_partition = image + base[erase_end:]
    verified, after_payload, _ = parse(final_partition, True)
    before, before_payload, _ = parse(original, tail_review is not None)
    for a,b in zip(before,verified):
        if a != b: raise ValueError('original resource changed')
    if after_payload[:len(before_payload)] != before_payload:
        raise ValueError('original payload region changed')
    report = {'format':'vendor mmap_assets_table, <32sIIHH, ZZ prefix; unsigned-byte sum16',
        'partition_offset':'0x800000','partition_capacity':CAPACITY,'used_bytes':used,
        'write_bytes':len(image),'unused_by_index_bytes':CAPACITY-used,'original_used_bytes':original_used,
        'original_image_sha256':sha(original),'new_image_sha256':sha(image),
        'postwrite_partition_sha256':sha(final_partition),
        'erase_end_offset':erase_end,'erase_end_address':hex(0x800000+erase_end),
        'unindexed_replaced_range':[original_used,used],
        'unindexed_replaced_bytes':used-original_used,
        'unindexed_replaced_nonff_bytes':sum(b!=255 for b in base[original_used:used]),
        'original_tail_nonff_bytes':sum(b!=255 for b in base[original_used:]),
        'unindexed_remainder_preserved_offset':used,
        'unindexed_remainder_preserved_bytes':CAPACITY-used,
        'unindexed_remainder_sha256':sha(base[used:]),
        'last_sector_original_padding_bytes':erase_end-used,
        'all_bytes_after_new_used_preserved':final_partition[used:]==base[used:],
        'tail_review_applied':tail_review is not None,
        'original_payload_region_preserved':True,'original_index_json_unchanged':True,
        'preserved_resources':[{'name':e[0],'bytes':e[1],'sha256':sha(e[5])} for e in before],
        'added_resources':added,'original_resource_count':len(before)}
    return image, report

if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--original',type=Path,required=True)
    p.add_argument('--upstream',type=Path,required=True); p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True); p.add_argument('--report',type=Path,required=True)
    p.add_argument('--tail-review',type=Path)
    a=p.parse_args()
    if a.output.exists() or a.report.exists(): raise SystemExit('refusing to overwrite output/report')
    review=json.loads(a.tail_review.read_text(encoding='utf-8')) if a.tail_review else None
    image,report=repack(a.original.read_bytes(),a.upstream,a.manifest,review)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_bytes(image); a.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('preserved_resources','added_resources')},indent=2))
