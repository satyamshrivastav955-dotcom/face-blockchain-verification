#!/usr/bin/env python3
"""
Generate the README's animated SVGs into assets/readme/.

    python scripts/make_readme_assets.py

* hero.svg, pipeline.svg, evidence_ladder.svg, merkle.svg are diagrams of the design (they contain
  no measurements).
* benchmark.svg is drawn from docs/results/lfw_benchmark.json, the raw output of
  scripts/benchmark_face.py: every bar and label is computed from that file.

Animation is plain CSS inside the SVG (works when the SVG is shown with <img>, including on GitHub)
and is switched off for ``prefers-reduced-motion``. System fonts only.
"""

from __future__ import annotations

import json
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "readme"

PAPER, SHEET, CARD = "#e9e0c9", "#f5efe0", "#faf6ea"
INK, INK2, MUTED = "#211c16", "#483f33", "#7a6f5d"
RULE, RULE2 = "#d2c7ae", "#b3a584"
OXBLOOD, FOREST, OCHRE, NAVY = "#86281f", "#2e5842", "#9e6b14", "#24364f"
SERIF = "Iowan Old Style, Palatino Linotype, Palatino, Book Antiqua, Georgia, serif"
MONO = "ui-monospace, Cascadia Mono, SF Mono, Menlo, Consolas, Courier New, monospace"

COMMON_CSS = f"""
text {{ font-family: {SERIF}; fill: {INK}; }}
.mono {{ font-family: {MONO}; }}
.cap {{ font-family: {MONO}; font-size: 11px; letter-spacing: 2.2px; text-transform: uppercase; fill: {MUTED}; }}
@media (prefers-reduced-motion: reduce) {{ * {{ animation: none !important; }} }}
"""


def wrap(text: str, width: int) -> list[str]:
    import textwrap

    return textwrap.wrap(text, width)


def svg(width: int, height: int, body: str, css: str = "", title: str = "") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{escape(title)}">\n<title>{escape(title)}</title>\n<style>{COMMON_CSS}{css}</style>\n'
        f"{body}\n</svg>\n"
    )


def ledger_bg(w: int, h: int, step: int = 32) -> str:
    return (
        f'<rect width="{w}" height="{h}" fill="{SHEET}"/>'
        f'<g stroke="{RULE}" stroke-width="1" opacity="0.55">'
        + "".join(f'<line x1="0" y1="{y}" x2="{w}" y2="{y}"/>' for y in range(step, h, step))
        + "</g>"
        f'<rect x="1" y="1" width="{w - 2}" height="{h - 2}" fill="none" stroke="{INK}" stroke-width="2"/>'
    )


# ------------------------------------------------------------------------------------ hero


def hero() -> str:
    css = """
    @keyframes rise { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }
    @keyframes draw { from { stroke-dashoffset: 200; } to { stroke-dashoffset: 0; } }
    @keyframes thump { 0% { opacity: 0; transform: rotate(-20deg) scale(2); } 60% { opacity: .95; transform: rotate(-8deg) scale(.94); } 100% { opacity: .9; transform: rotate(-8deg) scale(1); } }
    @keyframes spin { from { opacity: 0; transform: rotate(-90deg) scale(1.3); } to { opacity: .85; transform: rotate(-10deg) scale(1); } }
    @keyframes pop { from { opacity: 0; transform: scale(.7); } to { opacity: 1; transform: scale(1); } }
    .a { opacity: 0; animation: rise .8s ease forwards; }
    .under { stroke-dasharray: 200; stroke-dashoffset: 200; animation: draw 1.1s .9s ease forwards; }
    .stamp { transform-box: fill-box; transform-origin: center; opacity: 0; animation: thump .6s 1.5s cubic-bezier(.2,1.3,.4,1) forwards; }
    .seal { transform-box: fill-box; transform-origin: center; opacity: 0; animation: spin 1s 1.2s ease forwards; }
    .tag { transform-box: fill-box; transform-origin: center; opacity: 0; animation: pop .5s ease forwards; }
    """
    w, h = 1200, 470
    rows = [
        ("evidence_type", "face_match | image_derivative"),
        ("decision_rule", "named, never implied"),
        ("derivative_basis", "geometric | phash"),
        ("scores", "cosine · inliers · pHash"),
        ("content_credentials", "C2PA state, signer"),
        ("integrity", "sha256 · restricted JCS"),
        ("anchor", "hash + keccak256(url)"),
    ]
    sheet = "".join(
        f'<text class="mono" x="772" y="{150 + i * 26}" font-size="12.5" fill="{INK2}" style="fill:{INK2}">{escape(k)}</text>'
        f'<line x1="{772 + len(k) * 7.6 + 8:.0f}" y1="{146 + i * 26}" x2="1070" y2="{146 + i * 26}" stroke="{RULE2}" stroke-dasharray="1 4" stroke-width="1.6"/>'
        f'<text x="1128" y="{150 + i * 26}" text-anchor="end" font-size="13" font-style="italic" style="fill:{INK2}">{escape(v)}</text>'
        for i, (k, v) in enumerate(rows)
    )
    tags = [
        ("DETECT", "LOCAL", FOREST),
        ("SEARCH", "WITH CONSENT", OCHRE),
        ("RE-EXAMINE", "LOCAL", FOREST),
        ("SEAL", "LOCAL", FOREST),
        ("ANCHOR", "ON-CHAIN", NAVY),
    ]
    strip = ""
    for i, (name, where, colour) in enumerate(tags):
        x = 56 + i * 196
        strip += (
            f'<g class="tag" style="animation-delay:{2.0 + i * 0.18:.2f}s">'
            f'<rect x="{x}" y="404" width="176" height="46" fill="{CARD}" stroke="{INK}" stroke-width="1.5"/>'
            f'<text class="mono" x="{x + 12}" y="424" font-size="12.5" font-weight="700" style="fill:{INK}">{i + 1} · {name}</text>'
            f'<text class="mono" x="{x + 12}" y="441" font-size="10" letter-spacing="1.6" style="fill:{colour}">{where}</text></g>'
        )
    body = (
        ledger_bg(w, h)
        + '<text class="cap a" x="56" y="62" style="animation-delay:.1s">File no. FP-001 · Image provenance, kept on file</text>'
        + '<text class="a" x="56" y="140" font-size="62" letter-spacing="-1.5" style="animation-delay:.25s">The receipts for</text>'
        + f'<text class="a" x="56" y="214" font-size="62" letter-spacing="-1.5" style="animation-delay:.45s"><tspan font-style="italic" style="fill:{OXBLOOD}">where</tspan> an image</text>'
        + '<text class="a" x="56" y="288" font-size="62" letter-spacing="-1.5" style="animation-delay:.65s">appeared.</text>'
        + f'<path class="under" d="M58 226 C 90 232, 130 221, 196 228" fill="none" stroke="{OXBLOOD}" stroke-width="3" opacity=".6"/>'
        + f'<text class="a" x="58" y="330" font-size="16.5" style="fill:{INK2};animation-delay:1s">Re-examine every search lead locally. Say plainly whether the evidence is a face match</text>'
        + f'<text class="a" x="58" y="354" font-size="16.5" style="fill:{INK2};animation-delay:1.1s">or only image similarity. Anchor a tamper-evident hash, never a face or a URL.</text>'
        # dossier sheets
        + f'<g transform="rotate(2.2 930 240)"><rect x="716" y="82" width="440" height="300" fill="{CARD}" stroke="{RULE2}"/></g>'
        + f'<g transform="rotate(-1.6 930 240)"><rect x="716" y="82" width="440" height="300" fill="#efe7d3" stroke="{RULE2}"/></g>'
        + f'<g class="a" style="animation-delay:.5s"><rect x="728" y="92" width="416" height="296" fill="{CARD}" stroke="{INK}" stroke-width="1.5"/>'
        + f'<text class="mono" x="772" y="124" font-size="10.5" letter-spacing="2" style="fill:{MUTED}">RECORD · FACEVERIFY/V2</text>'
        + f'<line x1="772" y1="132" x2="1128" y2="132" stroke="{INK}" stroke-width="2"/>{sheet}</g>'
        + f'<g class="seal"><circle cx="790" cy="352" r="26" fill="none" stroke="{OXBLOOD}" stroke-width="2.4"/>'
        + f'<circle cx="790" cy="352" r="21" fill="none" stroke="{OXBLOOD}" stroke-width="1" stroke-dasharray="2 3"/>'
        + f'<path d="M779 353 l8 8 15 -18" fill="none" stroke="{OXBLOOD}" stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round"/></g>'
        + f'<g class="stamp"><rect x="1000" y="334" width="124" height="36" fill="none" stroke="{FOREST}" stroke-width="2.6"/>'
        + f'<rect x="1004" y="338" width="116" height="28" fill="none" stroke="{FOREST}" stroke-width="1"/>'
        + f'<text class="mono" x="1062" y="358" text-anchor="middle" font-size="15" font-weight="700" letter-spacing="4" style="fill:{FOREST}">SEALED</text></g>'
        + strip
    )
    return svg(w, h, body, css, "FaceProof: the receipts for where an image appeared")


# -------------------------------------------------------------------------------- pipeline


def pipeline() -> str:
    w, h = 1200, 480
    nodes = [
        ("1", "Detect", "SCRFD-10G\n5-point landmarks", "LOCAL", FOREST),
        ("2", "Embed", "align → ArcFace\n512-d, flip TTA", "LOCAL", FOREST),
        ("3", "Search", "reverse-image\nprovider leads", "CONSENT", OCHRE),
        ("4", "Download", "SSRF-guarded\nparallel, bounded", "NETWORK", OCHRE),
        ("5", "Re-examine", "face · SIFT+RANSAC\n· pHash", "LOCAL", FOREST),
        ("6", "Seal", "restricted JCS\n+ SHA-256", "LOCAL", FOREST),
        ("7", "Anchor", "single or\nMerkle batch", "ON-CHAIN", NAVY),
    ]
    nw, gap, x0, y0, nh = 140, 28, 26, 150, 150
    css = f"""
    @keyframes flow {{ to {{ stroke-dashoffset: -28; }} }}
    @keyframes glow {{ 0%, 11% {{ stroke: {OXBLOOD}; stroke-width: 3.2; }} 15%, 100% {{ stroke: {INK}; stroke-width: 1.5; }} }}
    @keyframes lift {{ 0%, 11% {{ transform: translateY(-5px); }} 15%, 100% {{ transform: none; }} }}
    @keyframes rise {{ from {{ opacity: 0; transform: translateY(12px); }} to {{ opacity: 1; transform: none; }} }}
    .link {{ stroke-dasharray: 5 9; animation: flow 1.2s linear infinite; }}
    .node {{ animation: lift 7.7s ease-in-out infinite; }}
    .box {{ animation: glow 7.7s ease-in-out infinite; }}
    .in {{ opacity: 0; animation: rise .7s ease forwards; }}
    """
    body = ledger_bg(w, h)
    body += '<text class="cap" x="36" y="50">Pipeline · where each stage runs</text>'
    body += f'<text x="36" y="86" font-size="26" letter-spacing="-.4" style="fill:{INK}">One image in; a sealed, anchorable record out.</text>'
    # C2PA branch above
    body += (
        f'<g class="in" style="animation-delay:.2s"><rect x="{x0}" y="104" width="372" height="30" fill="{CARD}" stroke="{FOREST}" stroke-width="1.4" stroke-dasharray="4 3"/>'
        f'<text class="mono" x="{x0 + 12}" y="124" font-size="11" style="fill:{FOREST}">C2PA Content Credentials · read in parallel · LOCAL</text></g>'
    )
    for i, (num, title, sub, where, colour) in enumerate(nodes):
        x = x0 + i * (nw + gap)
        if i < len(nodes) - 1:
            body += f'<line class="link" x1="{x + nw}" y1="{y0 + nh / 2}" x2="{x + nw + gap}" y2="{y0 + nh / 2}" stroke="{RULE2}" stroke-width="2.4"/>'
        lines = sub.split("\n")
        body += (
            f'<g class="in" style="animation-delay:{0.3 + i * 0.12:.2f}s"><g class="node" style="animation-delay:{i * 0.9:.1f}s">'
            f'<rect class="box" x="{x}" y="{y0}" width="{nw}" height="{nh}" fill="{CARD}" stroke="{INK}" stroke-width="1.5" style="animation-delay:{i * 0.9:.1f}s"/>'
            f'<text class="mono" x="{x + 12}" y="{y0 + 26}" font-size="11" style="fill:{MUTED}">{num:0>2}</text>'
            f'<text x="{x + 12}" y="{y0 + 56}" font-size="21" style="fill:{INK}">{escape(title)}</text>'
            + "".join(
                f'<text x="{x + 12}" y="{y0 + 82 + j * 18}" font-size="12.5" style="fill:{INK2}">{escape(t)}</text>'
                for j, t in enumerate(lines)
            )
            + f'<rect x="{x + 12}" y="{y0 + nh - 36}" width="{12 + len(where) * 7.2:.0f}" height="22" fill="none" stroke="{colour}" stroke-width="1.5"/>'
            f'<text class="mono" x="{x + 18}" y="{y0 + nh - 21}" font-size="10" font-weight="700" letter-spacing="1.4" style="fill:{colour}">{where}</text></g></g>'
        )
    # bottom bracket notes
    body += f'<line x1="{x0}" y1="338" x2="{w - 26}" y2="338" stroke="{INK}" stroke-width="2"/>'
    notes = [
        (
            "Never sent anywhere",
            "Face crops and embeddings. The query image stays local unless you consent to search.",
            FOREST,
        ),
        ("Needs your consent", "Search provider and optional public image host. What is sent is shown first.", OCHRE),
        (
            "On the public ledger",
            "A 32-byte hash and a keccak256 URL commitment. Never a face, vector or the URL.",
            NAVY,
        ),
    ]
    for i, (t, d, c) in enumerate(notes):
        x = 36 + i * 388
        body += (
            f'<g class="in" style="animation-delay:{1.4 + i * 0.2:.1f}s"><rect x="{x}" y="356" width="10" height="70" fill="{c}"/>'
            f'<text class="mono" x="{x + 24}" y="372" font-size="11" font-weight="700" letter-spacing="1.6" style="fill:{c}">{t.upper()}</text>'
            + "".join(
                f'<text x="{x + 24}" y="{392 + j * 17}" font-size="13" style="fill:{INK2}">{escape(line)}</text>'
                for j, line in enumerate(wrap(d, 44))
            )
            + "</g>"
        )
    return svg(w, h, body, css, "Pipeline: detect, embed, search, download, re-examine, seal, anchor")


# -------------------------------------------------------------------------- evidence ladder


def ladder() -> str:
    w, h = 1200, 450
    css = """
    @keyframes slide { from { opacity: 0; transform: translateX(-26px); } to { opacity: 1; transform: none; } }
    @keyframes thump { 0% { opacity: 0; transform: rotate(-12deg) scale(1.8); } 60% { opacity: .95; transform: rotate(var(--t)) scale(.94); } 100% { opacity: .9; transform: rotate(var(--t)) scale(1); } }
    .card { opacity: 0; animation: slide .7s ease forwards; }
    .st { transform-box: fill-box; transform-origin: center; opacity: 0; animation: thump .55s cubic-bezier(.2,1.3,.4,1) forwards; }
    """
    tiers = [
        (
            "Tier 1",
            "Face match",
            "A face in the candidate scores at or above the engine's threshold against the query face.",
            "Similarity under a named model. Never identity.",
            "FACE MATCH",
            FOREST,
            -4,
        ),
        (
            "Tier 2",
            "Image derivative · geometric",
            "SIFT + RANSAC: ≥25 local features agree on one transform (crop, rotate, mirror, resize).",
            "Shared rendered content. Says nothing about faces.",
            "NOT A FACE MATCH",
            OCHRE,
            3,
        ),
        (
            "Tier 3",
            "Image derivative · pHash",
            "64-bit DCT hash within 12 bits of the query image.",
            "Image similarity only. Misses heavy crops and mirrors.",
            "NOT A FACE MATCH",
            OCHRE,
            -3,
        ),
    ]
    body = ledger_bg(w, h)
    body += (
        '<text class="cap" x="36" y="48">Evidence ladder · every accepted candidate carries exactly one label</text>'
    )
    for i, (tier, name, rule, limit, stamp, colour, tilt) in enumerate(tiers):
        y = 72 + i * 108
        d = 0.15 + i * 0.25
        body += (
            f'<g class="card" style="animation-delay:{d:.2f}s"><rect x="36" y="{y}" width="808" height="96" fill="{CARD}" stroke="{INK}" stroke-width="1.5"/>'
            f'<rect x="36" y="{y}" width="8" height="96" fill="{colour}"/>'
            f'<text class="mono" x="62" y="{y + 24}" font-size="11" letter-spacing="2" style="fill:{MUTED}">{tier.upper()}</text>'
            f'<text x="62" y="{y + 52}" font-size="23" style="fill:{INK}">{escape(name)}</text>'
            f'<text x="62" y="{y + 73}" font-size="13" style="fill:{INK2}">{escape(rule[:104])}</text>'
            f'<text x="62" y="{y + 90}" font-size="12" font-style="italic" style="fill:{MUTED}">{escape(limit)}</text></g>'
            f'<g class="st" style="--t:{tilt}deg;animation-delay:{d + 0.55:.2f}s"><rect x="866" y="{y + 22}" width="{40 + len(stamp) * 10.5:.0f}" height="46" fill="none" stroke="{colour}" stroke-width="2.6"/>'
            f'<text class="mono" x="{866 + (40 + len(stamp) * 10.5) / 2:.0f}" y="{y + 51}" text-anchor="middle" font-size="14" font-weight="700" letter-spacing="3" style="fill:{colour}">{stamp}</text></g>'
        )
    # arrow strong -> weak
    body += (
        f'<g class="card" style="animation-delay:.9s"><line x1="1150" y1="84" x2="1150" y2="372" stroke="{INK}" stroke-width="2"/>'
        f'<path d="M1143 362 L1150 378 L1157 362" fill="none" stroke="{INK}" stroke-width="2"/>'
        f'<text class="mono" x="1138" y="84" text-anchor="end" font-size="10" letter-spacing="2" style="fill:{MUTED}">STRONGER</text>'
        f'<text class="mono" x="1138" y="384" text-anchor="end" font-size="10" letter-spacing="2" style="fill:{MUTED}">WEAKER</text></g>'
    )
    body += (
        f'<g class="card" style="animation-delay:1.1s"><rect x="36" y="402" width="1060" height="30" fill="none" stroke="{FOREST}" stroke-width="1.4" stroke-dasharray="4 3"/>'
        f'<text class="mono" x="50" y="422" font-size="11" style="fill:{FOREST}">Independent of the ladder: C2PA Content Credentials on the source and the matched image. Valid ≠ trusted; absent ≠ evidence.</text></g>'
    )
    return svg(w, h, body, css, "Evidence ladder: face match, geometric derivative, pHash derivative")


# --------------------------------------------------------------------------------- merkle


def merkle() -> str:
    w, h = 1200, 470
    css = """
    @keyframes pulse { 0%, 100% { stroke-width: 2; } 50% { stroke-width: 4.2; } }
    @keyframes show { from { opacity: 0; } to { opacity: 1; } }
    @keyframes dash { to { stroke-dashoffset: -24; } }
    .path { animation: pulse 2.4s ease-in-out infinite; }
    .proof { opacity: 0; animation: show .5s ease forwards; }
    .flow { stroke-dasharray: 6 6; animation: dash 1s linear infinite; }
    """
    leaves_x = [40 + i * 102 for i in range(8)]
    ly, lh, lw = 350, 46, 88
    # node positions: level0 leaves centres
    cx0 = [x + lw / 2 for x in leaves_x]
    lvl = [cx0]
    for _ in range(3):
        prev = lvl[-1]
        lvl.append([(prev[i] + prev[i + 1]) / 2 for i in range(0, len(prev), 2)])
    ys = [ly, 268, 186, 104]
    target = 5  # highlighted leaf
    path_idx = [target, target // 2, target // 4, 0]
    proof = [(0, target ^ 1), (1, (target // 2) ^ 1), (2, (target // 4) ^ 1)]
    body = ledger_bg(w, h)
    body += '<text class="cap" x="36" y="46">Merkle-batched anchoring · RFC 6962 · illustrative 8-record batch</text>'
    # edges
    for lv in range(3):
        for j, cx in enumerate(lvl[lv]):
            px = lvl[lv + 1][j // 2]
            on = j == path_idx[lv]
            colour, wdt = (OXBLOOD, 2) if on else (RULE2, 1.4)
            cls = ' class="path"' if on else ""
            y1 = ys[lv] if lv else ly
            body += f'<line{cls} x1="{cx}" y1="{y1}" x2="{px}" y2="{ys[lv + 1] + 14}" stroke="{colour}" stroke-width="{wdt}"/>'
    # internal nodes
    for lv in (1, 2, 3):
        for j, cx in enumerate(lvl[lv]):
            on = j == path_idx[lv]
            is_proof = (lv, j) in proof
            fill = CARD
            stroke = OXBLOOD if on else (FOREST if is_proof else INK)
            label = "root" if lv == 3 else "H"
            body += (
                f'<rect x="{cx - 26}" y="{ys[lv] - 14}" width="52" height="28" fill="{fill}" stroke="{stroke}" stroke-width="{2.4 if (on or is_proof) else 1.4}"/>'
                f'<text class="mono" x="{cx}" y="{ys[lv] + 5}" text-anchor="middle" font-size="11" font-weight="700" style="fill:{stroke}">{label}</text>'
            )
    # leaves
    for i, x in enumerate(leaves_x):
        on = i == target
        is_proof = i == proof[0][1]
        stroke = OXBLOOD if on else (FOREST if is_proof else INK)
        body += (
            f'<rect x="{x}" y="{ly}" width="{lw}" height="{lh}" fill="{CARD}" stroke="{stroke}" stroke-width="{2.4 if (on or is_proof) else 1.4}"/>'
            f'<text class="mono" x="{x + lw / 2}" y="{ly + 20}" text-anchor="middle" font-size="10" style="fill:{MUTED}">record {i}</text>'
            f'<text class="mono" x="{x + lw / 2}" y="{ly + 36}" text-anchor="middle" font-size="9.5" style="fill:{INK2}">hash‖url</text>'
        )
    # proof badges (staggered)
    for k, (lv, j) in enumerate(proof):
        cx = lvl[lv][j]
        yy = ys[lv] if lv else ly
        top = yy - 14 if lv else yy
        body += (
            f'<g class="proof" style="animation-delay:{0.6 + k * 0.5:.1f}s"><circle cx="{cx}" cy="{top - 16}" r="11" fill="{FOREST}"/>'
            f'<text class="mono" x="{cx}" y="{top - 12}" text-anchor="middle" font-size="12" font-weight="700" style="fill:{CARD}">{k + 1}</text></g>'
        )
    # on-chain box
    rx = lvl[3][0]
    body += (
        f'<line class="flow" x1="{rx + 30}" y1="{ys[3]}" x2="880" y2="{ys[3]}" stroke="{NAVY}" stroke-width="2"/>'
        f'<rect x="880" y="62" width="290" height="124" fill="{CARD}" stroke="{NAVY}" stroke-width="2"/>'
        f'<text class="mono" x="898" y="86" font-size="11" letter-spacing="2" font-weight="700" style="fill:{NAVY}">ON-CHAIN · ONE TRANSACTION</text>'
        f'<text x="898" y="116" font-size="19" style="fill:{INK}">registerBatch(root, size)</text>'
        f'<text x="898" y="142" font-size="13" style="fill:{INK2}">≈ 74,200 gas for N = 1 or N = 1,000</text>'
        f'<text x="898" y="162" font-size="13" font-style="italic" style="fill:{MUTED}">≈ 74 gas per record at N = 1,000</text>'
    )
    # explanation
    body += (
        f'<g class="proof" style="animation-delay:.3s"><text class="mono" x="880" y="232" font-size="10.5" letter-spacing="2" style="fill:{OXBLOOD}">RECORD 5 KEEPS</text>'
        f'<text x="880" y="256" font-size="14" style="fill:{INK2}">its own proof: 3 sibling hashes (green).</text>'
        f'<text x="880" y="276" font-size="14" style="fill:{INK2}">Recompute the leaf from the record,</text>'
        f'<text x="880" y="296" font-size="14" style="fill:{INK2}">fold the proof, compare to the root,</text>'
        f'<text x="880" y="316" font-size="14" style="fill:{INK2}">then look the root up on-chain.</text>'
        f'<text x="880" y="344" font-size="12.5" font-style="italic" style="fill:{MUTED}">The leaf binds the URL commitment, so a</text>'
        f'<text x="880" y="362" font-size="12.5" font-style="italic" style="fill:{MUTED}">valid proof also proves the URL matches.</text></g>'
    )
    body += f'<text class="mono" x="36" y="448" font-size="10.5" style="fill:{MUTED}">Gas measured on an in-process EVM (solc 0.8.24); real chains add calldata and L1 data fees. Registry v3 is compiled and tested, not deployed.</text>'
    return svg(w, h, body, css, "Merkle batch: one transaction anchors many records")


# ------------------------------------------------------------------------------ benchmark


def benchmark() -> str:
    data = json.loads((ROOT / "docs" / "results" / "lfw_benchmark.json").read_text(encoding="utf-8"))
    eng = data["engines"]
    order = [
        ("opencv", "SFace", MUTED),
        ("arcface-r50", "ArcFace-R50", OXBLOOD),
        ("arcface-r100", "ArcFace-R100", NAVY),
    ]
    w, h = 1200, 770
    lo, hi = 85.0, 100.0
    css = """
    @keyframes grow { from { transform: scaleX(0); } to { transform: scaleX(1); } }
    @keyframes show { from { opacity: 0; } to { opacity: 1; } }
    .bar { transform-box: fill-box; transform-origin: left; transform: scaleX(0); animation: grow .9s cubic-bezier(.2,.8,.2,1) forwards; }
    .val { opacity: 0; animation: show .4s ease forwards; }
    """
    groups = [
        ("Accuracy, 10-fold (LFW, 6,000 pairs)", lambda e: e["accuracy_10fold_mean"] * 100),
        ("True accepts at 1-in-1,000 false accepts", lambda e: e["tar_at_far_0.001"] * 100),
        ("Accuracy, probe downscaled 5×", lambda e: e["stress_at_clean_threshold"]["downscale 5x"]["accuracy"] * 100),
        ("Accuracy, probe rotated 30°", lambda e: e["stress_at_clean_threshold"]["rotate 30 deg"]["accuracy"] * 100),
    ]
    body = ledger_bg(w, h)
    body += '<text class="cap" x="36" y="46">Face-verification benchmark · LFW · measured, not claimed</text>'
    x_lab, x0, x1 = 36, 330, 1090
    scale = (x1 - x0) / (hi - lo)
    # axis ticks
    for t in (85, 90, 95, 100):
        x = x0 + (t - lo) * scale
        body += f'<line x1="{x}" y1="74" x2="{x}" y2="568" stroke="{RULE2}" stroke-width="1" stroke-dasharray="2 5"/>'
        body += (
            f'<text class="mono" x="{x}" y="586" text-anchor="middle" font-size="11" style="fill:{MUTED}">{t}%</text>'
        )
    y = 84
    delay = 0.0
    for title, fn in groups:
        body += f'<text x="{x_lab}" y="{y + 14}" font-size="15" style="fill:{INK}">{escape(title)}</text>'
        for k, (key, label, colour) in enumerate(order):
            v = fn(eng[key])
            bw = max(2.0, (v - lo) * scale)
            by = y + 26 + k * 28
            body += (
                f'<text class="mono" x="{x0 - 10}" y="{by + 16}" text-anchor="end" font-size="11" style="fill:{INK2}">{label}</text>'
                f'<rect class="bar" x="{x0}" y="{by}" width="{bw:.1f}" height="22" fill="{colour}" opacity=".9" style="animation-delay:{delay:.2f}s"/>'
                f'<text class="mono val" x="{x0 + bw + 8:.1f}" y="{by + 16}" font-size="12" font-weight="700" style="fill:{INK};animation-delay:{delay + 0.7:.2f}s">{v:.2f}%</text>'
            )
            delay += 0.07
        y += 120
    # latency strip
    y += 26
    body += f'<text x="{x_lab}" y="{y + 6}" font-size="15" style="fill:{INK}">Latency per 1280-px image (median)</text>'
    lat = [(name, eng[k]["timing_1280px"]["p50_ms"], eng[k]["timing_1280px"]["provider"], c) for k, name, c in order]
    mx = max(v for _, v, _, _ in lat)
    for k, (label, v, prov, colour) in enumerate(lat):
        by = y + 18 + k * 28
        bw = v / mx * 560
        body += (
            f'<text class="mono" x="{x0 - 10}" y="{by + 15}" text-anchor="end" font-size="11" style="fill:{INK2}">{label}</text>'
            f'<rect class="bar" x="{x0}" y="{by}" width="{bw:.1f}" height="20" fill="{colour}" opacity=".9" style="animation-delay:{delay:.2f}s"/>'
            f'<text class="mono val" x="{x0 + bw + 8:.1f}" y="{by + 15}" font-size="12" font-weight="700" style="fill:{INK};animation-delay:{delay + 0.7:.2f}s">{v:.0f} ms · {"GPU" if "CUDA" in prov else "CPU"}</text>'
        )
        delay += 0.07
    body += (
        f'<text class="mono" x="36" y="728" font-size="10.5" style="fill:{MUTED}">Accuracy axes start at 85% (stated, not hidden). LFW is near-saturated: clean accuracy barely separates the models; the stressed probes do.</text>'
        f'<text class="mono" x="36" y="746" font-size="10.5" style="fill:{MUTED}">ArcFace ran on an RTX 4050 laptop GPU, SFace on CPU: a latency comparison of setups, not of models. ArcFace weights are non-commercial research only.</text>'
    )
    return svg(w, h, body, css, "Benchmark: SFace versus ArcFace on LFW")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in (
        ("hero", hero),
        ("pipeline", pipeline),
        ("evidence_ladder", ladder),
        ("merkle", merkle),
        ("benchmark", benchmark),
    ):
        text = fn()
        (OUT / f"{name}.svg").write_text(text, encoding="utf-8")
        print(f"wrote assets/readme/{name}.svg ({len(text) // 1024} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
