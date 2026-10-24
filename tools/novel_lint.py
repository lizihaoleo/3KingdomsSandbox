"""小说稿检查：机器能查的不交给模型。
用法：python3 tools/novel_lint.py novel/谍战线 [--fill] [--from N] [--to M]
  --fill    按日期补全/改正 账本.md 时间线的“星期”一栏
  --from/--to  只查这些章（默认全部）
检查：账本时间线星期；正文禁用词与阳历“X月初X”；电文字条里的真名；正文里“X月X日，星期X”是否对得上；
“不是……是”与破折号的每章用量；单句短段收章。"""
import re, sys, datetime
from pathlib import Path

CN = {c: i for i, c in enumerate("零一二三四五六七八九")}
WD = "一二三四五六日"


def cn2int(s):
    s = s.replace("廿", "二十").replace("卅", "三十")
    if s.isdigit(): return int(s)
    if "十" in s:
        a, _, b = s.partition("十")
        return (CN.get(a, 1) if a else 1) * 10 + (CN.get(b, 0) if b else 0)
    return CN.get(s, 0)


args = sys.argv[1:]
root = Path(args[0]); fill = "--fill" in args
lo = int(args[args.index("--from") + 1]) if "--from" in args else 0
hi = int(args[args.index("--to") + 1]) if "--to" in args else 999
ledger = root / "账本.md"
out = []

# 一、账本时间线星期
if ledger.exists():
    lines = ledger.read_text(encoding="utf-8").split("\n"); changed = False
    for i, l in enumerate(lines):
        m = re.match(r"\| (\d{4})-(\d{2})-(\d{2}) \| ([^|]*) \|", l)
        if not m: continue
        d = datetime.date(int(m[1]), int(m[2]), int(m[3])); w = WD[d.weekday()]
        if m[4].strip() != w:
            if fill: lines[i] = l.replace(f"| {m[4]} |", f"| {w} |", 1); changed = True
            else: out.append(f"账本 时间线 {d}：星期应为{w}，写的是“{m[4].strip()}”")
    if changed: ledger.write_text("\n".join(lines), encoding="utf-8"); print("已补全账本星期")

BANNED = ["除夕", "年夜饭", "元宵", "影佐将军", "晴气课长"]
REAL = ["沈墨言", "林知微", "邵子钧"]
LIMIT_BUSHI, LIMIT_DASH = 3, 2

for p in sorted(root.glob("[0-9][0-9]-*.md")):
    n = int(p.name[:2])
    if not lo <= n <= hi: continue
    text = p.read_text(encoding="utf-8"); L = text.split("\n")
    head = "\n".join(L[:4])
    years = [cn2int(y) + 1911 for y in re.findall(r"民国([一二三四五六七八九十]+)年", head)]
    tag = p.stem
    for i, l in enumerate(L, 1):
        for b in BANNED:
            if b in l and not (b in ("除夕", "年夜饭", "元宵") and re.search(r"旧历|腊月|正月|春节|农历", l)):
                out.append(f"{tag}:{i} 禁用词“{b}”（指旧历时请在同段写明旧历/腊月/正月）")
        for m in re.finditer(r"[一二三四五六七八九十]+月初[一二三四五六七八九十]", l):
            out.append(f"{tag}:{i} 阳历不写“{m[0]}”，写“X月X日”")
        for s in re.split(r"[。！？]", l):
            if re.search(r"(电报|电文|回电|字条|纸条|回话)[^：]{0,12}：", s) and any(r in s.split("：", 1)[-1] for r in REAL):
                out.append(f"{tag}:{i} 电文或字条里出现真名：{s[:40]}")
        for m in re.finditer(r"([一二三四五六七八九十]+)月([一二三四五六七八九十廿]+)日[，,]?\s*(星期|礼拜)([一二三四五六日天])", l):
            mo, dd = cn2int(m[1]), cn2int(m[2])
            y = years[0] if years else 1939
            if len(set(years)) > 1 and mo < 7: y = max(years)
            try:
                w = WD[datetime.date(y, mo, dd).weekday()]
                got = "日" if m[4] == "天" else m[4]
                if got != w: out.append(f"{tag}:{i} {y}年{mo}月{dd}日是星期{w}，文中写星期{got}")
            except ValueError:
                out.append(f"{tag}:{i} 日期不存在：{m[0]}")
    bushi = [i for i, l in enumerate(L, 1) for _ in re.finditer(r"不是[^。！？\n]{0,30}?(而是|，是|,是|是)", l)]
    if len(bushi) > LIMIT_BUSHI: out.append(f"{tag} “不是……是”{len(bushi)}处，超过{LIMIT_BUSHI}：行 {bushi}")
    dash = [i for i, l in enumerate(L, 1) for _ in range(l.count("——"))]
    if len(dash) > LIMIT_DASH: out.append(f"{tag} 破折号{len(dash)}处，超过{LIMIT_DASH}：行 {dash}")
    paras = [l.strip() for l in L if l.strip() and l.strip() != "---"]
    if paras and len(paras[-1]) <= 25 and re.search(r"(不是|只是|就是|原来|从此|永远|终于|总会|才知道|明白了)", paras[-1]): out.append(f"{tag} 末段像点题短句：“{paras[-1]}”")

print("\n".join(out) if out else "没有发现问题")
print(f"共 {len(out)} 条")
