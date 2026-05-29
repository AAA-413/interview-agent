# 质量基准报告 - 2026-05-29

生成时间：2026-05-29 14:47
数据集版本：1.0.0
样本数：5

## 总体结论

综合通过率：**65.9%** (29/44)

当前版本：**不建议发布** ⚠️
通过率 65.9% 未达到演示门槛 (75%)

## 五条质量线

| 质量线 | 通过率 | 失败数 |
|--------|--------|--------|
| 出题质量 | 100.0% | 0 |
| 追问质量 | 44.4% | 14 |
| 评分质量 | 0.0% | 1 |

## 分样本通过率

| 样本 | 通过率 | Pass/Fail |
|------|--------|-----------|
| AI Agent / RAG 开发 | 71.4% | 5/7 |
| Java 后端 / Redis / MySQL | 71.4% | 5/7 |
| 前端 / React / 性能优化 | 56.2% | 9/16 |
| Python 后端 / FastAPI | 71.4% | 5/7 |
| LLM 微调 / LoRA / DPO | 71.4% | 5/7 |

## 失败清单

- [F_TOPIC_MISSING] rag_multi_channel_retrieval not in plan
- [F_TOPIC_MISSING] mcp_tool_integration not in plan
- [F_TOPIC_MISSING] cache_penetration_avalanche not in plan
- [F_TOPIC_MISSING] mysql_indexing_optimization not in plan
- [F_score_band_strong_react_state_management] score=50, expected [80, 95]
- [F_decision_action_normal_react_state_management] action=NEXT_TOPIC for normal answer
- [F_score_band_normal_react_state_management] score=45, expected [60, 82]
- [F_decision_action_vague_react_state_management] action=NEXT_TOPIC for vague answer
- [F_decision_action_off_topic_react_state_management] action=NEXT_TOPIC for off_topic answer
- [S_ranking_accuracy_react_state_management] scores: strong=50, normal=45, vague=47, off_topic=25
- [F_TOPIC_MISSING] frontend_performance not in plan
- [F_TOPIC_MISSING] async_task_queue_design not in plan
- [F_TOPIC_MISSING] api_idempotency_design not in plan
- [F_TOPIC_MISSING] lora_finetuning_practice not in plan
- [F_TOPIC_MISSING] dpo_alignment not in plan

## 建议动作

- 出题质量低于 80%：检查 Topic Registry 映射和 JD 解析规则
- 追问质量低于 70%：优化 StrictInterviewPolicy 追问逻辑
- 评分质量低于 80%：校准评分 prompt 和维度权重

## 下次改进

- 接入真实 LLM 评估追问质量和教练提示质量
- 增加人工抽检层
- 建立版本对比机制
