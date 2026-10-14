import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('otto_assets', REPO/'scripts/development/otto_firmware/repack_assets.py')
assets = importlib.util.module_from_spec(spec); spec.loader.exec_module(assets)
def image(payload=b'ZZ{"original":true}', name='index.json'):
    body=assets.ENTRY.pack(name.encode(),len(payload)-2,0,0,0)+payload
    return struct.pack('<III',1,sum(body)&65535,len(body))+body

class AssetTests(unittest.TestCase):
    def test_roundtrip_preserves_payload_and_index(self):
        with tempfile.TemporaryDirectory(prefix='otto-assets-synthetic-') as temp:
            root=Path(temp);(root/'gifs').mkdir(); files=[]
            for i in range(21):
                path=f'gifs/face{i}.gif';data=b'GIF89a'+struct.pack('<HH',240,240)+b'\x80\0\0'+bytes([i])
                (root/path).write_bytes(data)
                blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
                files.append({'path':path,'bytes':len(data),'git_blob_sha1':blob})
            manifest=root/'manifest.json'
            manifest.write_text(json.dumps({'commit':'970cf66906d7c30059faa2704e7002f06b8c3619','files':files}))
            original=image(); output,report=assets.repack(original,root,manifest)
            before,raw,_=assets.parse(original); after,newraw,_=assets.parse(output)
            self.assertEqual(before[0],after[0]);self.assertEqual(raw,newraw[:len(raw)])
            self.assertEqual(len(output)%4096,0);self.assertEqual(len(after),22)
            self.assertTrue(report['original_index_json_unchanged'])
            indexed_only=image(); original=indexed_only+b'\x12'*(2097152-len(indexed_only))
            review={'original_image_sha256':assets.sha(original),'original_used_bytes':len(indexed_only),
                'no_reachable_tail_consumers':True,'code_evidence':['synthetic fixture: indexed-only consumer']}
            output,report=assets.repack(original,root,manifest,review)
            self.assertEqual(output[report['used_bytes']:],original[report['used_bytes']:len(output)])
            self.assertTrue(report['all_bytes_after_new_used_preserved'])
            self.assertGreater(report['unindexed_replaced_nonff_bytes'],0)
            with self.assertRaisesRegex(ValueError,'unindexed tail'):assets.repack(original,root,manifest)
            review['original_image_sha256']='bad'
            with self.assertRaisesRegex(ValueError,'fingerprint'):assets.repack(original,root,manifest,review)
            (root/files[0]['path']).write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError,'fingerprint'):assets.repack(indexed_only,root,manifest)

    def test_bad_checksum(self):
        data=bytearray(image());data[5]^=1
        with self.assertRaisesRegex(ValueError,'checksum'):assets.parse(data)
    def test_unindexed_tail_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'unindexed tail'):assets.parse(image()+b'private')
        assets.parse(image()+b'\xff'*100)
    def test_invalid_bounds(self):
        with self.assertRaisesRegex(ValueError,'bounds'):assets.parse(struct.pack('<III',4000,0,0))
    def test_invalid_magic(self):
        with self.assertRaisesRegex(ValueError,'magic'):assets.parse(image(payload=b'XXdata'))
    def test_duplicate_names(self):
        item=assets.ENTRY.pack(b'index.json',4,0,0,0)
        body=item+item+b'ZZdata'
        data=struct.pack('<III',2,sum(body)&65535,len(body))+body
        with self.assertRaisesRegex(ValueError,'duplicate'):assets.parse(data)

if __name__=='__main__':unittest.main()
