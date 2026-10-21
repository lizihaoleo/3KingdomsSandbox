#!/usr/bin/env python3
"""季汉推演引擎：只负责状态读写、简报生成与裁定落地；思考全部交给 Claude Code 的子代理。

子命令：
  status                     当前日期与天下大势
  pick [--n 7]               选出本季登场人物，写入 .work/agents.txt
  brief 人物 [--out 文件]    生成该人物的私人简报（只含此人能知道的信息）
  judge-brief [--out 文件]   汇总 .work/act-*.json，生成天道裁判简报
  apply                      校验并落地 .work/judge.json，写编年史、更新查看器，清空 .work
  direct "干预"              设置下一季的天命干预（空字符串清除）
  export [--out 文件]        导出完整推演记录（Markdown）
  build-viewer               重新生成 viewer/data.js
"""
import argparse, glob, json, os, random, re, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, ".work")
SEASONS = "春夏秋冬"
DEAD = re.compile("阵亡|病故|被杀")
STATUSES = ["在任", "出征", "下狱", "隐退", "阵亡", "病故", "被杀", "叛逃"]
ACTION_TYPES = ["内政", "军事", "外交", "谋略", "人事", "密信", "观望"]


def p(*a):
    return os.path.join(ROOT, *a)


def rj(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def wj(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def out(text, path=None):
    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"已写入 {path}（{len(text)} 字）")
    else:
        sys.stdout.write(text + "\n")


def cn(n):
    d = "〇一二三四五六七八九"
    if n <= 10:
        return "十" if n == 10 else d[n]
    if n < 20:
        return "十" + (d[n % 10] if n % 10 else "")
    return d[n // 10] + "十" + (d[n % 10] if n % 10 else "")


class Sim:
    def __init__(self):
        self.cfg = rj(p("sim", "config.json"))
        self.world = rj(p("sim", "world.json"))
        self.chars = {n: rj(p("sim", "characters", n + ".json")) for n in self.cfg["order"]}
        self.log = rj(p("chronicle", "log.json"))

    # ---------- 工具 ----------
    def date(self, y=None, s=None):
        y = self.world["year"] if y is None else y
        s = self.world["season"] if s is None else s
        era = self.cfg["era"]
        return {"main": f"{era['name']}{cn(y - era['base'])}年 · {SEASONS[s]}", "sub": f"公元 {y} 年"}

    def age(self, n):
        return self.world["year"] - self.chars[n]["birth"]

    def alive(self):
        return [n for n in self.cfg["order"] if not DEAD.search(self.chars[n]["status"])]

    @staticmethod
    def rk(a, b):
        return f"{a}|{b}" if a < b else f"{b}|{a}"

    def world_brief(self):
        cities = "、".join(f"{k}({c['owner']}{c['troops']}万)" for k, c in self.world["cities"].items())
        fac = "；".join(f"{f}：粮{v['food']} 民心{v['morale']}" for f, v in self.world["factions"].items())
        return f"城池：{cities}\n国力：{fac}"

    def recent(self, k=3):
        parts = []
        for t in self.log[-k:]:
            s = f"【{t['date']['main']}】{t['summary']}"
            s += "".join(f"\n- {e['title']}：{e['text']}" for e in t.get("events", []))
            parts.append(s)
        return "\n".join(parts)

    def save(self):
        wj(p("sim", "world.json"), self.world)
        for n, c in self.chars.items():
            wj(p("sim", "characters", n + ".json"), c)
        wj(p("chronicle", "log.json"), self.log)
        self.build_viewer()

    # ---------- 选人 ----------
    def pick(self, n):
        alive = self.alive()
        must = [x for x in ["刘禅", "司马懿", "孙权", "曹叡"] if x in alive]
        mail = [x for x in alive if self.chars[x]["inbox"] and x not in must]
        rest = [x for x in alive if x not in must and x not in mail]
        random.Random(self.world["turn"] * 7919 + len(self.log)).shuffle(rest)
        return (must + mail + rest)[: max(n, len(must))]

    # ---------- 简报 ----------
    def brief(self, n):
        c, d = self.chars[n], self.date()
        rels = "，".join(f"{[x for x in k.split('|') if x != n][0]}:{v}" for k, v in self.world["rel"].items() if n in k.split("|"))
        last = self.log[-1].get("acts", [])
        speeches = "\n".join(f"{a['name']}公开说：{a['public_speech']}" for a in last if a.get("public_speech"))
        secret = "（你就是那个被诸葛亮之魂附身的刘禅。）" if n == "刘禅" else "（你并不知道刘禅被附身这件事，除非你在下方记忆或密信中得知，或从他的言行中自己推断。）"
        inbox = "\n".join(f"{m['from']}来信：{m['content']}" for m in c["inbox"]) or "无"
        return f"""你将扮演三国历史人物「{n}」，参与一场多智能体历史推演。其他人物由其他独立的AI扮演，他们看不到你的内心。请完全代入此人的身份、性格、立场与认知局限，深思熟虑后行动。

【推演前提】{self.cfg['premise']}
{secret}

【当前】{d['main']}（{d['sub']}），第{self.world['turn'] + 1}季，每季约三个月。
【你的身份】{n}，{self.age(n)}岁，{c['faction']}，{c['role']}，状态：{c['status']}，所在：{c['loc']}。{c['bio']}
【性格与处境】{c['persona']}

【天下大势】
{self.world_brief()}

【近期公开发生的事】
{self.recent(3)}
{('【上季众人公开言论】' + chr(10) + speeches) if speeches else ''}

【你私下记得的事】{'；'.join(c['memory'][-8:]) or '无'}
【你收到的密信】
{inbox}
【你对他人的好恶（-100敌视…100亲信）】{rels or '无'}

规则：只依据你这个身份能知道的信息行事；可以说谎、试探、结盟、背叛、拖延，一切以此人真实会有的考量为准。行动要具体可执行，本季只做一件主要的事。人物名必须用以下名单中的：{'、'.join(self.cfg['order'])}。

输出一个JSON对象（只写JSON，不要其他文字）：
{{"thought":"第一人称内心盘算，150-300字：你如何解读局势、揣测谁在想什么、权衡几种选择、为何选这一步","action":{{"type":"内政|军事|外交|谋略|人事|密信|观望 之一","target":"目标人物/城池/势力","detail":"具体做法，60字内"}},"public_speech":"在朝堂或军中公开说的话，可为空字符串","secret_letters":[{{"to":"人物名","content":"密信内容，80字内"}}],"memory":"本季想记住的要点，30字内"}}
"""

    def judge_brief(self, agents, acts):
        chars = "\n".join(
            f"{n}|{c['faction']}|{self.age(n)}岁|{c['role']}|{c['status']}|在{c['loc']}" for n, c in self.chars.items())
        blocks = []
        for a in acts:
            act = a.get("action") or {}
            letters = "；".join(f"致{l['to']}：{l['content']}" for l in a.get("secret_letters", [])) or "无"
            blocks.append(f"◆{a['name']}\n内心：{a.get('thought', '')}\n行动：{act.get('type', '观望')}→{act.get('target', '')}：{act.get('detail', '')}\n公开言论：{a.get('public_speech') or '无'}\n密信：{letters}")
        d = self.date()
        director = self.world.get("director", "").strip()
        return f"""你是一场三国架空历史推演的“天道”裁判。前提：{self.cfg['premise']}
现在是{d['main']}（{d['sub']}）。请裁定这一季（三个月）众人行动的结果。

要求：依据历史常识、兵力粮草、地理、人物能力与性格判断成败，有因果、有代价、偶有意外，不偏袒任何一方；一季之内不要发生过度剧变（攻城需兵力优势、远征需粮草）；行动之间会相互影响（密信可能被截获、谋略可能被识破）。年老者可能病故，但要合理。未登场人物与无人涉及之地维持现状，也可加入少量合理的背景事件（天灾、羌胡、山越、内乱等）。

【人物（姓名|势力|年龄|职位|状态|所在）】
{chars}

【天下大势】
{self.world_brief()}

【上季回顾】
{self.recent(1)}

【本季登场人物】{'、'.join(agents)}

【本季众人行动】
{chr(10).join(blocks)}
{('【天命干预：本季必须发生并据此推演】' + director) if director else ''}

输出一个JSON对象（只写JSON）：
{{"summary":"本季大事记，史书笔法，150-250字","events":[{{"title":"四字以内地名或事名","text":"一两句话","actors":["人物名"]}}],"city_changes":[{{"city":"城名(仅限已有城池：{'、'.join(self.world['cities'])})","owner":"蜀|魏|吴","troops":整数万}}],"faction_changes":[{{"faction":"蜀|魏|吴","food":增减整数,"morale":增减整数}}],"relation_changes":[{{"a":"人物","b":"人物","delta":-40到40的整数,"reason":"简述"}}],"character_changes":[{{"name":"人物","status":"{'|'.join(STATUSES)}","role":"新职位或留空","loc":"所在城池或留空","faction":"若改投他国则填，否则留空"}}],"knowledge":[{{"name":"人物","learns":"此人私下得知的信息，40字内"}}],"intercepted_letters":[{{"from":"写信人","to":"收信人","by":"截获者"}}]}}
events 3-6条；只列出有变化的城池、关系和人物；被截获的密信不会送达收信人，而会被截获者得知。
"""

    # ---------- 落地 ----------
    def apply(self, agents, acts, J):
        names = set(self.cfg["order"])
        factions = self.cfg["factions"]
        changed = []
        intercepted = {(x.get("from"), x.get("to")): x.get("by") for x in J.get("intercepted_letters") or [] if isinstance(x, dict)}
        for n in agents:
            self.chars[n]["inbox"] = []
        for a in acts:
            c = self.chars[a["name"]]
            if a.get("thought"):
                c["thought"] = a["thought"]
            if a.get("memory"):
                c["memory"].append(a["memory"])
            for l in a.get("secret_letters", []):
                by = intercepted.get((a["name"], l["to"]))
                if by in names:
                    self.chars[by]["memory"].append(f"截获{a['name']}致{l['to']}密信：{l['content']}")
                else:
                    self.chars[l["to"]]["inbox"].append({"from": a["name"], "content": l["content"]})
        for cc in J.get("city_changes") or []:
            k = cc.get("city")
            if k not in self.world["cities"]:
                continue
            cur = self.world["cities"][k]
            if cc.get("owner") in factions and cc["owner"] != cur["owner"]:
                cur["owner"] = cc["owner"]; changed.append(k)
            try:
                t = max(0, min(60, round(float(cc.get("troops")))))
                if t != cur["troops"]:
                    cur["troops"] = t
                    if k not in changed: changed.append(k)
            except (TypeError, ValueError):
                pass
        for fc in J.get("faction_changes") or []:
            F = self.world["factions"].get(fc.get("faction"))
            if not F:
                continue
            F["food"] = max(0, F["food"] + round(float(fc.get("food") or 0)))
            F["morale"] = max(0, min(100, F["morale"] + round(float(fc.get("morale") or 0))))
        for r in J.get("relation_changes") or []:
            a, b = r.get("a"), r.get("b")
            if a not in names or b not in names or a == b:
                continue
            k = self.rk(a, b)
            dlt = max(-40, min(40, round(float(r.get("delta") or 0))))
            self.world["rel"][k] = max(-100, min(100, self.world["rel"].get(k, 0) + dlt))
        for ch in J.get("character_changes") or []:
            c = self.chars.get(ch.get("name"))
            if not c:
                continue
            if ch.get("status"): c["status"] = str(ch["status"])
            if ch.get("role"): c["role"] = str(ch["role"])
            if ch.get("loc") in self.world["cities"]: c["loc"] = ch["loc"]
            if ch.get("faction") in factions: c["faction"] = ch["faction"]
        for kn in J.get("knowledge") or []:
            if kn.get("name") in self.chars and kn.get("learns"):
                self.chars[kn["name"]]["memory"].append("得知：" + kn["learns"])
        for c in self.chars.values():
            c["memory"] = c["memory"][-14:]
        entry = {
            "turn": self.world["turn"] + 1, "date": self.date(),
            "summary": str(J.get("summary") or "本季无大事。"),
            "events": [{"title": str(e.get("title", "")), "text": str(e.get("text", ""))} for e in (J.get("events") or [])[:8]],
            "director": self.world.get("director", ""), "changed": changed, "acts": acts,
        }
        self.log.append(entry)
        self.write_turn_md(entry)
        self.world["director"] = ""
        self.world["turn"] += 1
        self.world["season"] += 1
        if self.world["season"] > 3:
            self.world["season"] = 0; self.world["year"] += 1
        self.save()
        return entry

    def turn_md(self, t):
        prefix = "序幕 · " if t["turn"] == 0 else "第%d季 · " % t["turn"]
        L = [f"## {prefix}{t['date']['main']}（{t['date']['sub']}）", ""]
        if t.get("director"):
            L += [f"> 天命干预：{t['director']}", ""]
        L += [t["summary"], ""]
        L += [f"- **{e['title']}**：{e['text']}" for e in t.get("events", [])]
        if t.get("acts"):
            L += ["", "### 众人心思与行动", ""]
            for a in t["acts"]:
                act = a.get("action") or {}
                L.append(f"#### {a['name']}（{act.get('type', '观望')}{(' → ' + act['target']) if act.get('target') else ''}）")
                if a.get("thought"): L.append(f"*内心*：{a['thought']}  ")
                if act.get("detail"): L.append(f"*行动*：{act['detail']}  ")
                if a.get("public_speech"): L.append(f"*公开言论*：{a['public_speech']}  ")
                for l in a.get("secret_letters", []):
                    L.append(f"*密信致{l['to']}*：{l['content']}  ")
                L.append("")
        return "\n".join(L) + "\n"

    def write_turn_md(self, t):
        fn = p("chronicle", f"{t['turn']:04d}-{t['date']['sub'].replace('公元 ', '').replace(' 年', '')}{t['date']['main'][-1]}.md")
        with open(fn, "w", encoding="utf-8") as f:
            f.write(self.turn_md(t))

    def export(self):
        L = [f"# {self.cfg['title']} · 推演全记录", "", f"> {self.cfg['premise']}", ""]
        L += [self.turn_md(t) for t in self.log]
        L += ["## 当前局势", "", self.world_brief().replace("\n", "\n\n"), "", "## 人物现状", ""]
        L += [f"- {n}｜{c['faction']}｜{self.age(n)}岁｜{c['role']}｜{c['status']}｜在{c['loc']}" for n, c in self.chars.items()]
        return "\n".join(L) + "\n"

    def build_viewer(self):
        try:
            import subprocess
            branch = subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        except Exception:
            branch = ""
        data = {"cfg": self.cfg, "world": self.world, "chars": self.chars, "log": self.log, "date": self.date(), "branch": branch}
        with open(p("viewer", "data.js"), "w", encoding="utf-8") as f:
            f.write("window.SIM = " + json.dumps(data, ensure_ascii=False) + ";\n")


# ---------- 校验 ----------
def load_act(name, path, order):
    try:
        r = rj(path)
    except Exception as e:
        return None, f"{path} 不是合法 JSON：{e}"
    if not isinstance(r, dict):
        return None, f"{path} 顶层必须是对象"
    act = r.get("action") if isinstance(r.get("action"), dict) else {}
    if act.get("type") not in ACTION_TYPES:
        act["type"] = "观望" if not act.get("type") else str(act["type"])[:4]
    letters = []
    for l in r.get("secret_letters") or []:
        if isinstance(l, dict) and l.get("to") in order and l.get("to") != name and l.get("content"):
            letters.append({"to": l["to"], "content": str(l["content"])})
    return {"name": name, "thought": str(r.get("thought") or ""),
            "action": {"type": act["type"], "target": str(act.get("target") or ""), "detail": str(act.get("detail") or "")},
            "public_speech": str(r.get("public_speech") or ""), "secret_letters": letters[:3],
            "memory": str(r.get("memory") or "")}, None


def read_agents():
    f = os.path.join(WORK, "agents.txt")
    if not os.path.exists(f):
        sys.exit("找不到 .work/agents.txt，请先运行 pick")
    return [x.strip() for x in open(f, encoding="utf-8") if x.strip()]


def main():
    ap = argparse.ArgumentParser(description="季汉推演引擎")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("status")
    x = sp.add_parser("pick"); x.add_argument("--n", type=int, default=7)
    x = sp.add_parser("brief"); x.add_argument("name"); x.add_argument("--out")
    x = sp.add_parser("judge-brief"); x.add_argument("--out")
    sp.add_parser("apply")
    x = sp.add_parser("direct"); x.add_argument("text")
    x = sp.add_parser("export"); x.add_argument("--out")
    sp.add_parser("build-viewer")
    a = ap.parse_args()
    S = Sim()

    if a.cmd == "status":
        d = S.date()
        print(f"第 {S.world['turn']} 季已完成；下一季：{d['main']}（{d['sub']}）")
        print(S.world_brief())
        if S.world.get("director"): print("待生效天命干预：" + S.world["director"])
        dead = [n for n in S.cfg["order"] if DEAD.search(S.chars[n]["status"])]
        if dead: print("已故：" + "、".join(dead))
    elif a.cmd == "pick":
        os.makedirs(WORK, exist_ok=True)
        for f in glob.glob(os.path.join(WORK, "*")):
            os.remove(f)
        ag = S.pick(a.n)
        open(os.path.join(WORK, "agents.txt"), "w", encoding="utf-8").write("\n".join(ag) + "\n")
        print("\n".join(ag))
    elif a.cmd == "brief":
        if a.name not in S.chars: sys.exit(f"没有人物：{a.name}")
        out(S.brief(a.name), a.out)
    elif a.cmd == "judge-brief":
        agents = read_agents()
        acts, errs = [], []
        for n in agents:
            path = os.path.join(WORK, f"act-{n}.json")
            if not os.path.exists(path):
                errs.append(f"缺少 {path}"); continue
            r, e = load_act(n, path, S.cfg["order"])
            if e: errs.append(e)
            else: acts.append(r)
        if errs:
            sys.exit("\n".join(errs) + "\n请让对应人物的子代理重新写入后再运行。")
        wj(os.path.join(WORK, "acts.json"), acts)
        out(S.judge_brief(agents, acts), a.out)
    elif a.cmd == "apply":
        agents = read_agents()
        try:
            acts = rj(os.path.join(WORK, "acts.json"))
        except FileNotFoundError:
            sys.exit("缺少 .work/acts.json，请先运行 judge-brief")
        try:
            J = rj(os.path.join(WORK, "judge.json"))
        except Exception as e:
            sys.exit(f".work/judge.json 不是合法 JSON：{e}\n请让 judge 子代理重新写入。")
        t = S.apply(agents, acts, J)
        shutil.rmtree(WORK, ignore_errors=True)
        first = re.split("[。；]", t["summary"])[0][:60]
        print(f"COMMIT_MSG: 第{t['turn']}季 {t['date']['main']}：{first}")
        print(t["summary"])
        if t["changed"]: print("变动城池：" + "、".join(t["changed"]))
    elif a.cmd == "direct":
        S.world["director"] = a.text.strip()
        wj(p("sim", "world.json"), S.world); S.build_viewer()
        print("已设置天命干预：" + (S.world["director"] or "（已清除）"))
    elif a.cmd == "export":
        out(S.export(), a.out)
    elif a.cmd == "build-viewer":
        S.build_viewer(); print("viewer/data.js 已更新")


if __name__ == "__main__":
    main()
