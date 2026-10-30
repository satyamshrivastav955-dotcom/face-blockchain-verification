#!/usr/bin/env python3
"""
Capture the README screenshots and the demo GIF from the REAL running web app.

    pip install playwright            # uses your installed Microsoft Edge or Chrome; no browser download
    (cd web && npm ci && npm run build)
    python scripts/capture_screenshots.py

It starts ``python -m src.web --demo`` on a spare port, drives the actual UI (mount the bundled
synthetic sample, run the examination, examine the sealed record), and writes PNGs plus a GIF to
``assets/readme/``. Nothing is mocked or composited: every pixel is the app's own rendering of
real pipeline output. It runs in DEMO mode (stub engine, synthetic fixture), and the screenshots
show the demo banner for that reason. No personal images are used.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "readme"
PORT = 8791
URL = f"http://127.0.0.1:{PORT}"


def wait_up(timeout: float = 30.0) -> None:
    import urllib.request

    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(URL + "/api/health", timeout=2)
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.4)
    raise SystemExit("the web app did not start")


def shrink_pngs(max_width: int = 1500) -> None:
    """Downscale and palette-quantise the PNGs so the repository stays light (needs Pillow)."""
    from PIL import Image

    for path in OUT.glob("*.png"):
        im = Image.open(path).convert("RGB")
        if im.width > max_width:
            resample = getattr(Image, "Resampling", Image).LANCZOS
            im = im.resize((max_width, round(im.height * max_width / im.width)), resample)
        im.quantize(colors=192, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(path, optimize=True)


def main() -> int:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    video_dir = OUT / "_video"
    shutil.rmtree(video_dir, ignore_errors=True)
    server = subprocess.Popen(
        [sys.executable, "-m", "src.web", "--demo", "--port", str(PORT)],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_up()
        with sync_playwright() as p:
            browser = None
            for channel in ("msedge", "chrome"):
                try:
                    browser = p.chromium.launch(channel=channel)
                    break
                except Exception:  # noqa: BLE001
                    continue
            if browser is None:
                raise SystemExit("neither Microsoft Edge nor Chrome could be launched")

            ctx = browser.new_context(
                viewport={"width": 1280, "height": 800},
                device_scale_factor=2,
                color_scheme="light",
                record_video_dir=str(video_dir),
                record_video_size={"width": 1280, "height": 800},
            )
            page = ctx.new_page()

            # -- landing --------------------------------------------------------
            page.goto(URL + "/#/")
            page.wait_for_selector(".hero h1")
            page.wait_for_timeout(1500)  # let the stamp land
            page.screenshot(path=str(OUT / "landing_hero.png"))

            # -- open a case ---------------------------------------------------
            page.goto(URL + "/#/verify")
            page.wait_for_selector("text=Mount the synthetic sample")
            page.wait_for_timeout(600)
            page.click("text=Mount the synthetic sample")
            page.wait_for_selector(".mount img")
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUT / "workspace_intake.png"))
            page.click("text=Begin examination")
            page.wait_for_selector(".finding-sheet", timeout=60000)
            for el in page.query_selector_all(".reveal"):
                el.evaluate("e => e.classList.add('in')")
            page.wait_for_timeout(1800)
            page.locator(".jobview").screenshot(path=str(OUT / "workspace_result.png"))

            # -- examine the sealed record -----------------------------------
            page.click("text=Examine this record now")
            page.wait_for_selector(".verdict.in", timeout=30000)
            page.wait_for_timeout(1500)
            page.locator(".examination").screenshot(path=str(OUT / "examination.png"))
            page.wait_for_timeout(800)

            ctx.close()
            browser.close()

        webm = next(video_dir.glob("*.webm"))
        palette = OUT / "_palette.png"
        gif = OUT / "demo.gif"
        base = "fps=8,scale=800:-1:flags=lanczos"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(webm),
                "-vf",
                f"{base},palettegen=max_colors=64",
                str(palette),
            ],
            check=True,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(webm),
                "-i",
                str(palette),
                "-lavfi",
                f"{base}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4",
                str(gif),
            ],
            check=True,
        )
        palette.unlink(missing_ok=True)
        shutil.rmtree(video_dir, ignore_errors=True)
        shrink_pngs()
        print("wrote", ", ".join(sorted(p.name for p in OUT.iterdir() if p.suffix in (".png", ".gif"))))
    finally:
        server.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
