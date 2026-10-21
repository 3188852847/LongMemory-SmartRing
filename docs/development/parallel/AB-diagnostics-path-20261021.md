# AB：诊断路径前缀与双进程CI修复

日期：2026-10-21。基线 `7746e728a356f90f5d034f193fd37861fbaec91a`。独立树 `local/worktrees/ab-diagnostics-ci-20261021`，分支 `codex/ab-diagnostics-ci-20261021`。原预热分支、工作树和证据保留。本轮ROOT授权定位单项CI失败、最小实现及相关测试；后续追加授权仅登记本文的manifest条目、为一个确切symlink权限skip登记CI资源例外。本文为待ROOT审查的隔离候选，不表示远程CI、日用或设备验收通过。既有边界见 [观测契约](../observability-contract.md) 和 [ADR-0180](../../adr/0180-explicit-voice-diagnostics-and-retention.md)。

## 原CI事实

Quality运行39620914580，backend job119293725274：`tests/unit/infrastructure/test_diagnostics.py::test_real_separate_processes_write_distinct_files` 预期两个 `api-PID-nonce.jsonl`，实际一个。原日志结果为1 failed / 3897 passed / 259 skipped，360.26秒；失败记录保留，不用本地成功重跑改写。只读ROOT指定的公共合成 `quality-backend.log`，未读个人库、对话、音频或其他私有日志。

两个子进程均communicate等待完成、返回码0，脚本明确调用observer.close；因此没有证据把问题归为“测试没等退出/没flush”。原始CI日志未输出内部初始化状态，不能倒推那一次具体OS错误码。下面在同基线实际复现相同可见失败，并捕获了确定的实现缺陷。

## 本地取证与原因

未改实现时，原测试单跑1 passed；自然双子进程探针分别在第7、第4、第31组观察到相同缺文件。探针只包装返回/异常进行取证，没有注入失败、延时或业务重试；遇首个失败便停止，次数不是故障概率估计。

失败子进程在finish前已是persistence=unavailable、handler=None，finish后仍如此；进程正常退出。捕获构造函数主动抛出的固定 `diagnostic_path_outside_root`，没有PermissionError或WinError5。其root为普通 `D:\…`，而尚不存在的日志目标经真实Path.resolve返回等价 `\\?\D:\…`。原is_relative_to进行词法驱动比较，认为二者不属于同根，因而在打开日志前拒绝，随后按fail-open（诊断失败不阻断业务）降级。

固定Python3.12.13的ntpath.realpath会先调用_getfinalpathname，并在缺失路径上做非strict回退；只有再次检查的winerror与首次相同时才去除新增扩展前缀。真实取证捕获首次ERROR_PATH_NOT_FOUND=3，另一个子进程创建父目录后再检查变为ERROR_FILE_NOT_FOUND=2，因3≠2保留了扩展前缀。两种路径仍指向同一目标。这与此前管理marker的WinError5没有已证实关联。

原始探针和分阶段回执保存在本树忽略目录 `data/test-tmp/ab-diagnostics-ci-20261021-01/`：natural-01、natural-02、native-errors-01与fixed-natural-01。最终取证脚本 `diagnostics_probe.py` SHA256为 `7fe2e88787b0153496641b2f0b341e6686c588bb28930cbaf334b7dff2d4e7e6`。原始合成路径和进程明细未加入Git。

## 最小实现及安全边界

只在diagnostics.py的归属比较增加私有_comparison_path：对**已经resolve的PureWindowsPath**，把标准extended-length ASCII驱动路径及结构完整的UNC驱动表示换为相同词法表示。UNC必须有非空server/share、不是点段、没有控制字符或Windows非法名称字符。GLOBALROOT、Volume设备、Win32设备命名空间及畸形UNC不重写。普通POSIX路径原样返回。

创建目录前、后的两个真实resolve和包含校验都保留；比较前分别统一目标与root的表示，实际传给mkdir和handler的路径完全不改。没有增加等待、重试、异步flush或删除/迁移。PID＋nonce命名、每进程独占、轮转、关闭和有界摘要保持原契约。

真正根外路径仍拒绝。确定性用例覆盖第一次/第二次解析的根外返回；真实junction指向合成根外目录被拒绝，目标标记文件字节和目录条目保留。真实symlink用例因本机无创建权限跳过，不冒充实测通过；没有提权、改DeveloperMode或安装依赖。两个链接的父与目标均在各自pytest合成目录，不指向用户资料。

初始化resolve、mkdir、handler打开的确定性I/O失败仍fail-open：内存结果保持unknown、persistence=unavailable，异常正文、绝对路径不进入摘要，stdout/stderr为空。原日志写入失败、隐私白名单和root logger不变测试仍通过。原双进程测试的等待、关闭、两文件断言与内容断言保持原样。

## 验证与CI资源守卫

- 修复前新增的两个确定性扩展驱动别名用例均失败（unavailable而非enabled）；修复后通过，且每个都断言两个归属检查确实执行。
- 修复后100组真实双进程，共200个子进程，全部两份有效unknown记录、persistence=enabled。期间仍出现6次真实扩展前缀返回，修复覆盖了触发路径，而非仅靠不再遇到竞态。
- 最终相关诊断、HTTP观测、跨进程语音观测及CosyVoice诊断回归：**70 passed / 1 skipped，2.36秒**。唯一skip为下面精确的创建symlink权限限制。
- 实际diagnostics JUnit报告为37 passed / 1 skipped，backend_quality.audit_report审计结果(37,1)。资源清单相对7746只多下列一个精确键，所有原键和原因未变。
- 全测试收集4184项；263个资源声明全部命中收集项，orphan=0。质量报告守卫7项通过；另验证错误skip原因、junction参数冒用权限例外及原双进程测试冒用例外均被拒绝。

新增权限例外：

| 字段 | 精确值 |
|---|---|
| classname | tests.unit.infrastructure.test_diagnostics |
| name | test_real_directory_link_outside_root_is_refused[symlink] |
| skip reason | directory symlink privilege unavailable |

该skip只在创建合成symlink实际报winerror=1314时发生，其他OSError继续抛出。junction、原双进程用例、纯路径边界和I/O失败隐私断言不在这个例外中；没有模块/前缀通配放行。收集及实际JUnit报告保留在上述忽略目录，未运行整个后端3897项或声称远程Quality已转绿。

## 交付范围

仅diagnostics实现与测试、backend_resources精确权限例外、本文及manifest中本文的唯一条目。ROOT特别授予manifest窄归属，其余条目、topic、状态与review不改；不修改AI/AD文件。Hy方法源码组合未动，**不需要因本补丁重签无关Hy管理proof**，本轮也没有读取或改写任何日用proof/配置。

不合main、不推送、不部署，不操作日用进程、个人数据或设备。下一步由ROOT轻审合入、推送触发真实CI；原失败与本地修复证据并存。本地symlink权限缺口由精确例外保留，若CI具备权限，该用例必须实际执行根外拒绝断言。
