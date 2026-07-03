"""Story 3: downloading article images alongside the markdown via the h2md CLI."""

from __future__ import annotations

import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest
from toon_format import decode

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from types import ModuleType

    from typer.testing import CliRunner

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-image-bytes"
DATA_URI = "data:image/gif;base64,R0lGODlhAQABAAAAACw="


@pytest.fixture
def serve_routes() -> Generator[Callable[[dict[str, tuple[str, bytes]]], str]]:
    servers: list[HTTPServer] = []

    def _serve(routes: dict[str, tuple[str, bytes]]) -> str:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                route = routes.get(self.path)
                if route is None:
                    self.send_error(404)
                    return
                content_type, body = route
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            @override
            def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield _serve

    for server in servers:
        server.shutdown()


@pytest.fixture
def refused_url() -> str:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}/gone.png"


@pytest.fixture
def mock_lint(monkeypatch: pytest.MonkeyPatch) -> None:
    def clean_lint(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", clean_lint)


def _article_html(*img_tags: str) -> str:
    images = "\n".join(img_tags)
    return f"""<!DOCTYPE html><html><head><title>Image guide</title></head><body><article>
    <h1>Image guide</h1>
    <p>This guide explains how images travel with an article when it is converted to markdown.</p>
    {images}
    <p>Every image referenced above should end up next to the markdown so the article stays portable.</p>
    </article></body></html>"""


def _workspace_of(runner: CliRunner, h2md: ModuleType, url: str) -> Path:
    result = runner.invoke(h2md.app, [url])
    assert result.exit_code == 0, result.output
    parsed = decode(result.output)
    assert isinstance(parsed, dict)
    return Path(parsed["h2md"]["workspace"])


@pytest.mark.usefixtures("mock_lint")
def test_3_1_1_downloads_images_and_rewrites_their_sources(
    h2md: ModuleType, runner: CliRunner, serve_routes: Callable[[dict[str, tuple[str, bytes]]], str]
) -> None:
    routes: dict[str, tuple[str, bytes]] = {"/diagram.png": ("image/png", PNG_BYTES)}
    base = serve_routes(routes)
    html = _article_html(f'<img src="{base}/diagram.png" alt="diagram">')
    routes["/article"] = ("text/html", html.encode())

    workspace = _workspace_of(runner, h2md, f"{base}/article")

    article_html = (workspace / "article.html").read_text()
    assert 'src="assets/' in article_html


@pytest.mark.usefixtures("mock_lint")
def test_3_1_2_keeps_data_uris_and_unreachable_images_untouched(
    h2md: ModuleType,
    runner: CliRunner,
    serve_routes: Callable[[dict[str, tuple[str, bytes]]], str],
    refused_url: str,
) -> None:
    html = _article_html(f'<img src="{DATA_URI}" alt="inline">', f'<img src="{refused_url}" alt="gone">')
    base = serve_routes({"/article": ("text/html", html.encode())})

    workspace = _workspace_of(runner, h2md, f"{base}/article")

    article_html = (workspace / "article.html").read_text()
    assert DATA_URI in article_html
    assert refused_url in article_html
    assert not (workspace / "assets").exists() or not list((workspace / "assets").iterdir())
