---
description: 推演一季或多季。用法：/turn [季数] [每季登场人数]
argument-hint: [季数，默认1] [登场人数，默认7]
---
参数：$ARGUMENTS（第一个数字是季数，默认 1；第二个是每季登场人数，默认 7，填 18 为全员）。

每一季按顺序执行以下步骤，做完一季再做下一季：

1. 运行 `python3 tools/sim.py pick --n <登场人数>`，得到本季登场人物。
2. 对每个登场人物运行 `python3 tools/sim.py brief <人物> --out .work/brief-<人物>.txt`（可以用一条 bash 循环）。
3. 在**同一条消息里并行**为每个人物启动一个 `character` 子代理，prompt 只写这一句，不加任何别的信息、提示或你自己的倾向：
   「你扮演<人物>。读取 .work/brief-<人物>.txt，按其要求思考，把 JSON 写入 .work/act-<人物>.json。」
4. 全部返回后运行 `python3 tools/sim.py judge-brief --out .work/judge.txt`。如果报告某个文件缺失或不是合法 JSON，只让那个人物的子代理重写一次。
5. 启动一个 `judge` 子代理：「读取 .work/judge.txt，裁定本季结果，把 JSON 写入 .work/judge.json。」
6. 运行 `python3 tools/sim.py apply`。若 judge.json 不合法，让 judge 重写一次再 apply。
7. 用 apply 输出里 `COMMIT_MSG:` 后面的文字提交：`git add -A && git commit -m "<那段文字>"`。

全部完成后，用几句话告诉我这几季发生了什么、谁的处境变化最大、有哪些悬而未决的暗线（比如在途的密信、被截获的信、正在积累的怨恨）。不要自己改动 sim/ 或 chronicle/ 下的文件。
