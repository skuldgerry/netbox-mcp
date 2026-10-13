"""Check the permissions and scheduled paths used by the coverage reporter."""

from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def workflow(name):
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    # PyYAML's YAML 1.1 parser treats GitHub's YAML 1.2 `on` key as True.
    if True in data:
        data["on"] = data.pop(True)
    return data


def test_alert_reads_use_separate_least_privilege_scopes():
    maintenance = workflow("maintenance.yml")
    tracker = workflow("maintenance-tracker.yml")
    probe = maintenance["jobs"]["tracker-probe"]["permissions"]
    for permissions in (probe, tracker["permissions"]):
        assert permissions["vulnerability-alerts"] == "read"
        assert permissions["security-events"] == "read"
    assert probe["issues"] == "read"
    assert maintenance["permissions"] == {"contents": "read"}
    assert "vulnerability-alerts" not in workflow("codeql.yml")["jobs"]["analyze"]["permissions"]


def test_schedules_and_published_scan_are_preserved():
    maintenance = workflow("maintenance.yml")
    assert maintenance["on"]["schedule"] == [{"cron": "23 6 * * *"}]
    assert workflow("codeql.yml")["on"]["schedule"] == [{"cron": "43 6 * * 1"}]
    assert workflow("maintenance-tracker.yml")["on"]["schedule"] == [{"cron": "53 8 * * *"}]
    assert maintenance["jobs"]["published"]["if"] == (
        "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'"
    )


def test_write_enabled_tracker_checks_out_only_the_default_branch():
    tracker = workflow("maintenance-tracker.yml")
    checkout = tracker["jobs"]["dashboard"]["steps"][0]
    assert checkout["with"]["ref"] == "${{ github.event.repository.default_branch }}"
    assert checkout["with"]["persist-credentials"] is False
