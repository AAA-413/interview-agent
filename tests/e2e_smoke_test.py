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


def test_health(client: httpx.Client):
    log_section("1. 健康检查")
    r = client.get("/api/health")
    ok = r.status_code == 200 and r.json().get("status") == "UP"
    log(f"GET /api/health -> {r.status_code} {r.json()}", ok)
    return ok


def test_auth(client: httpx.Client) -> str | None:
    log_section("2. 用户认证")

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
    log_section("3. 简历列表")
    r = client.get("/api/resumes", headers=headers)
    ok = r.status_code == 200 and r.json().get("code") == 0
    count = len(r.json().get("data", []))
    log(f"GET /api/resumes -> {r.status_code}, {count} 条简历", ok)
    return ok


def test_kb_list(client: httpx.Client, headers: dict):
    log_section("4. 知识库列表")
    r = client.get("/api/knowledgebase", headers=headers)
    ok = r.status_code == 200 and r.json().get("code") == 0
    count = len(r.json().get("data", []))
    log(f"GET /api/knowledgebase -> {r.status_code}, {count} 个知识库", ok)
    return ok


def test_interview_skills(client: httpx.Client, headers: dict):
    log_section("5. 面试方向")
    r = client.get("/api/interview/skills", headers=headers)
    ok = r.status_code == 200
    if ok:
        skills = r.json()
        log(f"GET /api/interview/skills -> {len(skills)} 个方向", True)
    else:
        log(f"GET /api/interview/skills -> {r.status_code}", False)
    return ok


def test_interview_sessions(client: httpx.Client, headers: dict):
    log_section("6. 面试会话列表")
    r = client.get("/api/interview/sessions", headers=headers)
    ok = r.status_code == 200 and r.json().get("code") == 0
    count = len(r.json().get("data", []))
    log(f"GET /api/interview/sessions -> {r.status_code}, {count} 个会话", ok)
    return ok


def test_401_rejection(client: httpx.Client):
    log_section("7. 认证拒绝")
    r = client.get("/api/resumes")
    ok = r.status_code == 401
    log(f"GET /api/resumes (no token) -> {r.status_code}", ok)

    r = client.get("/api/resumes", headers={"Authorization": "Bearer invalid_token"})
    ok2 = r.status_code == 401
    log(f"GET /api/resumes (bad token) -> {r.status_code}", ok2)
    return ok and ok2


def test_input_validation(client: httpx.Client, headers: dict):
    log_section("8. 输入校验")
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


def test_data_isolation(client: httpx.Client):
    log_section("9. 数据隔离")
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
