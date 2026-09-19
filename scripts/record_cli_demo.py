"""Records the CLI demo GIF in the root README: two terminal panes side by
side. On the left Bob (a member `make seed` creates) runs `tadas` one
command at a time; on the right the owner runs `tadas listen` and each
change shows up a moment later.

Both are real subprocesses of the CLI on this checkout. Each person signs
in through the API over the Python client in `clients/python/`, the way
`record_demo.py` does, and the CLI gets its session token through the
environment: no `tadas login` and nothing secret in the picture. The task
list is emptied first. Every line is stamped when it is typed or when it
arrives from the pipe, and the panes are drawn from those stamps on one
timeline into a GIF.

    make up
    uv run --with pillow python scripts/record_cli_demo.py docs/media/cli-demo.gif

Other stacks: --api. --still writes a PNG per pane of the final state
instead of the GIF; --stills-dir writes those PNGs next to the GIF as well,
to check the layout.
"""

import argparse
import asyncio
import os
import re
import shutil
import signal
import sys
import tempfile
import time
from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFont

from tadas.client.client import ApiClient
from tadas.client.types import TaskScope, TaskStatus

WIDTH, HEIGHT = 420, 330  # each pane in the GIF; the two match the portal GIF's width
SCALE = 2  # render at twice the size, then downscale, for crisp text
FPS = 12
GAP = 12
FONT_SIZE, LINE_HEIGHT, TITLE_HEIGHT, PAD = 12, 18, 26, 10
KEY_DELAY = 0.07  # seconds per typed character
FONTS = [
    "/System/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]

BACKGROUND = (28, 29, 34)
TITLE_BAR = (46, 48, 56)
TITLE_TEXT = (170, 172, 180)
TEXT = (226, 226, 222)
DIM = (140, 142, 150)
PROMPT = (98, 200, 120)
CURSOR = (200, 200, 196)
DOTS = [(237, 106, 94), (245, 191, 79), (98, 197, 84)]
ACCENTS = [BACKGROUND, TITLE_BAR, TEXT, DIM, PROMPT, *DOTS]
STAMP = re.compile(r"^\d\d:\d\d:\d\d  ")


def font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONTS:
        if os.path.exists(path):
            return ImageFont.truetype(path, FONT_SIZE * SCALE)
    return ImageFont.load_default(FONT_SIZE * SCALE)


class Api:
    """The two things the recorder asks of the API, over the Python client."""

    def __init__(self, base: str) -> None:
        self.base = base

    def _client(self, token: str | None = None) -> ApiClient:
        return ApiClient(self.base, app="cli", app_version="cli@demo", token=token)

    async def token(self, email: str, password: str) -> str:
        """A session token for the person's first org, what `tadas login` would keep."""
        async with self._client() as client:
            login = await client.login(email, password)
            org = login.memberships[0].org
            issued = await client.exchange_session(login.token, org.id)
        return issued.token

    async def clear_tasks(self, token: str) -> int:
        cleared = 0
        async with self._client(token) as client:
            for status in (TaskStatus.open, TaskStatus.done):
                while True:
                    page = await client.tasks(status, TaskScope.team, limit=200)
                    if not page.items:
                        break
                    for task in page.items:
                        await client.delete_task(task.id)
                        cleared += 1
        return cleared


class Pane:
    """One terminal: its lines, and when each line came to say what it says.
    An event is (moment, row, text); typing a prompt is many events on one row."""

    def __init__(self, name: str, title: str) -> None:
        self.name, self.title = name, title
        self.events: list[tuple[float, int, str]] = []
        self.rows = 0

    def say(self, text: str) -> None:
        self.events.append((time.monotonic(), self.rows, text))
        self.rows += 1

    async def type(self, command: str) -> None:
        """A prompt line typed one character at a time, then a beat before Enter."""
        row = self.rows
        self.rows += 1
        for n in range(len(command) + 1):
            self.events.append((time.monotonic(), row, "$ " + command[:n]))
            await asyncio.sleep(KEY_DELAY)
        await asyncio.sleep(0.3)

    def lines_at(self, count: int) -> list[str]:
        """The lines after the first `count` events."""
        lines: dict[int, str] = {}
        for _, row, text in self.events[:count]:
            lines[row] = text
        return [lines[row] for row in sorted(lines)]

    def events_by(self, moment: float) -> int:
        return sum(1 for stamp, _, _ in self.events if stamp <= moment)


class Cli:
    """Runs the CLI on this checkout as one person, with the credential in the
    environment and nothing on disk but an empty TADAS_HOME."""

    def __init__(self, api: str, token: str, home: str) -> None:
        self.env = {
            **os.environ,
            "TADAS_API_URL": api,
            "TADAS_TOKEN": token,
            "TADAS_HOME": home,
            "PYTHONUNBUFFERED": "1",
        }

    async def spawn(self, *args: str, stderr: int | None) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "tadas.apps.cli.main",
            *args,
            env=self.env,
            stdout=asyncio.subprocess.PIPE,
            stderr=stderr,
        )

    async def run(self, *args: str) -> list[str]:
        """One command; what it says on stderr belongs in the pane too."""
        process = await self.spawn(*args, stderr=asyncio.subprocess.STDOUT)
        out, _ = await process.communicate()
        return out.decode().splitlines()


def shell_words(args: Sequence[str]) -> str:
    """How the command reads at a prompt: arguments with spaces in double quotes."""
    return " ".join(f'"{a}"' if " " in a else a for a in args)


async def command(pane: Pane, cli: Cli, *args: str) -> list[str]:
    """Types the command, runs it, shows what it printed, then pauses as a
    person would before the next one."""
    await pane.type(shell_words(["tadas", *args]))
    lines = await cli.run(*args)
    for line in lines:
        pane.say(line)
    await asyncio.sleep(1.7)
    return lines


def short_id(added: list[str]) -> str:
    """The id `add` prints: `added <short id>  <title>`."""
    return added[0].split()[1]


async def story(bob: Pane, cli: Cli) -> None:
    """Bob's session: two tasks, one renamed, completed and reopened, a third
    added, one removed, and a last one completed."""
    migrate = short_id(await command(bob, cli, "add", "Migrate DB"))
    review = short_id(await command(bob, cli, "add", "Review PR #42"))
    await command(bob, cli, "edit", migrate, "--title", "Migrate the DB")
    await command(bob, cli, "done", migrate)
    await command(bob, cli, "reopen", migrate)
    changelog = short_id(await command(bob, cli, "add", "Write changelog"))
    await command(bob, cli, "rm", review)
    await command(bob, cli, "done", changelog)
    bob.say("$ ")


async def follow(process: asyncio.subprocess.Process, pane: Pane) -> None:
    """Stamps each line of the listener as it arrives on the pipe."""
    assert process.stdout is not None
    while line := await process.stdout.readline():
        pane.say(line.decode().rstrip("\n"))


async def wait_for_first_line(pane: Pane) -> None:
    """The listener is ready once it has said whom it listens as."""
    for _ in range(200):
        if pane.rows > 1:
            return
        await asyncio.sleep(0.1)
    raise TimeoutError("the listener did not start")


class Renderer:
    def __init__(self) -> None:
        self.font = font()
        self.char = self.font.getlength("M")
        self.cols = int((WIDTH - 2 * PAD) * SCALE // self.char)
        self.visible = (HEIGHT - TITLE_HEIGHT - 2 * PAD) // LINE_HEIGHT

    def wrap(self, lines: Sequence[str]) -> list[str]:
        """Long lines wrap the way a terminal wraps them, at the last column."""
        wrapped: list[str] = []
        for line in lines:
            pieces = [line[i : i + self.cols] for i in range(0, len(line), self.cols)]
            wrapped.extend(pieces or [""])
        return wrapped

    def pane(self, pane: Pane, lines: Sequence[str]) -> Image.Image:
        image = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), BACKGROUND)
        draw = ImageDraw.Draw(image)
        self._title_bar(draw, pane.title)
        rows = self.wrap(lines)[-self.visible :]
        y = (TITLE_HEIGHT + PAD) * SCALE
        for n, row in enumerate(rows):
            x = PAD * SCALE
            for colour, text in self._segments(row):
                draw.text((x, y), text, font=self.font, fill=colour)
                x += self.font.getlength(text)
            if n == len(rows) - 1 and lines and lines[-1].startswith("$ "):
                draw.rectangle((x + 2, y, x + 2 + self.char, y + LINE_HEIGHT * SCALE - 4), CURSOR)
            y += LINE_HEIGHT * SCALE
        return image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)

    def _title_bar(self, draw: ImageDraw.ImageDraw, title: str) -> None:
        draw.rectangle((0, 0, WIDTH * SCALE, TITLE_HEIGHT * SCALE), TITLE_BAR)
        radius, middle = 5 * SCALE, TITLE_HEIGHT * SCALE // 2
        for n, colour in enumerate(DOTS):
            x = (PAD + 4 + n * 16) * SCALE
            draw.ellipse((x - radius, middle - radius, x + radius, middle + radius), colour)
        draw.text((WIDTH * SCALE // 2, middle), title, font=self.font, fill=TITLE_TEXT, anchor="mm")

    @staticmethod
    def _segments(row: str) -> list[tuple[tuple[int, int, int], str]]:
        if row.startswith("$"):
            return [(PROMPT, "$"), (TEXT, row[1:])]
        if stamp := STAMP.match(row):
            return [(DIM, stamp.group()), (TEXT, row[stamp.end() :])]
        return [(DIM, row)]


def compose(renderer: Renderer, bob: Pane, owner: Pane, start: float, end: float, out: str) -> None:
    canvas_w, canvas_h = WIDTH * 2 + GAP * 3, HEIGHT + GAP * 2
    frames: list[Image.Image] = []
    durations: list[int] = []
    step_ms = round(1000 / FPS)
    moment, last = start, None
    while moment <= end:
        state = (bob.events_by(moment), owner.events_by(moment))
        if state == last:
            durations[-1] += step_ms  # an unchanged moment lengthens the frame before it
        else:
            canvas = Image.new("RGB", (canvas_w, canvas_h), (220, 220, 216))
            canvas.paste(renderer.pane(bob, bob.lines_at(state[0])), (GAP, GAP))
            canvas.paste(renderer.pane(owner, owner.lines_at(state[1])), (GAP * 2 + WIDTH, GAP))
            frames.append(canvas)
            durations.append(step_ms)
            last = state
        moment += step_ms / 1000

    # One palette for the whole GIF, from frames across the recording plus the
    # terminal's own colours, so the prompt and the title bar keep theirs.
    samples = frames[:: max(1, len(frames) // 12)]
    sheet = Image.new("RGB", (canvas_w, canvas_h * (len(samples) + 1)))
    for n, sample in enumerate(samples):
        sheet.paste(sample, (0, canvas_h * n))
    swatch = canvas_w // len(ACCENTS)
    for n, colour in enumerate(ACCENTS):
        top = canvas_h * len(samples)
        sheet.paste(colour, (n * swatch, top, (n + 1) * swatch, top + canvas_h))
    palette = sheet.quantize(colors=64, method=Image.Quantize.MEDIANCUT)
    quantized = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    quantized[0].save(
        out, save_all=True, append_images=quantized[1:], duration=durations, loop=0, optimize=True
    )
    seconds = sum(durations) / 1000
    print(f"{out}: {len(frames)} frames, {seconds:.1f}s, {os.path.getsize(out) / 1e6:.2f} MB")


def stills(renderer: Renderer, panes: Sequence[Pane], out: str, directory: str) -> None:
    os.makedirs(directory, exist_ok=True)
    stem = os.path.basename(out).removesuffix(".gif")
    for pane in panes:
        path = os.path.join(directory, f"{stem}-{pane.name}.png")
        renderer.pane(pane, pane.lines_at(len(pane.events))).save(path)
        print(path)


async def record(args: argparse.Namespace) -> None:
    api = Api(args.api)
    owner_token = await api.token(args.owner, args.password)
    bob_token = await api.token(args.member, args.password)
    print(f"cleared {await api.clear_tasks(owner_token)} tasks")

    home = tempfile.mkdtemp(prefix="tadas-demo-cli-")
    bob = Pane("bob", "bob - command mode")
    owner = Pane("owner", "owner - tadas listen")
    listener = None
    try:
        start = time.monotonic()
        await owner.type("tadas listen")
        # The listener's stderr (the "stopped" after Ctrl-C) stays out of the pane.
        listener = await Cli(args.api, owner_token, home).spawn("listen", stderr=None)
        following = asyncio.create_task(follow(listener, owner))
        await wait_for_first_line(owner)
        await asyncio.sleep(1.2)
        await story(bob, Cli(args.api, bob_token, home))
        await asyncio.sleep(1.5)
        end = time.monotonic()
        listener.send_signal(signal.SIGINT)
        await asyncio.wait_for(following, timeout=5)
    finally:
        if listener is not None and listener.returncode is None:
            listener.terminate()
            await listener.wait()
        shutil.rmtree(home, ignore_errors=True)

    renderer = Renderer()
    stills_dir = args.stills_dir or (os.path.dirname(args.out) or "." if args.still else None)
    if stills_dir is not None:
        stills(renderer, (bob, owner), args.out, stills_dir)
    if not args.still:
        compose(renderer, bob, owner, start, end, args.out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out", help="the GIF to write, e.g. docs/media/cli-demo.gif")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--owner", default="owner@example.test")
    parser.add_argument("--member", default="bob@example.test")
    parser.add_argument("--password", default="tadas-local")
    parser.add_argument("--still", action="store_true", help="write a PNG per pane instead")
    parser.add_argument("--stills-dir", help="also write a PNG per pane into this directory")
    asyncio.run(record(parser.parse_args()))


if __name__ == "__main__":
    main()
