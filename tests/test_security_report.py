"""Security reporting must fail closed and retain vulnerabilities without fixes."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "security_report", Path(__file__).parents[1] / "scripts/security_report.py"
)
reporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reporter)


@pytest.mark.parametrize(
    "report", [{}, {"SchemaVersion": 2}, {"Results": []}, {"SchemaVersion": 2, "Results": None}]
)
def test_missing_scan_is_not_clean(report):
    with pytest.raises(ValueError, match="Missing or unsupported"):
        reporter.summarize(report)


def test_unfixed_critical_blocks_and_duplicate_packages_are_collapsed():
    vulnerability = {
        "VulnerabilityID": "CVE-TEST",
        "PkgName": "example",
        "Severity": "CRITICAL",
        "InstalledVersion": "1",
        "FixedVersion": "",
    }
    text, blocked = reporter.summarize(
        {
            "SchemaVersion": 2,
            "Results": [{"Vulnerabilities": [vulnerability]}, {"Vulnerabilities": [vulnerability]}],
        }
    )
    assert blocked
    assert text.count("CVE-TEST") == 1
    assert "No fix reported" in text


def test_completed_scan_without_high_findings():
    text, blocked = reporter.summarize({"SchemaVersion": 2, "Results": []})
    assert not blocked
    assert "completed scan" in text
