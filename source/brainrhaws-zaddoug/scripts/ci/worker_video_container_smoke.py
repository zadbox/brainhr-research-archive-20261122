#!/usr/bin/env python3
"""Runtime proof for the confined worker image, using synthetic media only."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from microservices.cal_video_ai_worker.audio import PulseAudioController
from microservices.cal_video_ai_worker.config import get_settings
from playwright.sync_api import sync_playwright


def status_value(name: str) -> str:
    prefix = f"{name}:"
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    raise RuntimeError(f"missing process status field: {name}")


def chromium_command_lines() -> list[str]:
    command_lines: list[str] = []
    for path in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            raw = path.read_bytes()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        command = raw.replace(b"\0", b" ").decode("utf-8", errors="replace").strip()
        if "chromium" in command:
            command_lines.append(command)
    return command_lines


def main() -> None:
    if (os.geteuid(), os.getegid()) != (10001, 10001):
        raise RuntimeError("worker image did not start with the fixed non-root identity")
    if status_value("NoNewPrivs") != "1":
        raise RuntimeError("no-new-privileges is not active")
    if int(status_value("CapEff"), 16) != 0:
        raise RuntimeError("effective Linux capabilities are not empty")
    if os.getenv("AWS_EC2_METADATA_DISABLED") != "true":
        raise RuntimeError("IMDS credential discovery is not disabled")
    for forbidden in ("SECRET_KEY", "CALCOM_API_KEY", "XAI_API_KEY", "AWS_SECRET_ACCESS_KEY"):
        if os.getenv(forbidden):
            raise RuntimeError(f"unexpected backend secret exposed to worker: {forbidden}")

    Path(os.environ["HOME"]).mkdir(mode=0o700, parents=True, exist_ok=True)
    Path(os.environ["XDG_RUNTIME_DIR"]).mkdir(mode=0o700, parents=True, exist_ok=True)

    xvfb = subprocess.Popen(
        ["Xvfb", ":99", "-screen", "0", "1280x720x24", "-ac", "+extension", "RANDR", "-nolisten", "tcp"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(50):
            if subprocess.run(
                ["xdpyinfo"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode == 0:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("synthetic X display did not become ready")

        PulseAudioController(get_settings()).prepare()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ["CAL_VIDEO_CHROMIUM_EXECUTABLE"],
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )
            page = browser.new_page()
            page.set_content("<title>BrainRH confined worker</title><h1 id='proof'>sandboxed</h1>")
            if page.title() != "BrainRH confined worker":
                raise RuntimeError("synthetic Chromium page title mismatch")
            if page.locator("#proof").inner_text() != "sandboxed":
                raise RuntimeError("synthetic Chromium DOM mismatch")
            commands = chromium_command_lines()
            if not commands:
                raise RuntimeError("no Chromium process found for sandbox inspection")
            if any("--no-sandbox" in command or "--disable-setuid-sandbox" in command for command in commands):
                raise RuntimeError("a Chromium sandbox opt-out reached the browser process")
            browser.close()
    finally:
        xvfb.terminate()
        try:
            xvfb.wait(timeout=5)
        except subprocess.TimeoutExpired:
            xvfb.kill()

    print("worker-video-container-smoke: non_root caps_empty nnp_on imds_off pulse_ready chromium_sandbox_flags_clean")


if __name__ == "__main__":
    main()
