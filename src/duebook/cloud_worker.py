"""Serialized Lambda reminder service; no local files or model access.

Reserved concurrency MUST be one. Persist claims before SES, never retry an unknown send.
"""

import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Asia/Hong_Kong")


def process(state, event, save, send, now, sender, recipient):
    action = event.get("action", "tick")
    plans = state.setdefault("plans", {})
    attempts = state.setdefault("attempts", [])
    key = event.get("key")
    plan = plans.get(key)

    def deliver(key, p, job=None, test=False):
        if (
            sum(
                datetime.fromisoformat(a["at"]).astimezone(ZONE).date() == now.date()
                for a in attempts
            )
            >= 20
        ):
            raise ValueError("Daily limit of 20 cloud email attempts reached.")
        attempt = {"key": key, "at": now.isoformat(), "status": "unknown", "test": test}
        attempts.append(attempt)
        if job is not None:
            job["status"] = "unknown"
            p["status"] = "paused"
            p["error"] = "Send outcome unknown. Check your inbox before resuming."
        save(state)
        try:
            mid = send(p["subject"], p["body"])
        except Exception as exc:
            attempt["error"] = str(
                getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)
            )[:100]
            save(state)
            return
        attempt.update(status="accepted", message_id=mid)
        if job is not None:
            job["status"] = "accepted"
            p.update(status="active", error="")
        save(state)

    if action == "state":
        return state
    if action in ("enable", "test"):
        p = event["preview"]
        key = p["key"]
        if (p["from"], p["to"]) != (sender, recipient):
            raise ValueError("Email configuration does not match the cloud deployment.")
        if datetime.fromisoformat(p["expires"]) <= now:
            raise ValueError("Preview expired. Preview again.")
        if not p.get("subject") or not p.get("body") or len(p["body"]) > 50000:
            raise ValueError("Invalid email preview.")
        if action == "test":
            if any(
                a["key"] == key
                and a.get("test")
                and now - datetime.fromisoformat(a["at"]) < timedelta(minutes=5)
                for a in attempts
            ):
                raise ValueError("Test already attempted. Check your inbox before retrying.")
            deliver(key, p, test=True)
        else:
            if plans.get(key, {}).get("status") == "active":
                raise ValueError("Reminders already active. Cancel before replacing them.")
            future = [t for t in p["schedule"] if datetime.fromisoformat(t) > now]
            if not future:
                raise ValueError("No future reminders remain. Preview again.")
            plans[key] = p | {
                "status": "active",
                "enabled_at": now.isoformat(),
                "jobs": [{"at": t, "status": "pending"} for t in future],
                "error": "",
            }
            save(state)
    elif action in ("cancel", "done", "pause", "snooze"):
        if plan:
            if action == "snooze":
                pending = [j for j in plan["jobs"] if j["status"] == "pending"]
                if plan["status"] != "active" or not pending:
                    raise ValueError("There is no active reminder to snooze.")
                until = max(now, min(datetime.fromisoformat(j["at"]) for j in pending))
                until += timedelta(hours=24)
                for job in pending:
                    if datetime.fromisoformat(job["at"]) <= until:
                        job["status"] = "superseded"
                plan["jobs"].append({"at": until.isoformat(), "status": "pending"})
            else:
                plan["status"] = {"cancel": "cancelled", "done": "completed", "pause": "paused"}[
                    action
                ]
                for job in plan["jobs"]:
                    if job["status"] == "pending":
                        job["status"] = "cancelled"
                plan["error"] = "Local record changed. Preview again." if action == "pause" else ""
            save(state)
        elif action == "snooze":
            raise ValueError("There is no active reminder to snooze.")
    elif action == "tick":
        count = 0
        for key, plan in plans.items():
            if plan["status"] != "active":
                continue
            if (plan["from"], plan["to"]) != (sender, recipient):
                plan.update(status="paused", error="Email configuration changed. Preview again.")
                save(state)
                continue
            ready = [
                j
                for j in plan["jobs"]
                if j["status"] == "pending" and datetime.fromisoformat(j["at"]) <= now
            ]
            if not ready or count >= 5:
                continue
            ready.sort(key=lambda j: j["at"])
            for job in ready[:-1]:
                job["status"] = "superseded"
            try:
                deliver(key, plan, ready[-1])
            except ValueError as exc:
                plan["error"] = str(exc)
                save(state)
            count += 1
        state["last_tick"] = now.isoformat()
        save(state)
    else:
        raise ValueError("Unknown cloud reminder action.")
    return state


def handler(event, context):
    import boto3
    from botocore.config import Config

    config = Config(connect_timeout=5, read_timeout=10, retries={"total_max_attempts": 1})
    s3 = boto3.client("s3", config=config)
    bucket = os.environ["STATE_BUCKET"]
    try:
        state = json.loads(s3.get_object(Bucket=bucket, Key="reminders.json")["Body"].read())
    except s3.exceptions.NoSuchKey:
        state = {"plans": {}, "attempts": []}

    def save(value):
        s3.put_object(
            Bucket=bucket,
            Key="reminders.json",
            Body=json.dumps(value).encode(),
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )

    def send(subject, body):
        return boto3.client("sesv2", config=config).send_email(
            FromEmailAddress=os.environ["EMAIL_FROM"],
            Destination={"ToAddresses": [os.environ["EMAIL_TO"]]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
                }
            },
        )["MessageId"]

    try:
        return {
            "state": process(
                state,
                event,
                save,
                send,
                datetime.now(ZONE),
                os.environ["EMAIL_FROM"],
                os.environ["EMAIL_TO"],
            )
        }
    except ValueError as exc:
        return {"error": str(exc)}
