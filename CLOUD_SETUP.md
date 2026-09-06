# 接上云端定时任务

本地 launchd 已经在跑了。云端这条是兜底：笔记本关机或合盖休眠时也能出简报。
云端会话跑在 Anthropic 的服务器上，碰不到你的 Mac，所以代码必须先上 GitHub。

## 你需要做的两步

仓库已经在本地初始化好并提交了第一个 commit，只差一个远程。

```bash
brew install gh
gh auth login          # 交互式，选 GitHub.com → HTTPS → 浏览器登录

cd /Users/eddie/Desktop/DSO429/taurient-lite
gh repo create taurient-lite --private --source=. --push
```

最后一条命令会打印仓库地址，形如 `https://github.com/<你的用户名>/taurient-lite`。

## 然后告诉我

把那个地址发给我，我会创建云端 routine：每周一到周五 13:00 UTC（也就是 6:00 PT）
克隆仓库、照 `RUNBOOK.md` 生成简报、发布到同一个 Artifact 链接、
再把当天的 JSON 和 Markdown commit 回仓库。

之后本地想同步归档就 `git pull`。

## 两边会不会打架

不会。`run_daily.sh` 和云端 prompt 都会先检查当天的 `briefs/<日期>.json` 是否存在，
存在就直接退出。谁先跑完谁算数。
