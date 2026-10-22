# 用 Managed Agents 跑每日简报（备用，未启用）

> **目前没有启用。** Managed Agents 属于 Claude 开发者平台，按 API 用量单独计费，不在 Claude 订阅的覆盖范围内。每日简报现在由 Claude Code 云端定时任务运行，流程见仓库根目录的 `RUNBOOK.md`，三个角色的 Claude Code 版本在 `.claude/agents/`。
>
> 这个目录是完整可用的迁移方案，以后想换到托管平台（开盘前现场取数、独立评分器返工）时，照下面的步骤做即可。以下所有命令都在 `managed-agents/` 目录下运行。

每个交易日 06:00（美西）由 Anthropic 托管的定时部署启动一个会话。会话里有三个角色：

- **主编**（`agents/editor.md`，Sonnet 5）：现场取数，派人扫描，编辑，派人核查，渲染，通过质量门后提交推送；
- **新闻扫描员**（`agents/scanner.md`，Haiku 4.5）：四个并行，各管一个话题；
- **核查员**（`agents/fact-checker.md`，Sonnet 5）：只读，逐条核对必读层的数字和日历日期。

会话最后由 outcome 评分器按 `rubric.md` 打分，不合格就让主编返工，最多三轮。机械规则（条数、时效、数据日期、禁用措辞）由 `check_brief.py` 判断，评分器只判断需要读懂内容的那几条。

## 文件

| 文件 | 作用 | 怎么同步 |
|---|---|---|
| `agents/*.md` | 三个 agent 的配置（frontmatter）和系统提示词（正文） | `ant apply` |
| `environments/cloud.yaml` | 沙箱：只放行行情数据源的网络白名单 | `ant apply` |
| `claude-lock.json` | `ant apply` 记下的资源 ID，要提交进仓库 | 自动生成 |
| `rubric.md` | outcome 评分标准 | `deploy.py setup` |
| `deploy.py` | 建立 / 更新部署，手动触发，查看运行记录 | 手动 |
| `deployment.json` | 部署 ID（不含任何秘密） | 自动生成 |

## 第一次设置

```bash
# 1. 工具和凭据
brew install anthropics/tap/ant      # 需要 1.30 以上
ant auth login
pip install -r requirements.txt
export GITHUB_TOKEN=github_pat_...   # 只授权本仓库、Contents 读写的 fine-grained PAT

# 2. 建 agent 和环境：先看计划，确认后再加 --yes
ant apply --dry-run -v agents environments
ant apply --yes agents environments
git add claude-lock.json && git commit -m "Managed Agents 资源 ID"

# 3. 试跑分支：新链路先只往这个分支写，不影响线上
git push origin main:agent-trial

# 4. 建部署，手动跑一次看效果
python3 deploy.py setup --branch agent-trial
python3 deploy.py run
```

## 日常

- **改提示词或模型**：编辑 `agents/*.md`，然后 `ant apply agents environments`。部署用的是 agent 的最新版本，下次触发自动生效。
- **改评分标准或分支**：编辑 `rubric.md`，或者换 `--branch`，然后再跑一次 `deploy.py setup`。
- **手动重跑**：`deploy.py run`，暂停时也能跑。
- **看最近几次跑得怎么样**：`deploy.py status`，或者去 Console 的 Sessions 页面看每个子 agent 的线程、评分结果和花费。

## 上线

试跑两三个交易日、质量和花费都满意之后：

1. `python3 deploy.py setup --branch main`；
2. 停掉旧的 Claude Code 云端 routine；
3. 删掉 `run_daily.sh`、`com.eddie.taurient-lite.plist.disabled`、`CLOUD_SETUP.md` 和 `.github/workflows/market-snapshot.yml`，`momentum-scan.yml` 只保留周日的名单重建；
4. 把 `RUNBOOK.md` 改写成指向这份文档的人类说明。
