"""SmartRing-Plus 圆屏皮肤档案。

内置皮肤来自版本库；本机还可保存一份由受限字段生成的自定义皮肤。两者都不执行
代码，也不接收任意 URL，避免把上游单分区 assets OTA 冒充成安全热更新。
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
_PALETTE_KEYS = {
    "background", "background_edge", "foreground", "muted", "accent",
    "listening", "thinking", "happy", "concerned", "warning", "error", "charging",
}
_FACE_KEYS = {"eye_width", "eye_height", "mouth_width"}
_MOTION_KEYS = {"blink_seconds", "speaking_seconds"}
_DEVICE_PALETTE_KEYS = (
    "background", "foreground", "muted", "accent", "listening", "thinking",
    "happy", "concerned", "error",
)
_CUSTOM_SKIN_ID = "local-custom-v1"


class RoundSkinConflict(ValueError):
    """另一个页面已改写本机自定义皮肤，拒绝用陈旧草稿覆盖。"""


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
    """读取内置/本机皮肤，并原子保存不含密钥的预览配置。"""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.skin_root = self.root / "firmware/smartring_plus/skins"
        self.selection_path = self.root / "local/config/display/round-skin-selection.json"
        self.custom_skin_path = self.root / "local/config/display/round-skin-custom.skin.json"

    @staticmethod
    def _read_skin(path: Path) -> dict:
        raw = path.read_bytes()
        value = validate_skin_manifest(json.loads(raw.decode("utf-8")))
        return {**value, "manifest_sha256": hashlib.sha256(raw).hexdigest()}

    def _skins(self) -> list[dict]:
        skins = []
        ids: set[str] = set()
        for path in sorted(self.skin_root.glob("*.skin.json")):
            value = self._read_skin(path)
            if value["id"] in ids:
                raise ValueError("duplicate_skin_id")
            ids.add(value["id"])
            skins.append(value)
        if not skins:
            raise ValueError("missing_round_skins")
        if self.custom_skin_path.exists():
            custom = self._read_skin(self.custom_skin_path)
            if custom["id"] != _CUSTOM_SKIN_ID or custom["id"] in ids:
                raise ValueError("invalid_custom_round_skin")
            skins.append(custom)
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
            "custom_skin_id": _CUSTOM_SKIN_ID,
            "delivery": {
                "console_preview": True,
                "upstream_assets_ota_detected": True,
                "device_apply_supported": False,
                "device_delivery_implemented": True,
                "reason": "device_capability_probe_required",
                "known_firmware_baseline": "round-face-0004",
            },
        }

    def save_custom(self, value: object) -> dict:
        """从已校验皮肤派生唯一的本机草稿，只开放真机当前能表达的字段。"""
        body = _exact_keys(
            value,
            {"base_skin_id", "expected_manifest_sha256", "palette", "face"},
            "invalid_custom_skin",
        )
        if not isinstance(body["base_skin_id"], str):
            raise ValueError("invalid_custom_skin")
        expected = body["expected_manifest_sha256"]
        if expected is not None and (
            not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None
        ):
            raise ValueError("invalid_custom_skin")
        palette = _exact_keys(body["palette"], set(_DEVICE_PALETTE_KEYS), "invalid_custom_skin")
        if any(not isinstance(color, str) or _COLOR.fullmatch(color) is None for color in palette.values()):
            raise ValueError("invalid_custom_skin")
        face = _exact_keys(body["face"], _FACE_KEYS, "invalid_custom_skin")
        _integer(face["eye_width"], 12, 36, "invalid_custom_skin")
        _integer(face["eye_height"], 18, 48, "invalid_custom_skin")
        _integer(face["mouth_width"], 20, 64, "invalid_custom_skin")

        skins = self._skins()
        matches = [item for item in skins if item["id"] == body["base_skin_id"]]
        if len(matches) != 1:
            raise ValueError("unknown_round_skin")
        current = next((item for item in skins if item["id"] == _CUSTOM_SKIN_ID), None)
        current_hash = current["manifest_sha256"] if current else None
        if expected != current_hash:
            raise RoundSkinConflict("custom_round_skin_conflict")

        base = matches[0]
        manifest = {
            "schema_version": 1,
            "id": _CUSTOM_SKIN_ID,
            "name": "我的自定义皮肤",
            "description": "由本机控制台受限参数编辑器生成；不包含脚本、URL 或外部资源。",
            "target": dict(base["target"]),
            "palette": {**base["palette"], **palette},
            "face": dict(face),
            "motion": dict(base["motion"]),
        }
        validate_skin_manifest(manifest)
        serialized = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        self.custom_skin_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.custom_skin_path.with_name(f".{self.custom_skin_path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(serialized, encoding="utf-8")
            temporary.replace(self.custom_skin_path)
        finally:
            temporary.unlink(missing_ok=True)
        return self.describe()

    def device_payload(self, skin_id: str) -> dict:
        """生成 skin_api=1 的固件子集；浏览器动画和渐变边缘不冒充设备能力。"""
        matches = [item for item in self._skins() if item["id"] == skin_id]
        if len(matches) != 1:
            raise ValueError("unknown_round_skin")
        skin = matches[0]
        return {
            "skin_api": 1,
            "skin_id": skin["id"],
            "manifest_sha256": skin["manifest_sha256"],
            **{key: int(skin["palette"][key][1:], 16) for key in _DEVICE_PALETTE_KEYS},
            **skin["face"],
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
