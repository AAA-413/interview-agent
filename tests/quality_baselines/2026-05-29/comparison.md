# 质量基准版本对比

上一版本：previous-example
当前版本：2026-05-30

## 总体变化

综合通过率：**65.9% -> 100.0%** (+34.1pp)
通过检查：29/44 -> 155/155

## 质量线变化

| 质量线 | 上一版 | 当前版 | 变化 | 失败数变化 |
|--------|--------|--------|------|------------|
| 追问质量 | 44.4% | 100.0% | +55.6pp | 14 -> 0 |
| LLM 评审 | 0.0% | 100.0% | +100.0pp | 0 -> 0 |
| 出题质量 | 100.0% | 100.0% | +0.0pp | 0 -> 0 |
| 评分质量 | 0.0% | 100.0% | +100.0pp | 1 -> 0 |

## 新增失败

- 无

## 已修复失败

- [F_TOPIC_MISSING] api_idempotency_design not in plan
- [F_TOPIC_MISSING] async_task_queue_design not in plan
- [F_TOPIC_MISSING] cache_penetration_avalanche not in plan
- [F_TOPIC_MISSING] dpo_alignment not in plan
- [F_TOPIC_MISSING] frontend_performance not in plan
- [F_TOPIC_MISSING] lora_finetuning_practice not in plan
- [F_TOPIC_MISSING] mcp_tool_integration not in plan
- [F_TOPIC_MISSING] mysql_indexing_optimization not in plan
- [F_TOPIC_MISSING] rag_multi_channel_retrieval not in plan
- [F_score_band_normal_react_state_management] score=45, expected [60, 82]
- [F_score_band_strong_react_state_management] score=50, expected [80, 95]
- [S_ranking_accuracy_react_state_management] scores: strong=50, normal=45, vague=47, off_topic=25

## 仍未修复

- 无
