# 季汉推演

建兴十二年，诸葛亮病逝五丈原，魂魄附在了刘禅身上。十八位历史人物各由一个独立的 Claude 子代理扮演，只知道自己该知道的事，互相试探、结盟、写密信；“天道”裁判汇总众人行动，裁定一季（三个月）之后天下如何。每一季是一个 git 提交，每条分支是一条平行历史。

在 Claude Code 里运行，用的是你的 Claude 订阅额度，不需要 API key。

## 开始

```bash
cd jihan-sim
claude
```

然后在 Claude Code 里输入：

```
/turn            # 推一季
/turn 4          # 连推四季（一年）
/turn 2 18       # 推两季，每季十八人全员登场
```

推完后用浏览器打开 `viewer/index.html`：沙盘页有按《中国历史地图集》三国图描摹的古地图（疆域随城池易手着色，可拖动缩放）、群臣、人物档案（心思/密信/记忆/人际）和编年史；“众人心思”页逐季揭开每人的决断与密信；“平行历史”页逐季对比各分支。顶部按钮会复制对应的 `/turn`、`/direct`、`/outline` 命令。手机上也能看。

## 平行历史

```
/fork 魏延不死线 从第0季 魏延在褒斜道截住了杨仪
/turn 4
git switch main
/fork 亮魂摊牌线 刘禅在朝会上当众承认自己是诸葛亮
/turn 4
```

- `/direct <内容>`：给下一季加天命干预，不开分支。
- `git log --oneline`：每一行就是一季。
- `git diff 魏延不死线 亮魂摊牌线 -- chronicle/`：对比两条历史。
- 想回到某一季重来：`/fork 新分支名 从第3季`。

## 变成小说大纲

```
/outline
/outline 偏重司马懿视角，按三卷写
```

会把当前分支的全部记录导出到 `outline/推演记录-<分支>.md`，并整理成 `outline/大纲-<分支>.md`：书名候选、核心冲突、人物弧光、分卷与逐章大纲（每章标注对应第几季）、重点场面、后续悬念。

## 自定义

- 改人物性格或加人物：编辑 `sim/characters/*.json`，新人物要同时加进 `sim/config.json` 的 `order`。
- 改初始局势：`sim/world.json`（城池归属、驻军、粮草、民心、人物关系值）。
- 改前提：`sim/config.json` 的 `premise`。
- 省额度：在 `.claude/agents/character.md` 的开头加一行 `model: sonnet`，让人物用较快的模型，裁判保持默认。

## 文件

| 路径 | 内容 |
|---|---|
| `tools/sim.py` | 引擎：选人、生成私人简报、汇总给裁判、落地裁定、导出 |
| `.claude/agents/` | 人物与裁判两种子代理 |
| `.claude/commands/` | `/turn` `/fork` `/direct` `/outline` |
| `sim/` | 当前状态 |
| `chronicle/` | 每季的可读记录与完整日志 |
| `viewer/` | 本地查看器 |
| `outline/` | 导出的记录与大纲 |
