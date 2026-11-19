# 现场接入

| 数据方向 | 实现 | 谁负责运行 |
|---|---|---|
| 导播读取赛事、队伍、BP 和阵容 | [导播读取接口](../routes/broadcast.py) | 网站；独立导播是调用方 |
| GSI、导播现场帧、连接检查、单图回执、GOTV 统计写入 | [接收接口](../routes/live_ingest.py) | 网站；保留原有机器认证 |
| 从 GOTV 转发统计 | [中继命令](gotv_relay/relay.py) | 采集端手工运行，复用网站配置和解析器，不由 Flask 自动启动 |

在网站根目录运行 `python -m integrations.gotv_relay.relay` 可查看用法；不带参数不会连接服务器。导播桌面端和广播 HUD 各自构建，不在网站发布包内。本机带令牌的 CS2 配置只留在工作区的 `runtime/cs2/`。
