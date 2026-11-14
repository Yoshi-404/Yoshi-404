#!/usr/bin/env python3
"""
Generates animated ASCII-Sharks + Live GitHub Telemetry SVGs (dark & light themes).
- Left viewport: 16-frame seamless swimming simulation ported from stackedlol/ascii-sharks
  (continuous S-loop figure-8 trajectory, Reynolds-style fleeing fish schools, diffusing cyan wake,
  and authentic cell-by-cell ASCII supersampled rasterization).
- Right panel: Live GitHub telemetry fetched dynamically from the GitHub API for @Yoshi-404
  (public repos, total commits, real language byte percentages, and latest active repository),
  with CSS-animated progress bars and blinking terminal cursor.
"""

import json
import math
import os
import urllib.request
from datetime import datetime, timezone

GITHUB_USER = "Yoshi-404"

# stackedlol/ascii-sharks constants
SHARK_NODES = 16
SKIN_RAMP = ":;t%SX8#@"
FIN_GLYPHS = "%;tS:"
RIDGE_GLYPHS = "@8%"
EDGE_HEAVY = ":;"
EDGE_LIGHT = ".',`"
ACCENTS = ["#e0892c", "#e03a32", "#b44ae0", "#33c8cc", "#3cb54a", "#3150e8", "#d9c14a"]

FLAG_BODY = 1
FLAG_EDGE = 2
FLAG_FIN = 3
FLAG_RIDGE = 4
FLAG_EYE = 5

SUBSAMPLES = [(0.25, 0.3), (0.75, 0.3), (0.25, 0.72), (0.75, 0.72)]


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def smoothstep(a, b, x):
    t = clamp((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def hash3(a, b, c):
    h = (int(a) * 374761393 + int(b) * 668265263 + int(c) * 2147483647) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    h = (h ^ (h >> 16)) & 0xFFFFFFFF
    return h / 4294967296.0


def classic_half_width(s):
    if s < 0.13:
        return 0.09 * math.pow(math.sin(((s / 0.13) * math.pi) / 2.0), 0.95)
    if s < 0.3:
        return 0.09 + 0.016 * smoothstep(0.13, 0.3, s)
    if s < 0.84:
        return 0.019 + 0.087 * math.pow(1.0 - (s - 0.3) / 0.54, 1.25)
    k = (s - 0.84) / 0.16
    return 0.019 * (1.0 - k) + 0.012 * math.sin(k * math.pi)


def hammerhead_half_width(s):
    if s < 0.06:
        return 0.045
    if s < 0.3:
        return 0.045 + 0.061 * smoothstep(0.06, 0.3, s)
    return classic_half_width(s) * 0.92


HAMMERHEAD_SHAPE = {
    "halfWidth": hammerhead_half_width,
    "head": {"span": 0.175, "sweep": 0.035, "depth": 0.09, "notch": 0.0},
    "pectoral": (0.17, 0.4, 0.5, 0.23),
    "falcate": True,
    "pelvic": (0.56, 0.63, 0.67, 0.075),
    "caudal": 0.115,
    "dorsal": (0.28, 0.44),
    "secondDorsal": (0.7, 0.74),
    "eye": None,
    "gills": (0.16, 0.26),
    "tint": (0.92, 0.97, 1.05),
}


def in_triangle(px, py, ax, ay, bx, by, cx, cy):
    d1 = (px - bx) * (ay - by) - (ax - bx) * (py - by)
    d2 = (px - cx) * (by - cy) - (bx - cx) * (py - cy)
    d3 = (px - ax) * (cy - ay) - (cx - ax) * (py - ay)
    neg = d1 < 0 or d2 < 0 or d3 < 0
    pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (neg and pos)


def sample_shark(px, py, L, spine, arc, arc_total, shape, fin_tip_left, fin_tip_right):
    N = len(spine)
    best = float("inf")
    best_s = 0.0
    best_sign = 1.0
    best_nx = 0.0
    best_ny = 0.0

    for k in range(N - 1):
        ax, ay = spine[k]
        bx, by = spine[k + 1]
        sx = bx - ax
        sy = by - ay
        len2 = sx * sx + sy * sy or 1.0
        u = clamp(((px - ax) * sx + (py - ay) * sy) / len2, 0.0, 1.0)
        qx = ax + sx * u
        qy = ay + sy * u
        d2 = (px - qx) ** 2 + (py - qy) ** 2
        if d2 < best:
            best = d2
            seg_len = math.sqrt(len2)
            best_s = (arc[k] + u * seg_len) / arc_total
            best_sign = 1.0 if (sx * (py - ay) - sy * (px - ax)) >= 0 else -1.0
            best_nx = (-sy / seg_len) * best_sign
            best_ny = (sx / seg_len) * best_sign

    a = math.sqrt(best)
    s = best_s
    u = s * L
    w = shape["halfWidth"](s) * L
    hit_dist = a
    hit_s = s
    hit_v = a * best_sign

    head = shape["head"]
    if head and u < L * (head["sweep"] + head["depth"] + head["notch"]):
        span = L * head["span"]
        r = a / span
        front = L * head["sweep"] * r * r + L * head["notch"] * max(0.0, 1.0 - r / 0.14)
        depth = L * head["depth"] * (1.0 - 0.2 * (r ** 4))
        if r <= 1.0 and front <= u <= front + depth:
            flag = FLAG_EYE if r > 0.84 else FLAG_BODY
            shade = 0.0 if r > 0.84 else (0.62 - 0.2 * r + (0.1 if u < front + L * 0.012 else 0.0))
            return True, flag, shade, hit_s, hit_v, hit_dist

    if a <= w:
        across = a / (w or 1.0)
        facing = (best_nx * -0.6 + best_ny * -0.8) * across
        shade = 0.58 - across * across * 0.42 + facing * 0.26
        flag = FLAG_BODY
        if shape["dorsal"][0] < s < shape["dorsal"][1] and across < 0.3:
            flag = FLAG_RIDGE
            shade = 1.0
        elif shape["secondDorsal"][0] < s < shape["secondDorsal"][1] and across < 0.4:
            shade = max(shade, 0.82)
        elif shape["eye"] and shape["eye"][0] < s < shape["eye"][1] and across > 0.6:
            flag = FLAG_EYE
            shade = 0.0
        elif shape["gills"][0] < s < shape["gills"][1] and across > 0.58:
            if int(((s - shape["gills"][0]) / (shape["gills"][1] - shape["gills"][0])) * 5) % 2 == 0:
                shade *= 0.45
        elif s < 0.05:
            shade = max(shade, 0.7)
        return True, flag, shade, hit_s, hit_v, hit_dist

    tip = fin_tip_right if best_sign > 0 else fin_tip_left
    p0, p1, p2, _ = shape["pectoral"]
    if in_triangle(u, a, L * p0, 0, L * p1, 0, L * p2, tip) and not (
        shape["falcate"] and in_triangle(u, a, L * p1, 0, L * (p1 + (p2 - p1) * 0.33), tip * 0.55, L * p2, tip)
    ):
        shade = 0.38 + 0.22 * (1.0 - clamp(a / tip, 0.0, 1.0))
        return True, FLAG_FIN, shade, hit_s, hit_v, hit_dist

    v0, v1, v2, vr = shape["pelvic"]
    if in_triangle(u, a, L * v0, 0, L * v1, 0, L * v2, L * vr) or (
        shape["caudal"] > 0 and in_triangle(u, a, L * 0.86, 0, L * 0.95, 0, L, L * shape["caudal"])
    ):
        return True, FLAG_FIN, 0.36, hit_s, hit_v, hit_dist

    return False, 0, 0.0, hit_s, hit_v, hit_dist


def xml_escape(s):
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def fetch_github_telemetry():
    """Fetches real-time profile, repository, commit, and language metrics from GitHub API."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    headers = {
        "User-Agent": "yoshi-404-telemetry-generator",
        "Accept": "application/vnd.github+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def get_json(url, extra_headers=None):
        hdrs = dict(headers)
        if extra_headers:
            hdrs.update(extra_headers)
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        user_data = get_json(f"https://api.github.com/users/{GITHUB_USER}")
        repos_data = get_json(f"https://api.github.com/users/{GITHUB_USER}/repos?per_page=100&sort=pushed")

        public_repos = user_data.get("public_repos", len(repos_data))
        latest_repo = repos_data[0]["name"] if repos_data else "Yoshi-404"

        # Aggregate language bytes across all non-fork repos
        lang_bytes = {}
        total_stars = 0
        for r in repos_data:
            total_stars += r.get("stargazers_count", 0)
            if r.get("fork"):
                continue
            l_url = r.get("languages_url")
            if l_url:
                try:
                    l_map = get_json(l_url)
                    for k, v in l_map.items():
                        lang_bytes[k] = lang_bytes.get(k, 0) + v
                except Exception:
                    pass

        # Group into clean developer categories while preserving real byte percentages
        py_bytes = lang_bytes.get("Python", 0)
        ts_js_bytes = lang_bytes.get("TypeScript", 0) + lang_bytes.get("JavaScript", 0)
        web_ui_bytes = lang_bytes.get("CSS", 0) + lang_bytes.get("HTML", 0) + lang_bytes.get("Dart", 0)
        sys_bytes = (
            lang_bytes.get("C++", 0)
            + lang_bytes.get("C", 0)
            + lang_bytes.get("Shell", 0)
            + lang_bytes.get("PowerShell", 0)
            + lang_bytes.get("Dockerfile", 0)
        )
        total_bytes = max(1, py_bytes + ts_js_bytes + web_ui_bytes + sys_bytes)

        p_py = round(py_bytes * 100.0 / total_bytes, 1)
        p_js = round(ts_js_bytes * 100.0 / total_bytes, 1)
        p_ui = round(web_ui_bytes * 100.0 / total_bytes, 1)
        p_sys = round(max(0.5, 100.0 - (p_py + p_js + p_ui)), 1)

        # Commit count via GitHub search API
        total_commits = 98
        try:
            c_data = get_json(
                f"https://api.github.com/search/commits?q=author:{GITHUB_USER}",
                extra_headers={"Accept": "application/vnd.github.cloak-preview+json"},
            )
            if "total_count" in c_data:
                total_commits = c_data["total_count"]
        except Exception:
            pass

        return {
            "public_repos": public_repos,
            "total_commits": total_commits,
            "latest_repo": latest_repo,
            "langs": [
                ("Python", "OpenGL / 3D / AI", p_py, "cyan"),
                ("JS & TypeScript", "Next.js / Web", p_js, "indigo"),
                ("HTML / CSS / UI", "Frontend & Design", p_ui, "rose"),
                ("C / C++ & Shell", "Systems / Embedded", p_sys, "emerald"),
            ],
            "updated_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
    except Exception as e:
        print("Warning: fallback telemetry used due to:", e)
        return {
            "public_repos": 17,
            "total_commits": 98,
            "latest_repo": "Antigravity-agent-teams",
            "langs": [
                ("Python", "OpenGL / 3D / AI", 63.6, "cyan"),
                ("JS & TypeScript", "Next.js / Web", 18.9, "indigo"),
                ("HTML / CSS / UI", "Frontend & Design", 11.1, "rose"),
                ("C / C++ & Shell", "Systems / Embedded", 6.4, "emerald"),
            ],
            "updated_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }


def simulate_ocean_frames(num_frames, cols, rows, cw, ch, vx, vy):
    """
    Simulates a continuous swimming shark loop across the viewport using follow-the-leader
    spine kinematics from stackedlol/ascii-sharks (world.ts) + diffusing cyan wake field
    and reactive fish schools.
    """
    W = cols * cw
    H = rows * ch
    L = 255.0
    N = SHARK_NODES
    seg = L / (N - 1)
    shape = HAMMERHEAD_SHAPE
    shark_id = 7

    # Spine nodes [x, y]
    nodes = [[0.0, 0.0] for _ in range(N)]

    # Snout path function: smooth horizontal cruise from right to left across the viewport
    # with gentle vertical S-curve undulation so it looks like a real ocean patrol!
    # Wait: to make a seamless loop where the shark swims all the way across the screen
    # OR cruises in a wide loop, let's check:
    # If the shark swims from right (x = W + 40) to left (x = -L - 20), at the wrap boundary
    # it enters smoothly from the right again! Even better: while Shark 1 exits left, a second
    # smaller classic shark or the same hammerhead glides in, OR the hammerhead patrols a wide
    # S-curve across the viewport!
    # Let's test a continuous right-to-left swim with a wide S-wave across the full viewport,
    # PLUS a second smaller shark at deeper depth so there is ALWAYS a shark visible in the center!
    # Wait: in stackedlol/ascii-sharks DEFAULT_SHARKS has multiple sharks at different depths!
    # Having 1 large Hammerhead swimming across + 1 medium Classic shark cruising on an offset phase
    # means the ocean is ALWAYS teeming with motion just like the real ascii-sharks canvas!

    def get_shark_path(shark_idx, step_t):
        # step_t in [0, 1) over the loop cycle
        if shark_idx == 0:
            # Main Hammerhead (size 1.0, depth 1.0): offset by 0.36 so at frame 0 it is centered!
            t1 = (step_t + 0.36) % 1.0
            travel = W + L + 36.0
            sx = (W + 24.0) - t1 * travel
            sy = H * 0.44 + math.sin(t1 * math.pi * 2.0) * 32.0
            dx = -travel
            dy = math.cos(t1 * math.pi * 2.0) * (math.pi * 2.0) * 32.0
            heading = math.atan2(dy, dx)
            turn = -math.sin(t1 * math.pi * 2.0) * 0.45
            return sx, sy, heading, turn, 255.0, 1.0, HAMMERHEAD_SHAPE, 7, t1
        else:
            # Secondary Classic shark (size 0.72, depth 0.68): phase-shifted by 0.86
            t2 = (step_t + 0.86) % 1.0
            L2 = 180.0
            travel = W + L2 + 36.0
            sx = (W + 18.0) - t2 * travel
            sy = H * 0.66 - math.sin(t2 * math.pi * 2.0) * 24.0
            dx = -travel
            dy = -math.cos(t2 * math.pi * 2.0) * (math.pi * 2.0) * 24.0
            heading = math.atan2(dy, dx)
            turn = math.sin(t2 * math.pi * 2.0) * 0.35
            return sx, sy, heading, turn, L2, 0.65, {
                "halfWidth": classic_half_width,
                "head": None,
                "pectoral": (0.15, 0.43, 0.55, 0.26),
                "falcate": True,
                "pelvic": (0.57, 0.65, 0.69, 0.085),
                "caudal": 0.085,
                "dorsal": (0.33, 0.47),
                "secondDorsal": (0.71, 0.76),
                "eye": (0.1, 0.14),
                "gills": (0.19, 0.29),
                "tint": (0.85, 0.93, 1.05),
            }, 13, t2

    # Build spine histories by running 2 full cycles (warm-up cycle + render cycle)
    sharks_spines = [[], []]
    substeps = 4
    total_steps = num_frames * substeps

    for s_idx in (0, 1):
        _, _, _, _, L_s, _, _, _, _ = get_shark_path(s_idx, 0.0)
        seg_s = L_s / (N - 1)
        sx0, sy0, h0, _, _, _, _, _, _ = get_shark_path(s_idx, 0.0)
        sp = [[sx0 - math.cos(h0) * k * seg_s, sy0 - math.sin(h0) * k * seg_s] for k in range(N)]
        prev_t_local = 0.0

        for cycle in range(2):
            for step in range(total_steps):
                t_norm = step / float(total_steps)
                sx, sy, heading, turn, L_s, depth, shp, sh_id, t_local = get_shark_path(s_idx, t_norm)
                # If wrap-around jump occurred on t_local, re-seed spine smoothly
                if t_local < prev_t_local or (cycle == 0 and step == 0):
                    sp = [[sx - math.cos(heading) * k * seg_s, sy - math.sin(heading) * k * seg_s] for k in range(N)]
                else:
                    sp[0][0] = sx
                    sp[0][1] = sy
                    # Follow-the-leader constraint (exact world.ts algorithm)
                    for k in range(1, N):
                        dx = sp[k][0] - sp[k - 1][0]
                        dy = sp[k][1] - sp[k - 1][1]
                        d = math.hypot(dx, dy) or 1.0
                        sp[k][0] = sp[k - 1][0] + (dx / d) * seg_s
                        sp[k][1] = sp[k - 1][1] + (dy / d) * seg_s
                prev_t_local = t_local

                if cycle == 1 and step % substeps == 0:
                    frame_i = step // substeps
                    # Apply travelling tail-beat wave
                    phase = frame_i * (math.pi * 2.0 / num_frames) * 3.0 + s_idx * 1.7
                    render_spine = []
                    for k in range(N):
                        s_frac = k / float(N - 1)
                        ka = max(0, k - 1)
                        kb = min(N - 1, k + 1)
                        tx = sp[ka][0] - sp[kb][0]
                        ty = sp[ka][1] - sp[kb][1]
                        tl = math.hypot(tx, ty) or 1.0
                        tx /= tl
                        ty /= tl
                        amp = L_s * 0.052 * (0.1 + 0.9 * math.pow(s_frac, 1.8))
                        off = amp * math.sin(phase - s_frac * 5.2)
                        render_spine.append((sp[k][0] - ty * off, sp[k][1] + tx * off))
                    sharks_spines[s_idx].append((render_spine, turn, phase, L_s, depth, shp, sh_id))

    # Simulate diffusing wake energy across the loop (2 cycles for seamless wrap)
    energy = [0.0] * (cols * rows)
    frame_energies = [None] * num_frames

    for cycle in range(2):
        for f in range(num_frames):
            # Deposit wake at shark tails
            for s_idx in (0, 1):
                rspine, _, _, _, _, _, _ = sharks_spines[s_idx][f]
                for tx, ty in rspine[N - 6 :]:
                    c0 = int(tx // cw)
                    r0 = int(ty // ch)
                    for dr in range(-2, 3):
                        for dc in range(-2, 3):
                            cc, rr = c0 + dc, r0 + dr
                            if 0 <= cc < cols and 0 <= rr < rows:
                                dist = math.hypot(dc, dr * 1.3)
                                if dist <= 2.4:
                                    energy[rr * cols + cc] = min(1.5, energy[rr * cols + cc] + 0.32 * (1.0 - dist / 2.8))

            # Diffuse + decay wake
            new_energy = [0.0] * (cols * rows)
            decay = 0.76
            for r in range(rows):
                for c in range(cols):
                    i = r * cols + c
                    l = energy[i - 1] if c > 0 else energy[i]
                    rt = energy[i + 1] if c < cols - 1 else energy[i]
                    u = energy[i - cols] if r > 0 else energy[i]
                    d = energy[i + cols] if r < rows - 1 else energy[i]
                    new_energy[i] = (energy[i] * 4.0 + l + rt + u + d) * 0.125 * decay
            energy = new_energy
            if cycle == 1:
                frame_energies[f] = list(energy)

    # Fish schools base positions (two schools that drift and scatter when a shark approaches)
    base_fish = [
        # School A (upper-mid)
        (14, 4), (16, 4), (18, 4), (15, 5), (17, 5), (19, 5), (21, 5),
        (16, 6), (18, 6), (20, 6), (22, 6), (19, 7), (21, 7),
        # School B (lower-right)
        (44, 17), (46, 17), (48, 17), (45, 18), (47, 18), (49, 18), (51, 18),
        (46, 19), (48, 19), (50, 19), (52, 19), (49, 20), (51, 20),
        # School C (upper-right)
        (50, 4), (52, 4), (54, 4), (51, 5), (53, 5), (55, 5), (53, 6), (55, 6),
    ]

    frames_svg = []
    for f in range(num_frames):
        t = f * 0.35
        shark_flag = {}
        shark_shade = {}
        shark_key = {}
        shark_depth = {}
        shark_tint = {}

        # Rasterize back-to-front: secondary shark (idx 1) then main hammerhead (idx 0)
        for s_idx in (1, 0):
            rspine, turn, phase, L_s, depth, shp, sh_id = sharks_spines[s_idx][f]
            arc = [0.0] * N
            for k in range(1, N):
                arc[k] = arc[k - 1] + math.hypot(rspine[k][0] - rspine[k - 1][0], rspine[k][1] - rspine[k - 1][1])
            arc_total = arc[-1] or 1.0

            bank = clamp(turn * 0.45, -0.35, 0.35)
            flex = 1.0 + 0.06 * math.sin(phase * 0.5)
            reach_fin = shp["pectoral"][3]
            fin_tip_right = L_s * reach_fin * flex * (1.0 - bank)
            fin_tip_left = L_s * reach_fin * flex * (1.0 + bank)

            xs = [p[0] for p in rspine]
            ys = [p[1] for p in rspine]
            reach = L_s * 0.34
            c0 = max(0, int((min(xs) - reach) // cw))
            c1 = min(cols - 1, int((max(xs) + reach) // cw))
            r0 = max(0, int((min(ys) - reach) // ch))
            r1 = min(rows - 1, int((max(ys) + reach) // ch))

            for r in range(r0, r1 + 1):
                for c in range(c0, c1 + 1):
                    x = c * cw
                    y = r * ch
                    center_hit, flag, shade, s_val, v_val, _ = sample_shark(
                        x + cw / 2.0, y + ch / 2.0, L_s, rspine, arc, arc_total, shp, fin_tip_left, fin_tip_right
                    )
                    hits = 1 if center_hit else 0
                    for sx_off, sy_off in SUBSAMPLES:
                        sub_hit, _, _, _, _, _ = sample_shark(
                            x + sx_off * cw, y + sy_off * ch, L_s, rspine, arc, arc_total, shp, fin_tip_left, fin_tip_right
                        )
                        if sub_hit:
                            hits += 1
                    if hits == 0:
                        continue
                    coverage = hits / 5.0
                    key = int(hash3(round(s_val * 52), round(v_val / (cw * 0.9)), sh_id) * 4294967295) & 0xFFFFFFFF
                    shark_key[(c, r)] = key
                    shark_depth[(c, r)] = depth
                    shark_tint[(c, r)] = shp["tint"]
                    if center_hit and coverage >= 0.6:
                        flicker = (hash3(c, r, int(t * 6)) - 0.5) * 0.06
                        shark_flag[(c, r)] = flag
                        shark_shade[(c, r)] = clamp(shade + flicker, 0.0, 1.0)
                    else:
                        if (c, r) not in shark_flag:
                            shark_flag[(c, r)] = FLAG_EDGE
                            shark_shade[(c, r)] = coverage

        lines = [f'    <g class="shark-frame f{f}">']

        # 1. Ambient & Cyan Wake Dots (grouped into paths by color for small SVG size)
        wake_e = frame_energies[f]
        wake_bright_path = []
        wake_dim_path = []
        ambient_paths = {
            "#3034eb": [],
            "#34cd3c": [],
            "#e4322c": [],
            "#bed4ff": [],
        }
        ambient_keys = list(ambient_paths.keys())

        for r in range(1, rows - 1):
            for c in range(1, cols - 1):
                if (c, r) in shark_flag:
                    continue
                e_val = wake_e[r * cols + c]
                dx = round(vx + c * cw + cw * 0.66 - 1)
                dy = round(vy + r * ch + ch * 0.64 - 1)
                if e_val > 0.14:
                    if e_val > 0.42:
                        wake_bright_path.append(f"M{dx},{dy}h3v3h-3z")
                    else:
                        wake_dim_path.append(f"M{dx},{dy}h2v2h-2z")
                else:
                    h = hash3(c, r, 17)
                    if h < 0.065:
                        twinkle = math.sin((f / float(num_frames)) * math.pi * 2.0 + hash3(c, r, 23) * 6.28)
                        if twinkle > -0.2:
                            k_col = ambient_keys[int(hash3(c, r, 31) * len(ambient_keys))]
                            ambient_paths[k_col].append(f"M{dx},{dy}h2v2h-2z")

        for k_col, segs in ambient_paths.items():
            if segs:
                lines.append(f'      <path d="{"".join(segs)}" fill="{k_col}" fill-opacity="0.75"/>')
        if wake_dim_path:
            lines.append(f'      <path d="{"".join(wake_dim_path)}" fill="#6ee6ff" fill-opacity="0.45"/>')
        if wake_bright_path:
            lines.append(f'      <path d="{"".join(wake_bright_path)}" fill="#6ee6ff" fill-opacity="0.9"/>')

        # 2. Shark cell background rects (grouped by quantized shade color into <path>)
        rect_paths_by_col = {}
        text_by_color = {}

        for (c, r), flag in shark_flag.items():
            x = vx + c * cw
            y = vy + r * ch
            key = shark_key[(c, r)]
            shade = shark_shade[(c, r)]
            dim = 0.65 + 0.35 * shark_depth[(c, r)]
            tr, tg, tb = shark_tint[(c, r)]
            tick = int(t * 2.4 + (key % 997) / 97.0)
            roll = hash3(key, tick, 7)

            if flag == FLAG_EDGE:
                glyph_set = EDGE_HEAVY if shade >= 0.5 else EDGE_LIGHT
                g = round(((70.0 + shade * 80.0) * dim) / 8.0) * 8
                if roll < 0.07:
                    color = ACCENTS[key % len(ACCENTS)]
                else:
                    color = f"rgb({round(g * tr)},{round(g * tg)},{min(255, round(g * tb + 6))})"
                glyph = glyph_set[(key >> 8) % len(glyph_set)]
                text_by_color.setdefault(color, []).append((x + cw / 2.0, y + ch / 2.0 + 3.0, glyph))
                continue

            if flag == FLAG_RIDGE:
                level = 226.0
                glyph = RIDGE_GLYPHS[(key >> 8) % len(RIDGE_GLYPHS)]
            elif flag == FLAG_EYE:
                level = 12.0
                glyph = "o"
            elif flag == FLAG_FIN:
                level = 40.0 + shade * 120.0
                glyph = FIN_GLYPHS[(key >> 8) % len(FIN_GLYPHS)]
            else:
                level = 46.0 + shade * 160.0
                jitter = ((key >> 4) % 3) - 1
                idx = clamp(int((1.0 - shade) * 8.99) + jitter, 0, len(SKIN_RAMP) - 1)
                glyph = SKIN_RAMP[idx]

            # Quantize level to multiples of 6 so cells share <path> elements cleanly
            q_level = round((level * dim) / 6.0) * 6
            bg_col = f"rgb({min(255, round(q_level * tr))},{min(255, round(q_level * tg))},{min(255, round(q_level * tb + 4))})"
            rect_paths_by_col.setdefault(bg_col, []).append(f"M{x + 1},{y + 1}h{cw - 1}v{ch - 1}h-{cw - 1}z")

            if flag == FLAG_EYE:
                fg_col = "#9aa0ad"
            elif roll < 0.09:
                fg_col = ACCENTS[key % len(ACCENTS)]
            elif roll < 0.13:
                fg_col = "#ffffff"
            else:
                fg_col = "#0e0f13" if shade > 0.55 else "#1b1d24"

            text_by_color.setdefault(fg_col, []).append((x + cw / 2.0, y + ch / 2.0 + 3.0, glyph))

        for bg_col, segs in rect_paths_by_col.items():
            lines.append(f'      <path d="{"".join(segs)}" fill="{bg_col}"/>')

        # 3. Fish schools that drift and flee from the approaching shark snout
        main_snout = sharks_spines[0][f][0][0]
        sec_snout = sharks_spines[1][f][0][0]
        drift_c = int(round(math.sin((f / float(num_frames)) * math.pi * 2.0) * 2.0))

        for idx, (fc0, fr0) in enumerate(base_fish):
            fc = fc0 + drift_c
            fr = fr0
            fx_px = fc * cw
            fy_px = fr * ch
            # Check distance to shark snouts for Reynolds flee scatter
            glint = False
            for snx, sny in (main_snout, sec_snout):
                ddx = fx_px - snx
                ddy = fy_px - sny
                dist = math.hypot(ddx, ddy)
                if dist < 72.0:
                    push = (72.0 - dist) / 18.0
                    fc += int(round((ddx / (dist or 1.0)) * push))
                    fr += int(round((ddy / (dist or 1.0)) * push))
                    glint = True
            if 1 <= fc < cols - 1 and 1 <= fr < rows - 1 and (fc, fr) not in shark_flag:
                col_str = "#ffffff" if (glint or (idx + f) % 6 == 0) else "#8fa4c4"
                text_by_color.setdefault(col_str, []).append(
                    (vx + fc * cw + cw / 2.0, vy + fr * ch + ch / 2.0 + 3.0, "-")
                )

        # Emit compact <text> per color
        for color, items in text_by_color.items():
            lines.append(f'      <g fill="{color}">')
            for tx_pos, ty_pos, ch_glyph in items:
                lines.append(f'        <text x="{tx_pos:.1f}" y="{ty_pos:.1f}">{xml_escape(ch_glyph)}</text>')
            lines.append("      </g>")

        lines.append("    </g>")
        frames_svg.append("\n".join(lines))

    return "\n".join(frames_svg)


def generate_svg(telemetry, frames_svg, num_frames, theme="dark"):
    is_dark = theme == "dark"
    cw, ch = 7, 10
    cols, rows = 66, 24
    vw, vh = cols * cw, rows * ch  # 462 x 240
    vx, vy = 22, 48

    cycle_sec = 4.8
    step_pct = 100.0 / num_frames
    anim_rules = []
    for f in range(num_frames):
        delay = (f / float(num_frames)) * cycle_sec
        anim_rules.append(f"    .f{f} {{ animation: sharkLoop {cycle_sec}s steps(1, end) infinite {delay:.2f}s; }}")
    anim_css = "\n".join(anim_rules)

    if is_dark:
        bg_stops = ("#070a0f", "#0d1117", "#111827")
        border_col = "#1e293b"
        topbar_fill = "#0d1117"
        title_col = "#64748b"
        card_bg = "#0b0f17"
        card_stroke = "#1e293b"
        heading_col = "#f8fafc"
        sub_col = "#94a3b8"
        muted_col = "#64748b"
        bar_bg = "#161f30"
        pill_bg = "#111827"
        palette = {
            "cyan": "#38bdf8",
            "indigo": "#818cf8",
            "rose": "#f43f5e",
            "emerald": "#10b981",
        }
    else:
        bg_stops = ("#ffffff", "#f8fafc", "#f1f5f9")
        border_col = "#cbd5e1"
        topbar_fill = "#f1f5f9"
        title_col = "#64748b"
        card_bg = "#ffffff"
        card_stroke = "#cbd5e1"
        heading_col = "#0f172a"
        sub_col = "#334155"
        muted_col = "#64748b"
        bar_bg = "#e2e8f0"
        pill_bg = "#f8fafc"
        palette = {
            "cyan": "#0284c7",
            "indigo": "#4f46e5",
            "rose": "#e11d48",
            "emerald": "#059669",
        }

    # Build language bars with real telemetry & CSS scan/shimmer animations
    lang_rows_svg = []
    max_bar_w = 358
    for idx, (name, subtitle, pct, col_key) in enumerate(telemetry["langs"]):
        y_off = 46 + idx * 30
        bar_w = max(8, round((pct / 100.0) * max_bar_w))
        col_hex = palette[col_key]
        delay_s = 0.35 * idx
        lang_rows_svg.append(f"""    <g transform="translate(18, {y_off})">
      <text x="0" y="10" class="mono" font-size="11" font-weight="600" fill="{heading_col}">{xml_escape(name)} <tspan fill="{muted_col}" font-weight="400">({xml_escape(subtitle)})</tspan></text>
      <text x="358" y="10" text-anchor="end" class="mono" font-size="11" font-weight="700" fill="{col_hex}">{pct:.1f}%</text>
      <rect x="0" y="16" width="{max_bar_w}" height="6" rx="3" fill="{bar_bg}" />
      <rect x="0" y="16" width="{bar_w}" height="6" rx="3" fill="{col_hex}" class="bar-anim" style="animation-delay: {delay_s:.2f}s" />
      <circle cx="{bar_w}" cy="19" r="3" fill="#ffffff" class="pulse-dot" style="animation-delay: {delay_s:.2f}s" />
    </g>""")

    langs_block = "\n".join(lang_rows_svg)
    latest_repo_short = telemetry["latest_repo"]
    if len(latest_repo_short) > 20:
        latest_repo_short = latest_repo_short[:19] + "…"

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 920 310" width="100%" height="100%">
  <defs>
    <linearGradient id="bg-term" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{bg_stops[0]}" />
      <stop offset="50%" stop-color="{bg_stops[1]}" />
      <stop offset="100%" stop-color="{bg_stops[2]}" />
    </linearGradient>

    <pattern id="ascii-grid" x="{vx}" y="{vy}" width="{cw}" height="{ch}" patternUnits="userSpaceOnUse">
      <path d="M {cw} 0 L 0 0 0 {ch}" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="1" />
    </pattern>

    <pattern id="scanlines" width="100" height="4" patternUnits="userSpaceOnUse">
      <line x1="0" y1="0" x2="100" y2="0" stroke="{border_col}" stroke-width="0.7" opacity="0.35" />
    </pattern>

    <clipPath id="ocean-clip">
      <rect x="{vx}" y="{vy}" width="{vw}" height="{vh}" rx="8" />
    </clipPath>
  </defs>

  <style>
    .mono {{
      font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, Menlo, Consolas, monospace;
    }}
    .shark-glyphs {{
      font-family: ui-monospace, 'JetBrains Mono', Menlo, Consolas, monospace;
      font-size: 8px;
      font-weight: 600;
      text-anchor: middle;
    }}
    .shark-frame {{
      opacity: 0;
    }}
{anim_css}
    @keyframes sharkLoop {{
      0%, {step_pct - 0.01:.2f}% {{ opacity: 1; }}
      {step_pct:.2f}%, 100% {{ opacity: 0; }}
    }}
    .pulse-dot {{
      animation: pulseGlow 2s ease-in-out infinite;
    }}
    @keyframes pulseGlow {{
      0%, 100% {{ opacity: 1; }}
      50% {{ opacity: 0.25; }}
    }}
    .cursor-blink {{
      animation: blinkCursor 1.1s steps(2, start) infinite;
    }}
    @keyframes blinkCursor {{
      0%, 49% {{ opacity: 1; }}
      50%, 100% {{ opacity: 0; }}
    }}
    .bar-anim {{
      transform-box: fill-box;
      transform-origin: left center;
      animation: barPulse 3.2s ease-in-out infinite;
    }}
    @keyframes barPulse {{
      0%, 100% {{ transform: scaleX(1); opacity: 1; }}
      50% {{ transform: scaleX(0.96); opacity: 0.82; }}
    }}
  </style>

  <!-- Outer Terminal Window -->
  <rect width="920" height="310" rx="12" fill="url(#bg-term)" stroke="{border_col}" stroke-width="1.5" />
  <rect width="920" height="310" rx="12" fill="url(#scanlines)" />

  <!-- Window Title Bar -->
  <path d="M0 12C0 5.373 5.373 0 12 0h896c6.627 0 12 5.373 12 12v26H0V12z" fill="{topbar_fill}" stroke="{border_col}" stroke-width="1" />
  <circle cx="22" cy="19" r="5" fill="#f43f5e" />
  <circle cx="40" cy="19" r="5" fill="#fbbf24" />
  <circle cx="58" cy="19" r="5" fill="#10b981" />
  <text x="460" y="23" text-anchor="middle" class="mono" font-size="11" font-weight="600" fill="{title_col}" letter-spacing="1.2">yoshi-404@ocean-engine: ~/telemetry --live-sync</text>

  <!-- ======================================================================= -->
  <!-- LEFT PANEL: LIVE SWIMMING ASCII-SHARKS VIEWPORT (462x240)               -->
  <!-- ======================================================================= -->
  <g clip-path="url(#ocean-clip)">
    <rect x="{vx}" y="{vy}" width="{vw}" height="{vh}" fill="#05070b" />
    <rect x="{vx}" y="{vy}" width="{vw}" height="{vh}" fill="url(#ascii-grid)" />

    <g class="shark-glyphs">
{frames_svg}
    </g>

    <!-- Viewport HUD Overlays -->
    <rect x="{vx + 10}" y="{vy + 8}" width="212" height="20" rx="4" fill="#0d1117" fill-opacity="0.84" stroke="#1e293b" stroke-width="0.8" />
    <circle cx="{vx + 20}" cy="{vy + 18}" r="3" fill="#6ee6ff" class="pulse-dot" />
    <text x="{vx + 29}" y="{vy + 22}" class="mono" font-size="9.5" font-weight="600" fill="#e2e8f0" letter-spacing="0.6">ASCII-SHARKS // LIVE OCEAN</text>

    <rect x="{vx + 10}" y="{vy + vh - 26}" width="236" height="18" rx="4" fill="#0d1117" fill-opacity="0.84" />
    <text x="{vx + 16}" y="{vy + vh - 14}" class="mono" font-size="9" fill="#64748b">SIM: BOIDS + SPINE • RAMP: ":;t%SX8#@"</text>
  </g>
  <rect x="{vx}" y="{vy}" width="{vw}" height="{vh}" rx="8" fill="none" stroke="{border_col}" stroke-width="1.2" />

  <!-- ======================================================================= -->
  <!-- RIGHT PANEL: DYNAMIC GITHUB API TELEMETRY                               -->
  <!-- ======================================================================= -->
  <g transform="translate(504, 48)">
    <rect width="394" height="240" rx="8" fill="{card_bg}" stroke="{card_stroke}" stroke-width="1.2" />

    <!-- Header with Blinking Terminal Cursor & Live Sync Badge -->
    <text x="18" y="24" class="mono" font-size="11" font-weight="700" fill="{palette['cyan']}" letter-spacing="0.8">$ yoshi --telemetry<tspan class="cursor-blink" fill="{palette['cyan']}"> █</tspan></text>
    <circle cx="272" cy="20" r="3" fill="{palette['emerald']}" class="pulse-dot" />
    <text x="376" y="24" text-anchor="end" class="mono" font-size="9.5" font-weight="600" fill="{muted_col}">LIVE GITHUB API</text>
    <line x1="18" y1="33" x2="376" y2="33" stroke="{card_stroke}" stroke-width="1" />

{langs_block}

    <line x1="18" y1="168" x2="376" y2="168" stroke="{card_stroke}" stroke-width="1" />

    <!-- Live GitHub Stats Pills (Auto-updated via GitHub API / Actions) -->
    <g transform="translate(18, 178)">
      <rect x="0" y="0" width="174" height="48" rx="6" fill="{pill_bg}" stroke="{card_stroke}" stroke-width="1" />
      <text x="10" y="18" class="mono" font-size="9" fill="{muted_col}">ACTIVITY &amp; REPOSITORIES</text>
      <text x="10" y="36" class="mono" font-size="11" font-weight="700" fill="{sub_col}">{telemetry["public_repos"]} Repos • {telemetry["total_commits"]} Commits</text>

      <rect x="184" y="0" width="174" height="48" rx="6" fill="{pill_bg}" stroke="{card_stroke}" stroke-width="1" />
      <text x="194" y="18" class="mono" font-size="9" fill="{muted_col}">LATEST ACTIVE REPO</text>
      <text x="194" y="36" class="mono" font-size="10.5" font-weight="700" fill="{palette['cyan']}">{xml_escape(latest_repo_short)}</text>
    </g>
  </g>
</svg>
"""
    return svg


def main():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assets_dir = os.path.join(repo_root, "assets")
    os.makedirs(assets_dir, exist_ok=True)

    telemetry = fetch_github_telemetry()
    print("Fetched Live Telemetry:", json.dumps(telemetry, indent=2))

    num_frames = 16
    cw, ch = 7, 10
    cols, rows = 66, 24
    vx, vy = 22, 48
    frames_svg = simulate_ocean_frames(num_frames, cols, rows, cw, ch, vx, vy)

    for theme in ("dark", "light"):
        out_path = os.path.join(assets_dir, f"ascii-telemetry-{theme}.svg")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(generate_svg(telemetry, frames_svg, num_frames, theme=theme))
        print(f"Wrote {out_path} ({os.path.getsize(out_path) / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
