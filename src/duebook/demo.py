"""Local Alexa+ simulation. UI writes use explicit controls; agent chat is read-only."""

import argparse
import base64
import binascii
import json
import mimetypes
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from duebook.demo_agent import DemoError, StrandsBridge

ASSETS = Path(__file__).parent / "demo_assets"
MAX_FILE = 2 * 1024 * 1024
MAX_BODY = 3 * 1024 * 1024
SAMPLES = {
    "insurance": "insurance-renewal-ambiguous.pdf",
    "immigration": "immigration-letter.pdf",
    "school": "school-fee-email.txt",
}


@dataclass
class Conversation:
    history: list[dict] = field(default_factory=list)
    pending: dict | None = None
    trace: list = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


class DemoService:
    def __init__(self, bridge, uploads: Path):
        self.bridge = bridge
        self.uploads = uploads
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.sessions = {}
        self.lock = threading.Lock()

    def create(self) -> dict:
        with self.lock:
            if len(self.sessions) >= 50:
                raise DemoError(
                    "Session limit reached. Restart the demo to clear old conversations."
                )
            session_id = str(uuid4())
            self.sessions[session_id] = Conversation()
        return {"session": session_id}

    def get(self, session_id: str) -> Conversation:
        if not isinstance(session_id, str) or session_id not in self.sessions:
            raise DemoError(
                "Conversation expired. Start a new conversation; saved deadlines remain."
            )
        return self.sessions[session_id]

    def state(self, session_id: str) -> dict:
        session = self.get(session_id)
        with session.lock:
            return self._state(session)

    def _state(self, session: Conversation) -> dict:
        warning = ""
        try:
            snapshot = self.bridge.snapshot()
        except Exception:
            snapshot = {"deadlines": [], "conflicts": []}
            warning = (
                "Cannot refresh deadlines. Check the MCP server; no saved entries were removed."
            )
        pending = None
        if session.pending:
            pending = {k: session.pending[k] for k in ("question", "candidate", "filename")}
        return snapshot | {
            "messages": session.history,
            "pending": pending,
            "trace": session.trace,
            "warning": warning,
        }

    def chat(self, session_id: str, message: str) -> dict:
        if not isinstance(message, str) or not message.strip() or len(message) > 2000:
            raise DemoError("Enter a question of 1–2,000 characters.")
        session = self.get(session_id)
        with session.lock:
            result = self.bridge.answer(session.history, message.strip())
            session.history.extend(
                [
                    {"role": "user", "text": message.strip()},
                    {"role": "assistant", "text": result["text"]},
                ]
            )
            session.history = session.history[-24:]
            session.trace = result["trace"]
            return self._state(session)

    def upload(self, session_id: str, filename: str, encoded: str) -> dict:
        session = self.get(session_id)
        if not isinstance(filename, str) or not isinstance(encoded, str):
            raise DemoError("Choose a PDF, TXT or EML file.")
        suffix = Path(filename).suffix.lower()
        if suffix not in (".pdf", ".txt", ".eml"):
            raise DemoError("Choose a PDF, TXT or EML file.")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise DemoError("The upload could not be decoded. Choose the file again.") from None
        if not data or len(data) > MAX_FILE:
            raise DemoError("Choose a nonempty file smaller than 2 MiB.")
        with session.lock:
            if session.pending:
                raise DemoError(
                    "Answer or cancel the current clarification before uploading again."
                )
            # Never use the submitted filename as a filesystem path.
            path = self.uploads / f"{uuid4().hex}{suffix}"
            path.write_bytes(data)
            try:
                result = self.bridge.ingest(str(path))
            except Exception:
                path.unlink(missing_ok=True)
                raise
            return self._ingestion_result(session, path, Path(filename).name, result)

    def sample(self, session_id: str, name: str) -> dict:
        if not isinstance(name, str) or name not in SAMPLES:
            raise DemoError("Choose one of the three synthetic sample documents.")
        path = ASSETS / "samples" / SAMPLES[name]
        return self.upload(session_id, path.name, base64.b64encode(path.read_bytes()).decode())

    def confirm(self, session_id: str, hint: str) -> dict:
        if not isinstance(hint, str) or not hint.strip() or len(hint) > 2000:
            raise DemoError("Enter the clarification requested, up to 2,000 characters.")
        session = self.get(session_id)
        with session.lock:
            if not session.pending:
                raise DemoError("There is no document waiting for clarification.")
            pending = session.pending
            # Use exactly the user's answer. The conversational model cannot invent this input.
            result = self.bridge.ingest(str(pending["path"]), hint.strip())
            return self._ingestion_result(session, pending["path"], pending["filename"], result)

    def _ingestion_result(self, session, path, filename, result):
        if result["status"] == "needs_confirmation":
            session.pending = {
                "path": path,
                "filename": filename,
                "question": result["question"],
                "candidate": result["candidate"],
            }
            text = result["question"] + " Nothing has been saved yet."
        elif result["status"] == "saved":
            session.pending = None
            path.unlink(missing_ok=True)
            entry = result["entry"]
            text = (
                f"Saved {entry['title']}, due {entry['due']}. The evidence is in the deadline card."
            )
        else:
            raise DemoError("The ingestion tool returned an unknown status.")
        session.history.extend(
            [
                {"role": "user", "text": f"Review document: {filename}"},
                {"role": "assistant", "text": text},
            ]
        )
        session.history = session.history[-24:]
        session.trace = [{"tool": "ingest_document", "status": result["status"]}]
        return self._state(session)

    def cancel(self, session_id: str) -> dict:
        session = self.get(session_id)
        with session.lock:
            if session.pending:
                session.pending["path"].unlink(missing_ok=True)
                session.pending = None
            return self._state(session)


def make_handler(service):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Requests may reference documents; don't log bodies or session IDs.

        def allowed(self):
            port = self.server.server_port
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            return self.headers.get("Host") in hosts and self.headers.get("Origin") in (
                None,
                *(f"http://{h}" for h in hosts),
            )

        def respond(self, status, value, content_type="application/json"):
            data = json.dumps(value).encode() if content_type == "application/json" else value
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; "
                "style-src 'self'; connect-src 'self'; img-src 'self' data:; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            )
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.allowed():
                return self.respond(403, {"error": "Local same-origin requests only."})
            parsed = urlparse(self.path)
            if parsed.path == "/api/state":
                try:
                    sid = parse_qs(parsed.query).get("session", [""])[0]
                    return self.respond(200, service.state(sid))
                except DemoError as exc:
                    return self.respond(400, {"error": str(exc)})
            names = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
            if parsed.path not in names:
                return self.respond(404, {"error": "Not found"})
            path = ASSETS / names[parsed.path]
            return self.respond(
                200,
                path.read_bytes(),
                (mimetypes.guess_type(path.name)[0] or "text/plain") + "; charset=utf-8",
            )

        def do_POST(self):
            if not self.allowed():
                return self.respond(403, {"error": "Local same-origin requests only."})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if (
                    not 0 < size <= MAX_BODY
                    or self.headers.get("Content-Type") != "application/json"
                ):
                    raise DemoError("Expected a JSON request under 3 MiB.")
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise DemoError("Expected a JSON object.")
                sid = body.get("session", "")
                routes = {
                    "/api/session": lambda: service.create(),
                    "/api/chat": lambda: service.chat(sid, body.get("message")),
                    "/api/upload": lambda: service.upload(
                        sid, body.get("filename"), body.get("data")
                    ),
                    "/api/sample": lambda: service.sample(sid, body.get("name")),
                    "/api/confirm": lambda: service.confirm(sid, body.get("hint")),
                    "/api/cancel": lambda: service.cancel(sid),
                }
                if self.path not in routes:
                    return self.respond(404, {"error": "Not found"})
                self.respond(200, routes[self.path]())
            except (DemoError, ValueError) as exc:
                self.respond(400, {"error": str(exc)[:500]})
            except Exception:
                self.respond(
                    503,
                    {
                        "error": "The agent or MCP server is unavailable. Check the "
                        "server and refresh AWS login. Reload deadlines before retrying a save."
                    },
                )

    return Handler


def seed_vault(directory: Path):
    """Seed once; never overwrite existing deadlines or reintroduce deleted samples."""
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / ".seeded"
    if not marker.exists():
        for path in (ASSETS / "seeds").glob("*.md"):
            dest = directory / path.name
            if not dest.exists():
                shutil.copy2(path, dest)
        marker.write_text("Synthetic demo seed data.\n")


def main():
    parser = argparse.ArgumentParser(description="Duebook: local Alexa+ simulation")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data-dir", type=Path, default=Path(".duebook-demo"))
    args = parser.parse_args()
    try:
        import strands  # noqa: F401
    except ImportError:
        raise SystemExit("Install demo dependencies: uv sync --extra demo") from None
    vault = args.data_dir.resolve() / "vault"
    seed_vault(vault)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        mcp_port = sock.getsockname()[1]
    env = os.environ | {
        "DUEBOOK_VAULT": str(vault),
        "DUEBOOK_PORT": str(mcp_port),
        "DUEBOOK_HOST": "127.0.0.1",
    }
    child = subprocess.Popen([sys.executable, "-m", "duebook.server"], env=env)
    try:
        for _ in range(60):
            if child.poll() is not None:
                raise SystemExit("Demo MCP server failed to start.")
            try:
                with socket.create_connection(("127.0.0.1", mcp_port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise SystemExit("Demo MCP server did not become ready.")
        with tempfile.TemporaryDirectory(prefix="duebook-uploads-") as temp:
            service = DemoService(StrandsBridge(f"http://127.0.0.1:{mcp_port}/mcp"), Path(temp))
            server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(service))
            print(f"Duebook demo: http://127.0.0.1:{server.server_port}", flush=True)
            print(f"Synthetic demo vault: {vault}", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
    finally:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


if __name__ == "__main__":
    main()
