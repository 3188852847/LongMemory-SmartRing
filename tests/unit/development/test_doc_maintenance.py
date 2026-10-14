"""文档机制使用合成工程验证，不读取私有资料或连接日用服务。"""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("project_doc_checker", ROOT / "scripts/development/check_docs.py")
checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = checker
SPEC.loader.exec_module(checker)


def write(root, path, text=""):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def entry(path, status="current"):
    return {"path": path, "title": path, "status": status, "basis": "合成文档用途明确", "review": {"state": "pending"}}


def manifest(documents, topics=None):
    return {"schema_version": 1, "documents": documents, "topics": topics or [], "old_path_rules": [{"id": "old-runtime", "tokens": ["D:\\OldRuntime"], "replacement": "local/runtime/"}]}


def test_source_imports_belong_to_current_worktree():
    import longmemory

    assert Path(longmemory.__file__).resolve().is_relative_to(ROOT / "src")
    assert Path(checker.__file__).resolve().is_relative_to(ROOT)


def test_existing_encoded_parentheses_title_reference_html_and_root_links(tmp_path):
    write(tmp_path, "docs/目标 (一).md", "# 目标\n")
    write(tmp_path, "README.md", "# 根入口\n")
    text = '''[编码](%E7%9B%AE%E6%A0%87%20%28%E4%B8%80%29.md#标题 "说明")
[括号](目标 (一).md)
![图片引用][目标]
[目标]: <目标 (一).md> "title"
<a href="/README.md">首页</a>
[仅锚点](#当前标题)
[网络](https://example.invalid/no-network)
'''
    assert checker.check_links(tmp_path, "docs/index.md", text, "current") == []


def test_code_examples_and_comments_are_not_links(tmp_path):
    text = '''`[例子](absent.md)`
```markdown
[例子](absent.md)
```
~~~
[例子](absent.md)
~~~
<!-- [例子](absent.md)
[例子](also-absent.md) -->
[真的](absent.md)
'''
    findings = checker.check_links(tmp_path, "docs/index.md", text, "current")
    assert [(f.code, f.line) for f in findings] == [("missing-link", 10)]


def test_missing_reference_and_file_are_errors_but_history_is_preserved(tmp_path):
    text = "[缺失](missing.md)\n[标签][unknown]\n"
    current = checker.check_links(tmp_path, "docs/index.md", text, "current")
    historical = checker.check_links(tmp_path, "docs/index.md", text, "historical")
    assert {f.code for f in current} == {"missing-link", "missing-reference"}
    assert {f.severity for f in current} == {"error"}
    assert {f.severity for f in historical} == {"note"}


def test_private_external_and_escape_targets_are_never_opened_or_statted(tmp_path, monkeypatch):
    original_exists = Path.exists
    original_read = Path.read_text
    original_symlink = Path.is_symlink

    def forbidden_if_private(path, function, *args, **kwargs):
        if path.is_relative_to(tmp_path) and any(part in {"local", "data", ".venv"} for part in path.relative_to(tmp_path).parts):
            raise AssertionError("不应检查私有路径：" + str(path))
        return function(path, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", lambda p: forbidden_if_private(p, original_exists))
    monkeypatch.setattr(Path, "read_text", lambda p, *a, **kw: forbidden_if_private(p, original_read, *a, **kw))
    monkeypatch.setattr(Path, "is_symlink", lambda p: forbidden_if_private(p, original_symlink))
    text = '''[配置](../local/config/secret.md)
[数据库](/data/databases/private.db)
[外部](../../outside.md)
[绝对](<D:\\private\\file.md>)
[虚拟环境](../.venv/secret.md)
'''
    findings = checker.check_links(tmp_path, "docs/index.md", text, "current")
    assert [f.code for f in findings] == ["private-or-external-target", "private-or-external-target", "outside-repository", "external-path", "private-or-external-target"]


def test_symlink_boundary_rejected_before_checking_child(tmp_path, monkeypatch):
    # Windows 普通账户可能不能创建符号链接；模拟目录联接的元数据。
    linked = tmp_path / "docs" / "linked"
    descendant = linked / "secret.md"
    original = Path.is_junction

    def junction(path):
        assert path != descendant, "拒绝联接后不能再查询内部目标"
        return path == linked or original(path)

    monkeypatch.setattr(Path, "is_junction", junction)
    assert checker.public_path(tmp_path, "docs/linked/secret.md") is None


def test_old_paths_include_commands_without_printing_body_and_date_does_not_change_status():
    text = "```\nD:\\OldRuntime\\secret-name SECRET_BODY\n```\n"
    rules = manifest([])["old_path_rules"]
    current = checker.check_old_paths("docs/current-20000101.md", text, "current", rules)
    old = checker.check_old_paths("docs/archive-20990101.md", text, "historical", rules)
    assert current[0].severity == "warning"
    assert old[0].severity == "note"
    assert current[0].line == 2
    assert "SECRET_BODY" not in current[0].detail


def test_only_public_env_examples_are_checked(tmp_path):
    write(tmp_path, "config/examples/.env.doubao.example", "SYNTHETIC_EXAMPLE=\n")
    findings = checker.check_links(tmp_path, "docs/index.md", "[模板](../config/examples/.env.doubao.example)\n[私有](../config/examples/.env.doubao.local)\n", "current")
    assert [f.code for f in findings] == ["private-or-external-target"]


def test_inventory_reports_new_documents_and_invalid_authority(tmp_path):
    write(tmp_path, "docs/a.md")
    write(tmp_path, "docs/new.md")
    data = manifest([entry("docs/a.md"), entry("docs/a.md"), entry("docs/absent.md")], [{"id": "task", "authority": "docs/missing.md", "sources": []}, {"id": "task", "authority": "docs/a.md", "sources": []}])
    codes = {f.code for f in checker.check_manifest(tmp_path, data)}
    assert codes == {"duplicate-document", "missing-document", "unlisted-document", "missing-authority", "duplicate-topic"}


def test_verified_and_replacement_claims_require_evidence(tmp_path):
    write(tmp_path, "docs/a.md")
    write(tmp_path, "docs/b.md")
    first = entry("docs/a.md", "superseded")
    first["review"] = {"state": "verified"}
    data = manifest([first, entry("docs/b.md")])
    assert {f.code for f in checker.check_manifest(tmp_path, data)} == {"review-evidence", "replacement-required"}
    first["review"].update(date="2026-10-14", scope="合成范围", evidence="合成测试")
    first["superseded_by"] = [{"path": "docs/b.md", "scope": "只有启动边界", "evidence": "明确的新决定"}]
    assert checker.check_manifest(tmp_path, data) == []


def test_impacts_are_deduplicated_and_unknown_changes_remain_visible():
    data = manifest([], [{"id": "voice", "scope": "声音", "authority": "docs/voice.md", "sources": ["src/voice/**"], "related": ["docs/shared.md"]}, {"id": "ui", "scope": "界面", "authority": "docs/ui.md", "sources": ["src/voice/panel.py"], "related": ["docs/shared.md"]}])
    report = checker.affected_documents(data, ["src\\voice\\panel.py", "src/voice/deep/model.py", "new/path.py"])
    assert report["unmapped"] == ["new/path.py"]
    shared = next(d for d in report["documents"] if d["path"] == "docs/shared.md")
    assert shared["topics"] == ["ui", "voice"]
    assert shared["changed"] == ["src/voice/deep/model.py", "src/voice/panel.py"]


def test_query_only_reads_manifest_and_audit_does_not_write(tmp_path, capsys, monkeypatch):
    write(tmp_path, "docs/a.md", "[正常](a.md)\n")
    write(tmp_path, "docs/historical.md", "[旧链接](gone.md)\nD:\\OldRuntime\n")
    data = manifest([entry("docs/a.md"), entry("docs/historical.md", "historical")], [{"id": "启动", "scope": "启动窗口", "authority": "docs/a.md", "sources": ["src/panel.py"], "related": []}])
    write(tmp_path, "src/panel.py")
    write(tmp_path, "docs/documentation-manifest.json", json.dumps(data))
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    original_read = Path.read_text

    def manifest_only(path, *args, **kwargs):
        assert path.name == "documentation-manifest.json", "检索不得读取所有文档正文"
        return original_read(path, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "read_text", manifest_only)
        assert checker.main(["--root", str(tmp_path), "--query", "启动", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["topics"][0]["authority"] == "docs/a.md"
    assert checker.main(["--root", str(tmp_path), "--strict", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["checked_documents"] == 2
    after = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after


def test_cli_exit_codes_and_only_selection(tmp_path, capsys):
    write(tmp_path, "docs/a.md", "[失效](gone.md)\nD:\\OldRuntime\n")
    write(tmp_path, "docs/documentation-manifest.json", json.dumps(manifest([entry("docs/a.md")])))
    assert checker.main(["--root", str(tmp_path), "--json"]) == 1
    capsys.readouterr()
    assert checker.main(["--root", str(tmp_path), "--only", "docs/unknown.md", "--json"]) == 1
    assert any(f["code"] == "unknown-selection" for f in json.loads(capsys.readouterr().out)["findings"])
    assert checker.main(["--root", str(tmp_path), "--changed", "unknown.py", "--strict", "--json"]) == 1
    capsys.readouterr()
    assert checker.main(["--root", str(tmp_path), "--manifest", "../private.json"]) == 2
    capsys.readouterr()
    write(tmp_path, "docs/a.md", "D:\\OldRuntime\n")
    assert checker.main(["--root", str(tmp_path), "--json"]) == 0
    capsys.readouterr()
    assert checker.main(["--root", str(tmp_path), "--strict", "--json"]) == 1


def test_git_diff_is_read_only_and_includes_tracked_worktree_changes(tmp_path):
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    write(tmp_path, "src/panel.py", "original\n")
    subprocess.run(["git", "add", "src/panel.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid", "commit", "--quiet", "-m", "synthetic"], cwd=tmp_path, check=True)
    write(tmp_path, "src/panel.py", "changed\n")
    write(tmp_path, "src/untracked.py")
    assert checker.git_changes(tmp_path, "HEAD") == ["src/panel.py"]
    (tmp_path / "src/panel.py").rename(tmp_path / "src/renamed.py")
    subprocess.run(["git", "add", "src/panel.py", "src/renamed.py"], cwd=tmp_path, check=True)
    assert checker.git_changes(tmp_path, "HEAD") == ["src/panel.py", "src/renamed.py"]
    with pytest.raises(ValueError):
        checker.git_changes(tmp_path, "--help")
