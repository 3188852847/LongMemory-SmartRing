# 现行文档整理前快照

这些文件保存整理前的完整正文，属于历史语境，不作为今天的操作命令或执行授权。
来源提交：`8f32727632d98ddcd3890181286a0f310622a97b`。

原文 SHA-256、长度、快照 SHA-256 和逐处链接重定位记录见 [manifest.json](manifest.json)。
原文以该提交的 Git blob 字节为准；Windows 工作树换行不作为原文身份。
只重定位代码块以外的相对 Markdown 链接，包内目标指向相应快照，其他目标仍指向同一仓库文件；不改历史代码、路径、数字或措辞。
按每个文件 `relocations` 的逆序，用 `archive_offset`（UTF-8 解码后 Python 字符串的字符偏移，非字节偏移）将 `relocated` 替回 `original`，UTF-8 编码后的 SHA-256 必须等于 `source_sha256`，并与 `git show <source_commit>:<source>` 逐字节一致。八份快照均已执行这一验证。

## 重复核验

在仓库根用已有 Python 执行下列标准库代码；只读文件和 Git 对象，不部署旧文或写数据：

```python
from pathlib import Path
import hashlib, json, subprocess
root = Path.cwd()
manifest = json.loads((root / 'docs/history/current-docs-before-20261014/manifest.json').read_text(encoding='utf-8'))
for item in manifest['files']:
    snapshot = (root / item['archive']).read_bytes()
    assert hashlib.sha256(snapshot).hexdigest() == item['archive_sha256']
    original = snapshot.decode('utf-8')
    for edit in reversed(item['relocations']):
        at = edit['archive_offset']
        assert original[at:at + len(edit['relocated'])] == edit['relocated']
        original = original[:at] + edit['original'] + original[at + len(edit['relocated']):]
    raw = original.encode('utf-8')
    assert hashlib.sha256(raw).hexdigest() == item['source_sha256']
    expected = subprocess.run(['git', 'show', f"{manifest['source_commit']}:{item['source']}"], check=True, capture_output=True).stdout
    assert raw == expected
print('8 snapshots: original SHA-256 and Git bytes verified')
```

| 原入口 | 完整快照 |
|---|---|
| 协作规则 | [AGENTS](AGENTS.md) |
| 使用说明 | [使用说明](docs/guides/使用说明.md) |
| 统一启动 | [统一启动](docs/guides/统一启动.md) |
| 本机布局 | [本机目录与依赖](docs/guides/本机目录与依赖.md) |
| 声音 | [声音设置](docs/guides/声音设置.md) |
| 架构 | [overview](docs/architecture/overview.md) |
| 流程 | [workflows](docs/architecture/workflows.md) |
| 仓库边界 | [repository-structure](docs/architecture/repository-structure.md) |

现行入口保留已发现的入站锚点“主动交流设置”和“首次使用人工纠正前显式升级-v3-日常库”；后者只指向历史迁移说明，不能按旧 V3→V4 示例迁移今天的日用库。
主会话负责把本快照登记到历史索引。本轮未重写历史 ADR、研究或测量文件。
