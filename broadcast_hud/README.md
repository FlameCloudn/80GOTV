# 80GOTV Broadcast HUD

这是给 80GOTV 比赛直播使用的 CS2 画面层，运行在 LHM.gg HUD Manager 中。

## 先看效果

在本目录运行：

```powershell
npm install
npm run dev
```

然后打开：

```text
http://localhost:3500/dev/?preview=1
```

`preview=1` 只是预览画面，不需要启动 CS2 或 LHM。

## 比赛时使用

1. 安装并打开 LHM.gg。
2. 在本目录运行 `npm run pack`。
3. 把生成的 ZIP 导入 LHM.gg 的 HUD 页面。
4. 在 HUD 设置的 `80GOTV Website` 中填写 `https://80gotv.cn`。
5. 如果现场只有一场正在进行的比赛，比赛编号可以留空；否则填写网站后台中的比赛编号。
6. 从 LHM.gg 复制 HUD 地址，添加到 OBS 的浏览器来源，画布设为 `1920 x 1080`。

CS2 中需要同时保留 LHM 和 80GOTV 的 GSI 配置。这样 LHM 负责本机直播画面，网站负责公网数据直播。

## 来源

本项目基于 Lexogrine 的 MIT 开源项目
[`lexogrine/cs2-react-hud`](https://github.com/lexogrine/cs2-react-hud)，原许可证保存在 `LICENSE`。
