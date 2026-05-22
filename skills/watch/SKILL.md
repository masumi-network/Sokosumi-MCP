---
description: Watch a long-running Sokosumi coworker task or job and report back automatically when it finishes, fails, or needs the user. Uses a zero-cost background poller when SOKOSUMI_API_KEY is set, otherwise a main-agent poll loop, so a task is never forgotten while it runs for 10-30 minutes.
---

# Sokosumi Watch

Target: "$ARGUMENTS"

Use the `sokosumi` MCP server. This skill arms a background monitor so a long-running Sokosumi task is not forgotten. Coworker tasks usually take 10-30 minutes.

It auto-selects one of two monitors:

- **Poller** (preferred): if `SOKOSUMI_API_KEY` is set in the shell, a standalone background script polls the Sokosumi API and re-invokes the agent once when the task is done. No model tokens are spent while waiting.
- **Loop** (fallback): if there is no shell API key (OAuth-only sessions), the main agent re-checks the task through the MCP server on a timer. Works everywhere, but spends one model wake per check.

There is no sub-agent — a background sub-agent cannot be resumed after a delay, so it cannot poll.

## When this runs

- Automatically: the `hannah` and `elena` skills invoke this right after they create a READY task.
- Manually: the user runs `/sokosumi:watch <task-or-job-id>` to arm or re-arm monitoring on any task or job.

## Step 1 - Arm the monitor

1. Resolve the target id: use `$ARGUMENTS` if it has an id, else the most recent Sokosumi task or job id in the conversation, else ask the user and stop.
2. Identify the kind: call `get_task` with the id — a result means kind `task`. A not-found error — call `get_job`; a result means kind `job`. Both not-found — tell the user the id was not found and stop.
3. If that check already shows a terminal or blocked status (see Step 3), skip the timer and go straight to Step 4.
4. Detect a shell API key. Run this with the Bash tool (it never prints the key value):

   ```
   [ -n "$SOKOSUMI_API_KEY" ] && echo HAVE_KEY || echo NO_KEY
   ```

5. `HAVE_KEY` — arm the **Poller** (Step 2A). `NO_KEY` — arm the **Loop** (Step 2B).
6. Tell the user in one line that you are monitoring `<ID>` in the background, that they can keep working, and that you will report back when it finishes or needs them. Do not poll synchronously and do not wait; let the rest of the current workflow finish normally.

## Step 2A - Poller (zero model cost)

Run the following as one Bash command with `run_in_background` set to `true`, substituting the real id for `<ID>`. The command references `$SOKOSUMI_API_KEY` by name; never write the key value into the command or a file.

For a **task**:

```
B="${SOKOSUMI_API_BASE_URL:-$([ "$SOKOSUMI_NETWORK" = preprod ] && echo https://api.preprod.sokosumi.com || echo https://api.sokosumi.com)}"
for i in $(seq 1 60); do
  s=$(curl -s --max-time 25 -H "Authorization: Bearer $SOKOSUMI_API_KEY" "$B/v1/tasks/<ID>" | python3 -c 'import sys,json;d=json.loads(sys.stdin.read() or "{}");o=d.get("data");print(o.get("status","") if isinstance(o,dict) else ("ERR" if isinstance(d,dict) and d.get("error") else ""))')
  case "$s" in
    COMPLETED|FAILED|CANCELED|CANCELLED|AUTHENTICATION_REQUIRED) echo "SOKOSUMI-WATCH-DONE: task <ID> status=$s"; exit 0;;
    ERR) echo "SOKOSUMI-WATCH-ERROR: task <ID> - the API rejected the request"; exit 0;;
  esac
  sleep 60
done
echo "SOKOSUMI-WATCH-TIMEOUT: task <ID> still running after about 60 minutes"
```

For a **job**, change `/v1/tasks/` to `/v1/jobs/` and the first `case` pattern to `completed|failed`.

The script polls every 60 seconds and exits once the task is finished, blocked, errored, or after ~60 minutes. It spends no model tokens while waiting; the agent is re-invoked only when it exits.

## Step 2B - Loop (no API key needed)

Run this with the Bash tool and `run_in_background` set to `true`, substituting the kind and id:

```
sleep 360 && echo 'SOKOSUMI-WATCH cycle 1/10: poll Sokosumi <KIND> <ID> now - check status, report if done or blocked, else re-arm'
```

This is a self-restarting timer: each time it exits you re-check (Step 3) and, if the task is still running, start the next one.

## Step 3 - On wake

When a finished background command's output contains one of these, act on it:

- `SOKOSUMI-WATCH-DONE` — the poller finished and the task is terminal or blocked. Go to Step 4.
- `SOKOSUMI-WATCH-TIMEOUT` — the poller hit its ~60-minute cap; the task is still running. Tell the user and offer to re-run `/sokosumi:watch <ID>`.
- `SOKOSUMI-WATCH-ERROR` — the poller's API key was rejected (likely a missing or expired `SOKOSUMI_API_KEY`). Tell the user; suggest fixing the key, or that re-arming without one falls back to the MCP loop.
- `SOKOSUMI-WATCH cycle N/M ...` — a loop tick. Check status:
  - Task: `get_task`, `list_task_events`, `list_task_jobs`. Job: `get_job`.
  - **Finished** (task `COMPLETED` or any finished status; job `completed`) or **failed/cancelled** (task `FAILED` or `CANCELED`; job `failed`) — go to Step 4.
  - **Needs the user** (task `AUTHENTICATION_REQUIRED`, or events or a linked job awaiting input or approval) — STOP, tell the user exactly what is needed, do not re-arm.
  - **Auth error** ("No Sokosumi authentication found") — STOP, tell the user to reconnect with `/mcp`, do not re-arm.
  - **Still running** — if `N < M`, re-arm with `sleep 360 && echo 'SOKOSUMI-WATCH cycle <N+1>/<M>: poll Sokosumi <KIND> <ID> now - check status, report if done or blocked, else re-arm'` (`run_in_background` true), give a one-line update, end your turn. If `N` reached `M`, STOP and tell the user it is still running after about 60 minutes so they can re-run `/sokosumi:watch <ID>`.

Keep each wake small: one status check and a one-line update.

## Step 4 - Report the result

Collect once through the MCP server, then report:
- Task: `list_task_events` (the latest comments often hold the deliverable) and `list_task_jobs`; for each linked job `get_job`, `list_job_files`, `list_job_links`.
- Job: `list_job_files`, `list_job_links`, `list_job_events`.

Give the user a concise summary: the id, the final status, and the deliverable / key output text / file and link URLs — or the failure reason. Then stop; do not re-arm.

## Notes

- The poll intervals and ~60-minute caps are deliberate; adjust them in this skill if Sokosumi tasks in your workspace run longer or shorter.
- The poller path costs no model tokens while waiting; the loop path spends one model wake per check, so its interval is in minutes, not seconds.
- Do not run two monitors for the same id. If asked to watch an id already being watched, say so instead of arming a second one.
