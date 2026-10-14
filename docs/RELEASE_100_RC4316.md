# v1.0 RC4.3.16 Windows UTF-8 兼容修复

Windows 便携测试中曾出现 LLM 无法返回信息。根因是 Windows 默认代码页与模型中文输入/输出协议不一致，API transport 和 Codex worker 子进程可能继承系统编码。

本版修复：

- 两个 Windows 启动 `.bat` 设置 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`，并保留 `chcp 65001`；
- API transport 子进程通过 UTF-8 字节 stdin/stdout 传输 JSON；
- API 父进程环境强制 UTF-8；
- Codex worker 的 stdout/stderr 子进程显式 UTF-8，错误替换避免中文错误输出阻塞；
- 新增 UTF-8 transport 环境回归。

Node 扩展/工作台和 Python transport 回归通过。Windows 真机 LLM 请求仍需测试人员在目标机器使用实际 API/Codex 配置验收。
