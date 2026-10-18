# Codex DSH Bridge (Windows)

Codex 负责规划、审查和验收，DeepSeek Harness 执行明确、有限的子任务。
这是独立的社区桥接，不是 OpenAI 或 DeepSeek 官方集成。不承诺固定省费比例。

## 安装

需要 Windows、Python 3.14、Node.js 24、PowerShell 7 和 npm（先从各自官方渠道安装）。
审查源码后在仓库目录运行：

```powershell
./Setup.ps1
./Install-Skill.ps1  # 可选：当前用户级技能；已有同名技能时拒绝覆盖
./Set-Token.ps1     # 在自己的交互终端隐藏输入，不发到聊天
./dsh-task.ps1 -Command doctor
./dsh-task.ps1 -Command network-check  # 可选：无 Token、无模型调用的联网检查
```

Setup 安装本地 `.venv` 和 `node_modules`，不修改系统 Python 或安装全局软件；使用锁定依赖，npm 生命周期脚本关闭。
Node/PowerShell 的机器路径仅写入忽略的 `.state/runtime-launch.json`，安装技能的路径映射也只在本机生成。
用户级技能目录是 `$HOME/.agents/skills/dsh-collaboration`；新技能未被发现时重启 Codex。
自然语言“用 DSH 协作模式”“启用 DSH”或 `$dsh-collaboration` 请求协作。只有启用、没有具体任务时，不调用付费模型。

## 网络连接故障

`doctor` 只初始化本地运行时；凭据存在与否、初始化成功都不证明 API 网络可达。
`network-check` 使用同一锁定 Node 和 DSH 代理实现，向官方 Messages 地址发送不带凭据的 HEAD 请求；
HTTP 401 表示已连通接口，不表示认证失败。该检查不会创建模型任务，也不验证账户余额或 Token。

若任务出现 `TRANSPORT` 或连接超时，先运行 `network-check`。桥接保留调用方显式设置的
`HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`NO_PROXY`；也可在忽略的 `.state/network.json`
配置当前机器已有、可信的 HTTP(S) 代理，例如：

```json
{
  "HTTP_PROXY": "http://127.0.0.1:7890",
  "HTTPS_PROXY": "http://127.0.0.1:7890",
  "NO_PROXY": "localhost,127.0.0.1,::1"
}
```

请换成自己实际使用的代理地址。环境变量按名称优先于本机文件，显式空值禁用该项；
不读取项目 `.env` 或 Windows 系统代理，不自动探测、选择代理，不修改系统 DNS/路由。
无设置时保持直连；不支持的协议或无效配置直接报错，不静默改为直连。检测失败也不会自动改网络配置或重派模型任务。
代理值不会显示在诊断输出中；含代理密码时它仍可被运行时及其子命令读取，勿提交本机配置。
代理机制见 [DSH 官方网络指南](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/network-proxy.md)。

## 派发与返工

协调方先检查原项目 Git 状态，按明确清单把非敏感、允许外发的输入放入本仓库忽略的 `.workspaces/task01`。
不要复制整个项目、`.git`、`.env`、密钥、日志或依赖。示例任务合同见 `task-template.md`。

```powershell
./dsh-task.ps1 -Command run -Workspace task01 -TaskFile C:\path\task.md
./dsh-task.ps1 -Command run -Workspace task01 -TaskFile C:\path\rework.md -ContinueFrom session-previous-id
```

返回 `model_completed=true` 只说明执行结束；`accepted_by_coordinator` 永远为 false，主助手必须独立审查差异和测试。
失败时 `result.json` 保留 `error.code` 和脱敏、限长的 `error.message`；`progress.jsonl`
保留重试序号、上限、等待时间和错误摘要。达到输出上限也明确记录未完成原因，不能合入部分编辑。
`OUTPUT_TOKEN_LIMIT` / `finish_reason=max-tokens` 表示单次生成截断：思考与最终回答共用
`config.json` 中的 `max_output_tokens_per_request`，与账户余额无关；只有服务返回 `QUOTA`
才是账户额度错误。默认单响应上限为 65536 tokens，修正了旧版 8192 过低、常在思考结束前被截断的问题。
结果与 `doctor` 会显示生效的请求上限、步数和超时；调整输出上限不会自动重派任务、修改沙箱、放宽步数或延长超时。
更高上限允许一次请求产生更多输出，用量仍以服务记录为准。
参数定义见 [DeepSeek 官方 API 文档](https://api-docs.deepseek.com/api/create-chat-completion/)。
SDK 不支持跨进程采用已有会话；返工新建会话，带上最多 12000 字符旧报告和当前工作区文件。
一次只派发一个任务。失败、取消、超时均可能留下部分编辑；停止不回滚。残留锁必须先确认无活动任务，再人工处理。

## 固定版本与限制

- 官方 Node DSH `@deepseek-ai/dsh@0.2.0-rc.2`、Python SDK `0.1.5rc1`；不使用 SDK 捆绑旧 SEA 运行时。
- `deepseek-flash`，官方 Messages 根地址 `https://api.deepseek.com/anthropic`；修改端点被拒绝。
- `workspace-write` + `never`（拒绝审批升级，不是自动批准）。不自动 fallback 为全权限。
- 600 秒超时，65536 单响应 token（包括思考与回答），12 模型步软保护；不是精准账单预算，通知时序、输入、重试、缓存或压缩可能影响费用。
- Windows Job 在超时/取消/父进程退出时停止工作进程及其后代。
- 禁用额外会话日志上传、遥测、插件清单上传、网页工具及子 Agent/循环目标工具。

## 隐私和安全

详见 [SECURITY.md](SECURITY.md)。DPAPI 只保护当前 Windows 用户之外的常规解密；不抵御同用户恶意程序或管理员。
Windows 沙箱是部分隔离，不保证读取、网络和进程隔离，也不保证所有 NTFS 硬链接边界。模型 shell 可读取它自己的环境，包括运行时 API 凭据。
不要处理敌意项目或机器上有敏感信息的任务；强隔离需专用非特权账户/虚拟机/网络策略。
“关闭额外上传”不是离线：真正执行时，任务、读取的文件内容和工具结果仍发送给 DeepSeek。
`.state` 包含密文凭据、上下文和日志；`.workspaces` 是任务文件；均禁止发布。Git ignore 不是防泄漏保证。

## 离线测试

```powershell
./.venv/Scripts/python.exe -m unittest discover -s tests -v
```

测试用本地模拟 Messages 服务配合真实锁定运行时，不用真实 Token、无付费模型请求。
覆盖 DPAPI dummy roundtrip、路径/配置拒绝、环境清理、进程树超时、事件计数、文件/命令写入及越界拒绝、升级拒绝和新会话返工。
这不等于真实 API 账户或所有 Windows 主机/沙箱边界的验收。

官方资料：[Python SDK](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/python-sdk.md)、[Protocol](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sdk/protocol/README.md)、[Safety](https://github.com/deepseek-ai/deepseek-harness/blob/master/SAFETY.md)。
上游文档可能快于锁定版本，以测试证据为准。
