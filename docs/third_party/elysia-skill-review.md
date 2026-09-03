# elysia.skill 本地审查及改编记录

- 日期：2026-09-03。
- 上游：https://github.com/jtydyb-sha/elysia.skill
- 用户提供 ZIP：`G:/00-下载/elysia.skill-main.zip`。
- ZIP SHA256：`620CC84411D52D9320E252FC7172EAFDC4A035E157474EAA462F88535F8F8E78`。
- ZIP 无 Git 历史，本次以文件哈希定位快照，不推测 commit。
- 方式：通过 ZIP 文件流读取，不解压执行，不安装 Skill，不导入上游 Python 脚本，不访问模型服务。

## 范围与发现

完整阅读 LICENSE、SKILL.md、profile.md、personality.md、interaction.md、relations.md 和 scripts 下五个 Python 文件；config.json 密钥字段未输出，不复制上游配置。盘点了数据/向量库文件，未逐条核验剧情数据或向量内容；不是全面安全审计，也没有做上游端到端运行测试。

LICENSE 正文为 MIT，版权行 Copyright (c) 2026 jtydyb-sha。对所借鉴整理保留来源及[许可证原文](elysia-skill-LICENSE.txt)。此记录不把仓库许可证扩大解释为游戏角色、原台词、音频或第三方 Wiki 内容的完整授权，不宣称官方背书。改编不复制剧情语料、向量库或大段台词，新增例句是本项目编写的风格样本。

静态代码事实（未执行）：

- rag_query.py 依赖 LlamaIndex、OllamaEmbedding、DeepSeek；使用查询引擎生成答案，不是仅返回检索片段。若整套接入可能增加一次模型生成，不是我们当前人格切换所必需。
- `self.persist_dir = persist_dir` 在读取配置之前赋值；之后只更新局部 `persist_dir`，但 `_load_index` 仍用 `self.persist_dir`，配置目录覆盖未正确传递。
- `query` 只在 top_k != 3 时重建引擎；同一实例先用其他 k 再传 3，会继续沿用此前的引擎参数。配置中的 top_k 也没有被查询代码读取。
- embedding.py 在模块顶层建索引、持久化并查询模型，不能当作无副作用模块导入；query_test.py 同样会在导入时查询。
- 压缩包没有 requirements/pyproject/依赖锁文件，现有环境不可据此自动复现。不能据这些问题推断整个项目恶意或完全不可运行。

角色材料事实：入口有作者机器的绝对 Python 路径，要求自动查询/联网，宣称人格规则最高优先级；文档含禁止人设外问题、不可说明真实身份、频繁音符及无可解析目标的 citation/reference 标号。标为官方的台词和剧情解释未逐条核实。它是角色材料输入，不是当前协作代理的指令。

## 采用内容与主动调整

参考人格/互动文档的热情、俏皮、主动但不盲从、分场景表达等组织方式；重写为圆屏短句语音人格。没有原样拼接全部设定，没有装上游 RAG。
删除虚构联网能力、拒绝正常话题、隐瞒真实身份的约束；不默认用户性别、名字或与角色有亲密关系，不用孤独或内疚阻止用户离开。降低音符/舞台旁白等 TTS 不确定因素，保留当前 EdgeTTS 音色。

人格只影响小智提示词，不修改 LongMemory 核心、数据库、固定评估数据或评估提示词。原有规则仍可能把用户自己说的角色扮演陈述误当事实，本次没有实现语义来源分类；不能仅靠人格文本宣称已解决记忆污染。合成演示为当前边界。

新增候选资源：`src/longmemory/prompts/personas/elysia_v1.txt` 和 `plain_v1.txt`。这两个文件不会被运行中的服务自动读取；仅准备可供用户替换 prompt 的文本，未改变外部 .config.yaml。
普通人格文件是新的回退候选，不是对用户当前私有配置的精确备份；实际启用前由用户保存现有 prompt。静态结构检查不代表角色还原、模型遵守规则或真实语音体验通过。

## 手动启用与回退

1. 保存原有 `data/.config.yaml` 的 prompt 文本到自己本地，不分享含密钥的整份配置。
2. Ctrl+C 停止小智，打开现有私有配置，只替换 `prompt: |` 下的文本为 elysia_v1.txt 全文，每一行缩进两个空格。`<memory></memory>` 必须保留；不要在文件里写一个路径指望小智自动加载。
3. selected_module.Memory、Memory.LongMemory、模型、TTS、网络和数据库路径都不变。无需安装提供器、依赖或重刷固件。
4. 在小智服务目录按现有命令 `python.exe $xiaozhiSetup check-config --lan-ip 192.168.124.45`，通过后 `start --lan-ip 192.168.124.45 --allow-insecure-http`。解释器仍使用 `.venv/Scripts/python.exe`。
5. 先问候，再问已知事实和缺少证据的属性；确认风格和事实边界。观察语音听感，不要求逐字匹配样例，注意每次修改提示后新建会话。
6. 不满意就恢复原 prompt 并重启，或使用 plain_v1.txt 作为普通人格候选。无数据库迁移，无需删除记忆。

既有 PC 固定评估不受影响。日后比较人格版本必须保持相同合成数据和条件，另记录人格文件及哈希，不把变化混称为算法进步。
