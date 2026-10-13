"""检验可审计增量补丁身份与纯模型副本一致性，不读取设备或外部 SDK。"""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'firmware/smartring_plus'


def test_motion_patch_and_header_identity():
    metadata = json.loads((ROOT / 'experiments/0013-continuous-round-face.json').read_text(encoding='utf-8'))
    patch_bytes = (ROOT / 'patches/0013-continuous-round-face.patch').read_bytes().replace(b'\r\n', b'\n')
    header = (ROOT / 'motion/round_face_motion.h').read_bytes().replace(b'\r\n', b'\n')
    assert hashlib.sha256(patch_bytes).hexdigest() == metadata['source']['patch_sha256']
    assert hashlib.sha256(header).hexdigest() == metadata['source']['motion_header_sha256']
    marker = 'diff --git a/main/boards/viewe-smartring-plus/round_face_motion.h b/main/boards/viewe-smartring-plus/round_face_motion.h\n'
    added = patch_bytes.decode().split(marker)[1]
    reconstructed = ''.join(line[1:] for line in added.splitlines(keepends=True)
                            if line.startswith('+') and not line.startswith('+++'))
    assert reconstructed.encode() == header
    assert patch_bytes.decode().count('diff --git ') == 2


def test_motion_preview_has_explicit_simulation_and_accessibility():
    preview = (ROOT / 'motion/preview.html').read_text(encoding='utf-8')
    assert '电脑模拟 · 尚未烧录设备' in preview
    assert "prefers-reduced-motion:reduce" in preview
    assert 'aria-pressed=' in preview
    for state in ('idle', 'listening', 'thinking', 'speaking', 'error'):
        assert f'data-state="{state}"' in preview
    for emotion in ('neutral', 'happy', 'concerned'):
        assert f'data-emotion="{emotion}"' in preview
    assert 'fetch(' not in preview
    assert 'https://' not in preview
