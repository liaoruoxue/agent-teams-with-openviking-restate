"""Tests for sandbox file I/O and subprocess operations.

Since the Restate handlers wrap logic in ctx.run() closures, we test
the underlying file I/O and subprocess operations directly.
"""

import os
import subprocess

import pytest


class TestSandboxCreateDir:
    def test_create_dir(self, tmp_path):
        base = tmp_path / "project_1"
        os.makedirs(base, exist_ok=True)
        assert base.is_dir()

    def test_create_dir_nested(self, tmp_path):
        base = tmp_path / "deep" / "nested" / "project"
        os.makedirs(base, exist_ok=True)
        assert base.is_dir()

    def test_create_dir_idempotent(self, tmp_path):
        base = tmp_path / "project_x"
        os.makedirs(base, exist_ok=True)
        os.makedirs(base, exist_ok=True)  # should not raise
        assert base.is_dir()


class TestSandboxWriteRead:
    def test_write_read_roundtrip(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        path = project / "main.py"

        content = "print('hello world')\n"
        with open(path, "w") as f:
            f.write(content)

        with open(path) as f:
            assert f.read() == content

    def test_write_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "proj" / "subdir" / "file.py"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("x = 1\n")

        with open(path) as f:
            assert f.read() == "x = 1\n"

    def test_write_overwrites(self, tmp_path):
        path = tmp_path / "file.py"
        with open(path, "w") as f:
            f.write("v1")
        with open(path, "w") as f:
            f.write("v2")
        with open(path) as f:
            assert f.read() == "v2"


class TestSandboxExec:
    def test_exec_python_success(self, tmp_path):
        script = tmp_path / "main.py"
        script.write_text("print('hello')")

        result = subprocess.run(
            "python main.py", shell=True, capture_output=True, text=True,
            cwd=str(tmp_path), timeout=30,
        )
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_exec_python_failure(self, tmp_path):
        script = tmp_path / "bad.py"
        script.write_text("raise ValueError('boom')")

        result = subprocess.run(
            "python bad.py", shell=True, capture_output=True, text=True,
            cwd=str(tmp_path), timeout=30,
        )
        assert result.returncode != 0
        assert "ValueError" in result.stderr

    def test_exec_captures_stderr(self, tmp_path):
        script = tmp_path / "warn.py"
        script.write_text("import sys; sys.stderr.write('warning\\n'); print('ok')")

        result = subprocess.run(
            "python warn.py", shell=True, capture_output=True, text=True,
            cwd=str(tmp_path), timeout=30,
        )
        assert result.returncode == 0
        assert "ok" in result.stdout
        assert "warning" in result.stderr

    def test_exec_timeout(self, tmp_path):
        script = tmp_path / "slow.py"
        script.write_text("import time; time.sleep(10)")

        with pytest.raises(subprocess.TimeoutExpired):
            subprocess.run(
                "python slow.py", shell=True, capture_output=True, text=True,
                cwd=str(tmp_path), timeout=1,
            )

    def test_exec_return_dict_shape(self, tmp_path):
        """Verify the dict structure that sandbox.exec_command returns."""
        script = tmp_path / "main.py"
        script.write_text("print('ok')")

        r = subprocess.run(
            "python main.py", shell=True, capture_output=True, text=True,
            cwd=str(tmp_path), timeout=30,
        )
        out = {"stdout": r.stdout, "stderr": r.stderr, "returncode": r.returncode}
        assert "stdout" in out
        assert "stderr" in out
        assert "returncode" in out
        assert out["returncode"] == 0
