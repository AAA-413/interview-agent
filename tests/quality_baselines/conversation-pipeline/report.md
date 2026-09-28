# Conversation Quality 基线（deterministic）

- 生成时间：2026-09-28T11:44:34
- 通过：18/18（100.0%）

| Check | 结果 | 说明 |
| --- | --- | --- |
| context_contains_previous_question | PASS | history=面试官：你们为什么使用 Redis Streams？
候选人：因为需要 Consumer Group 支持多个消费者并行消费。
面试官：那消费失败怎么重试？
候 |
| context_contains_previous_answer | PASS | previous answers present in rendered history |
| context_contains_current_answer | PASS | current_answer=我们后来用 Redis Streams 做异步任务队列，Producer 用 X |
| recent_turns_capped | PASS | turns in context=4, budget=4 |
| oldest_turn_dropped | PASS | rendered chars=175 |
| policy_emits_intent_only | PASS | action=FOLLOW_UP, intent=VERIFY_OWNERSHIP, next_question=None |
| intent_forwarded_to_realizer | PASS | intent=VERIFY_OWNERSHIP |
| realizer_receives_answer_not_only_gap | PASS | candidate's concrete terms present in user prompt |
| untrusted_data_not_in_system_prompt | PASS | candidate answer stays in user message only |
| realizer_returns_question | PASS | question=你刚才提到 XREADGROUP，重复投递怎么处理？ |
| fallback_on_timeout | PASS | realized=你刚才讲到了一些点，但我还没听清楚最小链路。就选一个最小闭环，从一次请求或任务进 |
| fallback_on_exception | PASS | realized=你刚才讲到了一些点，但我还没听清楚最小链路。就选一个最小闭环，从一次请求或任务进 |
| transition_context_has_previous_topic | PASS | previous=async_task_pipeline |
| transition_prompt_has_both_topics | PASS | previous and next topic both in prompt |
| transition_composed_into_opening | PASS | opening=这块先到这里。

消费者重复收到任务时怎么保证幂等？ |
| transition_fallback_uses_main_question | PASS | opening=请讲清楚消费端怎么保证幂等。 |
| single_flight_key_differs_on_state | PASS | followup-realize|3b4a31b vs followup-realize|918b10a |
| single_flight_key_stable_on_same_state | PASS | same context merges |

结论：对话主链路契约检查通过