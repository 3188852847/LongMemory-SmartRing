# React 聊天页体验与构建

## 现在怎么打开

这次已在本机完成构建。统一启动面板现在默认打开 `/chat-react`，“打开控制台”按钮也进入 React 版，无需再手动修改网址。例如控制台在 8767 时地址为 `http://127.0.0.1:8767/chat-react`。

不用另开终端或启动 Vite。React 左侧“返回原版聊天”可立即回到 `/chat`，原版左侧也可进入 React 新版。两版使用同一聊天和记忆数据库，发送真实消息也会真实保存；它不是隔离实验沙盒。不要同时在两个页面发送同一会话。

可以依次体验：新建聊天 → 输入合成内容 → 展开本轮证据 → 刷新恢复 → 重命名/切换 → 主题与字号。请求结果未知时只点击“查询结果”，不重复提交。当前仍是原来的规则记忆方法，迁移不提升记忆智能程度。

浏览器交互尚待验收。遇到空白页、弹窗或下拉异常，先返回原版，并提供现象；不要关闭安全策略解决。

## 换电脑或源码更新后怎么构建

开发环境需要 Node（本次 24.19.0）和 pnpm（本次 11.19.0）。安装阶段会下载前端依赖，不调用模型；日常运行不下载。项目不会自动修改全局 PATH 或安装 Node。

已经配置 Node/pnpm 的 PowerShell：

```powershell
Set-Location "D:\02-项目\LongMemory-SmartRing\web\react-chat"
pnpm install --frozen-lockfile
node node_modules/typescript/bin/tsc --noEmit
if ($LASTEXITCODE -ne 0) { throw "类型检查失败，请勿继续构建" }
node node_modules/vite/bin/vite.js build
if ($LASTEXITCODE -ne 0) { throw "构建失败" }
node --test src/api.test.ts
```

助手当前使用的随附 pnpm 不代表用户终端已有 `pnpm` 命令。若提示找不到命令，先核对开发工具路径，不重新安装 Python 或删除项目。

构建输出在 `web/react-chat/dist/`，不提交 Git；依赖锁文件提交，个人数据库不提交。出现 503 表示缺少或无效构建；出现 404 通常先检查是否仍运行旧控制台进程。旧版入口不依赖这些产物。

## 目录用途

- `web/react-chat/src/`：React 页面、接口封装、局部样式和接口测试。
- `web/react-chat/dist/`：生成的生产页面与资源，不手写。
- `web/react-chat/node_modules/`：包管理器安装的开发依赖，不手写。

当前构建 JS 约 576 kB（gzip 约 189 kB），构建器给出体积提醒但无构建错误；暂未为此增加复杂分包。已通过类型检查、434 项 Python 和 24 项前端/API 测试；这些结果不代表浏览器视觉、弹窗及学校模型验收已完成。
