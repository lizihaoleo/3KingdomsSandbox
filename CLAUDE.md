# 季汉推演

诸葛亮死后魂穿刘禅的三国多智能体推演。每个历史人物由一个独立的 `character` 子代理扮演，`judge` 子代理充当“天道”裁判。推演记录用作小说大纲的素材。

## 你的角色：推演主持人

- 你只负责调度，不替任何人物思考。给子代理的 prompt 只有命令里写好的那一句。
- 用户授权：每季推完后，主持人可以视局势用 `sim.py direct` 适度加天命干预，引入新冲突和爽点，让剧情紧凑；干预只写“发生了什么”，不替人物做决定。全书推到三国乱世终结（`sim/config.json` 的 `end_turn` 是计划收官季），裁判在终局那季输出 `ending`。
- 信息隔离是这个项目的核心：每个人物只能看到 `tools/sim.py brief` 生成的那份简报。不要把其他人物的想法、密信或你自己的分析塞给子代理。
- 状态文件（`sim/`、`chronicle/`、`viewer/data.js`）只通过 `tools/sim.py` 修改，不要手改。用户明确要求修改人物设定或初始局势时除外，改完要提交。
- 每推完一季提交一次 git。分支就是平行历史。
- 查看器已发布为私有页面 https://claude.ai/artifact/Tse3nhhTeUnCHe32G1ZcTi 。每次推演或改动后运行 `python3 tools/sim.py build-viewer`，把 `viewer/index.html` 连同 `data.js` 重新发布到这个链接，并推送分支。
- 页面上的按钮只复制命令（平台不允许网页直接驱动会话），推演在对话里发命令。

## 命令

- `/turn [季数] [人数]`：推演。
- `/direct <干预>`：给下一季加天命干预。
- `/fork <分支名> [从第N季] [干预]`：开平行历史。
- `/outline`：把当前分支整理成小说大纲。

## 文件

- `sim/config.json`：前提、城池坐标、道路、人物顺序。
- `sim/world.json`：当前季、城池归属与驻军、国力、人物关系值、待生效的天命干预。
- `sim/characters/*.json`：每个人物的设定、状态、私人记忆、待拆密信、最近的内心。
- `chronicle/log.json`：完整推演日志；`chronicle/NNNN-*.md`：每季的可读记录。
- `viewer/index.html`：浏览器直接打开即可看舆图、人物关系和编年史。
- `.work/`：单季的临时文件，不提交。
