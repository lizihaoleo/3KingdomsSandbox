---
description: 推演一回或多回（孤岛线一回为一个月）。用法：/turn [回数] [登场人数上限]
argument-hint: [回数，默认1] [登场人数上限，默认不限]
---
参数：$ARGUMENTS（第一个数字是回数，默认 1；第二个是登场人数上限，可省略）。

每回跨多久（月、旬、周）由天道在裁定里调，`python3 tools/sim.py status` 会显示。每回登场谁由天道在上一回裁定时点名（`sim/config.json` 的 `always` 里的主角必定登场）；还没有点名时按旧法选 7 人。

每一回按顺序执行以下步骤，做完一回再做下一回：

1. 运行 `python3 tools/sim.py pick`（给了人数上限就加 `--n <上限>`），得到本回登场人物。
2. 对每个登场人物运行 `python3 tools/sim.py brief <人物> --out .work/brief-<人物>.txt`（可以用一条 bash 循环）。
3. 在**同一条消息里并行**为每个人物启动一个 `character` 子代理，prompt 只写这一句，不加任何别的信息、提示或你自己的倾向：
   「你扮演<人物>。读取 .work/brief-<人物>.txt，按其要求思考，把 JSON 写入 .work/act-<人物>.json。」
   pick 的输出给每人标了“主要”或“次要”（名单在 `sim/config.json` 的 `major`）：主要人物不指定模型，沿用当前会话的模型；次要人物指定 `model: "sonnet"`，跑得更快。judge 始终不指定模型。
4. 全部返回后运行 `python3 tools/sim.py judge-brief --out .work/judge.txt`。如果报告某个文件缺失或不是合法 JSON，只让那个人物的子代理重写一次。
5. 启动一个 `judge` 子代理：「读取 .work/judge.txt，裁定本回结果，把 JSON 写入 .work/judge.json。」
6. 运行 `python3 tools/sim.py apply`。若 judge.json 不合法，让 judge 重写一次再 apply。
7. 用 apply 输出里 `COMMIT_MSG:` 后面的文字提交：`git add -A && git commit -m "<那段文字>"`。

全部完成后，用几句话告诉我这几回发生了什么、谁的处境变化最大、谁登场谁退场、天道点名下回由谁登场、哪些旧线索有了下文或被了结，以及有哪些悬而未决的暗线（比如在途的密信、被截获的信、正在积累的怨恨）。不要自己改动 sim/ 或 chronicle/ 下的文件。
