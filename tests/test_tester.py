"""Tests for tester agent helper functions."""

from src.agents.tester import _analyse_result, _parse_verdict


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


class TestParseVerdict:
    def test_pass_verdict(self):
        assert _parse_verdict("Everything looks good.\nVERDICT: PASS") is True

    def test_fail_verdict(self):
        assert _parse_verdict("There was a traceback.\nVERDICT: FAIL") is False

    def test_case_insensitive_pass(self):
        assert _parse_verdict("verdict: pass") is True

    def test_case_insensitive_fail(self):
        assert _parse_verdict("Verdict: Fail") is False

    def test_mixed_case(self):
        assert _parse_verdict("VERDICT: Pass") is True

    def test_no_verdict_returns_none(self):
        assert _parse_verdict("No clear conclusion here.") is None

    def test_empty_string_returns_none(self):
        assert _parse_verdict("") is None

    def test_verdict_with_extra_whitespace(self):
        assert _parse_verdict("VERDICT:   PASS") is True

    def test_verdict_in_middle_of_text(self):
        response = "Analysis: code failed.\nVERDICT: FAIL\nEnd of report."
        assert _parse_verdict(response) is False
