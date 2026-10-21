# AH：Quality组件单worker调度（2026-10-21）

基线 `0c64b78605398ea270fc905dad7acff2c9d11c5d`，从干净AH树新建 `codex/ah-quality-single-worker-20261021`；旧分支及成果保留，未reset。只把 `.github/workflows/quality.yml` 的组件命令改为 `pnpm test --maxWorkers=1`，并将错误的“原15秒”说明改为“默认5秒”；其余工作流语义、63文件350测试、CSS/角色/业务断言、既有隔离和固定依赖均未改。

依据前轮受控单CPU实证：2worker两流程约6.92/5.89秒超时，1worker约3.64/3.54秒通过。本次明确授权仅降低组件并发争用；不证明远程5c/0c超时的唯一原因，也不改写fa前端全过与0c再次组件失败、backend成功的既有事实。原始0c日志由ROOT提供于主项目 `local/archive/hy-advanced-release/voice-waiting-20261021T101911Z-2ce0d7/quality-0c-full.log`。

实际一次完整本地验证：固定Node24.19.0执行已安装pnpm11.19.0 CLI，`pnpm test --maxWorkers=1`，**63文件350/350通过，0失败/跳过，退出0**；目标MemoryApp用例2508ms，所有suite路径均属AH。现有依赖版本匹配、632链接均在AH树内。初次pnpm预检触发隐式同步并被非TTY保护中止；随后仅该命令使用 `--config.verify-deps-before-run=false` 禁止自动安装，未安装/下载/重建或联接依赖，未修改全局配置。

静态检查通过：PyYAML解析；严格比对仅上述两行文本变化；还原组件命令后YAML语义与0c完全相等，backend、job限制、actions、锁和前端/测试/CI脚本不变。证据为本AH ignored `data/test-tmp/ah-quality-single-worker-20261021/{components-final.json,components-final.log,workflow-static.json,tool-provenance.json}`。

本轮未额外运行browser/后端/构建，不冒称远程新候选已通过。生产前端源码与运行时不变，无需产品部署；日用、配置、数据、0016源码/BIN及设备未动，未合main/推送或联系其他会话。共享清单登记留ROOT；下一次精确远程Quality由主会话审查、合入推送后验收。
