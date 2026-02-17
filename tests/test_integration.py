"""Integration tests against a real Restate server.

Requires:
  1. Restate server running on localhost (admin: 9070, ingress: 8080)
  2. App served on localhost:9080

How to run:
  Terminal 1:  uv run python -m src.main          # start app on 9080
  Terminal 2:  curl localhost:9070/deployments      # verify Restate is up
               curl localhost:9070/deployments -H 'content-type: application/json' \
                 -d '{"uri": "http://localhost:9080"}'   # register once
               uv run pytest tests/test_integration.py -v
"""

import os
import subprocess
import time

import httpx
import pytest

RESTATE_INGRESS = os.getenv("RESTATE_URL", "http://localhost:8080")
RESTATE_ADMIN = "http://localhost:9070"
APP_URL = "http://localhost:9080"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _restate_is_up() -> bool:
    try:
        r = httpx.get(f"{RESTATE_ADMIN}/deployments", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def _app_is_up() -> bool:
    try:
        r = httpx.get(f"{APP_URL}/restate/health", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def _services_registered() -> bool:
    try:
        r = httpx.get(f"{RESTATE_ADMIN}/services", timeout=2)
        names = [s["name"] for s in r.json().get("services", [])]
        return "sandbox" in names and "manager" in names
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ensure_app():
    """Ensure Restate and the app are up and services registered."""
    if not _restate_is_up():
        pytest.skip("Restate server not running on localhost:9070")
    if not _app_is_up():
        pytest.skip(
            "App not running on localhost:9080. "
            "Start with: uv run python -m src.main"
        )
    if not _services_registered():
        # Try to register
        r = httpx.post(
            f"{RESTATE_ADMIN}/deployments",
            json={"uri": APP_URL},
            headers={"content-type": "application/json"},
            timeout=10,
        )
        if r.status_code not in (200, 201, 409):
            pytest.skip(f"Failed to register app with Restate: {r.status_code} {r.text}")
        # Give Restate a moment to discover services
        time.sleep(1)
        if not _services_registered():
            pytest.skip("Services not registered after deployment")


# ---------------------------------------------------------------------------
# Sandbox Service — direct Restate calls
# ---------------------------------------------------------------------------


class TestSandboxViaRestate:
    """Test sandbox service through the Restate ingress."""

    def test_create_project(self, ensure_app):
        r = httpx.post(
            f"{RESTATE_INGRESS}/sandbox/create_project",
            json="integration_test_proj",
            headers={"content-type": "application/json"},
            timeout=10,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["project_id"] == "integration_test_proj"
        assert "/tmp/lbg/integration_test_proj" in body["path"]

    def test_write_and_read_file(self, ensure_app):
        # Write
        r = httpx.post(
            f"{RESTATE_INGRESS}/sandbox/write_file",
            json={
                "project_id": "integration_test_proj",
                "filename": "hello.py",
                "content": "print('hello from integration test')",
            },
            headers={"content-type": "application/json"},
            timeout=10,
        )
        assert r.status_code == 200

        # Read
        r = httpx.post(
            f"{RESTATE_INGRESS}/sandbox/read_file",
            json={
                "project_id": "integration_test_proj",
                "filename": "hello.py",
            },
            headers={"content-type": "application/json"},
            timeout=10,
        )
        assert r.status_code == 200
        assert "hello from integration test" in r.json()["content"]

    def test_exec_command(self, ensure_app):
        r = httpx.post(
            f"{RESTATE_INGRESS}/sandbox/exec_command",
            json={
                "project_id": "integration_test_proj",
                "command": "python hello.py",
            },
            headers={"content-type": "application/json"},
            timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["returncode"] == 0
        assert "hello from integration test" in body["stdout"]

    def test_exec_failing_command(self, ensure_app):
        # Write a failing script
        httpx.post(
            f"{RESTATE_INGRESS}/sandbox/write_file",
            json={
                "project_id": "integration_test_proj",
                "filename": "fail.py",
                "content": "raise ValueError('intentional error')",
            },
            headers={"content-type": "application/json"},
            timeout=10,
        )
        r = httpx.post(
            f"{RESTATE_INGRESS}/sandbox/exec_command",
            json={
                "project_id": "integration_test_proj",
                "command": "python fail.py",
            },
            headers={"content-type": "application/json"},
            timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["returncode"] != 0
        assert "ValueError" in body["stderr"]


# ---------------------------------------------------------------------------
# Coder Agent — isolated test (needs LLM)
# ---------------------------------------------------------------------------


class TestCoderViaRestate:
    """Test coder virtual object through the Restate ingress."""

    def test_generate_code(self, ensure_app):
        """Coder should call LLM and write code to sandbox."""
        project_id = "coder_test"

        # First create project
        httpx.post(
            f"{RESTATE_INGRESS}/sandbox/create_project",
            json=project_id,
            headers={"content-type": "application/json"},
            timeout=10,
        )

        # Call coder
        r = httpx.post(
            f"{RESTATE_INGRESS}/coder/{project_id}/generate_code",
            json={"task": "写一个Python函数计算斐波那契数列前10个数并打印", "reference": ""},
            headers={"content-type": "application/json"},
            timeout=60,  # LLM call may take a while
        )
        assert r.status_code == 200
        body = r.json()
        assert "filename" in body
        assert "code" in body
        assert len(body["code"]) > 10

        # Verify file was written to sandbox
        r2 = httpx.post(
            f"{RESTATE_INGRESS}/sandbox/read_file",
            json={"project_id": project_id, "filename": body["filename"]},
            headers={"content-type": "application/json"},
            timeout=10,
        )
        assert r2.status_code == 200
        assert len(r2.json()["content"]) > 10


# ---------------------------------------------------------------------------
# Tester Agent
# ---------------------------------------------------------------------------


class TestTesterViaRestate:
    """Test tester virtual object through the Restate ingress."""

    def test_run_test_pass(self, ensure_app):
        project_id = "tester_test"
        httpx.post(
            f"{RESTATE_INGRESS}/sandbox/create_project",
            json=project_id,
            headers={"content-type": "application/json"},
            timeout=10,
        )
        httpx.post(
            f"{RESTATE_INGRESS}/sandbox/write_file",
            json={
                "project_id": project_id,
                "filename": "ok.py",
                "content": "print('all good')",
            },
            headers={"content-type": "application/json"},
            timeout=10,
        )

        r = httpx.post(
            f"{RESTATE_INGRESS}/tester/{project_id}/run_test",
            json={"project_id": project_id, "filename": "ok.py"},
            headers={"content-type": "application/json"},
            timeout=60,  # Tester now calls LLM for analysis
        )
        assert r.status_code == 200
        body = r.json()
        assert body["passed"] is True

    def test_run_test_fail(self, ensure_app):
        project_id = "tester_fail_test"
        httpx.post(
            f"{RESTATE_INGRESS}/sandbox/create_project",
            json=project_id,
            headers={"content-type": "application/json"},
            timeout=10,
        )
        httpx.post(
            f"{RESTATE_INGRESS}/sandbox/write_file",
            json={
                "project_id": project_id,
                "filename": "bad.py",
                "content": "raise RuntimeError('boom')",
            },
            headers={"content-type": "application/json"},
            timeout=10,
        )

        r = httpx.post(
            f"{RESTATE_INGRESS}/tester/{project_id}/run_test",
            json={"project_id": project_id, "filename": "bad.py"},
            headers={"content-type": "application/json"},
            timeout=60,  # Tester now calls LLM for analysis
        )
        assert r.status_code == 200
        body = r.json()
        assert body["passed"] is False


# ---------------------------------------------------------------------------
# Manager Agent — full orchestration (needs LLM + OV)
# ---------------------------------------------------------------------------


class TestManagerViaRestate:
    """End-to-end test of the manager orchestration."""

    def test_handle_task_bubble_sort(self, ensure_app):
        """Full workflow: manager → coder → tester with retry."""
        project_id = f"e2e_{int(time.time())}"

        r = httpx.post(
            f"{RESTATE_INGRESS}/manager/{project_id}/handle_task",
            json={"task": "写一个冒泡排序，对列表 [5,3,1,4,2] 排序并打印结果"},
            headers={"content-type": "application/json"},
            timeout=120,  # Full workflow with LLM calls
        )
        assert r.status_code == 200
        body = r.json()

        assert body["project_id"] == project_id
        assert body["status"] in ("success", "failed")
        assert "code" in body
        assert len(body["code"]) > 0

        # If succeeded, verify the code actually runs
        if body["status"] == "success":
            assert body["retries"] <= 3
            # Run it ourselves to double check
            r2 = httpx.post(
                f"{RESTATE_INGRESS}/sandbox/exec_command",
                json={"project_id": project_id, "command": "python main.py"},
                headers={"content-type": "application/json"},
                timeout=15,
            )
            assert r2.status_code == 200
            assert r2.json()["returncode"] == 0


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def cleanup_sandbox():
    """Remove integration test sandbox dirs after all tests."""
    yield
    import shutil
    for name in ("integration_test_proj", "coder_test", "tester_test", "tester_fail_test"):
        path = f"/tmp/lbg/{name}"
        if os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)
    # e2e dirs
    if os.path.exists("/tmp/lbg"):
        for d in os.listdir("/tmp/lbg"):
            if d.startswith("e2e_"):
                shutil.rmtree(f"/tmp/lbg/{d}", ignore_errors=True)
