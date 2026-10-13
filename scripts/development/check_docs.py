"""只读文档检查与任务检索；仅使用标准库，不访问网络、配置或个人数据。"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import fnmatch
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit


STATUSES = {"current", "reference", "historical", "draft", "pending", "superseded"}
# 只允许检查公开工程内容。引用私有目录只报告边界，不 stat、不读取目标。
PUBLIC_DIRS = {"docs", "src", "scripts", "tests", "config", "datasets", "firmware", "web", "assets", "notebooks", ".agents", ".github"}
PRIVATE_PARTS = {"local", "data", "experiments", ".git", ".venv", "node_modules", "dist", "build", "managed_components", "__pycache__"}
ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    path: str
    line: int
    detail: str


def public_path(root: Path, relative: str) -> Path | None:
    """先检查词法边界，再 resolve 联接/符号链接，避免沿链接进入私有目录。"""
    name = relative.replace("\\", "/")
    parts = PurePosixPath(name).parts
    if not parts or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return None
    if ".." in parts or (len(parts) > 1 and parts[0] not in PUBLIC_DIRS):
        return None
    if any(part in PRIVATE_PARTS for part in parts):
        return None
    if any(part.startswith(".env") for part in parts) and not (
        parts[:2] == ("config", "examples")
        and len(parts) == 3
        and (parts[-1] == ".env.example" or parts[-1].endswith(".example"))
    ):
        return None
    candidate = root.joinpath(*parts)
    # 不跟随目录联接，即便最终目标仍在仓库内；公开文档不应依赖本机联接。
    for parent in reversed([candidate, *candidate.parents]):
        if parent == root or root not in parent.parents:
            continue
        if parent.is_symlink() or parent.is_junction():
            return None
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def visible_lines(text: str):
    """忽略围栏代码、行内代码与 HTML 注释，但保留原行号。"""
    text = re.sub(r"<!--.*?-->", lambda m: "\n" * m[0].count("\n"), text, flags=re.S)
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
            yield number, ""
        elif fence:
            yield number, ""
        else:
            yield number, re.sub(r"(`+).*?\1", "", line)


def destination(value: str) -> str:
    value = value.strip()
    if value.startswith("<"):
        end = value.find(">")
        return value[1:end] if end != -1 else value
    # Markdown 可选 title 不属于文件路径。
    return re.sub(r'''\s+(?:"[^"]*"|'[^']*'|\([^)]*\))\s*$''', "", value).strip()


def links(text: str):
    """支持常见行内/图片/引用式链接、HTML href/src 和尖括号链接。

    不作为完整 CommonMark 解析器：跨行标签与动态模板表达式需人工检查。
    平衡括号允许文件名中带括号，不把代码示例当作可执行文档链接。
    """
    lines = list(visible_lines(text))
    definitions = {}
    for number, line in lines:
        match = re.match(r"^\s{0,3}\[([^]]+)\]:\s*(.+)$", line)
        if match:
            definitions[match[1].casefold()] = destination(match[2])
    for number, line in lines:
        if re.match(r"^\s{0,3}\[[^]]+\]:", line):
            continue
        used = []
        for match in re.finditer(r"!?\[([^]\n]*)\]\(", line):
            start = match.end()
            depth, end, angle = 1, start, False
            while end < len(line) and depth:
                character = line[end]
                if character == "\\":
                    end += 2
                    continue
                if character == "<":
                    angle = True
                elif character == ">":
                    angle = False
                elif not angle and character == "(":
                    depth += 1
                elif not angle and character == ")":
                    depth -= 1
                end += 1
            if depth == 0:
                used.append((match.start(), end))
                yield number, destination(line[start:end - 1])
        for match in re.finditer(r"!?\[([^]\n]+)\](?:\[([^]\n]*)\])?", line):
            if any(start <= match.start() < end for start, end in used):
                continue
            key = (match[2] or match[1]).casefold()
            if key in definitions:
                yield number, definitions[key]
            elif match[2] is not None:
                yield number, "reference-missing:" + key
        for match in re.finditer(r'''(?:href|src)\s*=\s*["']([^"']+)["']''', line):
            yield number, match[1]
        for match in re.finditer(r"<([^<>\s]+)>", line):
            if any(start <= match.start() < end for start, end in used):
                continue
            if not re.match(r"/?[a-zA-Z][a-zA-Z0-9-]*$", match[1]):
                yield number, match[1]


def load_manifest(root: Path, relative="docs/documentation-manifest.json") -> dict:
    path = public_path(root, relative)
    if path is None:
        raise ValueError("清单必须位于公开工程目录内")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def inventory(root: Path) -> set[str]:
    """仅遍历 docs；不扫描 local/data/实验结果，也不跟随目录联接。"""
    result = set()
    queue = [root / "docs"]
    while queue:
        directory = queue.pop()
        if not directory.is_dir() or directory.is_symlink() or directory.is_junction():
            continue
        for child in directory.iterdir():
            if child.is_symlink() or child.is_junction():
                continue
            if child.is_dir():
                queue.append(child)
            elif child.suffix.lower() == ".md":
                result.add(child.relative_to(root).as_posix())
    return result


def check_manifest(root: Path, manifest: dict) -> list[Finding]:
    findings = []
    documents = manifest.get("documents", [])
    paths = [entry["path"] for entry in documents]
    for path, count in Counter(paths).items():
        if count != 1:
            findings.append(Finding("error", "duplicate-document", path, 0, "清单路径重复"))
    if manifest.get("schema_version") != 1:
        findings.append(Finding("error", "manifest-schema", "docs/documentation-manifest.json", 0, "仅支持 schema_version=1"))
    for entry in documents:
        path = entry["path"]
        target = public_path(root, path)
        if target is None or not target.is_file():
            findings.append(Finding("error", "missing-document", path, 0, "清单文件不存在或越过公开目录边界"))
        if entry.get("status") not in STATUSES or not entry.get("basis"):
            findings.append(Finding("error", "document-status", path, 0, "状态非法或缺少分类依据"))
        if entry.get("review", {}).get("state") not in {"pending", "verified"}:
            findings.append(Finding("error", "document-review", path, 0, "缺少核对状态"))
        elif entry["review"]["state"] == "verified" and not all(entry["review"].get(field) for field in ("scope", "evidence", "date")):
            findings.append(Finding("error", "review-evidence", path, 0, "已核对项须有范围、证据与日期"))
        if entry.get("status") == "superseded" and not entry.get("superseded_by"):
            findings.append(Finding("error", "replacement-required", path, 0, "已被替代须标明替代文档与范围"))
        for replacement in entry.get("superseded_by", []):
            if replacement.get("path") not in paths or not replacement.get("scope") or not replacement.get("evidence"):
                findings.append(Finding("error", "replacement-evidence", path, 0, "替代关系须有清单内目标、范围与证据"))
    for path in sorted(inventory(root) - set(paths)):
        findings.append(Finding("warning", "unlisted-document", path, 0, "新增文档尚未登记；不能按目录/日期自动决定状态"))
    topic_ids, scopes = set(), set()
    for topic in manifest.get("topics", []):
        authority = topic["authority"]
        if topic["id"] in topic_ids or (topic.get("scope") and topic["scope"] in scopes):
            findings.append(Finding("error", "duplicate-topic", authority, 0, "同一事实范围存在多份权威入口"))
        topic_ids.add(topic["id"])
        scopes.add(topic.get("scope"))
        if authority not in paths:
            findings.append(Finding("error", "missing-authority", authority, 0, "权威文档未登记"))
        for related in topic.get("related", []):
            if related not in paths:
                findings.append(Finding("error", "missing-related", related, 0, "关联文档未登记"))
        for pattern in topic.get("sources", []):
            # 前缀目录存在即可；不遍历源码/厂商资源或读取正文。
            literal_prefix = re.split(r"[*?[]", pattern, maxsplit=1)[0]
            prefix = literal_prefix.rstrip("/")
            if literal_prefix and not literal_prefix.endswith("/") and prefix != pattern:
                prefix = PurePosixPath(prefix).parent.as_posix()
            target = public_path(root, prefix)
            if target is None or not target.exists():
                findings.append(Finding("warning", "missing-source", authority, 0, f"源码关联前缀不存在：{pattern}"))
    return findings


def check_links(root: Path, path: str, text: str, status: str) -> list[Finding]:
    findings = []
    severity = "note" if status in {"historical", "superseded"} else "error"
    for line, raw in links(text):
        if raw.startswith("reference-missing:"):
            findings.append(Finding(severity, "missing-reference", path, line, raw.split(":", 1)[1]))
            continue
        if re.match(r"^[A-Za-z]:[/\\]", raw) or raw.startswith(("\\\\", "//")):
            findings.append(Finding("note", "external-path", path, line, "本机/外部路径未验证"))
            continue
        parsed = urlsplit(raw)
        if parsed.scheme:
            continue
        name = unquote(parsed.path).replace("\\", "/")
        if not name:
            # 锚点语义由 Markdown 渲染器决定；本轮只检查文件目标。
            continue
        if name.startswith("/"):
            normalized = name.lstrip("/")
        else:
            parts = list(PurePosixPath(path).parent.parts)
            escaped = False
            for part in PurePosixPath(name).parts:
                if part == "..":
                    if parts:
                        parts.pop()
                    else:
                        escaped = True
                elif part != ".":
                    parts.append(part)
            normalized = "/".join(parts)
            if escaped:
                findings.append(Finding("warning", "outside-repository", path, line, raw))
                continue
        target = public_path(root, normalized)
        if target is None:
            findings.append(Finding("note", "private-or-external-target", path, line, "跳过私有/外部/联接目标：" + normalized))
        elif not target.exists():
            findings.append(Finding(severity, "missing-link", path, line, normalized))
    return findings


def check_old_paths(path: str, text: str, status: str, rules: list[dict]) -> list[Finding]:
    # 包括代码块和行内代码：旧命令恰恰经常写在这里。只输出规则 ID，不打印正文。
    findings = []
    for line, content in enumerate(text.splitlines(), 1):
        for rule in rules:
            if any(token.casefold() in content.casefold() for token in rule["tokens"]):
                findings.append(Finding("note" if status in {"historical", "superseded", "reference"} else "warning", "old-path", path, line, f'{rule["id"]} → {rule["replacement"]}；人工判断是否为历史说明'))
    return findings


def affected_documents(manifest: dict, changed: list[str]) -> dict:
    """返回候选复核范围；关联匹配不代表文档必改，也不证明语义一致。"""
    impacts, unmapped = {}, []
    for raw in changed:
        path = raw.replace("\\", "/").removeprefix("./")
        matches = [topic for topic in manifest.get("topics", []) if path == topic["authority"] or any(fnmatch.fnmatchcase(path, pattern) for pattern in topic.get("sources", []))]
        if not matches:
            unmapped.append(path)
        for topic in matches:
            for document in [topic["authority"], *topic.get("related", [])]:
                impact = impacts.setdefault(document, {"path": document, "topics": set(), "changed": set()})
                impact["topics"].add(topic["id"])
                impact["changed"].add(path)
    return {"documents": [{**value, "topics": sorted(value["topics"]), "changed": sorted(value["changed"])} for _, value in sorted(impacts.items())], "unmapped": sorted(set(unmapped))}


def search_documents(manifest: dict, query: str) -> dict:
    query = query.casefold()
    topics = [topic for topic in manifest.get("topics", []) if query in json.dumps(topic, ensure_ascii=False).casefold()]
    selected = {path for topic in topics for path in [topic["authority"], *topic.get("related", [])]}
    documents = [entry for entry in manifest["documents"] if entry["path"] in selected or query in (entry["path"] + " " + entry.get("title", "") + " " + " ".join(entry.get("tags", []))).casefold()]
    return {"topics": topics, "documents": documents}


def git_changes(root: Path, base: str) -> list[str]:
    # argv 不经过 shell；明确拒绝 option 注入。仅查询差异，不修改 Git。
    if base.startswith("-"):
        raise ValueError("base 不得是 Git 选项")
    result = subprocess.run(["git", "diff", "--no-renames", "--name-only", "-z", base, "--"], cwd=root, capture_output=True, check=True)
    return [name for name in result.stdout.decode("utf-8").split("\0") if name]


def audit(root: Path, manifest: dict, only: list[str] | None = None) -> dict:
    findings = check_manifest(root, manifest)
    count = 0
    entries = {entry["path"]: entry for entry in manifest["documents"]}
    for path in sorted(only if only is not None else entries):
        entry = entries.get(path)
        if entry is None:
            findings.append(Finding("error", "unknown-selection", path, 0, "--only 目标不在文档清单"))
            continue
        target = public_path(root, path)
        if target is None or not target.is_file():
            continue
        text = target.read_text(encoding="utf-8-sig")
        count += 1
        findings.extend(check_links(root, path, text, entry["status"]))
        findings.extend(check_old_paths(path, text, entry["status"], manifest.get("old_path_rules", [])))
    return {"checked_documents": count, "status_counts": dict(Counter(entry["status"] for entry in entries.values())), "findings": [asdict(finding) for finding in findings]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--manifest", default="docs/documentation-manifest.json")
    parser.add_argument("--only", action="append", help="只读取指定清单文档；可重复")
    parser.add_argument("--query", help="按任务检索清单，不读所有正文")
    parser.add_argument("--changed", action="append", default=[], help="源码改动路径；可重复")
    parser.add_argument("--base", help="只读 git diff <base>，包含相对该提交的工作树差异")
    parser.add_argument("--json", action="store_true", help="输出机器可读结果到 stdout；不写文件")
    parser.add_argument("--strict", action="store_true", help="warning 也返回失败；note 不失败")
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        manifest = load_manifest(root, args.manifest)
        changed = args.changed + (git_changes(root, args.base) if args.base else [])
        if args.query:
            report = search_documents(manifest, args.query)
        elif changed or args.base:
            report = affected_documents(manifest, changed)
        else:
            report = audit(root, manifest, args.only)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.query:
            for topic in report["topics"]:
                print(f'{topic["id"]}: {topic["authority"]} ({topic["scope"]})')
            for entry in report["documents"]:
                print(f'{entry["status"]} / 语义{entry["review"]["state"]}: {entry["path"]} — {entry["title"]}')
        elif changed or args.base:
            for entry in report["documents"]:
                print(f'{entry["path"]}: {", ".join(entry["topics"])} ← {", ".join(entry["changed"])}')
            for path in report["unmapped"]:
                print(f"未关联，需人工判断: {path}")
        else:
            print(f'检查 {report["checked_documents"]} 份文档；分类 {report["status_counts"]}')
            for finding in report["findings"]:
                print(f'{finding["severity"]} {finding["code"]} {finding["path"]}:{finding["line"]} {finding["detail"]}')
            print("结果统计: " + str(dict(Counter(f["severity"] for f in report["findings"]))))
        failed = {"error", "warning"} if args.strict else {"error"}
        return int(any(f["severity"] in failed for f in report.get("findings", [])) or (args.strict and bool(report.get("unmapped"))))
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        print(f"文档检查未完成：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
