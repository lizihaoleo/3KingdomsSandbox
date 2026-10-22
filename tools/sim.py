#!/usr/bin/env python3
"""多智能体推演引擎：只负责状态读写、简报生成与裁定落地；思考全部交给 Claude Code 的子代理。
时代、阵营、计时单位、地图用语都来自 sim/config.json，换时代只需换配置。

子命令：
  status                     当前日期与天下大势
  pick [--n 上限]            取天道上季点名的登场人物（无则按旧法选 7 人），写入 .work/agents.txt；输出标注主要/次要人物
  brief 人物 [--out 文件]    生成该人物的私人简报（只含此人能知道的信息）
  judge-brief [--out 文件]   汇总 .work/act-*.json，生成天道裁判简报
  apply                      校验并落地 .work/judge.json，写编年史、更新查看器，清空 .work
  direct "干预" [--public 众人可知的开局] [--cast 甲,乙]  设置下一季的天命干预（空字符串清除）
  pace 月|旬|周               按月计时的线：设置下一回起每回跨多久（天道也可在裁定里用 next_pace 调）
  thread "标题" "详情" [--actors 甲,乙]  登记一条悬而未决的线索，交天道日后推进或了结
  export [--out 文件]        导出完整推演记录（Markdown）
  build-viewer               重新生成 viewer/data.js
"""
import argparse, calendar, glob, json, os, random, re, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, ".work")
SEASONS = "春夏秋冬"
PACES = {"月": 31, "旬": 10, "周": 7}  # 按月计时时每回的步长（天）
MAX_SLOW = 2  # 按旬或按周最多连续几回
COOLDOWN = 2  # 放慢到上限后至少按月几回
MONTHS = ["", "一月", "二月", "三月", "四月", "五月", "六月", "七月", "八月", "九月", "十月", "十一月", "十二月"]
DEAD = re.compile("阵亡|病故|被杀|赐死|遇害|自尽|牺牲|处决|遇刺")
OFFSTAGE = ("未出场", "退场")  # 未出场：候场人物，到时由天道安排登场；退场：仍在世但剧情暂不需要
STATUSES = ["在任", "出征", "下狱", "隐退", "退场", "叛逃", "阵亡", "病故", "被杀", "自尽"]
ACTION_TYPES = ["内政", "军事", "外交", "谋略", "人事", "密信", "观望"]
# 配置里没写的用语沿用三国线的说法
LABELS = {"genre": "三国历史推演", "unit": "季", "span": "三个月", "city": "城池", "troops": "驻军", "troop_unit": "万",
          "food": "粮", "morale": "民心", "world": "天下大势", "power": "国力"}


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
        self.L = {**LABELS, **(self.cfg.get("labels") or {})}
        self.monthly = "month" in self.world
        self.statuses = self.cfg.get("statuses") or STATUSES
        self.action_types = self.cfg.get("action_types") or ACTION_TYPES

    # ---------- 工具 ----------
    def span(self):
        """按月计时时本回覆盖的日子：(起日, 止日)。步长由 world.pace 决定：月、旬、周；月底剩不足四天并入本回。"""
        y, m, d = self.world["year"], self.world["month"], self.world.get("day", 1)
        last = calendar.monthrange(y, m)[1]
        pace = self.world.get("pace", "月")
        end = last if pace == "月" else d + PACES[pace] - 1
        return d, (last if end >= last - 3 else end)

    def span_text(self):
        """本回时长的说法，如“一周”“一个月”。"""
        if not self.monthly:
            return self.L["span"]
        a, b = self.span()
        if self.world.get("pace", "月") == "月":
            return "一个月" if a == 1 else "这个月余下的日子"
        return {7: "一周", 10: "十天"}.get(b - a + 1, f"{b - a + 1}天")

    def date(self, y=None, s=None):
        y = self.world["year"] if y is None else y
        era = self.world.get("era") or self.cfg["era"]
        if self.monthly:
            m = self.world["month"]
            a, b = self.span()
            last = calendar.monthrange(y, m)[1]
            pace = self.world.get("pace", "月")
            if a == 1 and b == last:
                tick = MONTHS[m]
            elif pace == "周" and a in (1, 8, 15, 22):
                tick = f"{MONTHS[m]}第{cn(a // 7 + 1)}周"
            elif pace == "旬" and a in (1, 11, 21):
                tick = MONTHS[m] + "上中下"[a // 10] + "旬"
            else:
                tick = f"{MONTHS[m]}{cn(a)}日至{cn(b)}日"
            return {"main": f"{era['name']}{'元' if y - era['base'] == 1 else cn(y - era['base'])}年 · {tick}", "sub": f"公元 {y} 年",
                    "range": f"{y}年{m}月{a}日至{m}月{b}日", "key": f"{y}-{m:02d}-{a:02d}"}
        else:
            s = self.world["season"] if s is None else s
            tick = SEASONS[s]
        return {"main": f"{era['name']}{'元' if y - era['base'] == 1 else cn(y - era['base'])}年 · {tick}", "sub": f"公元 {y} 年"}

    def dead_line(self):
        """已故人物名单：人物的记忆里常把死人当活人，简报里要明说。"""
        dead = [f"{n}（{self.chars[n]['status']}）" for n in self.cfg["order"] if DEAD.search(self.chars[n]["status"])]
        return "【已故人物】" + ("、".join(dead) if dead else "无")

    def always(self):
        """每回合必定登场的主角。"""
        return self.cfg.get("always") or [self.cfg["leads"]["male"]]

    def level(self, kind, v):
        """把数值换成人物会用的说法；配置里的 plain 是 [[上限, 说法], ...]，最后一项为兜底。"""
        for lim, word in self.cfg["plain"][kind]:
            if lim is None or v < lim:
                return word

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
        L = self.L
        if "plain" in self.cfg:
            if plain:
                cities = "、".join(f"{k}（{c['owner']}，{self.level('troops', c['troops'])}）" for k, c in self.world["cities"].items())
                fac = "；".join(f"{f}：{self.level('food', v['food'])}，{self.level('morale', v['morale'])}" for f, v in self.world["factions"].items())
            else:
                cities = "、".join(f"{k}({c['owner']}{c['troops']}{L['troop_unit']})" for k, c in self.world["cities"].items())
                fac = "；".join(f"{f}：{L['food']}{v['food']} {L['morale']}{v['morale']}" for f, v in self.world["factions"].items())
            return f"{L['city']}（{L['troops']}）：{cities}\n{L['power']}：{fac}"
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
            lead = [x for x in self.always() if x in alive]
            ag = lead + [x for x in cast if x not in lead]
            ag = (ag[:n] if n else ag) + [x for x in self.world.get("director_cast") or [] if x in alive and x not in ag]
            return ag
        n = n or 7
        must = [x for x in self.cfg["must"] if x in alive]
        mail = [x for x in alive if self.chars[x]["inbox"] and x not in must]
        rest = [x for x in alive if x not in must and x not in mail]
        random.Random(self.world["turn"] * 7919 + len(self.log)).shuffle(rest)
        ag = (must + mail + rest)[: max(n, len(must))]
        return ag + [x for x in self.world.get("director_cast") or [] if x in alive and x not in ag]

    # ---------- 简报 ----------
    def brief(self, n):
        c, d = self.chars[n], self.date()
        rels = "，".join(f"{[x for x in k.split('|') if x != n][0]}:{v}" for k, v in self.world["rel"].items() if n in k.split("|"))
        last = self.log[-1].get("acts", [])
        speeches = "\n".join(f"{a['name']}公开说：{a['public_speech']}" for a in last if a.get("public_speech"))
        L = self.L
        soul = n in self.cfg.get("insiders", [self.cfg["leads"]["male"]])
        premise = self.cfg["premise"] if soul else self.cfg.get("public_premise", self.cfg["premise"])
        secret = (self.cfg["leads"].get("secret", "") if soul else "") + (f"【只有你自己知道的底牌】{c['secret']}" if c.get("secret") else "")
        inbox = "\n".join(f"{m['from']}来信：{m['content']}" for m in c["inbox"]) or "无"
        types = "|".join(self.action_types)
        return f"""你将扮演{L['genre']}中的人物「{n}」，参与一场多智能体推演。其他人物由其他独立的AI扮演，他们看不到你的内心。请完全代入此人的身份、性格、立场与认知局限，深思熟虑后行动。

【推演前提】{premise}
{secret}

【当前】{d['main']}（{d.get('range') or d['sub']}），第{self.world['turn'] + 1}{L['unit']}，本{L['unit']}约{self.span_text()}。
【你的身份】{n}，{self.age(n)}岁，{c['faction']}，{c['role']}，状态：{c['status']}，所在：{c['loc']}。{c['bio']}
【性格与处境】{c['persona']}

【{L['world']}】
{self.world_brief(plain=True)}

【近期公开发生的事】
{self.recent(3, public=not soul)}
{(f"【本{L['unit']}开局】" + self.world['director_public']) if self.world.get('director_public') else ''}
{(f"【上{L['unit']}众人公开言论】" + chr(10) + speeches) if speeches else ''}

{self.dead_line()}
【你私下记得的事】{'；'.join(c['memory'][-8:]) or '无'}
【你收到的密信】
{inbox}
【你对他人的好恶（-100敌视…100亲信）】{rels or '无'}

规则：只依据你这个身份能知道的信息行事；想事情、说话都用这个人物在那个年代会用的说法，不要出现“{L['food']}40”“{L['morale']}60”这类数值；可以说谎、试探、结盟、背叛、拖延，一切以此人真实会有的考量为准。行动要具体可执行，本{L['unit']}只做一件主要的事。人物名必须用以下名单中的：{'、'.join(self.known())}。
{self.cfg.get('brief_rule', '')}

输出一个JSON对象（只写JSON，不要其他文字）：
{{"thought":"第一人称内心盘算，150-300字：你如何解读局势、揣测谁在想什么、权衡几种选择、为何选这一步","action":{{"type":"{types} 之一","target":"目标人物/{L['city']}/势力","detail":"具体做法，60字内"}},"public_speech":"{self.cfg.get('speech_hint', '在朝堂或军中公开说的话')}，可为空字符串","secret_letters":[{{"to":"人物名","content":"密信内容，80字内"}}],"memory":"本{L['unit']}想记住的要点，30字内"}}
"""

    def judge_brief(self, agents, acts):
        L, U = self.L, self.L["unit"]
        chars = "\n".join(
            f"{n}|{c['faction']}|{self.age(n)}岁|{c['role']}|{c['status']}|在{c['loc']}｜{c.get('hist') or ''}"
            + (f"｜底牌（原话是对本人说的）：{c['secret']}" if c.get("secret") else "")
            for n in self.known() for c in [self.chars[n]])
        pool = "\n".join(
            f"{n}|{c['faction']}|{self.age(n)}岁|{c['bio']}｜史载约{c['debut']}年登上舞台｜{c.get('hist') or ''}"
            + (f"｜底牌：{c['secret']}" if c.get("secret") else "")
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
            return f"已超期，本{U}必须了结" if left <= 0 else f"还剩{left}{U}须了结"
        threads = "\n".join(
            f"#{x['id']} {x['title']}（第{x['since']}{U}起，{due(x)}，已{now - 1 - x['last']}{U}无进展）：{x['detail']}" + (f"［相关：{'、'.join(x['actors'])}］" if x.get("actors") else "")
            for x in sorted(self.world.get("threads") or [], key=lambda x: (bool(x.get("major")), x["since"]))) or "无"
        n_major = sum(1 for x in self.world.get("threads") or [] if x.get("major"))
        la = self.last_acted()
        idle = "、".join(f"{n}（{'从未' if n not in la else f'{now - 1 - la[n]}{U}'}）" for n in self.alive()
                         if now - 1 - la.get(n, 0) >= 4) or "无"
        blocks = []
        for a in acts:
            act = a.get("action") or {}
            letters = "；".join(f"致{l['to']}：{l['content']}" for l in a.get("secret_letters", [])) or "无"
            blocks.append(f"◆{a['name']}\n内心：{a.get('thought', '')}\n行动：{act.get('type', '观望')}→{act.get('target', '')}：{act.get('detail', '')}\n公开言论：{a.get('public_speech') or '无'}\n密信：{letters}")
        d = self.date()
        director = self.world.get("director", "").strip()
        END = self.cfg.get("end_turn", 40)
        R = self.cfg["rules"]
        fill = lambda s: s.replace("{END}", str(END)).replace("{now}", str(now)).replace("{half}", str(END // 2))
        leads = "、".join(self.always())
        highlight = fill(R.get("highlight") or f"8. 爽点每{U}都要有：至少一个让读者拍案的高光时刻，优先给男主{self.cfg['leads']['male']}。高光要靠众人行动里的谋划挣来，写清因果；同一{U}对手也可以有自己的胜利，主角照样会挨打。")
        pace = fill(R.get("pace") or "")
        owners = "|".join(self.cfg["factions"])
        pace_note = "" if not self.monthly else f"""
本{U}按{self.world.get('pace', '月')}推进。时间的快慢由你掌握：平时一{U}一个月；遇到关键时刻（审讯、刺杀前夜、出逃、接头、身份将要暴露），在 JSON 里加 "next_pace":"周"（或"旬"），把下一{U}放慢，让人物之间的试探一来一回写细；事情了结后加 "next_pace":"月" 恢复。不写则保持现在的步长。放慢最多连续 {MAX_SLOW} {U}，眼下已连续放慢 {self.world.get('slow', 0)} {U}，到了上限引擎会自动恢复按月，之后至少按月 {COOLDOWN} {U}才能再放慢{f"（还需按月 {self.world.get('cool', 0)} {U}）" if self.world.get('cool', 0) else ""}。全书要在1941年12月收官，现在离终点还远，平时请按月推进。史实时间表上的日子落在哪一{U}，就在哪一{U}发生。"""
        return f"""你是一场{L['genre']}的“天道”裁判。前提：{self.cfg['premise']}
现在是{d['main']}（{d.get('range') or d['sub']}）。请裁定这一{U}（{self.span_text()}）众人行动的结果。{pace_note}

要求：依据{R.get('basis', '历史常识、兵力粮草、地理、人物能力与性格')}判断成败，有因果、有代价，不偏袒任何一方；行动之间会相互影响（密信可能被截获、谋略可能被识破）。这份记录要写成小说，所以“公正”不等于“温吞”：
1. 每{U}至少裁出一场分出胜负的正面冲突，有明确的赢家和代价，不要各自退缩、不了了之。
2. 每三四{U}至少一次大转折：{R.get('twist', '城池易手、重要人物死亡、叛变或下狱、秘密险些曝光')}。距上次大转折已三{U}以上的，本{U}就要安排。
3. 谋划周密又抓住时机的一方，给足回报（大胜而不是小胜）；冒进、失算的一方要付出沉重代价。主角也会挨重拳。
{R['secret']}
5. 各方都按兵不动时，用意外死亡、内奸、外部大事等变数打破僵局，但要合理。
{R['leads']}
7. 伏笔要回收：优先让已铺垫的线索结出果子，不要只开新坑。
{highlight}
{pace}
summary 与 events 用史书或小说的笔法，不要出现“{L['food']}40”“{L['morale']}60”这类数值。

【人物（姓名|阵营|年龄|身份|状态|所在｜{R.get('hist_label', '史实走向，仅供你参考')}｜底牌，只有本人和你知道）】
{chars}

{self.dead_line()}（他们已经死了，不得再以活人身份出现在任何事件里，只能作为往事被提起。）

【候场人物（尚未登场）】
{pool}

【{L['world']}】
{self.world_brief()}

【近四{U}回顾】
{self.recent(4)}

【本{U}登场人物】{'、'.join(agents)}

【本{U}众人行动】
{chr(10).join(blocks)}
{(f'【天命干预：本{U}必须发生并据此推演】' + director) if director else ''}

【登场名单与人物进退】
{R.get('history') or f"- 历史已因{R['change']}而改变，史实走向只是参考：因人事而死者（如被杀）要看本推演中的局势是否还会走到那一步。"}
- 候场人物到了史载的时候，或剧情需要时，用 debuts 安排登场（同样可让“退场”者重新登场）。剧情暂时不需要、但仍在世的人，在 character_changes 里把状态设为“退场”；死亡用相应状态。
【悬而未决的线索】（按搁置时间排序，最久的在前）
{threads}
- 伏笔要按时回收，读者才不会迷惑：普通线索从开出到了结不得超过 8 {U}；“还剩 2 {U}”以内的要推向结局，“已超期”的本{U}必须了结，并写明结局。每{U}至少了结一条，同时开出的新线索不得多于了结的数量加一。
- 只有全书级的重大反转或主钩子（如{R['hook']}）可以登记为 major，长期保留，目前已有 {n_major} 条，全书最多 3 条；它们也要在全书高潮时回收，不能不了了之。已有线索可在 update 里加 "major": true 升格。
- 已搁置 4 {U}以上没有进展的，本{U}必须有下文。用 threads.update 记进展，threads.close 了结并写明结局。
- 本{U}新出现、但{self.span_text()}内办不完的事（请示未批、审查未结、密谋未发、承诺未兑现等），用 threads.open 登记，免得日后被遗忘。
- 久未亲自思考的人物（4 {U}以上）：{idle}。他们的处境同样在变化，可在背景中交代，必要时点名登场。

- 用 next_cast 点名下一{U}需要独立思考的人：身处事件中心、刚收到密信、局势骤变、或即将做出关键抉择者，一般 4-9 人；{leads}每{U}必定登场，无需列出。其余人物下一{U}照常行事、由你在背景中裁定。目前持有未拆密信者：{mail}
- 密信积压两{U}以上未拆的：{overdue}。本{U}要么点名让收信人登场，要么在背景中交代他如何处置这些信。

输出一个JSON对象（只写JSON）：
{{"summary":"本{U}大事记，150-250字","events":[{{"title":"四字以内地名或事名","text":"一两句话","actors":["人物名"]}}],"city_changes":[{{"city":"{L['city']}名(仅限已有：{'、'.join(self.world['cities'])})","owner":"{owners}","troops":整数}}],"faction_changes":[{{"faction":"{owners}","food":{L['food']}增减整数,"morale":{L['morale']}增减整数}}],"relation_changes":[{{"a":"人物","b":"人物","delta":-40到40的整数,"reason":"简述"}}],"character_changes":[{{"name":"人物","status":"{'|'.join(self.statuses)}","role":"新身份或留空","loc":"所在{L['city']}或留空","faction":"若改换阵营则填，否则留空"}}],"knowledge":[{{"name":"人物","learns":"此人私下得知的信息，40字内"}}],"intercepted_letters":[{{"from":"写信人","to":"收信人","by":"截获者"}}],"debuts":[{{"name":"候场或退场人物","role":"身份","loc":"所在{L['city']}","why":"登场缘由，30字内"}}],"next_cast":[{{"name":"人物","why":"下{U}为何要他亲自思考，20字内"}}],"threads":{{"open":[{{"title":"十字内","detail":"来龙去脉，80字内","actors":["人物"],"major":false}}],"update":[{{"id":编号,"detail":"新进展，60字内","major":false}}],"close":[{{"id":编号,"outcome":"结局，60字内"}}]}}}}
events 3-6条；只列出有变化的{L['city']}、关系和人物；被截获的密信不会送达收信人，而会被截获者得知。{R.get('json_note', '')}
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
            "summary": str(J.get("summary") or f"本{self.L['unit']}无大事。"),
            "events": [{"title": str(e.get("title", "")), "text": str(e.get("text", ""))} for e in (J.get("events") or [])[:8]],
            "director": self.world.get("director", ""), "changed": changed, "acts": acts,
            "before": before, "after": self.snapshot(),
            "threads": tlog, "debuts": debuts, "exits": exits, "next_cast": [{"name": n, "why": why.get(n, "")} for n in cast[:12]],
        }
        if isinstance(J.get("era"), dict) and J["era"].get("name") and isinstance(J["era"].get("base"), int):
            self.world["era"] = {"name": str(J["era"]["name"]), "base": J["era"]["base"]}
        if J.get("ending"):
            entry["ending"] = str(J["ending"]); self.world["ended"] = entry["ending"]
        self.log.append(entry)
        self.write_turn_md(entry)
        self.world["director"] = ""
        self.world["director_public"] = ""
        self.world["director_cast"] = []
        self.world["turn"] += 1
        if self.monthly:
            _, b = self.span()
            if b >= calendar.monthrange(self.world["year"], self.world["month"])[1]:
                self.world["day"] = 1
                self.world["month"] += 1
                if self.world["month"] > 12:
                    self.world["month"] = 1; self.world["year"] += 1
            else:
                self.world["day"] = b + 1
            # 放慢最多连续 MAX_SLOW 回；恢复按月后至少按月 COOLDOWN 回才能再放慢，免得全书卡在几个星期里
            cool = self.world.get("cool", 0)
            if J.get("next_pace") in PACES and (J["next_pace"] == "月" or cool <= 0):
                self.world["pace"] = J["next_pace"]
            self.world["cool"] = max(0, cool - 1)
            self.world["slow"] = self.world.get("slow", 0) + 1 if self.world.get("pace", "月") != "月" else 0
            if self.world["slow"] > MAX_SLOW:
                self.world["pace"], self.world["slow"], self.world["cool"] = "月", 0, COOLDOWN
        else:
            self.world["season"] += 1
            if self.world["season"] > 3:
                self.world["season"] = 0; self.world["year"] += 1
        self.save()
        return entry

    def turn_md(self, t):
        U = self.L["unit"]
        prefix = "序幕 · " if t["turn"] == 0 else f"第{t['turn']}{U} · "
        L = [f"## {prefix}{t['date']['main']}（{t['date']['sub']}）", ""]
        if t.get("director"):
            L += [f"> 天命干预：{t['director']}", ""]
        L += [t["summary"], ""]
        if t.get("ending"):
            L += [f"**终局：** {t['ending']}", ""]
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
            L += ["", f"下{U}登场：" + "、".join(d["name"] for d in t["next_cast"])]
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
        y = t['date']['sub'].replace('公元 ', '').replace(' 年', '')
        tick = t['date']['main'].split(" · ")[-1]
        tick = f"-{MONTHS.index(tick):02d}" if tick in MONTHS else tick
        fn = p("chronicle", f"{t['turn']:04d}-{t['date']['key'] if t['date'].get('key') else y + tick}.md")
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
                    if json.loads(git("show", f"{b}:sim/config.json").stdout).get("era") != self.cfg.get("era"):
                        continue  # 别的时代，不放在一起比
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


def load_act(name, path, order, types=ACTION_TYPES):
    try:
        r = rj(path)
    except Exception as e:
        return None, f"{path} 不是合法 JSON：{e}"
    if not isinstance(r, dict):
        return None, f"{path} 顶层必须是对象"
    act = r.get("action") if isinstance(r.get("action"), dict) else {}
    if act.get("type") not in types:
        act["type"] = "观望" if not act.get("type") else str(act["type"])[:4]
    letters = []
    for l in r.get("secret_letters") or []:
        if isinstance(l, dict) and l.get("to") in order and l.get("to") != name and l.get("content"):
            letters.append({"to": l["to"], "content": str(l["content"])})
    return {"name": name, "thought": str(r.get("thought") or ""),
            "action": {"type": act["type"], "target": str(act.get("target") or ""), "detail": str(act.get("detail") or "")},
            "public_speech": str(r.get("public_speech") or ""), "secret_letters": letters[:3],
            "memory": str(r.get("memory") or "")}, None


def load_judge(path):
    """读裁定 JSON；裁判常把对象提前多闭合一个括号、后面还跟着字段，此时去掉那个括号再读。"""
    s = open(path, encoding="utf-8").read()
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        rest = s[e.pos:].lstrip()
        if not e.msg.startswith("Extra data") or not rest.startswith(","):
            raise
        head = s[:e.pos].rstrip()
        if not head.endswith("}"):
            raise
        return json.loads(head[:-1] + s[e.pos:])


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
    x = sp.add_parser("direct"); x.add_argument("text"); x.add_argument("--public", default="", help="开局时众人都知道的部分，写进人物简报"); x.add_argument("--cast", default="", help="本季额外登场的人物，逗号分隔")
    x = sp.add_parser("pace"); x.add_argument("step", choices=list(PACES), help="下一回起每回跨多久：月、旬、周")
    x = sp.add_parser("thread"); x.add_argument("title"); x.add_argument("detail"); x.add_argument("--actors", default=""); x.add_argument("--since", type=int); x.add_argument("--last", type=int)
    x = sp.add_parser("export"); x.add_argument("--out")
    sp.add_parser("build-viewer")
    a = ap.parse_args()
    S = Sim()

    if a.cmd == "status":
        d = S.date()
        U = S.L["unit"]
        print(f"第 {S.world['turn']} {U}已完成；下一{U}：{d['main']}（{d.get('range') or d['sub']}）" + (f"，每{U}一{'个月' if S.world.get('pace', '月') == '月' else S.world['pace']}" if S.monthly else ""))
        print(S.world_brief())
        if S.world.get("director"): print("待生效天命干预：" + S.world["director"])
        dead = [n for n in S.cfg["order"] if DEAD.search(S.chars[n]["status"])]
        if dead: print("已故：" + "、".join(dead))
        if S.world.get("cast"): print(f"天道点名下{U}登场：" + "、".join(S.world["cast"]))
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
            r, e = load_act(n, path, S.known(), S.action_types)
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
            J = load_judge(os.path.join(WORK, "judge.json"))
        except Exception as e:
            sys.exit(f".work/judge.json 不是合法 JSON：{e}\n请让 judge 子代理重新写入。")
        t = S.apply(agents, acts, J)
        shutil.rmtree(WORK, ignore_errors=True)
        first = re.split("[。；]", t["summary"])[0][:60]
        print(f"COMMIT_MSG: 第{t['turn']}{S.L['unit']} {t['date']['main']}：{first}")
        print(t["summary"])
        if t["changed"]: print("变动城池：" + "、".join(t["changed"]))
    elif a.cmd == "thread":
        nid = S.add_thread(a.title, a.detail, [x for x in a.actors.split(",") if x])
        th = S.world["threads"][-1]
        if a.since is not None: th["since"] = a.since
        th["last"] = a.last if a.last is not None else th["since"]
        wj(p("sim", "world.json"), S.world); S.build_viewer()
        print(f"已登记线索 #{nid}：{a.title}")
    elif a.cmd == "pace":
        if not S.monthly: sys.exit("这条线按季计时，不能调步长")
        S.world["pace"] = a.step
        wj(p("sim", "world.json"), S.world); S.build_viewer()
        d = S.date()
        print(f"下一回起每回一{'个月' if a.step == '月' else a.step}；下一回：{d['main']}（{d['range']}）")
    elif a.cmd == "direct":
        S.world["director"] = a.text.strip()
        S.world["director_public"] = a.public.strip()
        S.world["director_cast"] = [x for x in re.split(r"[,，、\s]+", a.cast) if x]
        wj(p("sim", "world.json"), S.world); S.build_viewer()
        print("已设置天命干预：" + (S.world["director"] or "（已清除）"))
    elif a.cmd == "export":
        out(S.export(), a.out)
    elif a.cmd == "build-viewer":
        S.build_viewer(); print("viewer/data.js 已更新")


if __name__ == "__main__":
    main()
