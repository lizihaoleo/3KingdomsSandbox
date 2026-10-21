---
description: 开一条平行历史分支，可从某一季开始，可附带天命干预。用法：/fork <分支名> [从第N季] [干预内容]
argument-hint: <分支名> [从第N季] [天命干预]
---
参数：$ARGUMENTS

1. 确认工作区干净（`git status`），有未提交的改动先告诉我。
2. 如果指定了“从第N季”：用 `git log --oneline` 找到提交信息以“第N季”开头的那个提交（第0季就是初始提交），然后 `git switch -c <分支名> <提交>`。否则从当前位置 `git switch -c <分支名>`。
3. 如果给了天命干预，运行 `python3 tools/sim.py direct "<干预内容>"`，然后 `git commit -am "开分支：<分支名>｜<干预内容>"`。
4. 运行 `python3 tools/sim.py status`，告诉我现在在哪条分支、下一季是什么时间、下一季会生效什么干预。
