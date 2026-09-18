# 0.4.7 三核心功能加速版

本版聚焦侧栏三个核心功能返回过慢：

- 默认 `gpt-5.6-luna` + `low` 推理档；
- 默认 2 个并行 Codex worker，避免自动判断阻塞改简历或准备回复；
- worker 空闲轮询 0.5 秒；
- 后续任务只携带有界的历史决策/策略/草稿，减少上下文长度；
- 独立精确页识别问题已登记在 `KNOWN_ISSUES.md`，本轮暂不继续处理。

当前账户隔离实测：虚构岗位一次岗位判断约 136 秒。该数据说明模型服务与独立会话启动仍是主耗时来源，本版不能承诺秒回；但可消除本地串行排队，并为后续低延迟模型/API 留出接口。

启动方式：

```bash
python3 launch.py                 # 默认 2 个 worker
python3 launch.py --workers 1     # 更省额度
JOB_ASSISTANT_CODEX_MODEL=gpt-5.6-sol JOB_ASSISTANT_CODEX_REASONING=medium python3 launch.py
```
