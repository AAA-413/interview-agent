# Interview Engine Invariant Registry

本文件是 **PR1–PR6 面试主链的不变量清单（single source of truth）**。

用途：

```text
1. Code Review 时对照「这条不变量属于谁、破了会怎样」
2. 新人 / 面试讲解：主链到底谁在什么时刻做决定
3. Release Gate 的语义依据：CI 报错对应哪条不变量被改坏
```

本文只描述**当前代码真实行为**，不是设计愿景。每一条都能在代码里指到落点。

---

## 1. 主链

### 1.1 Planning（建会话）

```text
JD + Resume
      ↓  Resume: Canonical（source-validated facts）
         └─ canonical 不可用 → legacy ResumeProfile
      ↓  Interview Planner（deterministic + canonical-first）
      ↓  Topics（topic_key / skill_key / question_type / main_question / coverage targets）
      ↓  resume_evidence_refs 冻结在 topic 上（随 topic 落库）
```

关键点：

- **canonical-first**：`settings.resume.canonical_extractor_enabled` 为真且 canonical `READY`
  时，Planner **只信 canonical**；即使 `projects == []` 也**不回退 legacy**（确定性 fallback）。
  只有 canonical 根本不可用（STALE / NOT_EXTRACTED / FAILED / kill switch 关闭）才走 legacy。
- canonical 的每条 fact 都带 `claim_id + quote + start/end + line`，并经过
  exact／全局唯一 quote、逐 span value-support、project locality（verified source scope）校验。
- `topic.resume_evidence_refs` 一旦落库即**冻结**；retry session 复制原 refs，不重读最新 canonical。

### 1.2 Answer（一次作答）

```text
Candidate Answer
      ↓
E0 Snapshot                    （独立短 DB session，只读，随即关闭）
      ↓
Deterministic Hard Guard        （纯计算：空 / 极短 / 纯符号 → RULE_ONLY，skip semantic）
      ↓
Knowledge Grounding             （**仅 KNOWLEDGE**；0 DB transaction 跨外部调用）
      ↓
Hybrid Evaluator LLM            （语义判断；期间无业务 transaction）
      ↓
Phase 1（唯一的 correctness commit 点）
         turn FOR UPDATE
         → topic FOR UPDATE
         → revalidate（防重复提交 / 状态漂移）
         → coverage reducer
         → Policy（intent-only）
         → persist answer / evaluation / decision / next turn
         → commit
      ↓
Phase 2 Realizer（LLM 生成措辞；期间不访问 DB，失败 → 确定性兜底问题）
      ↓
Phase 3 best-effort enhancement（只把措辞落库；失败 → 保留 Phase 1 兜底状态）
```

---

## 2. 谁拥有哪类决策

| Concern | Owner |
| --- | --- |
| session lifecycle | deterministic code |
| topic lifecycle | deterministic code |
| max_turns | deterministic code |
| score weighting | deterministic code |
| hard caps | deterministic code |
| evidence validation | deterministic code |
| coverage reducer | deterministic code |
| Policy action | deterministic code |
| semantic dimension scoring | LLM |
| factual relation judgement | LLM + validated Knowledge Evidence |
| natural language wording | LLM |
| resume provenance | Canonical Resume |
| candidate provenance | Candidate Answer |
| knowledge provenance | Knowledge KB chunk |

推论（都不允许被 LLM 破坏）：

```text
- LLM 输出的分数只是「语义判断的原始素材」，最终加权 / cap / confidence
  全部由代码计算。
- LLM 生成的措辞只能出现在 wording 字段；不能改写 topic_key / question_type /
  main_question / decision.action。
- LLM 不能生成 claim_id / evidence_id / 行号 / 字符位置。
```

---

## 3. 三类 Evidence 严格分离

| Evidence | 证明什么 | **不**证明什么 | 落点 |
| --- | --- | --- | --- |
| Resume Evidence | 简历原文**写了什么** | 现实事实 / 候选人真的做过 | `topic.resume_evidence_refs_json`（PR4） |
| Candidate Evidence | 候选人**本轮回答说了什么** | 说的内容是否正确 | `DynamicTurnEvaluationDTO.evidence` / `coverage.evidence_quotes`（PR2/PR3） |
| Knowledge Evidence | 知识库 corpus 里**有哪些参考依据** | 世界真理 / 客观正确 | `DynamicTurnEvaluationDTO.knowledge_grounding.references`（PR5） |

硬约束：

```text
- `EvaluationEvidenceDTO.quote` 必须逐字来自本轮 Candidate Answer（normalize 后包含）。
- Knowledge Evidence 的 content 必须逐字来自该用户 KB 的 chunk.content 前缀。
- Resume Evidence 只能来自通过校验的 canonical claim span。
- 三者禁止互相写入对方的字段：
  KB chunk 绝不进入 resume_evidence_refs / candidate evidence；
  candidate answer 绝不进入 knowledge refs；
  KB 文本绝不作为 coverage evidence。
- Coverage 只回答「候选人当前回答讲到了什么」，与知识库内容无关。
```

---

## 4. Transaction Boundary

**外部调用期间不能持有业务 transaction，也不能持有 `FOR UPDATE` 锁。**

| 外部调用 | 期间是否可持有业务 transaction | 落点 |
| --- | --- | --- |
| Canonical Resume LLM | 否 | `resume/async_tasks.py` R0–R4 短事务 |
| Embedding（Knowledge Grounding） | 否 | `evaluation/knowledge_grounding.py` G1 `asyncio.to_thread` |
| Rerank | 否（检索 session 已关闭） | 同上 G3 |
| Evaluator LLM | 否 | `dynamic_service.py` E0/E1 |
| Question Realizer LLM | 否（Phase 1 已提交） | `_run_realizer_outside_transaction` |
| Metric 写入 | 用**独立** session | `_record_operation_metric` |

Phase 1 锁顺序**永久固定**：

```text
turn FOR UPDATE
   → topic FOR UPDATE
```

不允许调换（否则不同请求会出现锁序反转 → 死锁）。

---

## 5. Correctness Path

定义（PR6 明确化）：

```text
Phase 1 commit 之前：
    核心状态由 deterministic code 决定。

Phase 1 commit 之后：
    LLM wording / enhancement / metric failure
    不能破坏已经提交的核心状态。
```

`Phase 1 commit` 提交的内容：

```text
turn.answer / turn.evaluation_json / turn.decision_json / turn.signals_json
topic.turn_count / topic.best_score / topic.coverage_state_json / topic.status
下一轮 turn（确定性兜底问题）
```

PR1 原话语义保留：

```text
LLM enhancement 不属于 correctness path。
```

具体含义：

```text
- evaluator LLM 失败 → HEURISTIC_FALLBACK（confidence 0.35），answer 照常提交
- grounding 失败 → status=ERROR，evaluator 继续，confidence 仍受 KNOWLEDGE cap 约束
- realizer LLM 失败 → 确定性兜底问题，decision 语义不变
- Phase 3 落库失败 → Phase 1 兜底状态保留
- metric 写入失败 → 只 warning，业务状态完全不变
```

---

## 6. Answer 侧的具体不变量（按 PR 归档）

### PR1 — Context / Policy / Realizer

```text
Policy 只输出 intent（action / target_gap / follow_up_intent / …），不输出措辞
Realizer 只生成 wording；NEXT_TOPIC 的问题正文 == next_topic.main_question
LLM enhancement 不属于 correctness path
```

### PR2 — Hybrid Evaluator

```text
active dimensions 由 question_type 决定（PROJECT / KNOWLEDGE / SYSTEM_DESIGN 三套）
分数越界 / 缺 active dimension / 0 条有效 evidence → HEURISTIC_FALLBACK
final score / hard cap / evidence cap(84) / confidence tier 全部由代码计算
confidence 由唯一 evidence 条数决定，不采信模型自报
turn → topic 锁顺序
```

### PR3 — Topic Coverage / Adaptive

```text
Score 与 Coverage 是两个 failure domain：coverage 局部异常不能打回 score
Coverage 单调不前退（NOT_COVERED → PARTIAL → COVERED 不可逆）
coverage evidence 只来自**当前这一轮** Candidate Answer
max_turns 是 hard stop
```

### PR4 — Resume Canonical Evidence

```text
Canonical 是 resume claim 的唯一 factual source
resume evidence 随 topic 冻结（retry 复制旧 refs）
Planner canonical-first；canonical READY + projects=[] 不回退 legacy
resume provenance 与 knowledge provenance 完全分离
```

### PR5 — Knowledge Grounding

```text
只对 KNOWLEDGE 生效（PROJECT / SYSTEM_DESIGN = NOT_APPLICABLE）
query deterministic，且**绝不包含** candidate answer
检索 user-scoped（JOIN knowledge_bases + user_id + index_status=COMPLETED）
score 恒为 bounded cosine relevance ∈ [0,1]；reranker raw 分只用于排序
NO_SOURCE 在 embedding 之前判定
只有 validated grounding 才解除 KNOWLEDGE confidence cap 0.75
CONTRADICTED 也可解除 cap（confidence = 我们对判断的把握，不是答得好不好）
```

### PR6 — Engineering Closure

```text
metric 永远不属于 correctness path（写失败只 warning，不递归写 metric）
diagnostics 是只读聚合：不重算 score、不重跑 evaluator / retrieval、不改 session
diagnostics 只返回聚合元数据，不返回任何用户文本
strict_config=True 时 embedding 真实失败 → fail closed，绝不写 hash 向量
strict 下失败**不**永久 flip provider（下一次仍尝试真实 provider）
```

---

## 7. 故障域隔离矩阵

| 故障 | 期望结果 | 不允许 |
| --- | --- | --- |
| Canonical LLM 超时 | grading 继续；canonical 标记失败 | 整份简历 analyze 失败 |
| Evaluator LLM 超时 | `HEURISTIC_FALLBACK` / 0.35 | answer 提交失败 |
| Knowledge Grounding 超时 / 报错 | `status=ERROR`，evaluator 照常 | HTTP 500 |
| Reranker 运行期异常 | grounding `ERROR`，不再声称 `VECTOR_RERANK` | 谎报 rerank 成功 |
| Coverage reducer 抛出 | score / answer 保留，旧 coverage 保留 | 打回 score |
| Realizer LLM 失败 | 确定性兜底问题 | decision 语义被改写 |
| Phase 3 落库失败 | Phase 1 状态保留 | 已提交状态回滚 |
| Metric 写入失败 | 只 `logger.warning` | 影响业务 / 递归写 metric |
| 重复提交同一轮 | 只成功一次 | turn_count 重复 +1 / 重复 coverage reduce |

---

## 8. 命令

```bash
# 全量本地质量门禁（compile + ruff + format + pytest + release gate + frontend build）
./scripts/quality_check.sh

# 只跑确定性 release gate
PYTHONPATH=. .venv/bin/python scripts/interview_release_gate.py
```
