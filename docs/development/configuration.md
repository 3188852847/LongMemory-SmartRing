# 本机配置集中管理

本轮只调整配置归属与加载位置，保留文件原字节、模型选择、角色、设备绑定及现有协议。个人数据库、模型资源和厂家源码目录不迁移。

## 当前目录契约

记忆算法替换的显式 Python 装配见[方法边界](../architecture/method-boundary.md)。`MemoryBackendStore` 保存的圆屏后端指针仍是现有三种选项，本轮未新增 Hy 日用选项、未编辑任何 `local/config`。新后端合成验收分别指定引擎资源目录与平台来源文件；不把旧 `--database` 当作任意后端目录，也不自动创建/迁移个人库。安装、下载和实际切换仍由所有者/后续明确范围处理。

| 内容 | 位置 | Git |
|---|---|---|
| 学校 / 官方模型档案 | `local/config/.env`、`local/config/.env.deepseek.local` | 忽略 |
| 搜索 / 豆包凭据 | `local/config/.env.web-search.local`、`local/config/.env.doubao.local` | 忽略 |
| 小智人工管理配置 | `local/config/xiaozhi.yaml` | 忽略 |
| 启动、模型、记忆及声音偏好 | `local/config/preferences/{launcher,model-profile,memory-backend,tts-backend}.json` | 忽略 |
| 圆屏皮肤选择及自定义皮肤 | `local/config/display/{round-skin-selection.json,round-skin-custom.skin.json}` | 忽略 |
| 小智配置修改备份 | `local/archive/config-backups/` | 忽略 |
| 小智旧运行副本 | `local/archive/config-generated/` | 忽略 |
| 迁移回执与回退副本 | `local/archive/config-migrations/` | 忽略 |
| 无凭据公共模板 | `config/examples/` | 跟踪 |

`data/control/` 保留运行令牌、控制桥发现文件、启动器状态及 TTS 基准历史；数据库、媒体、记忆角色仍按自身资产归属存放，不能当配置搬走。子进程环境变量由启动器从选定档案加载，不修改机器永久环境变量。

## 小智配置的来源和消费副本

标准受管目录是项目内 `local/runtime/xiaozhi-esp32-server/main/xiaozhi-server`。角色、模型、记忆后端、网络、声音及 VAD 同步工具在该实例上读写 `local/config/xiaozhi.yaml`；修改前继续核对摘要并备份，界面回执只证明磁盘配置，运行中服务需重启。

厂家代码固定读取自己的 `data/.config.yaml`。项目启动工具在完成 canonical（唯一管理来源）验证之后、启动小智之前生成字节完全相同的副本，记录 `data/.config.source.json` 的相对来源与 SHA-256 摘要，不向 YAML 注入字段、不改厂家源码。首次生成仅允许不存在的副本或与 canonical 字节相同的原副本。后续如果厂家副本与上一份生成摘要不符，则拒绝覆盖，避免丢失手工编辑。

不要直接编辑生成副本。需要保留副本上的临时修改时，先停止服务、核对两份差异，再将确认的修改应用到 canonical；本工具不自动猜测应该合并哪一份。显式指定其他 `--server-dir` 时仍使用那个实例自身 `data/.config.yaml`，不会隐式读取日用项目私有配置；此行为也用于合成测试。

## 已有机器的迁移与切换

由协调会话先核对正式启动器的服务状态，再受控停止旧启动器及其拥有的服务。旧 Python 进程可能动态读取根目录配置，所以不能在日用进程仍运行时直接搬迁。现有配置先预检：

```powershell
.\.venv\Scripts\python.exe scripts/development/migrate_local_config.py
```

预检仅列相对路径、摘要和动作，不输出配置正文。停止服务后才执行：

```powershell
.\.venv\Scripts\python.exe scripts/development/migrate_local_config.py --apply --services-stopped
```

脚本只处理明确列出的 4 份 env、6 份偏好及受管小智 YAML。env / 偏好在项目同一盘内原子移动；YAML 复制到 canonical，原厂家文件保留为消费副本。目标碰撞、软链接、联接、越界、超大文件和摘要变化都拒绝，已存在的新配置不从模板重建。若某一动作失败，尝试只回退本事务已完成且摘要未变化的文件，回执留在私有归档目录；不得在报错后假定全部完成。

第一次迁移完成应立即建立受管 YAML 来源回执（只生成本机配置，不启动服务）：

```powershell
.\.venv\Scripts\python.exe scripts/development/xiaozhi/config_paths.py --render
```

然后重新打开根目录 `启动智慧圆屏.cmd`，核对控制台、模型档案、记忆/声音偏好及圆屏重连。不能复用仍在内存中执行旧代码的启动面板。全部路径仍相对于项目根目录；uv 使用 `--env-file local/config/.env` 或 `--env-file local/config/.env.deepseek.local`，避免包含中文、空格和反斜杠的绝对 env 参数。

若需要退回旧代码，先停止新服务，再用该次回执的完整路径回退：

```powershell
.\.venv\Scripts\python.exe scripts/development/migrate_local_config.py --rollback "<该次回执的完整路径>" --services-stopped
```

回退先检查全部摘要和目标，任何配置已被后续编辑都会拒绝，不能覆盖用户的新设置。新增 canonical YAML 回退时移入回执旁的私有归档，保留全部内容。已迁移的新代码只读新目录，不保留根目录密钥副本；历史文档原路径仍是历史事实。

## 验证边界

2026-10-14 主目录实际切换完成：3 份 env、6 份偏好原样移动，受管 YAML 建立
管理来源并生成消费副本，共 10 项。启动后 3 份 env 与 6 份偏好摘要均与迁移前
一致，管理 YAML、生成 YAML 与来源标记摘要一致。正式启动器与语音服务就绪，
原模型/记忆/声音选择一致；圆屏重连，所有者确认正常回答。本地收据与只含
状态的切换验收记录位于 `local/archive/`，不提交私有配置。

合成测试覆盖字节保持、重复运行、碰撞拒绝、失败回退、修改后回退拒绝、链接/越界防护、实例隔离、生成副本漂移拒绝及 UI 同步后再生成。安装、联网模型调用、正式个人数据库写入、设备烧录不属于这些验证；上线结果由协调会话另行记录。
