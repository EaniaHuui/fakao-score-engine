---
name: fakao-update
description: 更新 Fakao Score Engine 的代码、Skills、模板和规则；先检查远端版本与用户本地改动，保护个人资料，自动合并无冲突内容，遇到冲突生成报告并等待确认。
---

# fakao-update

## 目标

安全更新项目，不覆盖用户自己的规则、资料和训练数据。更新必须可审计、可回退。

## 范围

允许自动更新：`skills/`、`_meta/` 的模板和标签、`09_导入与处理工具/cli/`、`README.md`、`AGENTS.md`、`DATA_NOTICE.md`、`.gitignore`、`fakao`。

禁止自动改动：`00_` 到 `08_` 内的用户资料、题库、训练记录、任务、模拟成绩，以及凭据和未跟踪个人文件。即使这些目录被用户加入 Git，也只报告，不自动合并。

## 流程

1. 确认项目根目录包含 `fakao`、`skills/`、`09_导入与处理工具/cli/`，并读取 Git remote。不是 Git 仓库或没有远端时停止，不猜地址。
2. 先只读检查：`git status --short`、`git branch --show-current`、`git remote -v`、`git log -1 --oneline`。区分未提交改动、未推送提交和远端新增提交。
3. 合并前记录当前提交、分支和工作区。需要暂存未提交改动时，只能在确认 stash 成功并记录 stash ID 后执行。
4. 使用 `git fetch --prune <remote>`，再比较 `HEAD`、`<remote>/<branch>` 与共同祖先。不要直接 `git pull`。
5. 按以下规则处理：
   - 没有远端新提交：报告无需更新，不制造提交。
   - 无本地改动且仅涉及允许范围：非破坏性合并。
   - 不同文件或同文件不同区块：合并后检查 diff。
   - 同一文件同一区块：停止，生成 `09_导入与处理工具/update/conflict-report.md`，写明文件、双方改动、风险和可选方案，等待用户确认。
   - 远端涉及受保护目录：拒绝该部分并报告。
6. 冲突优先级：用户个人数据和已确认法律内容 > 用户本地规则修改 > 远端工具修复 > 文档措辞。不能静默覆盖用户的法律版本、题目解析或训练记录。
7. 无冲突更新后执行 `./fakao --help`、`python3 -m compileall -q 09_导入与处理工具/cli`、`git diff --check`。检查 Skill 路径均为小写 kebab-case，且没有凭据、题库或运行时数据进入提交。
8. 交付报告：基线、远端版本、更新文件、保留的本地改动、冲突、验证结果。没有明确确认时，不自动提交或推送包含冲突解决的版本。

## 禁止事项

- 不用 `git reset --hard`、`git clean -fd`、`git checkout --`。
- 不删除、移动或覆盖用户资料、题库、错题、训练记录和模拟成绩。
- 不把冲突标记留在可运行的 Skill 或 Python 文件中。
