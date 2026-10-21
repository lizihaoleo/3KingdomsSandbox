#!/usr/bin/env python3
"""季汉推演引擎：只负责状态读写、简报生成与裁定落地；思考全部交给 Claude Code 的子代理。

子命令：
  status                     当前日期与天下大势
  pick [--n 上限]            取天道上季点名的登场人物（无则按旧法选 7 人），写入 .work/agents.txt；输出标注主要/次要人物
  brief 人物 [--out 文件]    生成该人物的私人简报（只含此人能知道的信息）
  judge-brief [--out 文件]   汇总 .work/act-*.json，生成天道裁判简报
  apply                      校验并落地 .work/judge.json，写编年史、更新查看器，清空 .work
  direct "干预"              设置下一季的天命干预（空字符串清除）
  thread "标题" "详情" [--actors 甲,乙]  登记一条悬而未决的线索，交天道日后推进或了结
  export [--out 文件]        导出完整推演记录（Markdown）
  build-viewer               重新生成 viewer/data.js
"""
import argparse, glob, json, os, random, re, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, ".work")
SEASONS = "春夏秋冬"
DEAD = re.compile("阵亡|病故|被杀|赐死|遇害|自尽")
OFFSTAGE = ("未出场", "退场")  # 未出场：候场人物，到时由天道安排登场；退场：仍在世但剧情暂不需要
STATUSES = ["在任", "出征", "下狱", "隐退", "退场", "叛逃", "阵亡", "病故", "被杀", "自尽"]
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
        """在场人物：在世且已登场、未退场。"""
        return [n for n in self.cfg["order"] if not DEAD.search(self.chars[n]["status"]) and self.chars[n]["status"] not in OFFSTAGE]

    def known(self):
        """可以被提及、写信的人：在世且已登场（含退场者）。"""
        return [n for n in self.cfg["order"] if not DEAD.search(self.chars[n]["status"]) and self.chars[n]["status"] != "未出场"]

    @staticmethod
    def rk(a, b):
        return f"{a}|{b}" if a < b else f"{b}|{a}"

    def world_brief(self, plain=False):
        """plain=True 给人物看：粮草与民心只用此人会有的说法，不出现抽象数值。"""
        cities = "、".join(f"{k}({c['owner']}{c['troops']}万)" for k, c in self.world["cities"].items())
        if plain:
            food = lambda v: "仓廪空虚" if v < 30 else "粮草吃紧" if v < 50 else "粮草尚可" if v < 80 else "仓廪充实" if v < 110 else "积谷如山"
            mor = lambda v: "人心离散" if v < 40 else "人心浮动" if v < 55 else "人心安定" if v < 70 else "上下归心" if v < 85 else "万众拥戴"
            fac = "；".join(f"{f}：{food(v['food'])}，{mor(v['morale'])}" for f, v in self.world["factions"].items())
        else:
            fac = "；".join(f"{f}：粮{v['food']} 民心{v['morale']}" for f, v in self.world["factions"].items())
        return f"城池：{cities}\n国力：{fac}"

    def recent(self, k=3, public=False):
        """public=True 给人物看：序幕的记载换成不含亮魂秘密的公开版本。"""
        parts = []
        for t in self.log[-k:]:
            summ = self.cfg.get("public_premise", t["summary"]) if public and t["turn"] == 0 else t["summary"]
            s = f"【{t['date']['main']}】{summ}"
            s += "".join(f"\n- {e['title']}：{e['text']}" for e in t.get("events", []))
            parts.append(s)
        return "\n".join(parts)

    def last_acted(self):
        last = {}
        for t in self.log:
            for a in t.get("acts") or []:
                last[a["name"]] = t["turn"]
        return last

    def add_thread(self, title, detail, actors):
        th = self.world.setdefault("threads", [])
        nid = max([x["id"] for x in th] + [0]) + 1
        th.append({"id": nid, "title": title[:20], "detail": detail[:120], "actors": [a for a in actors if a in self.chars],
                   "since": self.world["turn"], "last": self.world["turn"]})
        return nid

    def save(self):
        wj(p("sim", "world.json"), self.world)
        for n, c in self.chars.items():
            wj(p("sim", "characters", n + ".json"), c)
        wj(p("chronicle", "log.json"), self.log)
        self.build_viewer()

    # ---------- 选人 ----------
    def pick(self, n=None):
        alive = self.alive()
        cast = [x for x in self.world.get("cast") or [] if x in alive]
        if cast:
            ag = (["刘禅"] if "刘禅" in alive else []) + [x for x in cast if x != "刘禅"]
            return ag[:n] if n else ag
        n = n or 7
        must = [x for x in ["刘禅", "张皇后", "司马懿", "孙权", "曹叡"] if x in alive]
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
        soul = n == "刘禅"
        premise = self.cfg["premise"] if soul else self.cfg.get("public_premise", self.cfg["premise"])
        secret = "（你就是那个被诸葛亮之魂附身的刘禅。）" if soul else ""
        inbox = "\n".join(f"{m['from']}来信：{m['content']}" for m in c["inbox"]) or "无"
        return f"""你将扮演三国历史人物「{n}」，参与一场多智能体历史推演。其他人物由其他独立的AI扮演，他们看不到你的内心。请完全代入此人的身份、性格、立场与认知局限，深思熟虑后行动。

【推演前提】{premise}
{secret}

【当前】{d['main']}（{d['sub']}），第{self.world['turn'] + 1}季，每季约三个月。
【你的身份】{n}，{self.age(n)}岁，{c['faction']}，{c['role']}，状态：{c['status']}，所在：{c['loc']}。{c['bio']}
【性格与处境】{c['persona']}

【天下大势】
{self.world_brief(plain=True)}

【近期公开发生的事】
{self.recent(3, public=not soul)}
{('【上季众人公开言论】' + chr(10) + speeches) if speeches else ''}

【你私下记得的事】{'；'.join(c['memory'][-8:]) or '无'}
【你收到的密信】
{inbox}
【你对他人的好恶（-100敌视…100亲信）】{rels or '无'}

规则：只依据你这个身份能知道的信息行事；想事情、说话都用这个人物在那个年代会用的说法，不要出现“粮40”“民心60”这类数值；可以说谎、试探、结盟、背叛、拖延，一切以此人真实会有的考量为准。行动要具体可执行，本季只做一件主要的事。人物名必须用以下名单中的：{'、'.join(self.known())}。

输出一个JSON对象（只写JSON，不要其他文字）：
{{"thought":"第一人称内心盘算，150-300字：你如何解读局势、揣测谁在想什么、权衡几种选择、为何选这一步","action":{{"type":"内政|军事|外交|谋略|人事|密信|观望 之一","target":"目标人物/城池/势力","detail":"具体做法，60字内"}},"public_speech":"在朝堂或军中公开说的话，可为空字符串","secret_letters":[{{"to":"人物名","content":"密信内容，80字内"}}],"memory":"本季想记住的要点，30字内"}}
"""

    def judge_brief(self, agents, acts):
        chars = "\n".join(
            f"{n}|{c['faction']}|{self.age(n)}岁|{c['role']}|{c['status']}|在{c['loc']}｜{c.get('hist') or ''}"
            for n in self.known() for c in [self.chars[n]])
        pool = "\n".join(
            f"{n}|{c['faction']}|{self.age(n)}岁|{c['bio']}｜史载约{c['debut']}年登上舞台｜{c.get('hist') or ''}"
            for n in self.cfg["order"] for c in [self.chars[n]] if c["status"] == "未出场") or "无"
        mail = "、".join(f"{n}（{len(self.chars[n]['inbox'])}封）" for n in self.alive() if self.chars[n]["inbox"]) or "无"
        cur = self.world["turn"]
        overdue = "、".join(f"{n}（{sum(1 for m in self.chars[n]['inbox'] if cur - m.get('turn', cur) >= 2)}封）" for n in self.alive()
                            if any(cur - m.get("turn", cur) >= 2 for m in self.chars[n]["inbox"])) or "无"
        now = self.world["turn"] + 1
        LIMIT = 8
        def due(x):
            if x.get("major"):
                return "全书主钩子，终局前回收"
            left = x["since"] + LIMIT - now
            return "已超期，本季必须了结" if left <= 0 else f"还剩{left}季须了结"
        threads = "\n".join(
            f"#{x['id']} {x['title']}（第{x['since']}季起，{due(x)}，已{now - 1 - x['last']}季无进展）：{x['detail']}" + (f"［相关：{'、'.join(x['actors'])}］" if x.get("actors") else "")
            for x in sorted(self.world.get("threads") or [], key=lambda x: (bool(x.get("major")), x["since"]))) or "无"
        n_major = sum(1 for x in self.world.get("threads") or [] if x.get("major"))
        la = self.last_acted()
        idle = "、".join(f"{n}（{'从未' if n not in la else f'{now - 1 - la[n]}季'}）" for n in self.alive()
                         if now - 1 - la.get(n, 0) >= 4) or "无"
        blocks = []
        for a in acts:
            act = a.get("action") or {}
            letters = "；".join(f"致{l['to']}：{l['content']}" for l in a.get("secret_letters", [])) or "无"
            blocks.append(f"◆{a['name']}\n内心：{a.get('thought', '')}\n行动：{act.get('type', '观望')}→{act.get('target', '')}：{act.get('detail', '')}\n公开言论：{a.get('public_speech') or '无'}\n密信：{letters}")
        d = self.date()
        director = self.world.get("director", "").strip()
        return f"""你是一场三国架空历史推演的“天道”裁判。前提：{self.cfg['premise']}
现在是{d['main']}（{d['sub']}）。请裁定这一季（三个月）众人行动的结果。

要求：依据历史常识、兵力粮草、地理、人物能力与性格判断成败，有因果、有代价，不偏袒任何一方；行动之间会相互影响（密信可能被截获、谋略可能被识破）。这份记录要写成小说，所以“公正”不等于“温吞”：
1. 每季至少裁出一场分出胜负的正面冲突（战场、朝堂或谋略），有明确的赢家和代价，不要各自退兵、不了了之。
2. 每三四季至少一次大转折：城池易手、重要人物死亡、叛变或下狱、秘密险些曝光。距上次大转折已三季以上的，本季就要安排。
3. 谋划周密又抓住时机的一方，给足回报（大胜而不是小胜）；冒进、失算的一方要付出沉重代价。主角也会挨重拳。
4. 亮魂身份是全书最大的秘密：每隔几季安排一次真正的险情，让它差点被戳穿，而不只是有人心里起疑。
   众人的猜测要合乎常理：见到孔明的笔迹、口吻、谋略，旁人首先会想到“孔明诈死、藏身成都”或“孔明旧人代笔、留有锦囊”，尤其魏、吴两国没人亲眼见过孔明的尸身，诈死之说最可能流行，也最可能引出开棺验尸、搜宫索人这类行动。鬼神附体之说只能是谣言、方士之言或极少数人的直觉，不能成为聪明人的首选结论。
5. 各方都按兵不动时，用天灾、叛乱、意外死亡、内奸等外部变数打破僵局；年老者可能病故，但要合理。
6. 男女主角：男主是刘禅（亮魂），女主是张皇后与黄月英，辛宪英是魏方的对手型女主。每一两季至少安排一场男主与女主的直接互动（对话、冲突、试探或合作），写进 events；女主的行动同样要有实际后果。
7. 伏笔要回收：优先让已铺垫的线索结出果子，不要只开新坑。
summary 与 events 用史书或小说的笔法，不要出现“粮40”“民心60”这类数值。

【人物（姓名|势力|年龄|职位|状态|所在｜史实走向，仅供你参考）】
{chars}

【候场人物（尚未登场）】
{pool}

【天下大势】
{self.world_brief()}

【近四季回顾】
{self.recent(4)}

【本季登场人物】{'、'.join(agents)}

【本季众人行动】
{chr(10).join(blocks)}
{('【天命干预：本季必须发生并据此推演】' + director) if director else ''}

【登场名单与人物进退】
- 历史已因亮魂附身而改变，史实走向只是参考：寿数将尽者可能如期病故，也可能因剧情而早逝或延年；因人事而死者（如被杀）要看本推演中的局势是否还会走到那一步。
- 候场人物到了史载的时候，或剧情需要时，用 debuts 安排登场（同样可让“退场”者重新登场）。剧情暂时不需要、但仍在世的人，在 character_changes 里把状态设为“退场”；死亡用相应状态。
【悬而未决的线索】（按搁置时间排序，最久的在前）
{threads}
- 伏笔要按时回收，读者才不会迷惑：普通线索从开出到了结不得超过 8 季；“还剩 2 季”以内的要推向结局，“已超期”的本季必须了结，并写明结局。每季至少了结一条，同时开出的新线索不得多于了结的数量加一。
- 只有全书级的重大反转或主钩子（如亮魂身份最终如何揭晓）可以登记为 major，长期保留，目前已有 {n_major} 条，全书最多 3 条；它们也要在全书高潮时回收，不能不了了之。已有线索可在 update 里加 "major": true 升格。
- 已搁置 4 季以上没有进展的，本季必须有下文。用 threads.update 记进展，threads.close 了结并写明结局。
- 本季新出现、但三个月内办不完的事（请命未批、叛乱未平、密谋未发、承诺未兑现等），用 threads.open 登记，免得日后被遗忘。
- 久未亲自思考的人物（4 季以上）：{idle}。他们的处境同样在变化，可在背景中交代，必要时点名登场。

- 用 next_cast 点名下一季需要独立思考的人：身处事件中心、刚收到密信、局势骤变、或即将做出关键抉择者，一般 4-9 人；刘禅每季必定登场，无需列出。其余人物下一季照常行事、由你在背景中裁定。目前持有未拆密信者：{mail}
- 密信积压两季以上未拆的：{overdue}。本季要么点名让收信人登场，要么在背景中交代他如何处置这些信。

输出一个JSON对象（只写JSON）：
{{"summary":"本季大事记，史书笔法，150-250字","events":[{{"title":"四字以内地名或事名","text":"一两句话","actors":["人物名"]}}],"city_changes":[{{"city":"城名(仅限已有城池：{'、'.join(self.world['cities'])})","owner":"蜀|魏|吴","troops":整数万}}],"faction_changes":[{{"faction":"蜀|魏|吴","food":增减整数,"morale":增减整数}}],"relation_changes":[{{"a":"人物","b":"人物","delta":-40到40的整数,"reason":"简述"}}],"character_changes":[{{"name":"人物","status":"{'|'.join(STATUSES)}","role":"新职位或留空","loc":"所在城池或留空","faction":"若改投他国则填，否则留空"}}],"knowledge":[{{"name":"人物","learns":"此人私下得知的信息，40字内"}}],"intercepted_letters":[{{"from":"写信人","to":"收信人","by":"截获者"}}],"debuts":[{{"name":"候场或退场人物","role":"职位","loc":"所在城池","why":"登场缘由，30字内"}}],"next_cast":[{{"name":"人物","why":"下季为何要他亲自思考，20字内"}}],"threads":{{"open":[{{"title":"十字内","detail":"来龙去脉，80字内","actors":["人物"],"major":false}}],"update":[{{"id":编号,"detail":"新进展，60字内","major":false}}],"close":[{{"id":编号,"outcome":"结局，60字内"}}]}}}}
events 3-6条；只列出有变化的城池、关系和人物；被截获的密信不会送达收信人，而会被截获者得知。
"""

    # ---------- 落地 ----------
    def apply(self, agents, acts, J):
        names = set(self.cfg["order"])
        factions = self.cfg["factions"]
        changed = []
        before = self.snapshot()
        was_on = set(self.alive())
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
                    self.chars[l["to"]]["inbox"].append({"from": a["name"], "content": l["content"], "turn": self.world["turn"] + 1})
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
        debuts = []
        for d in J.get("debuts") or []:
            c = self.chars.get(d.get("name")) if isinstance(d, dict) else None
            if not c or c["status"] not in OFFSTAGE:
                continue
            c["status"] = "在任"
            if d.get("role"): c["role"] = str(d["role"])
            if d.get("loc") in self.world["cities"]: c["loc"] = d["loc"]
            debuts.append({"name": c["name"], "why": str(d.get("why") or "")})
        exits = [{"name": n, "status": self.chars[n]["status"]} for n in self.cfg["order"] if n in was_on and n not in self.alive()]
        on = self.alive()
        cast, why = [], {}
        for x in J.get("next_cast") or []:
            n = x.get("name") if isinstance(x, dict) else x
            if n in on and n not in cast:
                cast.append(n)
                why[n] = str(x.get("why") or "") if isinstance(x, dict) else ""
        self.world["cast"], self.world["cast_why"] = cast[:12], why
        T = J.get("threads") if isinstance(J.get("threads"), dict) else {}
        tlog = {"opened": [], "updated": [], "closed": []}
        live = {x["id"]: x for x in self.world.setdefault("threads", [])}
        turn = self.world["turn"] + 1
        for u in T.get("update") or []:
            x = live.get(u.get("id")) if isinstance(u, dict) else None
            if x and u.get("major") is True and sum(1 for y in live.values() if y.get("major")) < 3:
                x["major"] = True
            if x and u.get("detail"):
                x["detail"], x["last"] = str(u["detail"])[:120], turn
                tlog["updated"].append({"id": x["id"], "title": x["title"], "detail": x["detail"]})
        for c in T.get("close") or []:
            x = live.pop(c.get("id"), None) if isinstance(c, dict) else None
            if x:
                tlog["closed"].append({"id": x["id"], "title": x["title"], "outcome": str(c.get("outcome") or "")})
        self.world["threads"] = list(live.values())
        for o in T.get("open") or []:
            if isinstance(o, dict) and o.get("title"):
                nid = self.add_thread(str(o["title"]), str(o.get("detail") or ""), o.get("actors") or [])
                self.world["threads"][-1]["since"] = self.world["threads"][-1]["last"] = turn
                if o.get("major") is True and sum(1 for x in self.world["threads"] if x.get("major")) < 3:
                    self.world["threads"][-1]["major"] = True
                tlog["opened"].append({"id": nid, "title": str(o["title"])[:20]})
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
            "before": before, "after": self.snapshot(),
            "threads": tlog, "debuts": debuts, "exits": exits, "next_cast": [{"name": n, "why": why.get(n, "")} for n in cast[:12]],
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
        if t.get("debuts"):
            L += ["", "登场：" + "；".join(f"{d['name']}（{d['why']}）" if d.get("why") else d["name"] for d in t["debuts"])]
        if t.get("exits"):
            L += ["", "退场：" + "；".join(f"{d['name']}（{d['status']}）" for d in t["exits"])]
        th = t.get("threads") or {}
        if th.get("closed"):
            L += ["", "了结：" + "；".join(f"{x['title']}——{x['outcome']}" for x in th["closed"])]
        if th.get("opened"):
            L += ["", "新线索：" + "、".join(x["title"] for x in th["opened"])]
        if t.get("next_cast"):
            L += ["", "下季登场：" + "、".join(d["name"] for d in t["next_cast"])]
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

    def snapshot(self):
        return {"cities": {k: {"owner": v["owner"], "troops": v["troops"]} for k, v in self.world["cities"].items()},
                "factions": json.loads(json.dumps(self.world["factions"]))}

    def branches(self, current):
        """各本地分支的编年摘要与局势，供查看器对比平行历史。"""
        import subprocess
        git = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
        names = [b for b in git("for-each-ref", "--format=%(refname:short)", "refs/heads").stdout.split() if b]
        if current and current not in names:
            names.insert(0, current)
        res = []
        for b in names:
            if b == current:
                log, world, chars = self.log, self.world, self.chars
            else:
                try:
                    log = json.loads(git("show", f"{b}:chronicle/log.json").stdout)
                    world = json.loads(git("show", f"{b}:sim/world.json").stdout)
                except ValueError:
                    continue
                chars = {}
                for n in self.cfg["order"]:
                    try:
                        chars[n] = json.loads(git("show", f"{b}:sim/characters/{n}.json").stdout)
                    except ValueError:
                        pass
            res.append({
                "name": b, "current": b == current,
                "turns": [{"turn": t["turn"], "date": t["date"], "summary": t.get("summary", ""), "director": t.get("director", ""),
                           "events": [e.get("title", "") for e in t.get("events", [])]} for t in log],
                "cities": {k: v["owner"] for k, v in world["cities"].items()},
                "troops": {k: v["troops"] for k, v in world["cities"].items()},
                "dead": [n for n, c in chars.items() if re.search("阵亡|病故|被杀|赐死|遇害|身故", c.get("status", ""))],
            })
        return res

    def build_viewer(self):
        try:
            import subprocess
            branch = subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        except Exception:
            branch = ""
        try:
            branches = self.branches(branch)
        except Exception:
            branches = []
        data = {"cfg": self.cfg, "world": self.world, "chars": self.chars, "log": self.log, "date": self.date(),
                "branch": branch, "branches": branches}
        with open(p("viewer", "data.js"), "w", encoding="utf-8") as f:
            f.write("window.SIM = " + json.dumps(data, ensure_ascii=False) + ";\n")


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
    x = sp.add_parser("pick"); x.add_argument("--n", type=int, default=None)
    x = sp.add_parser("brief"); x.add_argument("name"); x.add_argument("--out")
    x = sp.add_parser("judge-brief"); x.add_argument("--out")
    sp.add_parser("apply")
    x = sp.add_parser("direct"); x.add_argument("text")
    x = sp.add_parser("thread"); x.add_argument("title"); x.add_argument("detail"); x.add_argument("--actors", default=""); x.add_argument("--since", type=int); x.add_argument("--last", type=int)
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
        if S.world.get("cast"): print("天道点名下季登场：" + "、".join(S.world["cast"]))
    elif a.cmd == "pick":
        os.makedirs(WORK, exist_ok=True)
        for f in glob.glob(os.path.join(WORK, "*")):
            os.remove(f)
        ag = S.pick(a.n)
        open(os.path.join(WORK, "agents.txt"), "w", encoding="utf-8").write("\n".join(ag) + "\n")
        major = set(S.cfg.get("major") or [])
        print("\n".join(f"{x}\t{'主要' if x in major else '次要'}" for x in ag))
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
            r, e = load_act(n, path, S.known())
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
    elif a.cmd == "thread":
        nid = S.add_thread(a.title, a.detail, [x for x in a.actors.split(",") if x])
        th = S.world["threads"][-1]
        if a.since is not None: th["since"] = a.since
        th["last"] = a.last if a.last is not None else th["since"]
        wj(p("sim", "world.json"), S.world); S.build_viewer()
        print(f"已登记线索 #{nid}：{a.title}")
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
