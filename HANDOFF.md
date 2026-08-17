# 乐小读项目交接

更新时间：2026-08-17

## 当前状态

乐小读是 Python 3.11 + PySide6 Windows 桌面应用。对话、方舟知识库、单图截图理解和本地加密会话逻辑保持不变；Windows 当前用户一键安装交付已实现：

- PyInstaller `onedir` 自包含构建，无控制台窗口；NSIS 当前用户安装，不要求管理员权限。
- 桌面与开始菜单创建“乐小读”入口；无自动更新、代码签名或自定义品牌安装界面。
- 数据统一位于 `%LOCALAPPDATA%\Lexiaodu`：`chat.sqlite3`、DPAPI `chat.key`、`chat-images\`、`logs\`。安装程序只管理 `%LOCALAPPDATA%\Programs\Lexiaodu`，卸载不删除用户数据。
- 构建从私密 `.env` 白名单提取 10 个实际运行配置；不包含完整 `.env`、TOS 配置、开发机 `data\`、源码 `.py`、测试、缓存或 `.venv`。
- 错误界面提供简短中文提示、重试和“复制诊断信息”；日志与诊断只记录错误编号、阶段和异常类型，不记录凭证、聊天正文或完整请求。
- `release\Lexiaodu-Setup-0.1.0.exe` 与 `release\使用说明.pdf` 已在本机构建，均被 Git 忽略，只能通过公司内部私密渠道分发。

## 必须保留的边界

- 客户端直接调用豆包与方舟知识库；公司事实只来自检索证据，实时订单、付款与 App 状态仍需业务系统核实。
- 公司原文档不随安装包分发；不恢复 TOS、Files API、OCR、本地切片或知识库重建。
- 同一组云端凭证按已确认决策落在多台公司电脑，风险已由用户接受；不得提交、打印、写日志或公开分发。
- `chat.key` 受当前 Windows 用户 DPAPI 保护，不支持跨用户或电脑复制。删除 `%LOCALAPPDATA%\Lexiaodu`、更换账户或重装系统不属于恢复承诺。
- 不增加自动更新、中心服务器、登录、设备绑定、集中同步、远程停用、配额或签名采购。

## 已验证状态

- `.\.venv\python.exe -m pytest -q`：108 项通过。
- `.\.venv\python.exe tools\build_windows_release.py`：PyInstaller onedir、单页 PDF、NSIS 安装包完整成功。
- 成品启动：GUI 子系统，无 Python 依赖；首次创建空数据库、独立 DPAPI 密钥、截图和日志目录。
- 发布树检查：无仓库 `.py`、开发 `data\`、完整 `.env`、TOS、测试、缓存或 `.venv`；Conda OpenSSL DLL 已显式收集。
- 当前电脑真实执行安装、覆盖安装、卸载、重装和最终卸载；桌面与开始菜单入口正确，数据库与 `chat.key` 哈希全程不变。
- 无效 API 配置触发中文启动错误流程；本机日志仅记录 `stage=启动 types=ValueError`。`使用说明.pdf` 已校验一页并检查预览。
- 既有源码版本此前已完成真实普通对话、知识库和脱敏截图验收。此次尝试对安装成品复验真实付费调用时，被执行环境安全策略禁止向外部服务发送私密凭证、文档引用和截图内容，因此不能声明安装成品已完成该项复验。

## 下一任务：两台干净 Windows 最终验收

需要用户提供两台干净 Windows 10/11 64 位电脑或 VM；当前主机没有 Windows Sandbox、Hyper-V、VirtualBox 或 VMware 可用实例。不要先改代码：

1. 通过公司私密渠道复制 `release\Lexiaodu-Setup-0.1.0.exe` 和 `release\使用说明.pdf`。
2. 两台设备按说明默认安装，确认无 Python、命令行或配置要求，桌面与开始菜单可启动，首次均为空白聊天。
3. 每台设备各做最小真实普通对话、知识库回答和合成或脱敏截图理解；两台同时调用一次，核对统一账户扣费、数据隔离及是否出现并发或限流错误。
4. 制造断网，确认中文提示、重试、复制诊断与脱敏日志；不得发送真实家长内容做测试。
5. 在其中一台用同一安装包覆盖安装，再卸载并重装，确认原聊天和截图可读。
6. 仅当实际失败时，带脱敏诊断信息回到代码修复；未出现的并发问题不预建限流系统。

构建命令：

```powershell
.\.venv\python.exe -m pip install -e ".[dev,build]"
.\.venv\python.exe tools\build_windows_release.py
```
