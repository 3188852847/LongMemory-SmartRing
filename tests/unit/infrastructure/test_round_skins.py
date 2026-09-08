import json

import pytest

from longmemory.infrastructure.config.round_skins import (
    RoundSkinConflict,
    RoundSkinStore,
    validate_skin_manifest,
)


def _manifest(skin_id="test-skin-v1"):
    return {
        "schema_version": 1, "id": skin_id, "name": "测试皮肤", "description": "仅用于合成验证。",
        "target": {"board": "viewe-smartring-plus", "width": 360, "height": 360,
                   "color_format": "RGB565", "skin_api": 1},
        "palette": {key: "#112233" for key in (
            "background", "background_edge", "foreground", "muted", "accent", "listening", "thinking",
            "happy", "concerned", "warning", "error", "charging")},
        "face": {"eye_width": 22, "eye_height": 36, "mouth_width": 38},
        "motion": {"blink_seconds": 5.4, "speaking_seconds": 0.52},
    }


def test_round_skin_store_validates_and_persists_only_known_selection(tmp_path):
    skin_root = tmp_path / "firmware/smartring_plus/skins"
    skin_root.mkdir(parents=True)
    (skin_root / "test.skin.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    store = RoundSkinStore(tmp_path)

    assert store.selected() == "test-skin-v1"
    result = store.select("test-skin-v1")
    assert result["delivery"]["device_apply_supported"] is False
    assert len(result["skins"][0]["manifest_sha256"]) == 64
    assert json.loads(store.selection_path.read_text(encoding="utf-8")) == {
        "version": 1, "selected_skin": "test-skin-v1"
    }
    with pytest.raises(ValueError, match="unknown_round_skin"):
        store.select("unknown-skin")

    payload = store.device_payload("test-skin-v1")
    assert payload == {
        "skin_api": 1, "skin_id": "test-skin-v1", "manifest_sha256": payload["manifest_sha256"],
        "background": 0x112233, "foreground": 0x112233, "muted": 0x112233,
        "accent": 0x112233, "listening": 0x112233, "thinking": 0x112233,
        "happy": 0x112233, "concerned": 0x112233, "error": 0x112233,
        "eye_width": 22, "eye_height": 36, "mouth_width": 38,
    }
    assert len(payload["manifest_sha256"]) == 64


def test_round_skin_manifest_rejects_open_ended_fields_and_unsupported_target():
    invalid = _manifest()
    invalid["script"] = "alert(1)"
    with pytest.raises(ValueError, match="invalid_skin_manifest"):
        validate_skin_manifest(invalid)
    invalid = _manifest()
    invalid["target"]["width"] = 466
    with pytest.raises(ValueError, match="unsupported_skin_target"):
        validate_skin_manifest(invalid)


def test_round_skin_store_generates_one_strict_local_custom_skin_with_conflict_guard(tmp_path):
    skin_root = tmp_path / "firmware/smartring_plus/skins"
    skin_root.mkdir(parents=True)
    (skin_root / "test.skin.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    store = RoundSkinStore(tmp_path)
    body = {
        "base_skin_id": "test-skin-v1",
        "expected_manifest_sha256": None,
        "palette": {key: "#224466" for key in (
            "background", "foreground", "muted", "accent", "listening",
            "thinking", "happy", "concerned", "error",
        )},
        "face": {"eye_width": 24, "eye_height": 38, "mouth_width": 44},
    }

    result = store.save_custom(body)
    custom = next(item for item in result["skins"] if item["id"] == "local-custom-v1")
    assert custom["palette"]["background"] == "#224466"
    assert custom["palette"]["background_edge"] == "#112233"
    assert custom["face"] == body["face"]
    assert custom["motion"] == _manifest()["motion"]
    assert store.custom_skin_path.is_file()
    payload = store.device_payload("local-custom-v1")
    assert payload["background"] == 0x224466
    assert payload["manifest_sha256"] == custom["manifest_sha256"]

    with pytest.raises(RoundSkinConflict, match="custom_round_skin_conflict"):
        store.save_custom(body)
    body["expected_manifest_sha256"] = custom["manifest_sha256"]
    body["face"]["eye_width"] = 26
    updated = store.save_custom(body)
    assert next(item for item in updated["skins"] if item["id"] == "local-custom-v1")["face"]["eye_width"] == 26

    invalid = dict(body)
    invalid["palette"] = {**body["palette"], "script": "#112233"}
    with pytest.raises(ValueError, match="invalid_custom_skin"):
        store.save_custom(invalid)
