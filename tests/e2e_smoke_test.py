"""
端到端冒烟测试脚本 — 验证核心链路可用
用法: python tests/e2e_smoke_test.py [--base-url http://localhost:8002]

需要:
1. 后端服务运行中
2. .env 中配置了有效的 AI API key
"""

import sys
import time

import httpx

BASE_URL = "http://localhost:8002"
if len(sys.argv) > 1 and sys.argv[1].startswith("--base-url"):
    BASE_URL = sys.argv[1].split("=")[1] if "=" in sys.argv[1] else sys.argv[2]


def log(msg: str, ok: bool = True):
    prefix = "[PASS]" if ok else "[FAIL]"
    print(f"{prefix} {msg}")


def log_section(name: str):
    print(f"\n{'=' * 50}")
    print(f"  {name}")
    print(f"{'=' * 50}")


def result_data(response: httpx.Response) -> dict:
    if response.status_code != 200:
        return {}
    data = response.json()
    if isinstance(data, dict) and data.get("code") == 0 and isinstance(data.get("data"), dict):
        return data["data"]
    return data if isinstance(data, dict) else {}


def test_health(client: httpx.Client):
    log_section("1. 健康检查")
    r = client.get("/api/health")
    ok = r.status_code == 200 and r.json().get("status") == "UP"
    log(f"GET /api/health -> {r.status_code} {r.json()}", ok)
    return ok


def test_config_status(client: httpx.Client):
    log_section("2. 配置检查")
    r = client.get("/api/health/config")
    data = r.json() if r.status_code == 200 else {}
    ok = r.status_code == 200 and data.get("status") in {"OK", "WARN", "ERROR"} and "issues" in data
    issue_count = len(data.get("issues", [])) if isinstance(data.get("issues"), list) else 0
    log(f"GET /api/health/config -> {r.status_code}, status={data.get('status')}, issues={issue_count}", ok)
    return ok


def test_auth(client: httpx.Client) -> str | None:
    log_section("3. 用户认证")

    # 注册新用户
    ts = int(time.time())
    r = client.post(
        "/api/auth/register",
        json={
            "username": f"e2e_test_{ts}",
            "password": "Test123456",
            "email": f"e2e_{ts}@test.com",
        },
    )
    if r.status_code in (200, 201):
        log(f"POST /api/auth/register -> {r.status_code}", True)
        login_user = r.json()["username"]
        login_pass = "Test123456"
    else:
        log(f"POST /api/auth/register -> {r.status_code} {r.text}", False)
        return None

    # 登录
    r = client.post("/api/auth/login", json={"username": login_user, "password": login_pass})
    ok = r.status_code == 200 and "access_token" in r.json()
    log(f"POST /api/auth/login -> {r.status_code}", ok)
    if ok:
        token = r.json()["access_token"]
        log(f"Token: {token[:20]}...", True)
        return token
    return None


def test_resume_list(client: httpx.Client, headers: dict):
    log_section("4. 简历列表")
    r = client.get("/api/resumes", headers=headers)
    ok = r.status_code == 200 and r.json().get("code") == 0
    count = len(r.json().get("data", []))
    log(f"GET /api/resumes -> {r.status_code}, {count} 条简历", ok)
    return ok


def test_kb_list(client: httpx.Client, headers: dict):
    log_section("5. 知识库列表")
    r = client.get("/api/knowledgebase", headers=headers)
    ok = r.status_code == 200 and r.json().get("code") == 0
    count = len(r.json().get("data", []))
    log(f"GET /api/knowledgebase -> {r.status_code}, {count} 个知识库", ok)
    return ok


def test_interview_skills(client: httpx.Client, headers: dict):
    log_section("6. 面试方向")
    r = client.get("/api/interview/skills", headers=headers)
    ok = r.status_code == 200
    if ok:
        skills = r.json()
        log(f"GET /api/interview/skills -> {len(skills)} 个方向", True)
    else:
        log(f"GET /api/interview/skills -> {r.status_code}", False)
    return ok


def test_interview_sessions(client: httpx.Client, headers: dict):
    log_section("7. 面试会话列表")
    r = client.get("/api/interview/sessions", headers=headers)
    ok = r.status_code == 200 and r.json().get("code") == 0
    count = len(r.json().get("data", []))
    log(f"GET /api/interview/sessions -> {r.status_code}, {count} 个会话", ok)
    return ok


def test_401_rejection(client: httpx.Client):
    log_section("8. 认证拒绝")
    r = client.get("/api/resumes")
    ok = r.status_code == 401
    log(f"GET /api/resumes (no token) -> {r.status_code}", ok)

    r = client.get("/api/resumes", headers={"Authorization": "Bearer invalid_token"})
    ok2 = r.status_code == 401
    log(f"GET /api/resumes (bad token) -> {r.status_code}", ok2)
    return ok and ok2


def test_input_validation(client: httpx.Client, headers: dict):
    log_section("9. 输入校验")
    r = client.post(
        "/api/interview/sessions",
        headers=headers,
        json={
            "skill_id": "ai-agent-dev",
            "question_count": 50,
        },
    )
    ok = r.status_code == 422
    log(f"POST /api/interview/sessions (question_count=50) -> {r.status_code}", ok)
    return ok


def test_interview_diagnosis(client: httpx.Client, headers: dict):
    log_section("10. 面试诊断")
    r = client.post(
        "/api/interview/diagnosis",
        headers=headers,
        json={
            "target_role": "Java 后端开发",
            "target_company": "演示公司",
            "level": "校招",
            "jd_text": "负责后端服务、数据库设计、接口稳定性和项目复盘。",
        },
    )
    data = r.json() if r.status_code == 200 else {}
    payload = data.get("data", {}) if isinstance(data, dict) else {}
    ok = (
        r.status_code == 200
        and data.get("code") == 0
        and payload.get("readiness_score") is not None
        and len(payload.get("today_tasks", [])) >= 1
    )
    log(f"POST /api/interview/diagnosis -> {r.status_code}, score={payload.get('readiness_score')}", ok)
    return ok


def test_dynamic_coach_mode(client: httpx.Client, headers: dict):
    log_section("11. 动态教练模式")
    jd_text = "负责 RAG 多路召回、MCP 工具集成、工作流编排、监控告警和系统稳定性。"

    r = client.post(
        "/api/interview/jd/parse",
        headers=headers,
        json={
            "target_role": "AI Agent 后端工程师",
            "skill_id": "ai-agent",
            "jd_text": jd_text,
        },
    )
    parsed_jd = result_data(r)
    ok_parse = (
        r.status_code == 200
        and parsed_jd.get("quality_score", 0) > 0
        and parsed_jd.get("topic_weights")
        and parsed_jd.get("question_type_mix")
    )
    log(
        f"POST /api/interview/jd/parse -> {r.status_code}, quality={parsed_jd.get('quality_score')}",
        ok_parse,
    )
    if not ok_parse:
        return False

    r = client.post(
        "/api/interview/dynamic-sessions",
        headers=headers,
        json={
            "target_role": "AI Agent 后端工程师",
            "jd_text": jd_text,
            "mode": "COACH",
            "skill_id": "ai-agent",
        },
    )
    created = result_data(r)
    topics = created.get("plan_summary", {}).get("topics", [])
    current_turn = created.get("current_turn", {})
    session_id = created.get("session_id")
    turn_id = current_turn.get("id")
    ok_create = (
        r.status_code == 200
        and created.get("status") == "INTERVIEWING"
        and isinstance(session_id, str)
        and len(topics) == 4
        and turn_id is not None
    )
    log(f"POST /api/interview/dynamic-sessions -> {r.status_code}, topics={len(topics)}", ok_create)
    if not ok_create:
        return False

    r = client.post(
        f"/api/interview/dynamic-sessions/{session_id}/turns/{turn_id}/answer",
        headers=headers,
        json={
            "answer": (
                "我负责把 RAG 多路召回接入 Agent 工作流。首先定义召回链路，然后设计 MCP 工具调用，"
                "最后用监控告警和降级兜底降低失败风险，延迟从 3s 降到 1.8s。"
            )
        },
    )
    answer = result_data(r)
    decision = answer.get("decision", {})
    evaluation = answer.get("evaluation", {})
    ok_answer = (
        r.status_code == 200
        and decision.get("action") in {"COACH_RETRY", "NEXT_TOPIC", "END"}
        and isinstance(evaluation.get("ability_score"), int)
        and answer.get("current_topic")
    )
    log(
        "POST /api/interview/dynamic-sessions/{session}/turns/{turn}/answer "
        f"-> {r.status_code}, action={decision.get('action')}, score={evaluation.get('ability_score')}",
        ok_answer,
    )
    if not ok_answer:
        return False

    r = client.get(f"/api/interview/dynamic-sessions/{session_id}", headers=headers)
    detail = result_data(r)
    ok_detail = (
        r.status_code == 200
        and len(detail.get("topics", [])) == 4
        and len(detail.get("turns", [])) >= 1
        and detail.get("structured_jd")
    )
    log(
        f"GET /api/interview/dynamic-sessions/{session_id} -> {r.status_code}, turns={len(detail.get('turns', []))}",
        ok_detail,
    )
    if not ok_detail:
        return False

    r = client.post(f"/api/interview/dynamic-sessions/{session_id}/complete", headers=headers)
    report = result_data(r)
    ok_complete = (
        r.status_code == 200
        and report.get("readiness_score") is not None
        and len(report.get("topic_summaries", [])) == 4
        and len(report.get("tomorrow_tasks", [])) == 3
    )
    log(
        f"POST /api/interview/dynamic-sessions/{session_id}/complete -> {r.status_code}, "
        f"tasks={len(report.get('tomorrow_tasks', []))}",
        ok_complete,
    )
    if not ok_complete:
        return False

    r = client.get(f"/api/interview/dynamic-sessions/{session_id}/report", headers=headers)
    fetched_report = result_data(r)
    ok_report = (
        r.status_code == 200
        and fetched_report.get("session_id") == session_id
        and len(fetched_report.get("tomorrow_tasks", [])) == 3
    )
    log(f"GET /api/interview/dynamic-sessions/{session_id}/report -> {r.status_code}", ok_report)
    return ok_report


def test_demo_mode(client: httpx.Client, headers: dict) -> str | None:
    log_section("12. 样例数据/演示模式")
    r = client.post("/api/demo/seed", headers=headers)
    data = r.json() if r.status_code == 200 else {}
    payload = data.get("data", {}) if isinstance(data, dict) else {}
    session_id = payload.get("interview_session_id")
    ok = (
        r.status_code == 200
        and data.get("code") == 0
        and payload.get("resume_id") is not None
        and isinstance(session_id, str)
    )
    log(
        f"POST /api/demo/seed -> {r.status_code}, resume={payload.get('resume_id')}, session={session_id}",
        ok,
    )
    return session_id if ok else None


def test_retry_question(client: httpx.Client, headers: dict, source_session_id: str):
    log_section("14. 同题再练")
    r = client.post(
        f"/api/interview/sessions/{source_session_id}/retry",
        headers=headers,
        json={"question_index": 0},
    )
    data = r.json() if r.status_code == 200 else {}
    payload = data.get("data", {}) if isinstance(data, dict) else {}
    questions = payload.get("questions", [])
    ok_retry = (
        r.status_code == 200
        and data.get("code") == 0
        and payload.get("session_id")
        and payload.get("total_questions") == 1
        and questions
        and "同题再练" in (questions[0].get("category") or "")
    )
    retry_session_id = payload.get("session_id")
    log(f"POST /api/interview/sessions/{source_session_id}/retry -> {r.status_code}", ok_retry)
    if not ok_retry:
        return False

    r = client.get(f"/api/interview/sessions/{retry_session_id}/retry-comparison", headers=headers)
    data = r.json() if r.status_code == 200 else {}
    comparison = data.get("data", {}) if isinstance(data, dict) else {}
    ok_comparison = (
        r.status_code == 200
        and data.get("code") == 0
        and comparison.get("source_session_id") == source_session_id
        and comparison.get("status") == "WAITING_ANSWER"
        and comparison.get("original_score") is not None
    )
    log(f"GET /api/interview/sessions/{retry_session_id}/retry-comparison -> {r.status_code}", ok_comparison)
    return ok_comparison


def test_training_plan(client: httpx.Client, headers: dict):
    log_section("13. 评分校准与个人训练计划")
    r = client.get("/api/training/calibration", headers=headers)
    data = r.json() if r.status_code == 200 else {}
    calibration = data.get("data", {}) if isinstance(data, dict) else {}
    ok_calibration = (
        r.status_code == 200
        and data.get("code") == 0
        and calibration.get("evaluated_sessions", 0) >= 1
        and calibration.get("total_questions", 0) >= 1
        and isinstance(calibration.get("questions", []), list)
    )
    log(
        f"GET /api/training/calibration -> {r.status_code}, questions={calibration.get('total_questions')}",
        ok_calibration,
    )
    questions = calibration.get("questions", []) if isinstance(calibration, dict) else []
    retry_calibration = next(
        (
            item
            for item in questions
            if isinstance(item, dict)
            and isinstance(item.get("latest_retry_delta"), int)
            and item.get("latest_retry_delta") > 0
        ),
        None,
    )
    ok_retry_calibration = retry_calibration is not None
    log(
        f"校准包含同题再练分差 -> delta={retry_calibration.get('latest_retry_delta') if retry_calibration else None}",
        ok_retry_calibration,
    )

    r = client.get("/api/training/plan?days=3", headers=headers)
    data = r.json() if r.status_code == 200 else {}
    plan = data.get("data", {}) if isinstance(data, dict) else {}
    days = plan.get("plan", []) if isinstance(plan, dict) else []
    ok_plan = (
        r.status_code == 200
        and data.get("code") == 0
        and plan.get("readiness_score", 0) > 0
        and len(days) == 3
        and any(day.get("tasks") for day in days)
    )
    log(f"GET /api/training/plan?days=3 -> {r.status_code}, days={len(days)}", ok_plan)
    if not ok_plan:
        return False

    all_tasks = [task for day in days for task in day.get("tasks", []) if isinstance(task, dict)]
    retry_task = next(
        (task for task in all_tasks if isinstance(task.get("latest_retry_delta"), int) and task.get("retry_signal")),
        None,
    )
    ok_retry_plan = retry_task is not None
    log(
        f"训练计划包含重练信号 -> signal={retry_task.get('retry_signal') if retry_task else None}",
        ok_retry_plan,
    )

    first_task = next((task for task in all_tasks if task.get("id")), None)
    if not first_task:
        log("训练计划没有可标记任务", False)
        return False

    r = client.put(
        "/api/training/tasks/progress",
        headers=headers,
        json={
            "task_id": first_task["id"],
            "status": "COMPLETED",
            "title": first_task.get("title"),
            "task_type": first_task.get("task_type"),
            "source_session_id": first_task.get("source_session_id"),
            "question_index": first_task.get("question_index"),
        },
    )
    data = r.json() if r.status_code == 200 else {}
    progress = data.get("data", {}) if isinstance(data, dict) else {}
    ok_progress = r.status_code == 200 and data.get("code") == 0 and progress.get("status") == "COMPLETED"
    log(f"PUT /api/training/tasks/progress -> {r.status_code}, status={progress.get('status')}", ok_progress)

    r = client.get("/api/training/plan?days=3", headers=headers)
    data = r.json() if r.status_code == 200 else {}
    refreshed_plan = data.get("data", {}) if isinstance(data, dict) else {}
    refreshed_days = refreshed_plan.get("plan", []) if isinstance(refreshed_plan, dict) else []
    refreshed_task = next(
        (task for day in refreshed_days for task in day.get("tasks", []) if task.get("id") == first_task["id"]),
        {},
    )
    ok_refreshed = r.status_code == 200 and refreshed_task.get("status") == "COMPLETED"
    log(f"GET /api/training/plan?days=3 (progress) -> {r.status_code}", ok_refreshed)

    r = client.get("/api/training/trends", headers=headers)
    data = r.json() if r.status_code == 200 else {}
    trend = data.get("data", {}) if isinstance(data, dict) else {}
    ok_trend = (
        r.status_code == 200
        and data.get("code") == 0
        and trend.get("completed_task_count", 0) >= 1
        and isinstance(trend.get("trend", []), list)
    )
    log(f"GET /api/training/trends -> {r.status_code}, completed={trend.get('completed_task_count')}", ok_trend)
    retry_trend_points = [
        item
        for item in trend.get("trend", [])
        if isinstance(item, dict)
        and item.get("metric_type") == "RETRY_DELTA"
        and isinstance(item.get("delta"), int)
        and item.get("delta") > 0
    ]
    ok_retry_trend = bool(retry_trend_points) and isinstance(trend.get("latest_retry_delta"), int)
    log(
        f"趋势包含同题再练分差 -> latest_delta={trend.get('latest_retry_delta')}",
        ok_retry_trend,
    )
    return (
        ok_calibration
        and ok_retry_calibration
        and ok_plan
        and ok_retry_plan
        and ok_progress
        and ok_refreshed
        and ok_trend
        and ok_retry_trend
    )


def test_data_isolation(client: httpx.Client):
    log_section("15. 数据隔离")
    # 注册新用户
    ts = int(time.time())
    r = client.post(
        "/api/auth/register",
        json={
            "username": f"isolated_{ts}",
            "password": "Test123456",
            "email": f"isolated_{ts}@test.com",
        },
    )
    if r.status_code not in (200, 201):
        log("无法注册测试用户", False)
        return False

    new_username = r.json()["username"]

    r = client.post(
        "/api/auth/login",
        json={
            "username": new_username,
            "password": "Test123456",
        },
    )
    if r.status_code != 200:
        log("无法登录测试用户", False)
        return False

    new_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = client.get("/api/resumes", headers=new_headers)
    ok = r.status_code == 200 and len(r.json().get("data", [])) == 0
    log(f"新用户简历列表为空: {len(r.json().get('data', []))} 条", ok)
    return ok


def main():
    print(f"端到端冒烟测试 — {BASE_URL}")
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    results = []
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        results.append(("健康检查", test_health(client)))
        results.append(("配置检查", test_config_status(client)))
        results.append(("认证拒绝", test_401_rejection(client)))

        token = test_auth(client)
        if not token:
            print("\n[FAIL] 无法获取 token，后续测试跳过")
            return

        headers = {"Authorization": f"Bearer {token}"}
        results.append(("简历列表", test_resume_list(client, headers)))
        results.append(("知识库列表", test_kb_list(client, headers)))
        results.append(("面试方向", test_interview_skills(client, headers)))
        results.append(("面试会话", test_interview_sessions(client, headers)))
        results.append(("输入校验", test_input_validation(client, headers)))
        results.append(("面试诊断", test_interview_diagnosis(client, headers)))
        results.append(("动态教练模式", test_dynamic_coach_mode(client, headers)))
        demo_session_id = test_demo_mode(client, headers)
        results.append(("样例数据/演示模式", demo_session_id is not None))
        results.append(("评分校准与个人训练计划", test_training_plan(client, headers)))
        if demo_session_id:
            results.append(("同题再练", test_retry_question(client, headers, demo_session_id)))
        else:
            results.append(("同题再练", False))
        results.append(("数据隔离", test_data_isolation(client)))

    # 汇总
    log_section("测试汇总")
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
    print(f"\n通过: {passed}/{total}")
    if passed == total:
        print("所有测试通过!")
    else:
        print("存在失败的测试，请检查。")


if __name__ == "__main__":
    main()
