# 匿名端到端示例

以下全是自制示例，不来自真题、题库或课程。

## 1. 导入后的题目

文件 `01_待导入资料/示例错题.md` 被解析为：

```json
{
  "id": "Q-demo-1",
  "subject": "民法",
  "knowledge_points": ["合同"],
  "is_imported_mistake": true,
  "review_status": "待审核"
}
```

## 2. 今日任务

```json
{
  "type": "review_question",
  "question_id": "Q-demo-1",
  "reason": "导入历史错题，到期首次复测",
  "estimated_minutes": 3
}
```

## 3. 对话训练

```text
AI：第 1 题 / 今日 1 题。请回复选项 + 信心。
用户：B C
AI：请选择错因：A 不会规则 B 规则混淆 C 漏条件 D 审题/陷阱。
用户：C
AI：先说出本题规则的成立条件，再重做原题；明天安排一题改变条件的草稿变体。
```

## 4. 作答记录

```json
{
  "question_id": "Q-demo-1",
  "result": "wrong",
  "confidence": "low",
  "reason": "漏条件",
  "source_type": "original",
  "training_stage": "original_review",
  "independent": true
}
```

错误、低信心猜对和历史错题进入强化与间隔复测；首次高信心独立答对的普通题只记录，不占用后续训练时间。
