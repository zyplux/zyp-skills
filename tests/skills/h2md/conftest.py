from __future__ import annotations

import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def h2md(skill_loader):
    return skill_loader("h2md")


@pytest.fixture
def fixture_dir():
    return FIXTURE_DIR


def _read_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text()


@pytest.fixture
def read_fixture():
    return _read_fixture


@pytest.fixture
def invoke(run, h2md):
    def _invoke(*args: str, **kwargs):
        return run(h2md.app, args, **kwargs)

    return _invoke


def _mock_subprocess_run(*args, **kwargs):
    return subprocess.CompletedProcess(
        args=args[0] if args else [], returncode=0, stdout="", stderr=""
    )


@pytest.fixture
def mock_lint():
    with patch("subprocess.run", side_effect=_mock_subprocess_run):
        yield


@pytest.fixture
def serve_html():
    servers: list[HTTPServer] = []

    def _serve(html: str, *, content_type: str = "text/html") -> str:
        body = html.encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        return f"http://127.0.0.1:{port}/article"

    yield _serve

    for s in servers:
        s.shutdown()


@pytest.fixture
def pipeline(h2md, run, serve_html, decode, mock_lint):
    def _run(html: str, *, selector: str | None = None, url: str | None = None):
        serve_url = serve_html(html)
        cli_args = [url or serve_url, "--no-assets"]
        if selector:
            cli_args.extend(["--selector", selector])
        result = run(h2md.app, cli_args)
        d = decode(result.output)
        ws = Path(d["h2md"]["workspace"])
        return SimpleNamespace(
            md=(ws / "article.md").read_text(),
            meta=decode((ws / "meta.toon").read_text()),
            issues=d.get("issues", []),
            sections=d["sections"],
            toon=d,
            workspace=ws,
        )

    return _run
