#!/usr/bin/env python3
"""管理每日简报的定时部署：建立或更新、手动跑一次、看最近几次的结果。

    cd managed-agents
    python3 deploy.py setup --branch agent-trial   # 建立或更新部署
    python3 deploy.py run                          # 立刻跑一次，实时打印进度
    python3 deploy.py status                       # 最近几次运行
    python3 deploy.py pause | unpause

**目前没有启用。** Managed Agents 按 API 用量单独计费，不走 Claude 订阅，
所以每日简报暂时仍由 Claude Code 云端定时任务运行（见仓库根目录的
``RUNBOOK.md`` 和 ``.claude/agents/``）。这个目录留着，以后要切换时直接用。

**分工。** agent 和运行环境是本目录下 ``agents/``、``environments/`` 里的文件，
在本目录用 ``ant apply`` 同步，ID 记在本目录的 ``claude-lock.json``。部署不走
``ant apply``，因为它要带一个 GitHub token，而 token 不能写进仓库里的任何
文件。所以部署由这个脚本从环境变量里读 token 来建，建好之后只把部署 ID
记进本目录的 ``deployment.json``——那个文件里没有任何秘密。

**要准备的环境变量。**

* ``ANTHROPIC_API_KEY``，或者先跑过 ``ant auth login``；
* ``GITHUB_TOKEN``：只授权 taurient-lite 这一个仓库、带 Contents 读写权限的
  fine-grained PAT。它存在 Anthropic 那边的 git 代理里，不会进沙箱；
* ``TAURIENT_REPO_URL``（可选）：不给就读 ``git remote get-url origin``。

这是仓库里唯一需要第三方包的脚本（``pip install -r requirements.txt``），
每日流水线本身仍然只用标准库。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import anthropic

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LOCK = HERE / "claude-lock.json"
STATE = HERE / "deployment.json"
RUBRIC = HERE / "rubric.md"

AGENT_FILE = "./agents/editor.md"
ENV_FILE = "./environments/cloud.yaml"

#: 仓库在沙箱里的位置。agents/editor.md 和 rubric.md 里写的都是这个路径，
#: 显式指定而不依赖默认值，免得仓库改名后三处对不上。
MOUNT_PATH = "/workspace/taurient-lite"

#: 周一到周五 06:00 美西。美东 09:00，开盘前半小时：前一交易日已收完盘，
#: 当天还没开盘，取到的全是完整交易日的数据。按时区写 wall-clock 时间，
#: 夏令时切换不用改。
SCHEDULE = {"type": "cron", "expression": "0 6 * * 1-5", "timezone": "America/Los_Angeles"}

#: 每次运行的花费上限（美分）。先给一个宽松的值，试跑几天看实际花费再收紧。
BUDGET_CENTS = "800"

OUTCOME = (
    "生成今天（美西日期）的盘前简报并发布：按你的系统提示词里的流程现场取数、"
    "派扫描员并行扫描、编辑、派核查员核对、渲染、通过质量门，然后提交推送到当前分支，"
    "最后写 /mnt/session/outputs/summary.md。"
)


def load_ids() -> tuple[str, str]:
    if not LOCK.exists():
        sys.exit("找不到 claude-lock.json：先在 managed-agents/ 目录下跑 ant apply agents environments")
    resources = json.loads(LOCK.read_text(encoding="utf-8")).get("resources", {})
    try:
        return resources[AGENT_FILE]["id"], resources[ENV_FILE]["id"]
    except KeyError as exc:
        sys.exit(f"claude-lock.json 里没有 {exc}：先 ant apply 这个文件")


def repo_url() -> str:
    url = os.environ.get("TAURIENT_REPO_URL", "").strip()
    if not url:
        url = subprocess.run(
            ["git", "-C", str(ROOT), "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    # git@github.com:user/repo.git → https://github.com/user/repo
    if url.startswith("git@github.com:"):
        url = "https://github.com/" + url.removeprefix("git@github.com:")
    return url.removesuffix(".git")


def deployment_body(branch: str) -> dict:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        sys.exit("没有 GITHUB_TOKEN 环境变量（只授权这个仓库、Contents 读写的 fine-grained PAT）")
    agent_id, env_id = load_ids()
    return {
        "name": "Taurient Lite 每日盘前简报",
        "agent": agent_id,  # 字符串形式：每次触发都用 agent 的最新版本
        "environment_id": env_id,
        "schedule": SCHEDULE,
        "budget": {"type": "limit", "max_list_cost": {"amount": BUDGET_CENTS, "currency": "USD"}},
        "resources": [{
            "type": "github_repository",
            "url": repo_url(),
            "authorization_token": token,
            "checkout": {"type": "branch", "name": branch},
            "mount_path": MOUNT_PATH,
        }],
        "initial_events": [{
            "type": "user.define_outcome",
            "description": OUTCOME,
            "rubric": {"type": "text", "content": RUBRIC.read_text(encoding="utf-8")},
            "max_iterations": 3,
        }],
        "metadata": {"branch": branch},
    }


def deployment_id() -> str:
    if not STATE.exists():
        sys.exit("还没有部署：先跑 python3 deploy.py setup --branch agent-trial")
    return json.loads(STATE.read_text(encoding="utf-8"))["id"]


def cmd_setup(client: anthropic.Anthropic, args) -> None:
    body = deployment_body(args.branch)
    if STATE.exists():
        dep = client.beta.deployments.update(deployment_id(), **body)
        print(f"已更新部署 {dep.id}")
    else:
        dep = client.beta.deployments.create(**body)
        STATE.write_text(json.dumps({"id": dep.id}, indent=2) + "\n", encoding="utf-8")
        print(f"已建立部署 {dep.id}，ID 记在 {STATE.relative_to(ROOT)}")
    print(f"  分支：{args.branch}")
    upcoming = (dep.schedule.upcoming_runs_at or [])[:3] if dep.schedule else []
    print(f"  接下来几次触发（UTC）：{', '.join(t.isoformat() for t in upcoming) or '—'}")


def cmd_run(client: anthropic.Anthropic, _args) -> None:
    run = client.beta.deployments.run(deployment_id())
    if run.error:
        sys.exit(f"没能启动：{run.error.type} {run.error.message}")
    print(f"会话 {run.session_id} 已启动，在 Console 的 Sessions 页面能看到每个子 agent 的线程。")
    print("下面只打印主编的发言和评分结果，Ctrl-C 只是停止打印，不会停掉会话。\n")

    with client.beta.sessions.events.stream(session_id=run.session_id) as stream:
        for event in stream:
            if event.type == "agent.message":
                for block in event.content:
                    if block.type == "text":
                        print(block.text, flush=True)
            elif event.type == "span.outcome_evaluation_end":
                print(f"\n[评分 第 {event.iteration + 1} 轮] {event.result}：{event.explanation}\n")
            elif event.type == "session.status_terminated":
                break
            elif event.type == "session.status_idle" and event.stop_reason.type != "requires_action":
                break

    session = client.beta.sessions.retrieve(run.session_id)
    cost = int(session.usage.list_cost.amount) / 100 if session.usage.list_cost else None
    print(f"\n会话结束，状态 {session.status}" + (f"，花费约 ${cost:.2f}" if cost is not None else ""))


def cmd_status(client: anthropic.Anthropic, _args) -> None:
    dep = client.beta.deployments.retrieve(deployment_id())
    upcoming = (dep.schedule.upcoming_runs_at or []) if dep.schedule else []
    print(f"部署 {dep.id}：{dep.status}，下次触发 {upcoming[0].isoformat() if upcoming else '—'}")
    for i, run in enumerate(client.beta.deployment_runs.list(deployment_id=dep.id)):
        if i >= 10:
            break
        outcome = run.session_id or f"失败：{run.error.type} {run.error.message}"
        print(f"  {run.created_at:%Y-%m-%d %H:%M}Z  {run.trigger_context.type:8s}  {outcome}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    setup = sub.add_parser("setup", help="建立或更新部署")
    setup.add_argument("--branch", default="agent-trial", help="简报推送到哪个分支，上线时改成 main")
    sub.add_parser("run", help="立刻手动跑一次")
    sub.add_parser("status", help="最近几次运行")
    sub.add_parser("pause", help="暂停定时触发")
    sub.add_parser("unpause", help="恢复定时触发")
    args = parser.parse_args()

    client = anthropic.Anthropic()
    if args.cmd == "setup":
        cmd_setup(client, args)
    elif args.cmd == "run":
        cmd_run(client, args)
    elif args.cmd == "status":
        cmd_status(client, args)
    elif args.cmd == "pause":
        print(f"已暂停 {client.beta.deployments.pause(deployment_id()).id}")
    elif args.cmd == "unpause":
        print(f"已恢复 {client.beta.deployments.unpause(deployment_id()).id}")


if __name__ == "__main__":
    main()
