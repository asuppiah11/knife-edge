"""Build a single-file, double-clickable copy of the studio.

Reads every answer the UI could ask the engine for (events, timeline, cues in
every audience and language, "why it moved" for every feed event, what-if
scenarios at every minute) from a running `knife-edge serve`, and bakes them
into web/index.html together with Three.js and the fonts. The result opens from
disk with no server, so it doubles as a no-setup demo and a backup for judging.

Usage:
    knife-edge serve --matches data/matches --ratings data/ratings.json   # in one terminal
    python scripts/build_static.py --base http://localhost:8000 --out dist/knife-edge-static.html
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
AUDIENCES = ("casual", "analyst", "bench")
LANGS = ("en", "es", "ta")
SCENARIOS = ({"home_goal": 1}, {"away_goal": 1}, {"red_home": 1}, {"red_away": 1}, {"chaos": 1.3})


def get(base: str, path: str):
    with urllib.request.urlopen(base + path, timeout=60) as r:
        return json.load(r)


def collect(base: str) -> dict:
    matches = get(base, "/matches")
    data = {"list": matches, "matches": {}}
    for m in matches:
        mid = m["match_id"]
        print(f"  {mid}: {m['home']['name']} v {m['away']['name']}", file=sys.stderr)
        d = {
            "match": get(base, f"/matches/{mid}"),
            "events": get(base, f"/matches/{mid}/events"),
            "timeline": get(base, f"/matches/{mid}/timeline"),
            "minutes": get(base, f"/matches/{mid}/minutes"),
            "moments": get(base, f"/matches/{mid}/moments?n=6"),
            "cues": {},
            "why": {},
            "scenario": {},
        }
        for aud in AUDIENCES:
            for lang in LANGS:
                for inject in (0, 1):
                    q = urllib.parse.urlencode({"audience": aud, "lang": lang, "max": 14, "inject": inject})
                    d["cues"][f"{aud}|{lang}|{inject}"] = get(base, f"/matches/{mid}/cues?{q}")
        for e in d["events"]:
            if e["type"] in ("shot", "card", "substitution"):
                d["why"][str(e["event_id"])] = get(base, f"/matches/{mid}/why/{e['event_id']}")
        end_min = math.ceil(d["events"][-1]["clock_s"] / 60) + 1
        for minute in range(0, end_min + 1):
            for sc in SCENARIOS:
                key = json.dumps(sc, sort_keys=True, separators=(",", ":"))
                q = urllib.parse.urlencode({"minute": minute, **sc})
                d["scenario"][f"{minute}|{key}"] = get(base, f"/matches/{mid}/scenario?{q}")
        data["matches"][mid] = d
        print(f"    {len(d['events'])} events, {len(d['why'])} why panels, {len(d['scenario'])} scenarios", file=sys.stderr)
    return data


SHIM = r"""
<script>
// ---- static build: every engine answer is embedded, fetch() reads from it ----
window.__KE_STATIC__ = __DATA__;
(function () {
  const D = window.__KE_STATIC__;
  const reply = v => Promise.resolve({ ok: true, json: () => Promise.resolve(v) });
  const miss = u => { console.warn('static build has no answer for', u); return reply(null); };
  window.fetch = function (url) {
    const u = new URL(String(url), 'http://static.local'), p = u.pathname, q = u.searchParams;
    if (p === '/matches') return reply(D.list);
    const m = p.match(/^\/matches\/([^/]+)(?:\/(.*))?$/); if (!m) return miss(url);
    const M = D.matches[m[1]]; if (!M) return miss(url);
    const rest = m[2] || '';
    if (rest === '') return reply(M.match);
    if (rest === 'events') return reply(M.events);
    if (rest === 'timeline') return reply(M.timeline);
    if (rest === 'minutes') return reply(M.minutes);
    if (rest === 'moments') return reply(M.moments);
    if (rest === 'cues') return reply(M.cues[`${q.get('audience') || 'casual'}|${q.get('lang') || 'en'}|${q.get('inject') === '1' ? 1 : 0}`] || []);
    if (rest.startsWith('why/')) return reply(M.why[rest.slice(4)] || miss(url));
    if (rest === 'scenario') {
      const minute = Math.round(parseFloat(q.get('minute') || '0')), sc = {};
      for (const k of ['home_goal', 'away_goal', 'red_home', 'red_away']) if (q.get(k) && +q.get(k)) sc[k] = +q.get(k);
      if (q.get('chaos') && +q.get('chaos') !== 1) sc.chaos = +q.get('chaos');
      const key = JSON.stringify(Object.fromEntries(Object.keys(sc).sort().map(k => [k, sc[k]])));
      let r = null; for (let d = 0; d < 4 && !r; d++) r = M.scenario[`${minute - d}|${key}`] || M.scenario[`${minute + d}|${key}`];
      return r ? reply(r) : miss(url);
    }
    return miss(url);
  };
  // Three.js and OrbitControls, inlined
  // (the inlined sources sit below this script, so they are read lazily, when init3D runs)
  window.__KE_THREE_URL__ = () => URL.createObjectURL(new Blob([document.getElementById('ke-three').textContent], { type: 'text/javascript' }));
  window.__KE_ORBIT__ = function (THREE) {
    const src = document.getElementById('ke-orbit').textContent;
    const { Controls, MOUSE, Quaternion, Spherical, TOUCH, Vector2, Vector3, Plane, Ray, MathUtils } = THREE;
    return new Function('Controls', 'MOUSE', 'Quaternion', 'Spherical', 'TOUCH', 'Vector2', 'Vector3', 'Plane', 'Ray', 'MathUtils', src + '\n;return OrbitControls;')(Controls, MOUSE, Quaternion, Spherical, TOUCH, Vector2, Vector3, Plane, Ray, MathUtils);
  };
})();
</script>
<script type="text/plain" id="ke-three">__THREE__</script>
<script type="text/plain" id="ke-orbit">__ORBIT__</script>
"""


def build(base: str, out: Path) -> Path:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    print("Collecting engine answers…", file=sys.stderr)
    data = collect(base)

    # fonts -> data URIs
    def font_uri(m: re.Match) -> str:
        p = WEB / m.group(1)
        return 'url("data:font/woff2;base64,' + base64.b64encode(p.read_bytes()).decode() + '") format("woff2")'
    html = re.sub(r'url\("(fonts/[^"]+\.woff2)"\) format\("woff2"\)', font_uri, html)

    # module loading -> inlined sources
    html = html.replace('<script type="importmap">{ "imports": { "three": "./vendor/three.module.min.js" } }</script>', "")
    html = html.replace("THREE = await import('three');", "THREE = await import(window.__KE_THREE_URL__());")
    html = html.replace("({ OrbitControls } = await import('./vendor/OrbitControls.js'));", "OrbitControls = window.__KE_ORBIT__(THREE);")
    for needle in ("import(window.__KE_THREE_URL__())", "window.__KE_ORBIT__(THREE)"):
        if needle not in html:
            raise SystemExit(f"index.html no longer matches the build script: could not patch {needle}")

    three = (WEB / "vendor" / "three.module.min.js").read_text(encoding="utf-8")
    orbit = (WEB / "vendor" / "OrbitControls.js").read_text(encoding="utf-8")
    orbit = re.sub(r"^import \{[^}]*\} from 'three';", "", orbit, count=1, flags=re.S)
    orbit = orbit.replace("export { OrbitControls };", "")
    for src in (three, orbit):
        if "</script" in src:
            raise SystemExit("vendor source contains '</script', cannot inline as-is")
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    shim = SHIM.replace("__DATA__", payload).replace("__THREE__", three).replace("__ORBIT__", orbit)
    html = html.replace("<title>Knife-Edge studio</title>", "<title>Knife-Edge studio (static)</title>" + shim, 1)
    html = html.replace('<span class="hint">Synthetic league. No real clubs, players or data.</span>',
                        '<span class="hint">Synthetic league. No real clubs, players or data. Static build.</span>')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out} ({out.stat().st_size / 1e6:.1f} MB)", file=sys.stderr)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--out", default=str(ROOT / "dist" / "knife-edge-static.html"))
    a = ap.parse_args()
    build(a.base.rstrip("/"), Path(a.out))
