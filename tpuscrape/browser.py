"""Launch a real (headed) Chrome and drive it over CDP.

We intentionally launch Chrome *ourselves* as a normal process (not through
Playwright's launcher) so the browser does not carry Playwright/Puppeteer's
automation markers (`cdc_...` globals, `--enable-automation`,
`navigator.webdriver`).  A dedicated persistent `--user-data-dir` keeps the
firewall token/cookies between runs so re-challenges are rare.
"""
from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path

from .config import Config


class BrowserSession:
    def __init__(self, config: Config):
        self.config = config
        self.port = config.get("browser.port", 9222)
        self.profile_dir: Path = config.path("profile_dir")
        self.chrome = config.get("browser.chrome_binary", "/usr/bin/google-chrome-stable")
        self.headless = config.get("browser.headless", False)
        ws = config.get("browser.window_size", [1440, 900])
        self.window_size = f"{ws[0]},{ws[1]}"
        self.proc: subprocess.Popen | None = None
        self.playwright = None
        self.browser = None
        self.context = None

    # -- lifecycle -----------------------------------------------------------
    def start(self):
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        args = [
            self.chrome,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.profile_dir}",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-sync",
            "--disable-features=Translate,AutofillServerCommunication",
            f"--window-size={self.window_size}",
            "--window-position=80,80",
            "about:blank",
        ]
        if self.headless:
            args.insert(1, "--headless=new")

        self.proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        self._wait_for_cdp(timeout=30)

        from playwright.sync_api import sync_playwright

        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.connect_over_cdp(
            f"http://127.0.0.1:{self.port}"
        )
        # The launched Chrome has a single default (non-incognito) context.
        self.context = self.browser.contexts[0]
        self.context.set_default_timeout(self.config.get("timing.nav_timeout_ms", 60000))
        return self

    def new_page(self):
        page = self.context.new_page()
        page.set_default_timeout(self.config.get("timing.nav_timeout_ms", 60000))
        return page

    def close(self):
        try:
            if self.playwright is not None:
                self.playwright.stop()
        except Exception:
            pass
        if self.proc is not None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=10)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass

    # -- helpers -------------------------------------------------------------
    def _wait_for_cdp(self, timeout: float):
        deadline = time.time() + timeout
        url = f"http://127.0.0.1:{self.port}/json/version"
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1) as resp:
                    json.load(resp)
                    return
            except Exception:
                time.sleep(0.25)
        raise RuntimeError(
            f"Chrome did not expose CDP on port {self.port} within {timeout}s"
        )
