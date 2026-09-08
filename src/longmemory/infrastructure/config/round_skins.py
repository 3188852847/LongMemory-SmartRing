"""SmartRing-Plus 圆屏皮肤档案。

首版只接受仓库内经过审查的声明式 JSON。它既不执行代码，也不接收任意 URL；
这样控制台可以先稳定皮肤契约，而不会把上游单分区 assets OTA 冒充成安全热更新。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re


_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,39}$")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_ROOT_KEYS = {"schema_version", "id", "name", "description", "target", "palette", "face", "motion"}
_TARGET_KEYS = {"board", "width", "height", "color_format", "skin_api"}
_PALETTE_KEYS = {"background", "background_edge", "foreground", "muted", "accent", "warning", "error", "charging"}
_FACE_KEYS = {"eye_width", "eye_height", "mouth_width"}
_MOTION_KEYS = {"blink_seconds", "speaking_seconds"}


def _exact_keys(value: object, expected: set[str], code: str) -> dict:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(code)
    return value


def _integer(value: object, minimum: int, maximum: int, code: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(code)
    return value


def validate_skin_manifest(value: object) -> dict:
    """验证可映射到固定 LVGL 控件的有限参数，不接受开放式样式或资源引用。"""
    root = _exact_keys(value, _ROOT_KEYS, "invalid_skin_manifest")
    if root["schema_version"] != 1 or not isinstance(root["id"], str) or not _ID.fullmatch(root["id"]):
        raise ValueError("invalid_skin_identity")
    if not isinstance(root["name"], str) or not 1 <= len(root["name"].strip()) <= 30:
        raise ValueError("invalid_skin_name")
    if not isinstance(root["description"], str) or not 1 <= len(root["description"].strip()) <= 120:
        raise ValueError("invalid_skin_description")

    target = _exact_keys(root["target"], _TARGET_KEYS, "invalid_skin_target")
    if target != {"board": "viewe-smartring-plus", "width": 360, "height": 360,
                  "color_format": "RGB565", "skin_api": 1}:
        raise ValueError("unsupported_skin_target")

    palette = _exact_keys(root["palette"], _PALETTE_KEYS, "invalid_skin_palette")
    if any(not isinstance(color, str) or not _COLOR.fullmatch(color) for color in palette.values()):
        raise ValueError("invalid_skin_color")

    face = _exact_keys(root["face"], _FACE_KEYS, "invalid_skin_face")
    _integer(face["eye_width"], 12, 36, "invalid_skin_face")
    _integer(face["eye_height"], 18, 48, "invalid_skin_face")
    _integer(face["mouth_width"], 20, 64, "invalid_skin_face")

    motion = _exact_keys(root["motion"], _MOTION_KEYS, "invalid_skin_motion")
    for key, minimum, maximum in (("blink_seconds", 2.0, 12.0), ("speaking_seconds", 0.25, 1.5)):
        item = motion[key]
        if type(item) not in {int, float} or not minimum <= float(item) <= maximum:
            raise ValueError("invalid_skin_motion")
    return root


class RoundSkinStore:
    """读取版本控制内置皮肤，并原子保存不含密钥的预览选择。"""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.skin_root = self.root / "firmware/smartring_plus/skins"
        self.selection_path = self.root / "data/control/round-skin-selection.json"

    def _skins(self) -> list[dict]:
        skins = []
        ids: set[str] = set()
        for path in sorted(self.skin_root.glob("*.skin.json")):
            raw = path.read_bytes()
            value = validate_skin_manifest(json.loads(raw.decode("utf-8")))
            if value["id"] in ids:
                raise ValueError("duplicate_skin_id")
            ids.add(value["id"])
            skins.append({**value, "manifest_sha256": hashlib.sha256(raw).hexdigest()})
        if not skins:
            raise ValueError("missing_round_skins")
        return skins

    def selected(self) -> str:
        skins = {item["id"] for item in self._skins()}
        try:
            body = json.loads(self.selection_path.read_text(encoding="utf-8"))
            selected = body.get("selected_skin") if isinstance(body, dict) else None
        except (OSError, ValueError, TypeError):
            selected = None
        default = "rose-night-v1" if "rose-night-v1" in skins else sorted(skins)[0]
        return selected if selected in skins else default

    def describe(self) -> dict:
        return {
            "selected_skin": self.selected(),
            "skins": self._skins(),
            "delivery": {
                "console_preview": True,
                "upstream_assets_ota_detected": True,
                "device_apply_supported": False,
                "reason": "firmware_skin_loader_missing",
                "known_firmware_baseline": "round-face-0004",
            },
        }

    def select(self, skin_id: str) -> dict:
        if skin_id not in {item["id"] for item in self._skins()}:
            raise ValueError("unknown_round_skin")
        body = {"version": 1, "selected_skin": skin_id}
        self.selection_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.selection_path.with_name(f".{self.selection_path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.selection_path)
        finally:
            temporary.unlink(missing_ok=True)
        return self.describe()
