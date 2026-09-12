from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from playwright.sync_api import expect, sync_playwright

if TYPE_CHECKING:
    from collections.abc import Iterator

    from conftest import Stack
    from playwright.sync_api import BrowserContext, Page

REPOSITORY = Path(__file__).resolve().parents[2]


@dataclass
class Console:
    stack: Stack
    url: str
    context: BrowserContext
    page: Page

    def login(self, email: str, password: str) -> None:
        self.page.goto(self.url)
        expect(self.page.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()
        self.page.get_by_label("Email", exact=True).fill(email)
        self.page.get_by_label("Password", exact=True).fill(password)
        self.page.get_by_role("button", name="Sign in", exact=True).click()
        expect(self.page.get_by_role("heading", name="Sign in", exact=True)).not_to_be_visible()

    def capture(self, name: str) -> None:
        self.page.screenshot(path=str(self.stack.tmp / f"{name}.png"), full_page=True, mask=[self.page.get_by_label("Key Secret", exact=True)])


@contextmanager
def running_console(stack: Stack) -> Iterator[Console]:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    environment = {**os.environ, "PORT": str(port), "CONTROL_PLANE_URL": stack.cp_url, "DATA_PLANE_URL": stack.dp_url}
    bun = shutil.which("bun")
    if bun is None:
        message = "Bun is required to run the console browser tests"
        raise RuntimeError(message)
    with (stack.tmp / "console.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(  # noqa: S603 test launches the repository's trusted Bun development server
            [bun, "run", "dev"], cwd=REPOSITORY, env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    if httpx.get(url, timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if process.poll() is not None or time.monotonic() >= deadline:
                    message = "Console failed to start; inspect console.log"
                    raise RuntimeError(message)
                time.sleep(0.1)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                context = browser.new_context(permissions=["clipboard-read", "clipboard-write"], viewport={"width": 1440, "height": 1000})
                try:
                    page = context.new_page()
                    page.set_default_timeout(10_000)
                    yield Console(stack, url, context, page)
                finally:
                    context.close()
                    browser.close()
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
