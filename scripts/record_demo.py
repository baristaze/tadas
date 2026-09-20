"""Records the realtime demo GIF in the root README: two portal windows side by
side, the owner and Bob (the two people `make seed` creates), both on Team's
Tasks, while a short script adds and completes tasks in one window and the
other follows live.

It drives a headless Chrome over the DevTools protocol, one isolated browser
context per person. Each signs in through the API (a session token, the way
the API tests do) rather than through the form, over the Python client in
`clients/python/` (ADR 0004 records the interval before that client
existed). The task list is emptied first, then both windows are screencast
and the frames are composed on one timeline into a GIF.

    make up
    uv run --with pillow python scripts/record_demo.py docs/media/realtime-demo.gif

`make demo-gif` runs the second line. Other stacks: --api and --portal (the
portal's build must point at the same API). Chrome: CHROME, or the default
install path. --still writes a PNG per window instead, to check the layout.
"""

import argparse
import asyncio
import base64
import io
import itertools
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.request
from collections.abc import Callable
from typing import Any

import websockets
from PIL import Image

from tadas.client.client import ApiClient
from tadas.client.types import TaskScope, TaskStatus

WIDTH, HEIGHT = 420, 840  # each window in the GIF: portrait, height twice the width
SCALE = 2  # render at twice the size, then downscale, for crisp text
FPS = 12
GAP = 12
DEBUG_PORT = 49222
ACCENTS = [(31, 157, 85), (232, 133, 12), (43, 91, 215), (180, 35, 24), (255, 255, 255)]


def chrome_path() -> str:
    candidates = [
        os.environ.get("CHROME"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    sys.exit("no Chrome found; set CHROME to its executable")


class Api:
    """The two things the recorder asks of the API, over the Python client."""

    def __init__(self, base: str) -> None:
        self.base = base

    def _client(self, token: str | None = None) -> ApiClient:
        return ApiClient(self.base, app="portal", app_version="portal@demo", token=token)

    async def session(self, email: str, password: str) -> dict[str, Any]:
        """What the portal keeps in localStorage once someone has signed in."""
        async with self._client() as client:
            login = await client.login(email, password)
            org = login.memberships[0].org
            issued = await client.exchange_session(login.token, org.id)
        return {"state": {"token": issued.token, "orgSlug": org.slug}, "version": 0}

    async def clear_tasks(self, token: str) -> int:
        cleared = 0
        async with self._client(token) as client:
            for status in (TaskStatus.open, TaskStatus.done):
                while True:
                    page = await client.tasks(status, TaskScope.team, limit=200)
                    if not page.items:
                        break
                    for task in page.items:
                        await client.delete_task(task.id, task.version)
                        cleared += 1
        return cleared


class Cdp:
    """A minimal DevTools protocol client: commands by id, events to handlers."""

    def __init__(self, ws: Any) -> None:
        self.ws = ws
        self.ids = itertools.count(1)
        self.pending: dict[int, asyncio.Future[Any]] = {}
        self.handlers: list[Callable[[dict[str, Any]], None]] = []

    async def pump(self) -> None:
        async for raw in self.ws:
            message = json.loads(raw)
            future = self.pending.pop(message.get("id"), None)
            if future is not None:
                if "error" in message:
                    future.set_exception(RuntimeError(message["error"]))
                else:
                    future.set_result(message.get("result", {}))
            elif "method" in message:
                for handler in self.handlers:
                    handler(message)

    async def send(
        self, method: str, params: dict[str, Any] | None = None, session: str = ""
    ) -> Any:
        command_id = next(self.ids)
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self.pending[command_id] = future
        payload: dict[str, Any] = {"id": command_id, "method": method, "params": params or {}}
        if session:
            payload["sessionId"] = session
        await self.ws.send(json.dumps(payload))
        return await future


class Window:
    def __init__(self, cdp: Cdp, name: str, session: str, zoom: float) -> None:
        self.cdp, self.name, self.session, self.zoom = cdp, name, session, zoom
        self.frames: list[tuple[float, bytes]] = []

    async def js(self, expression: str) -> Any:
        result = await self.cdp.send(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": True, "returnByValue": True},
            self.session,
        )
        return result.get("result", {}).get("value")

    async def wait_for(self, expression: str) -> None:
        """Polls the page (there is no event to await) for up to 20 seconds."""
        for _ in range(200):
            if await self.js(expression):
                return
            await asyncio.sleep(0.1)
        raise TimeoutError(f"{self.name}: {expression}")

    async def add_task(self, title: str) -> None:
        await self.js("document.querySelector('input[aria-label=\"New task\"]').focus()")
        for character in title:
            await self.cdp.send("Input.insertText", {"text": character}, self.session)
            await asyncio.sleep(0.07)
        await asyncio.sleep(0.35)
        enter = {"key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13}
        await self.cdp.send(
            "Input.dispatchKeyEvent", {"type": "keyDown", "text": "\r", **enter}, self.session
        )
        await self.cdp.send("Input.dispatchKeyEvent", {"type": "keyUp", **enter}, self.session)

    async def complete(self, title: str) -> None:
        box = await self.js(
            f"""(() => {{
              const open = document.querySelectorAll("section ul")[0];
              const rows = [...open.querySelectorAll(":scope > li")];
              const title = {json.dumps(title)};
              const row = rows.find((li) => li.querySelector("span").textContent === title);
              const r = row.querySelector('input[type="checkbox"]').getBoundingClientRect();
              return {{ x: r.x + r.width / 2, y: r.y + r.height / 2 }};
            }})()"""
        )
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            event = {"type": kind, "x": box["x"], "y": box["y"], "button": "left", "clickCount": 1}
            await self.cdp.send("Input.dispatchMouseEvent", event, self.session)


async def open_window(
    cdp: Cdp, api: Api, portal: str, name: str, email: str, password: str, zoom: float
) -> Window:
    context = (await cdp.send("Target.createBrowserContext"))["browserContextId"]
    target = await cdp.send(
        "Target.createTarget", {"url": "about:blank", "browserContextId": context}
    )
    attached = await cdp.send(
        "Target.attachToTarget", {"targetId": target["targetId"], "flatten": True}
    )
    window = Window(cdp, name, attached["sessionId"], zoom)
    for domain in ("Page", "Runtime"):
        await cdp.send(f"{domain}.enable", {}, window.session)
    # Browser zoom: a wider CSS viewport rendered into the same pixels.
    metrics = {
        "width": round(WIDTH / zoom),
        "height": round(HEIGHT / zoom),
        "deviceScaleFactor": SCALE * zoom,
        "mobile": False,
    }
    await cdp.send("Emulation.setDeviceMetricsOverride", metrics, window.session)
    await cdp.send("Page.navigate", {"url": f"{portal}/sign-in"}, window.session)
    await window.wait_for("document.readyState === 'complete'")
    stored = json.dumps(json.dumps(await api.session(email, password)))
    await window.js(
        f"localStorage.setItem('tadas.portal.session', {stored});"
        "localStorage.setItem('tadas.portal.taskScope', 'team'); true"
    )
    await cdp.send("Page.navigate", {"url": f"{portal}/"}, window.session)
    await window.wait_for(
        "!!document.querySelector('[aria-label=\"live updates: open\"]')"
        " && [...document.querySelectorAll('h2')].some((h) => h.textContent.startsWith('Open'))"
    )
    await asyncio.sleep(1.0)
    return window


async def story(owner: Window, bob: Window) -> None:
    """Additions alternate between the two; each completes the other's task."""
    await asyncio.sleep(1.5)
    await owner.add_task("Migrate DB")
    await asyncio.sleep(1.6)
    await bob.add_task("Review PR #42")
    await asyncio.sleep(1.6)
    await owner.add_task("Fix login test")
    await asyncio.sleep(1.6)
    await bob.add_task("Write changelog")
    await asyncio.sleep(1.8)
    await bob.complete("Migrate DB")
    await asyncio.sleep(2.2)
    await owner.complete("Review PR #42")
    await asyncio.sleep(2.2)
    await owner.add_task("Deploy to staging")
    await asyncio.sleep(3.0)


def frame_at(frames: list[tuple[float, bytes]], moment: float) -> bytes:
    """The last frame painted at or before the moment."""
    chosen = frames[0][1]
    for timestamp, data in frames:
        if timestamp > moment:
            break
        chosen = data
    return chosen


def compose(owner: Window, bob: Window, start: float, end: float, out: str) -> None:
    decoded: dict[int, Image.Image] = {}

    def image(data: bytes) -> Image.Image:
        if id(data) not in decoded:
            raw = Image.open(io.BytesIO(data)).convert("RGB")
            decoded[id(data)] = raw.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
        return decoded[id(data)]

    canvas_w, canvas_h = WIDTH * 2 + GAP * 3, HEIGHT + GAP * 2
    frames: list[Image.Image] = []
    durations: list[int] = []
    step_ms = round(1000 / FPS)
    moment, last = start, None
    while moment <= end:
        left, right = frame_at(owner.frames, moment), frame_at(bob.frames, moment)
        if (id(left), id(right)) == last:
            durations[-1] += step_ms  # an unchanged moment lengthens the frame before it
        else:
            canvas = Image.new("RGB", (canvas_w, canvas_h), (220, 220, 216))
            canvas.paste(image(left), (GAP, GAP))
            canvas.paste(image(right), (GAP * 2 + WIDTH, GAP))
            frames.append(canvas)
            durations.append(step_ms)
            last = (id(left), id(right))
        moment += step_ms / 1000

    # One palette for the whole GIF, from frames across the recording plus the
    # app's accent colours, so the live dot and checkboxes keep their colour.
    samples = frames[:: max(1, len(frames) // 12)]
    sheet = Image.new("RGB", (canvas_w, canvas_h * (len(samples) + 1)))
    for n, sample in enumerate(samples):
        sheet.paste(sample, (0, canvas_h * n))
    swatch = canvas_w // len(ACCENTS)
    for n, colour in enumerate(ACCENTS):
        top = canvas_h * len(samples)
        sheet.paste(colour, (n * swatch, top, (n + 1) * swatch, top + canvas_h))
    palette = sheet.quantize(colors=160, method=Image.Quantize.MEDIANCUT)
    quantized = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    quantized[0].save(
        out, save_all=True, append_images=quantized[1:], duration=durations, loop=0, optimize=True
    )
    seconds = sum(durations) / 1000
    print(f"{out}: {len(frames)} frames, {seconds:.1f}s, {os.path.getsize(out) / 1e6:.2f} MB")


async def still(window: Window, path: str) -> None:
    shot = await window.cdp.send("Page.captureScreenshot", {"format": "png"}, window.session)
    image = Image.open(io.BytesIO(base64.b64decode(shot["data"])))
    image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS).save(path)
    print(path)


async def record(args: argparse.Namespace) -> None:
    api = Api(args.api)
    if not args.still:  # a still shows whatever the list holds; a recording starts empty
        owner_session = await api.session(args.owner, args.password)
        cleared = await api.clear_tasks(owner_session["state"]["token"])
        print(f"cleared {cleared} tasks")

    profile = tempfile.mkdtemp(prefix="tadas-demo-chrome-")
    chrome = await asyncio.create_subprocess_exec(
        chrome_path(),
        "--headless=new",
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--hide-scrollbars",
        "--force-color-profile=srgb",
        "--disable-extensions",
        "about:blank",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        ws_url = await debugger_url()
        async with websockets.connect(ws_url, max_size=None) as ws:
            cdp = Cdp(ws)
            pump = asyncio.create_task(cdp.pump())
            windows = [
                await open_window(cdp, api, args.portal, name, email, args.password, args.zoom)
                for name, email in (("owner", args.owner), ("bob", args.member))
            ]
            owner, bob = windows
            if args.still:
                for window in windows:
                    await still(window, args.out.removesuffix(".gif") + f"-{window.name}.png")
            else:
                await screencast(cdp, owner, bob, args.out)
            pump.cancel()
    finally:
        chrome.terminate()
        await chrome.wait()
        shutil.rmtree(profile, ignore_errors=True)


async def debugger_url() -> str:
    def fetch() -> str:
        url = f"http://127.0.0.1:{DEBUG_PORT}/json/version"
        with urllib.request.urlopen(url) as response:
            return json.load(response)["webSocketDebuggerUrl"]

    for _ in range(100):
        try:
            return await asyncio.to_thread(fetch)
        except OSError:
            await asyncio.sleep(0.1)
    raise TimeoutError("Chrome did not open its debugging port")


async def screencast(cdp: Cdp, owner: Window, bob: Window, out: str) -> None:
    by_session = {owner.session: owner, bob.session: bob}
    acks: set[asyncio.Task[Any]] = set()

    def on_frame(message: dict[str, Any]) -> None:
        if message["method"] != "Page.screencastFrame":
            return
        params, session = message["params"], message["sessionId"]
        frame = (params["metadata"]["timestamp"], base64.b64decode(params["data"]))
        by_session[session].frames.append(frame)
        ack = {"sessionId": params["sessionId"]}
        task = asyncio.ensure_future(cdp.send("Page.screencastFrameAck", ack, session))
        acks.add(task)
        task.add_done_callback(acks.discard)

    cdp.handlers.append(on_frame)
    for window in (owner, bob):
        options = {"format": "jpeg", "quality": 92, "everyNthFrame": 1}
        await cdp.send("Page.startScreencast", options, window.session)
    await asyncio.sleep(0.8)
    start = time.time()
    await story(owner, bob)
    end = time.time()
    for window in (owner, bob):
        await cdp.send("Page.stopScreencast", {}, window.session)
    compose(owner, bob, start, end, out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out", help="the GIF to write, e.g. docs/media/realtime-demo.gif")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--portal", default="http://localhost:55173")
    parser.add_argument("--owner", default="owner@example.test")
    parser.add_argument("--member", default="bob@example.test")
    parser.add_argument("--password", default="tadas-local")
    parser.add_argument("--zoom", type=float, default=0.9, help="browser zoom, e.g. 0.9 for 90%%")
    parser.add_argument("--still", action="store_true", help="write a PNG per window instead")
    asyncio.run(record(parser.parse_args()))


if __name__ == "__main__":
    main()
