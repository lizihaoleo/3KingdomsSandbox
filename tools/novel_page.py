"""把 novel/<线名>/NN-*.md 合成一页手机友好的 HTML，供发布成私有页面在手机上读。
用法：python3 tools/novel_page.py novel/谍战线   →  novel/谍战线/正文.html
可选 novel/<线名>/分卷.txt，每行“第一卷 雨夜 1-7”：左侧目录按卷分组，正文插卷名。"""
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
.toc{font-family:var(--ui);font-size:.86rem;line-height:1.5}
.toc .vol{display:block;margin:1.1rem 0 .3rem;color:var(--seal);font-weight:600;letter-spacing:.08em;text-decoration:none}
.toc .vol:first-child{margin-top:0}
.toc .ch{display:block;padding:.18rem .6rem;margin-left:-.6rem;border-radius:6px;color:var(--muted);text-decoration:none}
.toc .ch b{font-weight:400;color:var(--ink)}
.toc .ch:hover,.toc .ch.on{background:var(--tag)}
.toc .ch.on b{color:var(--accent);font-weight:600}
.toc a:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.side{position:fixed;top:0;bottom:0;left:0;width:15.5rem;overflow-y:auto;padding:28px 18px 40px 22px;background:var(--paper);border-right:1px solid var(--line);z-index:20;scrollbar-width:thin}
.side .bk{font-family:var(--display);font-size:1.25rem;letter-spacing:.16em;margin-bottom:1rem}
.cover{display:block;width:min(100%,26rem);margin:4.5rem auto -2.2rem;border-radius:4px;box-shadow:0 6px 24px rgb(0 0 0/.25)}
.vh{font-family:var(--display);text-align:center;color:var(--seal);font-size:1.05rem;letter-spacing:.3em;margin:4.5rem 0 -1.6rem;scroll-margin-top:24px}
.tocbtn{position:fixed;z-index:25;top:max(10px,calc(env(safe-area-inset-top,0px) + 8px));left:max(10px,env(safe-area-inset-left,0px));font:600 .85rem var(--ui);color:var(--accent);background:var(--paper);border:1px solid var(--line);border-radius:999px;padding:.35rem .9rem;min-height:36px;cursor:pointer}
.tocbtn:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media (min-width:1000px){.side{padding-top:64px}.wrap{margin-left:calc(15.5rem + max(0px,(100vw - 15.5rem - 38rem)/2))}
body.notoc .side{display:none}body.notoc .wrap{margin-left:auto}}
@media (max-width:999px){
.side{transform:translateX(-102%);transition:transform .22s ease;width:min(80vw,18rem);box-shadow:0 0 24px rgb(0 0 0/.18);padding-top:max(28px,calc(env(safe-area-inset-top,0px) + 16px))}
.side:not(.open){box-shadow:none;visibility:hidden;transition:transform .22s ease,visibility 0s .22s}
.side.open{transform:none}
.scrim{position:fixed;inset:0;background:rgb(0 0 0/.3);z-index:18;display:none}
.scrim.open{display:block}
.wrap{padding-top:56px}
h2{scroll-margin-top:56px}
}
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


CN = "零一二三四五六七八九"


def cnum(n):
    if n < 10: return CN[n]
    t, u = divmod(n, 10)
    return (CN[t] if t > 1 else "") + "十" + (CN[u] if u else "")


JS = """
const side=document.querySelector('.side'),scrim=document.querySelector('.scrim'),btn=document.querySelector('.tocbtn');
const wide=matchMedia('(min-width:1000px)');
function setOpen(o){side.classList.toggle('open',o);scrim.classList.toggle('open',o);btn.setAttribute('aria-expanded',o)}
function setHidden(h){document.body.classList.toggle('notoc',h);try{localStorage.setItem('notoc',h?'1':'')}catch(e){}label()}
function label(){const shown=wide.matches?!document.body.classList.contains('notoc'):side.classList.contains('open');btn.textContent=shown?'隐藏目录':'目录';btn.setAttribute('aria-expanded',shown)}
try{if(localStorage.getItem('notoc'))document.body.classList.add('notoc')}catch(e){}
btn.addEventListener('click',()=>{if(wide.matches)setHidden(!document.body.classList.contains('notoc'));else{setOpen(!side.classList.contains('open'));label()}});
wide.addEventListener('change',()=>{setOpen(false);label()});label();
scrim.addEventListener('click',()=>{setOpen(false);label()});
side.addEventListener('click',e=>{if(e.target.closest('a')&&!wide.matches){setOpen(false);label()}});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){setOpen(false);label()}});
const links=new Map([...document.querySelectorAll('.toc .ch')].map(a=>[a.getAttribute('href').slice(1),a]));
let cur=null;
const io=new IntersectionObserver(es=>{for(const e of es){if(e.isIntersecting){const a=links.get(e.target.id);if(a&&a!==cur){cur&&cur.classList.remove('on');a.classList.add('on');cur=a;
const r=a.getBoundingClientRect(),sr=side.getBoundingClientRect();if(r.top<sr.top+40||r.bottom>sr.bottom-40)a.scrollIntoView({block:'center'})}}}},{rootMargin:'0px 0px -70% 0px'});
document.querySelectorAll('h2[id]').forEach(h=>io.observe(h));
"""

src = Path(sys.argv[1])
files = sorted(p for p in src.glob("[0-9][0-9]-*.md"))
line_name = src.name
book = "孤岛"
vols = {}
vf = src / "分卷.txt"
if vf.exists():
    for l in vf.read_text(encoding="utf-8").splitlines():
        if m := re.match(r"(\S+)\s+(\S+)\s+(\d+)-(\d+)", l.strip()):
            vols[int(m[3])] = (m[1], m[2])
toc, body = [], []
vi = 0
for i, p in enumerate(files, 1):
    num = int(p.name[:2])
    cid, short, part = chapter(p.read_text(encoding="utf-8"), i)
    if num in vols:
        vi += 1; vn, vt = vols[num]
        toc.append(f'<a class="vol" href="#v{vi}">{html.escape(vn)} · {html.escape(vt)}</a>')
        cv = next((c for c in (src / "covers" / f"v{vi}.jpg", src / "covers" / f"v{vi}.png") if c.exists()), None)
        if cv:
            body.append(f'<img class="cover" src="covers/{cv.name}" alt="{html.escape(vn)} {html.escape(vt)}封面" loading="lazy">')
        body.append(f'<div class="vh" id="v{vi}">{html.escape(vn)}　{html.escape(vt)}</div>')
    toc.append(f'<a class="ch" href="#{cid}"><b>{html.escape(short)}</b></a>' if num == 0 else f'<a class="ch" href="#{cid}">{cnum(num)}　<b>{html.escape(short)}</b></a>')
    body += part
n = len([f for f in files if int(f.name[:2]) > 0])
last = max([int(x) for x in re.findall(r"-(\d+)", vf.read_text(encoding="utf-8"))] or [0]) if vf.exists() else 0
end = "—— 全书完 ——" if last and n >= last else "—— 未完 ——"
page = f"""<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{book}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;600;700&display=swap">
<style>{CSS}</style>
<button class="tocbtn" aria-expanded="false" aria-controls="toc">目录</button>
<div class="scrim"></div>
<aside class="side" id="toc"><div class="bk">{book}</div><nav class="toc" aria-label="目录">{''.join(toc)}</nav></aside>
<main class="wrap">
<h1>{book}</h1>
<div class="sub">{html.escape(line_name)} · 正文 · 第一至{cnum(n)}章</div>
{chr(10).join(body)}
<div class="end">{end}</div>
</main>
<script>{JS}</script>
"""
dst = src / "正文.html"
dst.write_text(page, encoding="utf-8")
print(dst)
