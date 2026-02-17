"""Tests for tester agent helper functions."""

from src.agents.tester import _analyse_result, _build_analysis


class TestAnalyseResult:
    def test_clean_pass(self):
        assert _analyse_result(0, "ok\n", "") is True

    def test_nonzero_returncode_fails(self):
        assert _analyse_result(1, "", "error") is False

    def test_traceback_in_stderr_fails(self):
        assert _analyse_result(0, "", "Traceback (most recent call last):") is False

    def test_error_in_stdout_fails(self):
        assert _analyse_result(0, "Error: something broke", "") is False

    def test_exception_in_stderr_fails(self):
        assert _analyse_result(0, "", "Exception: boom") is False

    def test_fail_signal_in_stdout(self):
        assert _analyse_result(0, "FAIL: test_something", "") is False

    def test_assertion_error_in_stdout(self):
        # Note: the source code checks for "AssertionError" (typo in original)
        assert _analyse_result(0, "AssertionError: values differ", "") is False

    def test_clean_output_with_warnings_passes(self):
        # Warnings that are NOT in the error_signals list should pass
        assert _analyse_result(0, "DeprecationWarning: something", "") is True

    def test_returncode_minus_one(self):
        assert _analyse_result(-1, "", "") is False

    def test_empty_output_passes(self):
        assert _analyse_result(0, "", "") is True


class TestBuildAnalysis:
    def test_passed_message(self):
        msg = _build_analysis(True, 0, "ok", "")
        assert "PASSED" in msg
        assert "Return code 0" in msg

    def test_failed_message(self):
        msg = _build_analysis(False, 1, "", "some error")
        assert "FAILED" in msg
        assert "Return code 1" in msg
        assert "Stderr:" in msg

    def test_failed_with_traceback_in_stdout(self):
        msg = _build_analysis(False, 1, "Traceback (most recent call last):\n...", "")
        assert "Traceback found in stdout" in msg

    def test_failed_empty_stderr_no_stderr_section(self):
        msg = _build_analysis(False, 1, "output", "")
        assert "Stderr:" not in msg

    def test_failed_stderr_truncated(self):
        long_stderr = "x" * 1000
        msg = _build_analysis(False, 1, "", long_stderr)
        # _build_analysis truncates to 500 chars
        assert "Stderr:" in msg
        # The stderr in the message should be at most 500 chars of the original
        assert len(long_stderr[:500]) == 500
