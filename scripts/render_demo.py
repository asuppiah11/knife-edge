"""Render the Knife-Edge demo video (docs/demo/knife-edge-demo.mp4) frame by frame.

The studio page is driven deterministically: the match clock, camera flights,
scrolling, a drawn cursor, captions and title cards are all computed per frame,
so the output is smooth regardless of how slow the headless GPU is.

    knife-edge serve --matches data/matches --ratings data/ratings.json      # in one terminal
    pip install playwright && playwright install chromium
    python scripts/render_demo.py --fps 24 --out /tmp/frames
    ffmpeg -framerate 24 -i /tmp/frames/%05d.jpg -c:v libx264 -pix_fmt yuv420p -crf 18 docs/demo/knife-edge-demo.mp4
"""
import argparse, asyncio, json, math, os, sys, time
from playwright.async_api import async_playwright

URL = "http://localhost:8000/"
VW, VH = 1680, 945                # CSS viewport; captured at 1920x1080 via device scale factor
DSF = 1920 / VW

ease = lambda t: 4 * t * t * t if t < .5 else 1 - (-2 * t + 2) ** 3 / 2
clamp = lambda v, a, b: max(a, min(b, v))

OVERLAY_CSS = """
#dir-cursor { position: fixed; z-index: 1000; width: 22px; height: 22px; margin: -11px 0 0 -11px; border-radius: 50%; background: rgba(16,25,43,.92); border: 2.5px solid #fff; box-shadow: 0 2px 10px rgba(16,25,43,.35); pointer-events: none; }
#dir-pulse { position: fixed; z-index: 999; width: 22px; height: 22px; margin: -11px 0 0 -11px; border-radius: 50%; border: 2px solid #e2452c; pointer-events: none; opacity: 0; }
#dir-cap { position: fixed; z-index: 1001; left: 50%; bottom: 44px; transform: translateX(-50%); max-width: 1180px; background: rgba(16,25,43,.94); color: #fff; font-family: "Instrument Sans", system-ui, sans-serif; font-weight: 500; font-size: 25px; line-height: 1.3; padding: 14px 24px 14px 20px; border-radius: 12px; display: flex; gap: 14px; align-items: center; opacity: 0; pointer-events: none; box-shadow: 0 10px 30px rgba(16,25,43,.25); text-align: left; }
#dir-cap i { flex: none; width: 8px; height: 26px; background: #e2452c; transform: skewX(-18deg); }
#dir-card { position: fixed; inset: 0; z-index: 1002; background: #f1f2ee radial-gradient(1400px 600px at 50% -10%, #ffffff 0%, rgba(255,255,255,0) 70%) no-repeat; display: flex; align-items: center; justify-content: center; text-align: center; opacity: 0; pointer-events: none; font-family: "Instrument Sans", system-ui, sans-serif; color: #10192b; }
#dir-card .brand { font-family: "Big Shoulders Display", "Arial Narrow", sans-serif; font-weight: 800; font-size: 118px; line-height: 1; letter-spacing: .01em; }
#dir-card .brand i { display: inline-block; width: 36px; height: 96px; background: #e2452c; transform: skewX(-18deg); margin: 0 26px 0 10px; vertical-align: -10px; }
#dir-card .tag { font-family: "Big Shoulders Display", "Arial Narrow", sans-serif; font-weight: 700; font-size: 44px; line-height: 1.15; margin: 26px auto 0; max-width: 1100px; }
#dir-card .sub { font-size: 22px; color: #4f5867; margin-top: 22px; line-height: 1.5; }
#dir-card .lines { font-size: 24px; line-height: 1.7; margin-top: 26px; color: #10192b; }
#dir-card .lines b { font-weight: 600; }
#dir-card .url { font-family: "Big Shoulders Display", "Arial Narrow", sans-serif; font-weight: 700; font-size: 40px; margin-top: 30px; }
#dir-card .fine { font-size: 16px; color: #8a919c; margin-top: 28px; max-width: 900px; margin-left: auto; margin-right: auto; }
#nudge { display: none !important; }
"""

TITLE = """<div><div class="brand">Knife<i></i>Edge</div>
<div class="tag">The next goal changes everything.<br>Knife-Edge tells you by how much, before it is scored.</div>
<div class="sub">Live match intelligence as Greeks on the win probability<br>Entry for the Microsoft × Premier League Inside the Game developer hackathon</div>
<div class="fine">Synthetic league. No real clubs, players, competitions or data.</div></div>"""

END = """<div><div class="brand">Knife<i></i>Edge</div>
<div class="lines"><b>Delta, Knife-edge, Theta and Vega</b> on the win probability, recomputed after every event<br>
Synthetic league and event-level match generator with hidden tactical regimes<br>
Closed-form engine, calibrated on 500 synthetic matches<br>
Five agents and one deterministic Verifier, in English, Spanish and Tamil<br>
FastAPI, Server-Sent Events replay, MCP tool server, Azure AI Foundry wiring</div>
<div class="url">github.com/asuppiah11/knife-edge</div>
<div class="fine">All data is synthetic; no real clubs, players or competitions appear. Probabilities are the engine's estimates of the match state and are not advice of any kind.</div></div>"""


class Director:
    def __init__(self, page, fps):
        self.page, self.fps = page, fps
        self.events = []            # (t, coroutine factory)
        self.captions = []          # (t0, t1, text)
        self.cards = []             # (t0, t1, html)
        self.scroll = (0, 0, 0, 0)  # y0, y1, t0, dur
        self.cursor = (VW * .62, VH * .55, VW * .62, VH * .55, 0, 0)
        self.pulses = []            # t of click
        self.clock_segs = []        # (t0, t1, c0, c1)  linear in sim seconds
        self.fly = None             # (t0, dur)
        self.sweep = None           # (sel, f0, f1, t0, dur, y_frac)
        self.sweep_last = None
        self.clock_end_state = (0.0, 0.0)  # (t, clock) at end of last segment
        self.T = 0.0

    # ----- timeline DSL
    def at(self, t, fn): self.events.append((t, fn))
    def caption(self, t0, t1, text): self.captions.append((t0, t1, text))
    def card(self, t0, t1, html): self.cards.append((t0, t1, html))
    def play(self, t0, t1, rate):
        c0 = self.clock_at(t0); self.clock_segs.append((t0, t1, c0, c0 + rate * (t1 - t0)))
    def jump(self, t0, t1, to): self.clock_segs.append((t0, t1, self.clock_at(t0), to))
    def clock_at(self, t):
        c = 0.0
        for t0, t1, c0, c1 in self.clock_segs:
            if t >= t1: c = c1
            elif t >= t0: return c0 + (c1 - c0) * (ease((t - t0) / (t1 - t0)) if c1 - c0 > 1000 else (t - t0) / (t1 - t0))
        return c
    def scroll_to(self, t, key, dur=1.2):
        async def go():
            y = await self.page.evaluate(f"window.__dirY['{key}']")
            cur = await self.page.evaluate("window.scrollY")
            self.scroll = (cur, y, t, dur)
        self.at(t, go)
    def cursor_to(self, t, sel=None, pos=None, dur=.7, frac=(.5, .5)):
        async def go():
            if sel:
                box = await self.page.locator(sel).first.bounding_box()
                x, y = box["x"] + box["width"] * frac[0], box["y"] + box["height"] * frac[1]
            else: x, y = pos() if callable(pos) else pos
            cx, cy = self.cursor_pos(t)
            self.cursor = (cx, cy, x, y, t, dur)
        self.at(t, go)
    def cursor_pos(self, t):
        x0, y0, x1, y1, t0, dur = self.cursor
        k = ease(clamp((t - t0) / dur, 0, 1)) if dur else 1
        return x0 + (x1 - x0) * k, y0 + (y1 - y0) * k
    def click(self, t, sel, real=True, lead=.75):
        self.cursor_to(t - lead, sel)
        async def go():
            self.pulses.append(t)
            if real:
                box = await self.page.locator(sel).first.bounding_box()
                await self.page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                await self.page.wait_for_timeout(250)
        self.at(t, go)
    def camera(self, t, name, dur=2.0):
        async def go():
            await self.page.evaluate(f"KE.flyTo('{name}'); if (KE.V && KE.V.fly) KE.V.fly.k = 0;")
            self.fly = (t, dur)
        self.at(t, go)
    def hover_sweep(self, t, sel, f0, f1, dur, y_frac=.5):
        async def go(): self.sweep = (sel, f0, f1, t, dur, y_frac)
        self.at(t, go)
        async def stop():
            self.sweep = None
            await self.page.mouse.move(VW * .62, VH * .18)   # off the chart, so the tooltip hides
            self.cursor = (*self.cursor_pos(t + dur), VW * .62, VH * .18, t + dur, .5)
        self.at(t + dur, stop)

    # ----- per frame
    async def frame(self, T, render=True):
        self.T = T
        while self.events and self.events[0][0] <= T:
            _, fn = self.events.pop(0); await fn()
        y0, y1, t0, dur = self.scroll
        y = y0 + (y1 - y0) * (ease(clamp((T - t0) / dur, 0, 1)) if dur else 1)
        if self.sweep:
            sel, f0, f1, s0, sdur, yf = self.sweep
            box = await self.page.locator(sel).first.bounding_box()
            f = f0 + (f1 - f0) * clamp((T - s0) / sdur, 0, 1)
            mx, my = box["x"] + box["width"] * f, box["y"] + box["height"] * yf
            await self.page.mouse.move(mx, my)
            self.cursor = (mx, my, mx, my, T, 0)
        cx, cy = self.cursor_pos(T)
        cap = next(((a, b, s) for a, b, s in self.captions if a <= T < b), None)
        cap_op, cap_txt = 0, ""
        if cap: cap_op, cap_txt = clamp(min((T - cap[0]) / .3, (cap[1] - T) / .3), 0, 1), cap[2]
        crd = next(((a, b, h) for a, b, h in self.cards if a - .6 <= T < b), None)
        crd_op, crd_html = 0, ""
        if crd: crd_op, crd_html = clamp(min((T - (crd[0] - .6)) / .6, (crd[1] - T) / .6, 1), 0, 1), crd[2]
        pulse = next((p for p in self.pulses if 0 <= T - p < .4), None)
        pk = (T - pulse) / .4 if pulse is not None else None
        flyk = None
        if self.fly:
            k = clamp((T - self.fly[0]) / self.fly[1], 0, 1); flyk = ease(k)
            if k >= 1: self.fly = None
        clock = self.clock_at(T)
        await self.page.evaluate("""(st) => {
          window.scrollTo(0, st.y);
          const c = document.getElementById('dir-cursor'); c.style.left = st.cx + 'px'; c.style.top = st.cy + 'px';
          const p = document.getElementById('dir-pulse'); if (st.pk == null) p.style.opacity = 0; else { p.style.left = st.cx + 'px'; p.style.top = st.cy + 'px'; p.style.opacity = 1 - st.pk; p.style.transform = `scale(${1 + 2.2 * st.pk})`; }
          const cap = document.getElementById('dir-cap'); cap.style.opacity = st.capOp; if (st.capTxt) cap.querySelector('span').textContent = st.capTxt;
          const card = document.getElementById('dir-card'); card.style.opacity = st.cardOp; if (st.cardHtml && card.dataset.h !== st.cardHtml) { card.innerHTML = st.cardHtml; card.dataset.h = st.cardHtml; }
          KE.step(st.clock);
          if (st.flyk != null && KE.V && KE.V.fly) KE.V.fly.k = st.flyk;
        }""", {"y": y, "cx": cx, "cy": cy, "pk": pk, "capOp": cap_op, "capTxt": cap_txt, "cardOp": crd_op, "cardHtml": crd_html, "clock": clock, "flyk": flyk})
        if render: await self.page.evaluate("new Promise(r => requestAnimationFrame(r))")


def build(d: Director):
    """The storyboard. Times are seconds of video."""
    # --- title
    d.card(0, 3.6, TITLE)
    d.caption(4.0, 8.6, "Knife-Edge reads a match the way a trader reads a position: how much does the next moment matter?")
    d.caption(8.8, 12.4, "Four Greeks on the win probability, recomputed after every event.")
    # --- play to the first goal
    d.scroll_to(9.0, "bandstage")
    d.click(11.2, '#speeds button[data-s="90"]')
    d.cursor_to(11.5, "#play")
    d.at(12.2, lambda: d.page.evaluate("KE.playingUI(true)"))
    d.at(12.2, lambda: _pulse(d, 12.2))
    d.play(12.2, 34.0, 90)                      # 0' -> 32'
    d.caption(12.8, 17.2, "Playing at 90×. Every pass, carry, pressure and shot is an event.")
    d.caption(23.0, 29.2, "16' goal. Delta +18.8: Oakenshaw's win probability jumped 18.8 points. The pillar is that moment.")
    d.caption(29.5, 33.8, "The cue on the right was written by the agents and verified against the event log first.")
    d.at(34.0, lambda: d.page.evaluate("KE.playingUI(false)"))
    # --- jump to 68'
    d.scroll_to(34.2, "river", 1.0)
    d.cursor_to(35.3, "#river", dur=.6, frac=(.715, .5))
    d.at(36.2, lambda: _pulse(d, 36.2))
    d.jump(36.2, 38.0, 4080)                    # -> 68'
    d.scroll_to(38.2, "bandstage", 1.0)
    d.caption(38.6, 42.6, "Minute 68, level at 1–1. The chip turns red: knife-edge.")
    d.caption(42.9, 48.6, "The next goal swings it 32 points, whoever scores. Gauge, river line and pitch readout agree.")
    d.scroll_to(45.5, "river", 1.0)
    d.hover_sweep(47.0, "#river", .30, .66, 4.0, y_frac=.55)
    d.caption(49.0, 52.6, "Hover the river to read the state at any minute.")
    # --- what-if
    d.scroll_to(52.0, "top", 1.0)
    d.click(54.2, "#whatif button:nth-of-type(2)")
    d.caption(54.6, 60.4, "What if Northam score now? Delta of a hypothetical: Oakenshaw drop from 23% to 6%.")
    # --- bad narrator + languages
    d.scroll_to(60.0, "bandstage", 1.0)
    d.click(62.0, "#inject")
    d.caption(62.4, 65.2, "Now swap in a narrator that invents numbers.")
    d.caption(65.4, 71.6, "The Verifier blocks both drafts, numbers not in the facts and a banned word, and the template takes over.")
    d.cursor_to(71.0, "#lang")
    d.at(71.8, lambda: _select(d, "#lang", "ta"))
    d.caption(72.2, 76.4, "The same cues in Spanish and Tamil, verified the same way.")
    d.at(76.6, lambda: _select(d, "#lang", "en"))
    d.at(76.7, lambda: d.page.click("#inject"))
    # --- cameras
    d.scroll_to(76.8, "stage", 1.0)
    d.cursor_to(77.2, "#cam-home")
    d.at(78.0, lambda: _pulse(d, 78.0))
    d.camera(78.0, "homeend", 2.2)
    d.caption(78.4, 84.6, "At every shot: the shooter, a disc for the chance size, a pillar for its Delta. Gold is a goal.")
    d.at(81.0, lambda: _hover_goal(d, 81.0))
    d.caption(84.9, 88.4, "Hover a shooter for the chance; click it for why the match moved.")
    d.at(85.2, lambda: _unhover(d, 85.2))
    d.click(87.0, '#cams button[data-cam="overhead"]', real=False)
    d.camera(87.0, "overhead", 2.0)
    d.click(89.2, '#layers button[data-layer="heat"]')
    d.caption(89.4, 93.0, "Overhead, with the touch map.")
    d.click(93.2, '#layers button[data-layer="heat"]')
    d.click(93.6, '#cams button[data-cam="broadcast"]', real=False)
    d.camera(93.6, "broadcast", 2.0)
    # --- play on
    d.cursor_to(95.0, "#play")
    d.at(95.8, lambda: d.page.evaluate("KE.playingUI(true)"))
    d.at(95.8, lambda: _pulse(d, 95.8))
    d.play(95.8, 107.0, 90)                     # 68' -> 85'
    d.caption(96.2, 102.0, "Replayed from the event log. The same engine streams it over Server-Sent Events and answers REST and MCP calls.")
    d.caption(102.3, 106.6, "Every number on screen traces back to an event id.")
    d.at(107.0, lambda: d.page.evaluate("KE.playingUI(false)"))
    # --- end card
    d.card(108.0, 117.0, END)
    return 117.0


async def _pulse(d, t): d.pulses.append(t)
async def _select(d, sel, val):
    await d.page.select_option(sel, val); d.pulses.append(d.T); await d.page.wait_for_timeout(250)
async def _hover_goal(d, t):
    pos = await d.page.evaluate("""() => { const V = KE.V, i = KE.S.shots.findIndex(s => s.ev.outcome === 'goal' && s.ev.team_id === KE.S.H.home.team_id); const root = V.shotsG.children.find(r => r.userData.i === i); if (!root) return null;
      const p = V.ball.position.clone(); root.userData.pillar.getWorldPosition(p); p.y += root.userData.pillar.scale.y * .55; p.project(V.camera); const r = document.getElementById('gl').getBoundingClientRect(); return [r.left + (p.x + 1) / 2 * r.width, r.top + (1 - p.y) / 2 * r.height]; }""")
    if not pos: return
    cx, cy = d.cursor_pos(t); d.cursor = (cx, cy, pos[0], pos[1], t, .8)
    async def arrive(): await d.page.mouse.move(pos[0], pos[1]); await d.page.wait_for_timeout(100)
    d.at(t + .85, arrive)
async def _unhover(d, t):
    await d.page.mouse.move(VW * .5, VH * .08); cx, cy = d.cursor_pos(t); d.cursor = (cx, cy, VW * .5, VH * .3, t, .6)


async def main(fps, out, start, end, quality):
    os.makedirs(out, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--enable-unsafe-swiftshader"])
        ctx = await b.new_context(viewport={"width": VW, "height": VH}, device_scale_factor=DSF)
        page = await ctx.new_page()
        errs = []; page.on("pageerror", lambda e: errs.append(str(e)))
        await page.goto(URL); await page.wait_for_function("document.getElementById('loading').classList.contains('hide')", timeout=60000)
        await page.add_style_tag(content=OVERLAY_CSS)
        await page.evaluate("""() => { for (const [id, html] of [['dir-pulse', ''], ['dir-cursor', ''], ['dir-cap', '<i></i><span></span>'], ['dir-card', '']]) { const e = document.createElement('div'); e.id = id; e.innerHTML = html; document.body.appendChild(e); }
          KE.S.fixedDt = 1 / 48; KE.seek(0);
          const top = el => el.getBoundingClientRect().top + window.scrollY, bar = document.querySelector('.bar').offsetHeight;
          const band = document.querySelector('.band'), stage = document.getElementById('stage'), river = document.getElementById('river');
          window.__dirY = { top: 0, bandstage: Math.max(0, top(band) - bar - 14), stage: Math.max(0, top(stage) - bar - 16), river: Math.max(0, top(river) + river.getBoundingClientRect().height + 160 - window.innerHeight) }; }""")
        await page.wait_for_timeout(300)
        d = Director(page, fps); total = build(d); d.events.sort(key=lambda e: e[0])
        n = int(total * fps); i0 = int(start * fps); i1 = int(end * fps) if end else n
        t0 = time.time()
        for i in range(0, i1):
            T = i / fps
            await d.frame(T, render=i >= i0 - fps)      # one second of warm-up renders before the first capture
            if i >= i0:
                await page.screenshot(path=f"{out}/{i:05d}.jpg", type="jpeg", quality=quality)
            if i % (fps * 5) == 0:
                print(f"{T:6.1f}s  frame {i}/{n}  {time.time() - t0:.0f}s elapsed", flush=True)
        print("page errors:", errs or "none", flush=True)
        await b.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fps", type=int, default=24); ap.add_argument("--out", default="frames")
    ap.add_argument("--start", type=float, default=0); ap.add_argument("--end", type=float, default=0); ap.add_argument("--quality", type=int, default=90)
    a = ap.parse_args()
    asyncio.run(main(a.fps, a.out, a.start, a.end, a.quality))
