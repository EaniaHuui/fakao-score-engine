# 项目内 Skills

这些 Skill 是围绕法考提分闭环定义的 AI 能力契约，均位于当前项目目录，可由已安装并已获项目目录访问权限的本地智能体读取。仓库不包含 AI 模型、Agent 运行器或 API 密钥。

| Skill | 作用 |
|---|---|
| `fakao` | 初始化用户档案、摸底和学习合同 |
| `Fakao-Interaction-Protocol` | 统一低输入提问、选项和作答格式 |
| `Fakao-Training-Session` | 逐题出题、追问、反馈、记录和掌握验收 |
| `Fakao-Metrics` | 只用正确率、耗时、猜对比例和模拟成绩评估提分 |
| `Fakao-Importer` | 资料解析、去重、来源与版本标记 |
| `Fakao-Mistake-Diagnostician` | 识别可行动错因 |
| `Fakao-Recall-Coach` | 主动回忆与间隔复测 |
| `Fakao-Variant-Generator` | 生成并审核同构变体题 |
| `Fakao-Planner` | 按预期提分收益安排任务 |
| `Fakao-Exam-Optimizer` | 模考、耗时和考场策略分析 |
| `Fakao-Question-Trend-Analyst` | 解释近十年真题趋势和预测候选 |
| `Fakao-Error-Attack-Coach` | 将错误聚类为专项突击任务 |
| `Fakao-Personalized-Bank` | 根据错误知识点和题型组成个人专项题库 |
| `Fakao-Adaptive-Planner` | 根据新作答记录迭代任务与计划 |

Skill 只允许基于有来源的资料作答；法律结论和 AI 生成题默认需要审核。
