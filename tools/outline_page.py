"""把 outline/大纲-*.md 转成手机友好的单页 HTML。用法：python3 tools/outline_page.py outline/大纲-xxx.md"""
import html, re, sys
from pathlib import Path

CSS = """
/* 竖排长卷：单栏阅读，章节为条目，人物表在手机上改为卡片 */
:root{--bg:#f3f4f1;--paper:#fbfbf9;--ink:#1f2523;--muted:#5d6763;--line:#d9ddd8;--accent:#2f6457;--seal:#a8322a;--tag:#e6ece8;
--display:"Noto Serif SC","Songti SC","STSong",serif;--body:-apple-system,"PingFang SC","Hiragino Sans GB","Noto Sans SC","Microsoft YaHei",sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#151a19;--paper:#1c2221;--ink:#e3e7e4;--muted:#9aa5a0;--line:#2f3836;--accent:#7fb8a8;--seal:#e07a6e;--tag:#25302d;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#151a19;--paper:#1c2221;--ink:#e3e7e4;--muted:#9aa5a0;--line:#2f3836;--accent:#7fb8a8;--seal:#e07a6e;--tag:#25302d;color-scheme:dark}
body{background:var(--bg);color:var(--ink);font:17px/1.85 var(--body);-webkit-text-size-adjust:100%}
.wrap{max-width:40rem;margin:0 auto;padding-block:28px 64px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
h1,h2,h3{font-family:var(--display);text-wrap:balance;line-height:1.35;margin:0}
h1{font-size:1.9rem;letter-spacing:.04em}
h2{font-size:1.3rem;margin-top:2.6rem;padding-bottom:.4rem;border-bottom:1px solid var(--line);scroll-margin-top:64px}
h3{font-size:1.1rem;margin-top:1.8rem;color:var(--accent)}
p,ul,ol,blockquote{margin:.7rem 0}
ul,ol{padding-left:1.3rem}li{margin:.35rem 0}
blockquote{margin-left:0;padding:.2rem 0 .2rem .9rem;border-left:3px solid var(--line);color:var(--muted);font-size:.9rem}
strong{color:var(--ink);font-weight:650}
code{font-size:.85em;background:var(--tag);padding:.05em .35em;border-radius:4px;word-break:break-all}
.meta{display:flex;flex-wrap:wrap;gap:6px;margin-top:.4rem}
.meta span{font-size:.78rem;background:var(--tag);color:var(--muted);padding:.1rem .55rem;border-radius:999px;letter-spacing:.03em}
.hit{display:inline-block;font-size:.72rem;line-height:1.5;color:var(--seal);border:1px solid var(--seal);border-radius:4px;padding:0 .35rem;margin-left:.3rem;vertical-align:.12em;white-space:nowrap}
li.hook{color:var(--muted);font-size:.93rem}
li.hook::marker{content:"◇ "}
nav{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--bg);margin:1.4rem calc(-1*max(16px,env(safe-area-inset-left,0px))) 0;padding:.5rem max(16px,env(safe-area-inset-left,0px));border-bottom:1px solid var(--line);display:flex;gap:6px;overflow-x:auto;scrollbar-width:none}
nav::-webkit-scrollbar{display:none}
nav a{flex:none;font-size:.85rem;color:var(--accent);text-decoration:none;padding:.2rem .7rem;border:1px solid var(--line);border-radius:999px;background:var(--paper)}
nav a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
body::before{content:"";position:fixed;inset:0 0 auto;height:env(safe-area-inset-top,0px);z-index:10;background:var(--bg)}
.cards{display:grid;gap:12px;margin-top:1rem}
.card{background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:.8rem 1rem;min-width:0}
.ch{font-family:var(--display);font-size:1.08rem;margin:1.6rem 0 0}
h3+.ch{margin-top:.8rem}
.card h4{margin:0 0 .3rem;font-family:var(--display);font-size:1.05rem}
.card dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:.25rem .8rem;font-size:.93rem}
.card dt{color:var(--muted);font-size:.8rem;padding-top:.2rem;letter-spacing:.05em}
.card dd{margin:0;min-width:0}
"""


def inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)
    return s.replace("（爽点）", '<span class="hit">爽点</span>').replace("（卷末反转）", '<span class="hit">卷末反转</span>')


def table(rows):
    head, body = rows[0], rows[2:]
    out = ['<div class="cards">']
    for r in body:
        out.append(f'<div class="card"><h4>{inline(r[0])}</h4><dl>')
        out += [f"<dt>{inline(h)}</dt><dd>{inline(v)}</dd>" for h, v in zip(head[1:], r[1:])]
        out.append("</dl></div>")
    return out + ["</div>"]


def convert(md):
    out, nav, lst, rows = [], [], None, []
    def close():
        nonlocal lst
        if lst: out.append(f"</{lst}>"); lst = None
    for line in md.splitlines() + [""]:
        if line.startswith("|"):
            rows.append([c.strip() for c in line.strip("|").split("|")]); continue
        if rows: out += table(rows); rows = []
        if m := re.match(r"(#{1,3}) (.+)", line):
            close(); n, t = len(m[1]), m[2]
            if n == 1: out.append(f"<h1>{inline(t)}</h1>"); continue
            if n == 2:
                i = f"s{len(nav)}"; nav.append((i, re.sub(r"^.、", "", t)))
                out.append(f'<h2 id="{i}">{inline(t)}</h2>'); continue
            if mm := re.match(r"(.+?)（(.+)）$", t):
                out.append(f"<h3>{inline(mm[1])}</h3>")
                out.append('<div class="meta">' + "".join(f"<span>{inline(x.strip())}</span>" for x in re.split(r"[，；]", mm[2])) + "</div>")
            else: out.append(f"<h3>{inline(t)}</h3>")
        elif m := re.match(r"(-|\d+\.) (.+)", line):
            kind = "ul" if m[1] == "-" else "ol"
            if lst != kind: close(); out.append(f"<{kind}>"); lst = kind
            cls = ' class="hook"' if m[2].startswith("伏笔") else ""
            out.append(f"<li{cls}>{inline(m[2])}</li>")
        elif m := re.match(r"\*\*(.+?)\*\*（(.+)）$", line):
            close(); out.append(f'<h4 class="ch">{inline(m[1])}</h4>')
            out.append('<div class="meta">' + "".join(f"<span>{inline(x.strip())}</span>" for x in re.split(r"[，；]", m[2])) + "</div>")
        elif line.startswith("> "): close(); out.append(f"<blockquote>{inline(line[2:])}</blockquote>")
        elif line.strip(): close(); out.append(f"<p>{inline(line)}</p>")
        else: close()
    navh = "<nav>" + "".join(f'<a href="#{i}">{html.escape(t)}</a>' for i, t in nav) + "</nav>"
    k = next(i for i, x in enumerate(out) if x.startswith("<h2"))
    return out[:k] + [navh] + out[k:]


src = Path(sys.argv[1])
md = src.read_text(encoding="utf-8")
title = re.search(r"^# (.+?)(?: · .+)?$", md, re.M)[1]
body = "\n".join(convert(md))
page = f"""<title>{html.escape(title)}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@600;700&display=swap">
<style>{CSS}</style>
<main class="wrap">
{body}
</main>
"""
dst = src.with_suffix(".html")
dst.write_text(page, encoding="utf-8")
print(dst)
