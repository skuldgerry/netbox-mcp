"""Summarize Trivy vulnerability results without treating missing scans as clean."""

import json
import os
import sys
from pathlib import Path


def summarize(report: dict) -> tuple[str, bool]:
    """Fail closed on invalid reports; retain unfixed high/critical findings."""
    if report.get("SchemaVersion") != 2 or not isinstance(report.get("Results"), list):
        raise ValueError("Missing or unsupported Trivy results; security coverage is unknown")
    findings = {}
    for result in report["Results"]:
        for vuln in result.get("Vulnerabilities") or []:
            if vuln.get("Severity") in {"HIGH", "CRITICAL"}:
                key = (vuln["VulnerabilityID"], vuln["PkgName"], vuln["InstalledVersion"])
                findings[key] = vuln
    lines = [
        "## Image security triage",
        "",
        "Scanner severity is a triage signal, not confirmation of exposure or exploitation.",
        "All HIGH/CRITICAL findings block this pilot pending remediation or explicit review.",
        "",
    ]
    if not findings:
        lines.append("No HIGH/CRITICAL vulnerabilities reported in this completed scan.")
    else:
        lines.extend(
            ["| Severity | Advisory | Package | Installed | Fixed |", "|---|---|---|---|---|"]
        )
        for vuln in sorted(findings.values(), key=lambda v: (v["Severity"], v["VulnerabilityID"])):
            values = [
                vuln["Severity"],
                vuln["VulnerabilityID"],
                vuln["PkgName"],
                vuln["InstalledVersion"],
                vuln.get("FixedVersion") or "No fix reported",
            ]
            # Untrusted scanner strings must not become Markdown structure or mentions.
            values = [
                str(v).replace("|", "\\|").replace("\n", " ").replace("@", "&#64;") for v in values
            ]
            lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n", bool(findings)


def main() -> int:
    try:
        report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        text, blocked = summarize(report)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        print(f"Security scan unavailable or invalid: {exc}", file=sys.stderr)
        return 2
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(text)
    print(text)
    return int(blocked)


if __name__ == "__main__":
    raise SystemExit(main())
