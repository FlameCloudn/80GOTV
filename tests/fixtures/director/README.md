# 旧导播兼容样本

`80gotv.ts` 是导播项目 `src/main/server/integrations/80gotv.ts` 的原文件，不是按网站返回值重写的模拟实现。它在原网站提交 `7ede96e` 和独立导播提交 `3c75c90` 中内容相同。随附原项目的 [LICENSE](LICENSE)。

两个兼容用例挑出其中实际使用的函数，交给 Node 在本机 SQLite 上执行。这样单独检出网站、运行 CI 或检查发布候选时，都不需要安装 Electron，也不会因相邻目录的版本变化而改变测试对象。

不要在这里开发导播。需要升级支持的导播版本时，从对应提交更新原文件及来源说明，在网站运行：

```powershell
python -m pytest tests/test_entrant_slice_compatibility.py tests/test_host_director_consumer.py -q
```

完整工作区可在根目录用 `git diff --no-index -- website/tests/fixtures/director/80gotv.ts tools/jts-hud-manager/src/main/server/integrations/80gotv.ts` 对照两份文件。CI 的这两个测试不等同于连接真实 CS2、导播或 OBS。
