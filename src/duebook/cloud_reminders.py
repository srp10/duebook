"""Mac-side preview and controls for the private cloud reminder service."""

import json
import os
from datetime import datetime

import boto3
from botocore.config import Config

from duebook.demo_agent import DemoError
from duebook.reminders import Reminders, fingerprint


class CloudReminders(Reminders):
    def __init__(self, vault_dir, data_dir, sender, function, **kwargs):
        super().__init__(vault_dir, data_dir, sender, **kwargs)
        self.function = function
        self.client = boto3.client(
            "lambda",
            region_name=os.environ.get("AWS_REGION", "ap-southeast-1"),
            config=Config(connect_timeout=5, read_timeout=150, retries={"total_max_attempts": 1}),
        )

    def remote(self, event):
        try:
            result = self.client.invoke(
                FunctionName=self.function,
                InvocationType="RequestResponse",
                Payload=json.dumps(event).encode(),
            )
            payload = json.loads(result["Payload"].read())
        except Exception:
            raise DemoError(
                "Cloud request was not confirmed. Refresh before retrying; "
                "check AWS login and your inbox for email attempts."
            ) from None
        if result.get("FunctionError"):
            raise DemoError("Cloud reminder operation failed. Refresh to check its status.")
        if payload.get("error"):
            raise DemoError(payload["error"])
        return payload["state"]

    def load(self):
        return self.remote({"action": "state"})

    def save(self, state):
        raise RuntimeError("Cloud state must only be changed by the Lambda service.")

    def approve(self, preview, action):
        with self.locked():
            d = self.record(preview["key"])
            if (
                d.status != "open"
                or fingerprint(d) != preview["fingerprint"]
                or self.clock() >= datetime.fromisoformat(preview["expires"])
            ):
                raise DemoError("Preview expired or record changed. Preview again.")
            if not self.sender or (preview["to"], preview["from"]) != (
                self.sender.recipient,
                self.sender.sender,
            ):
                raise DemoError("Email configuration changed. Preview again.")
            state = self.remote({"action": action, "preview": preview})
            if action == "test" and state["attempts"][-1]["status"] != "accepted":
                raise DemoError("Email outcome unknown. Check your inbox before retrying.")

    def change(self, key, action):
        import yaml

        from duebook import vault
        from duebook.reminders import atomic_write

        with self.locked():
            d = self.record(key)
            if action not in ("done", "cancel", "snooze"):
                raise DemoError("Unknown reminder action.")
            self.remote({"action": action, "key": key})
            # Cloud cancellation is confirmed BEFORE changing the local record.
            if action == "done":
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

    def tick(self):
        # Local watcher only reconciles edits; it NEVER sends a scheduled email.
        with self.locked():
            state = self.load()
            records = self.records()
            for key, plan in state["plans"].items():
                if plan["status"] != "active":
                    continue
                d = records.get(key)
                if d is None or d.status != "open" or fingerprint(d) != plan["fingerprint"]:
                    self.remote({"action": "pause", "key": key})

    def overview(self):
        result = super().overview()
        result["mode"] = "cloud"
        return result
