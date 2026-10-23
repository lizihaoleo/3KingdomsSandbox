"""把 novel/<线名>/NN-*.md 合成一页手机友好的 HTML，供发布成私有页面在手机上读。
用法：python3 tools/novel_page.py novel/谍战线   →  novel/谍战线/正文.html"""
import html, re, sys
from pathlib import Path

CSS = """
/* 单栏长卷：正文衬线、首行缩进，章节条目在顶栏横滑 */
:root{--bg:#f4f3ee;--paper:#fbfaf6;--ink:#22272a;--muted:#6a7278;--line:#dcdcd4;--accent:#3a5f6b;--seal:#9e3a2f;--tag:#e8eae4;
--display:"Noto Serif SC","Songti SC","STSong",serif;--body:"Noto Serif SC","Songti SC","STSong",Georgia,serif;--ui:-apple-system,"PingFang SC","Hiragino Sans GB","Noto Sans SC","Microsoft YaHei",sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#171a1c;--paper:#1e2225;--ink:#e4e4de;--muted:#9aa2a8;--line:#30363a;--accent:#8fb6c2;--seal:#d9796c;--tag:#262c30;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#171a1c;--paper:#1e2225;--ink:#e4e4de;--muted:#9aa2a8;--line:#30363a;--accent:#8fb6c2;--seal:#d9796c;--tag:#262c30;color-scheme:dark}
body{background:var(--bg);color:var(--ink);font:18px/1.95 var(--body);-webkit-text-size-adjust:100%}
.wrap{max-width:38rem;margin:0 auto;padding-block:28px 72px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
h1,h2{font-family:var(--display);text-wrap:balance;line-height:1.3;margin:0}
h1{font-size:2.1rem;letter-spacing:.12em}
.sub{font-family:var(--ui);font-size:.85rem;color:var(--muted);letter-spacing:.08em;margin-top:.4rem}
h2{font-size:1.45rem;margin-top:3.4rem;text-align:center;scroll-margin-top:72px}
.when{font-family:var(--ui);font-size:.8rem;color:var(--muted);text-align:center;letter-spacing:.06em;margin:.5rem 0 1.8rem}
p{margin:0 0 .25rem;text-indent:2em;text-align:justify;hanging-punctuation:first allow-end}
blockquote{margin:1.2rem 0 1.2rem 1.4em;padding:0;color:var(--muted);font-size:.95rem}
blockquote p{text-indent:0}
hr{border:0;height:auto;margin:2.2rem 0;text-align:center;color:var(--muted);font-size:.9rem;letter-spacing:.6em}
hr::before{content:"⁂"}
nav{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--bg);margin:1.4rem calc(-1*max(16px,env(safe-area-inset-left,0px))) 0;padding:.5rem max(16px,env(safe-area-inset-left,0px));border-bottom:1px solid var(--line);display:flex;gap:6px;overflow-x:auto;scrollbar-width:none;font-family:var(--ui)}
nav::-webkit-scrollbar{display:none}
nav a{flex:none;font-size:.85rem;color:var(--accent);text-decoration:none;padding:.2rem .7rem;border:1px solid var(--line);border-radius:999px;background:var(--paper)}
nav a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
body::before{content:"";position:fixed;inset:0 0 auto;height:env(safe-area-inset-top,0px);z-index:10;background:var(--bg)}
.end{font-family:var(--ui);color:var(--muted);font-size:.85rem;text-align:center;margin-top:3rem;letter-spacing:.1em}
@media (prefers-reduced-motion:no-preference){html{scroll-behavior:smooth}}
"""


def inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    return s


def chapter(md, idx):
    out, title, when = [], "", ""
    in_quote = False
    for line in md.splitlines() + [""]:
        if m := re.match(r"# (.+)", line):
            title = m[1]; continue
        if not when and title and line.strip() and not line.startswith(("#", ">", "---")):
            # 章题之后第一段是时间
            if len(line.strip()) <= 24 and re.match(r"民国|公元|一九", line.strip()):
                when = line.strip(); continue
        if line.startswith("> "):
            if not in_quote: out.append("<blockquote>"); in_quote = True
            out.append(f"<p>{inline(line[2:])}</p>"); continue
        if in_quote: out.append("</blockquote>"); in_quote = False
        if line.strip() == "---": out.append("<hr>"); continue
        if line.strip(): out.append(f"<p>{inline(line.strip())}</p>")
    cid = f"c{idx}"
    short = re.sub(r"^第.+?章\s*", "", title)
    head = [f'<h2 id="{cid}">{inline(title)}</h2>']
    if when: head.append(f'<div class="when">{inline(when)}</div>')
    return cid, short, head + out


src = Path(sys.argv[1])
files = sorted(p for p in src.glob("[0-9][0-9]-*.md"))
line_name = src.name
book = "孤岛"
nav, body = [], []
for i, p in enumerate(files, 1):
    cid, short, part = chapter(p.read_text(encoding="utf-8"), i)
    nav.append(f'<a href="#{cid}">{html.escape(short)}</a>')
    body += part
n = len(files)
page = f"""<title>{book}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;600;700&display=swap">
<style>{CSS}</style>
<main class="wrap">
<h1>{book}</h1>
<div class="sub">{html.escape(line_name)} · 正文 · 第一至{'一二三四五六七八九十'[n-1] if n <= 10 else n}章</div>
<nav>{''.join(nav)}</nav>
{chr(10).join(body)}
<div class="end">—— 未完 ——</div>
</main>
"""
dst = src / "正文.html"
dst.write_text(page, encoding="utf-8")
print(dst)
