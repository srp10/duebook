"""Opt-in local email scheduler. Durable claims favor no duplicate over silent retries."""

import fcntl
import hashlib
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from duebook import vault
from duebook.demo_agent import DemoError, agent_evidence

ZONE = ZoneInfo("Asia/Hong_Kong")
OFFSETS = (7, 1, 0)


def now_hk():
    return datetime.now(ZONE)


def key_for(d):
    return hashlib.sha256(f"{d.title}\n{d.due}".encode()).hexdigest()[:24]


def fingerprint(d):
    return hashlib.sha256(vault.render(d).encode()).hexdigest()


def atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".duebook-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def email_address(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+", value
    ):
        raise DemoError("Configure a single valid sender and recipient email address.")
    if len(value) > 254 or not value.isascii():
        raise DemoError("Use an ASCII email address under 255 characters.")
    return value


class EmailSender:
    def __init__(self, sender: str, recipient: str):
        self.sender = email_address(sender)
        self.recipient = email_address(recipient)

    def send(self, subject, body):
        import boto3
        from botocore.config import Config

        # SES SendEmail has no idempotency key. Disable SDK retries after ambiguous errors.
        client = boto3.client(
            "sesv2",
            region_name=os.environ.get("AWS_REGION", "ap-southeast-1"),
            config=Config(connect_timeout=10, read_timeout=15, retries={"total_max_attempts": 1}),
        )
        return client.send_email(
            FromEmailAddress=self.sender,
            Destination={"ToAddresses": [self.recipient]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
                }
            },
        )["MessageId"]


def configured_sender(data_dir: Path):
    config = {}
    path = data_dir / "email.json"
    if path.exists():
        config = json.loads(path.read_text())
    sender = os.environ.get("DUEBOOK_EMAIL_FROM", config.get("from", ""))
    recipient = os.environ.get("DUEBOOK_EMAIL_TO", config.get("to", ""))
    return EmailSender(sender, recipient) if sender and recipient else None


class Reminders:
    def __init__(self, vault_dir: Path, data_dir: Path, sender=None, clock=now_hk):
        self.vault_dir = vault_dir
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "reminders.json"
        self.sender = sender
        self.clock = clock
        self.stop = threading.Event()
        self.thread = None
        self.worker_error = ""

    @contextmanager
    def locked(self):
        with (self.data_dir / ".reminders.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def load(self):
        return (
            json.loads(self.path.read_text())
            if self.path.exists()
            else {"plans": {}, "attempts": []}
        )

    def save(self, state):
        atomic_write(self.path, json.dumps(state, indent=2))

    def records(self):
        return {key_for(d): d for d in vault.read_all(self.vault_dir)}

    def record(self, key):
        records = self.records()
        if not isinstance(key, str) or key not in records:
            raise DemoError("That deadline is no longer available. Refresh the list.")
        return records[key]

    def schedule(self, d):
        now = self.clock()
        return [
            datetime.combine(d.due - timedelta(days=n), time(9), ZONE).isoformat()
            for n in OFFSETS
            if datetime.combine(d.due - timedelta(days=n), time(9), ZONE) > now
        ]

    def preview(self, key):
        with self.locked():
            return self._preview(key)

    def _preview(self, key):
        d = self.record(key)
        if d.status != "open":
            raise DemoError("Completed or cancelled deadlines cannot receive reminders.")
        if not self.sender:
            raise DemoError(
                "Email setup is incomplete. Configure verified sender and recipient first."
            )
        clean = agent_evidence(d.summary())
        body = (
            f"Duebook demo reminder\n\n{d.title}\nDue: {d.due}\nType: {d.kind}\n\n"
            f"Source quote/reference:\n{d.source}\n\n"
            f"Saved context:\n{clean['notes'] or 'None recorded.'}\n\n"
            "User clarifications are not independently verified. "
            "These are synthetic demo records.\n"
        )
        clashes = [
            c["explanation"]
            for c in vault.find_conflicts(self.vault_dir)
            if any(
                c[k]["title"] == d.title and c[k]["due"] == d.due.isoformat() for k in ("a", "b")
            )
        ]
        if clashes:
            body += "\nNearby deadlines at the time this preview was created:\n" + "\n".join(
                clashes
            )
        body += (
            "\n\nOpen Duebook on your Mac to mark done, snooze 24 hours or cancel reminders. "
            "This email has no remote action links. Do not reply to change a deadline."
        )
        subject = "Duebook: " + re.sub(r"[\r\n]+", " ", d.title)[:140] + f" - due {d.due}"
        return {
            "key": key,
            "fingerprint": fingerprint(d),
            "to": self.sender.recipient,
            "from": self.sender.sender,
            "subject": subject,
            "body": body,
            "schedule": self.schedule(d),
            "expires": (self.clock() + timedelta(minutes=10)).isoformat(),
        }

    def approve(self, preview, action):
        with self.locked():
            if action not in ("enable", "test"):
                raise DemoError("Choose enable or send one test email.")
            d = self.record(preview["key"])
            if (
                d.status != "open"
                or fingerprint(d) != preview["fingerprint"]
                or self.clock() >= datetime.fromisoformat(preview["expires"])
            ):
                raise DemoError("This preview expired or the record changed. Preview again.")
            if not self.sender or (preview["to"], preview["from"]) != (
                self.sender.recipient,
                self.sender.sender,
            ):
                raise DemoError("Email configuration changed. Preview again.")
            state = self.load()
            previous = state["plans"].get(preview["key"], {})
            if action == "test":
                recent = [
                    a
                    for a in state["attempts"]
                    if a["key"] == preview["key"]
                    and a.get("test")
                    and self.clock() - datetime.fromisoformat(a["at"]) < timedelta(minutes=5)
                ]
                if recent:
                    raise DemoError(
                        "A test was already attempted in the last five minutes. "
                        "Check your inbox and delivery status."
                    )
                self._send(state, preview["key"], preview, test=True)
                return
            if previous.get("status") == "active":
                raise DemoError(
                    "Reminders are already active. Cancel them before changing the plan."
                )
            future = [t for t in preview["schedule"] if datetime.fromisoformat(t) > self.clock()]
            if not future:
                raise DemoError(
                    "No future 9am reminders remain for this deadline. "
                    "You can send one preview test instead."
                )
            state["plans"][preview["key"]] = preview | {
                "status": "active",
                "enabled_at": self.clock().isoformat(),
                "jobs": [{"at": t, "status": "pending"} for t in future],
                "error": "",
            }
            self.save(state)

    def change(self, key, action):
        with self.locked():
            d = self.record(key)
            state = self.load()
            plan = state["plans"].get(key)
            if action == "done":
                # Preserve unrecognized front-matter fields and the exact notes.
                match = vault.FRONT_MATTER.match(d.path.read_text())
                meta = yaml.safe_load(match.group(1))
                meta["status"] = "done"
                atomic_write(
                    d.path,
                    "---\n"
                    + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
                    + "---\n"
                    + match.group(2),
                )
                if plan:
                    plan["status"] = "completed"
            elif action == "cancel":
                if not plan:
                    raise DemoError("No reminder plan is configured for this deadline.")
                plan["status"] = "cancelled"
            elif action == "snooze":
                if not plan or plan["status"] != "active" or d.status != "open":
                    raise DemoError("Only active reminders can be snoozed.")
                pending_times = [
                    datetime.fromisoformat(j["at"])
                    for j in plan["jobs"]
                    if j["status"] == "pending"
                ]
                if not pending_times:
                    raise DemoError("There are no remaining reminders to snooze.")
                until = max(self.clock(), min(pending_times)) + timedelta(hours=24)
                for job in plan["jobs"]:
                    if job["status"] == "pending" and datetime.fromisoformat(job["at"]) <= until:
                        job["status"] = "superseded"
                plan["jobs"].append({"at": until.isoformat(), "status": "pending"})
            else:
                raise DemoError("Unknown reminder action.")
            if plan and action in ("done", "cancel"):
                for job in plan["jobs"]:
                    if job["status"] == "pending":
                        job["status"] = "cancelled"
            self.save(state)

    def _send(self, state, key, preview, job=None, test=False):
        today = self.clock().date()
        attempts_today = sum(
            datetime.fromisoformat(a["at"]).astimezone(ZONE).date() == today
            for a in state["attempts"]
        )
        if attempts_today >= 20:
            raise DemoError("Daily limit of 20 email attempts reached for this vault.")
        attempt = {"key": key, "at": self.clock().isoformat(), "status": "unknown", "test": test}
        state["attempts"].append(attempt)
        if job is not None:
            job["status"] = "unknown"
        # Claim before calling SES; a crash/timeout must not cause an automatic duplicate.
        self.save(state)
        try:
            mid = self.sender.send(preview["subject"], preview["body"])
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)
            attempt["error"] = str(code)[:100]
            if job is not None:
                preview["status"] = "paused"
                preview["error"] = (
                    "Send failed or outcome unknown; preview again before resuming. "
                    + str(code)[:100]
                )
            self.save(state)
            raise DemoError(
                "Email was not confirmed accepted. "
                "Check AWS login/SES and your inbox before retrying."
            ) from None
        attempt.update(status="accepted", message_id=mid)
        if job is not None:
            job["status"] = "accepted"
            preview["error"] = ""
        self.save(state)

    def tick(self):
        with self.locked():
            state = self.load()
            records = self.records()
            sent = 0
            for key, plan in state["plans"].items():
                if plan["status"] != "active":
                    continue
                d = records.get(key)
                if d is None or d.status != "open":
                    plan["status"] = "completed" if d and d.status == "done" else "cancelled"
                    continue
                if any(j["status"] == "unknown" for j in plan["jobs"]):
                    plan.update(
                        status="paused",
                        error="Previous send outcome unknown. Check inbox before re-enabling.",
                    )
                    continue
                if (
                    not self.sender
                    or fingerprint(d) != plan["fingerprint"]
                    or (plan["to"], plan["from"]) != (self.sender.recipient, self.sender.sender)
                ):
                    plan.update(
                        status="paused",
                        error="Record or email configuration changed. Preview again.",
                    )
                    continue
                ready = [
                    j
                    for j in plan["jobs"]
                    if j["status"] == "pending" and datetime.fromisoformat(j["at"]) <= self.clock()
                ]
                if not ready or sent >= 5:
                    continue
                ready.sort(key=lambda j: j["at"])
                for old in ready[:-1]:
                    old["status"] = "superseded"
                try:
                    self._send(state, key, plan, ready[-1])
                except DemoError as exc:
                    if plan["status"] == "active":
                        plan["error"] = str(exc)
                sent += 1
            self.save(state)

    def overview(self):
        with self.locked():
            state = self.load()
            records = self.records()
            rows = {}
            for key in records:
                plan = state["plans"].get(key, {})
                jobs = [j["at"] for j in plan.get("jobs", []) if j["status"] == "pending"]
                attempts = [a for a in state["attempts"] if a["key"] == key]
                rows[key] = {
                    "status": plan.get("status", "off"),
                    "next": min(jobs) if jobs and plan.get("status") == "active" else None,
                    "error": plan.get("error", ""),
                    "last": attempts[-1] if attempts else None,
                }
            return {
                "configured": bool(self.sender),
                "to": self.sender.recipient if self.sender else "",
                "timezone": str(ZONE),
                "items": rows,
                "worker_error": self.worker_error,
                "completed": [
                    d.summary() | {"key": key_for(d)}
                    for d in records.values()
                    if d.status == "done"
                ],
            }

    def start(self):
        def loop():
            while not self.stop.is_set():
                try:
                    self.tick()
                    self.worker_error = ""
                except Exception:
                    self.worker_error = (
                        "Reminder worker could not read or save state. Check local files."
                    )
                self.stop.wait(30)

        self.thread = threading.Thread(target=loop, daemon=True, name="duebook-reminders")
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=30)
