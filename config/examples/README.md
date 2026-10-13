# 公共配置模板

这里仅保存无真实凭据的模板，属于版本库。

| 模板 | 本机实际配置 |
|---|---|
| `.env.example` | `local/config/.env`（学校模型），或 `local/config/.env.deepseek.local`（官方模型） |
| `.env.doubao.example` | `local/config/.env.doubao.local` |
| `xiaozhi.example.yaml` | `local/config/xiaozhi.yaml`（标准受管小智实例） |

已有私有配置不能用模板覆盖。模型与联网搜索配置也可在控制台保存；密钥读取接口只返回是否配置。豆包凭据可在启动面板保存。其他本机偏好在 `local/config/preferences/` 与 `local/config/display/`，运行令牌、控制桥和服务状态继续位于 `data/control/`。

详见 [本机配置集中管理](../../docs/development/configuration.md)。
