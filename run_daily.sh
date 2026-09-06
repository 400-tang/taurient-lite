#!/bin/zsh
# Taurient Lite — 每日简报的本地运行入口。
# 由 launchd 在每个工作日 6:00 PT 调用，也可以手动执行。

set -u

DIR="/Users/eddie/Desktop/DSO429/taurient-lite"
CLAUDE="/Users/eddie/.local/bin/claude"
LOGDIR="$DIR/logs"
TODAY="$(date +%Y-%m-%d)"

mkdir -p "$LOGDIR"
cd "$DIR" || exit 1

# 已经生成过今天的简报就不重复跑（合盖休眠后补跑时会用到）。
if [ -f "$DIR/briefs/$TODAY.json" ]; then
  echo "[$(date)] $TODAY 的简报已存在，跳过。" >> "$LOGDIR/run.log"
  exit 0
fi

echo "[$(date)] 开始生成 $TODAY 的简报" >> "$LOGDIR/run.log"

"$CLAUDE" -p "严格照着这个目录里的 RUNBOOK.md 执行，生成 $TODAY 的盘前简报。四步都要做完：扫描新闻、筛选排序、写 briefs/$TODAY.json、跑 render.py 并把结果发布到 config.json 里记录的那个 Artifact 链接（作为 url 参数传入，保持链接不变）。" \
  --permission-mode acceptEdits \
  >> "$LOGDIR/$TODAY.log" 2>&1

STATUS=$?

# 生成成功就立刻推回 GitHub。云端任务靠远程仓库里有没有当天的 JSON
# 来判断是否已经跑过，不推上去它就会重复生成一遍。
if [ $STATUS -eq 0 ] && [ -f "$DIR/briefs/$TODAY.json" ]; then
  git add -A >> "$LOGDIR/run.log" 2>&1
  git commit -q -m "简报 $TODAY" >> "$LOGDIR/run.log" 2>&1
  git pull --rebase -q >> "$LOGDIR/run.log" 2>&1
  git push -q origin main >> "$LOGDIR/run.log" 2>&1
  echo "[$(date)] 已推送到 GitHub" >> "$LOGDIR/run.log"
fi

echo "[$(date)] 结束，退出码 $STATUS" >> "$LOGDIR/run.log"
exit $STATUS
