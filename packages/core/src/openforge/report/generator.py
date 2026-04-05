"""Report generation for OpenForge EDA flows."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openforge import __version__


def generate_report(
    project_dir: Path,
    output_dir: Path,
    format: str = "html",
    results: dict[str, Any] | None = None,
) -> Path:
    """Generate a report in the specified format.

    Returns the path to the generated report file.
    """
    results = results or _collect_results(project_dir)

    match format.lower():
        case "html":
            return _generate_html(output_dir, results)
        case "json":
            return _generate_json(output_dir, results)
        case "sarif":
            return _generate_sarif(output_dir, results)
        case "junit" | "xml":
            return _generate_junit(output_dir, results)
        case _:
            raise ValueError(f"Unknown report format: {format}")


def _collect_results(project_dir: Path) -> dict[str, Any]:
    """Collect results from .openforge/ directory."""
    results_dir = project_dir / ".openforge"
    results: dict[str, Any] = {
        "project": str(project_dir.name),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "openforge_version": __version__,
        "steps": {},
    }

    if results_dir.exists():
        for json_file in results_dir.glob("*.json"):
            try:
                step_data = json.loads(json_file.read_text())
                results["steps"][json_file.stem] = step_data
            except (json.JSONDecodeError, OSError):
                pass

    return results


def _generate_html(output_dir: Path, results: dict[str, Any]) -> Path:
    """Generate an HTML report."""
    output = output_dir / "report.html"

    steps_html = ""
    for step_name, step_data in results.get("steps", {}).items():
        status = step_data.get("status", "unknown")
        color = {"passed": "#9ece6a", "failed": "#f7768e", "skipped": "#e0af68"}.get(
            status, "#a9b1d6"
        )
        steps_html += f"""
        <div class="step">
            <span class="status" style="color:{color}">{status.upper()}</span>
            <span class="name">{step_name}</span>
            <span class="duration">{step_data.get('duration', '-')}s</span>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>OpenForge Report - {results['project']}</title>
    <style>
        body {{ font-family: 'Inter', sans-serif; background: #1e1e2e; color: #c0caf5; margin: 0; padding: 24px; }}
        h1 {{ color: #7aa2f7; border-bottom: 2px solid #3d3d5c; padding-bottom: 12px; }}
        .meta {{ color: #a9b1d6; font-size: 14px; margin-bottom: 24px; }}
        .step {{ display: flex; gap: 16px; padding: 8px 16px; border-bottom: 1px solid #2d2d3f; }}
        .status {{ font-weight: 700; width: 80px; }}
        .name {{ flex: 1; }}
        .duration {{ color: #a9b1d6; }}
        .summary {{ margin-top: 24px; padding: 16px; background: #2d2d3f; border-radius: 8px; }}
    </style>
</head>
<body>
    <h1>OpenForge EDA Report</h1>
    <div class="meta">
        Project: {results['project']} |
        Generated: {results['timestamp']} |
        OpenForge v{results['openforge_version']}
    </div>
    <h2>Flow Steps</h2>
    {steps_html or '<p style="color:#a9b1d6">No flow results collected yet. Run <code>openforge verify --all</code> first.</p>'}
    <div class="summary">
        <h3>Summary</h3>
        <p>Total steps: {len(results.get('steps', {}))}</p>
    </div>
</body>
</html>"""

    output.write_text(html)
    return output


def _generate_json(output_dir: Path, results: dict[str, Any]) -> Path:
    """Generate a JSON report."""
    output = output_dir / "report.json"
    output.write_text(json.dumps(results, indent=2))
    return output


def _generate_sarif(output_dir: Path, results: dict[str, Any]) -> Path:
    """Generate a SARIF report (Static Analysis Results Interchange Format)."""
    output = output_dir / "report.sarif"

    sarif: dict[str, Any] = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "OpenForge EDA",
                        "version": results.get("openforge_version", __version__),
                        "informationUri": "https://github.com/dyber-pqc/OpenForge",
                    }
                },
                "results": [],
            }
        ],
    }

    # Convert lint findings to SARIF results
    lint_data = results.get("steps", {}).get("lint", {})
    for finding in lint_data.get("findings", []):
        sarif["runs"][0]["results"].append({
            "ruleId": finding.get("rule", "unknown"),
            "message": {"text": finding.get("message", "")},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": finding.get("file", "")},
                        "region": {
                            "startLine": finding.get("line", 1),
                            "startColumn": finding.get("column", 1),
                        },
                    }
                }
            ],
            "level": "warning",
        })

    output.write_text(json.dumps(sarif, indent=2))
    return output


def _generate_junit(output_dir: Path, results: dict[str, Any]) -> Path:
    """Generate a JUnit XML report for CI integration."""
    output = output_dir / "report.xml"

    test_cases = ""
    failures = 0
    total = 0

    for step_name, step_data in results.get("steps", {}).items():
        total += 1
        status = step_data.get("status", "unknown")
        duration = step_data.get("duration", 0)

        if status == "failed":
            failures += 1
            errors_text = "\n".join(step_data.get("errors", []))
            test_cases += f"""
    <testcase name="{step_name}" time="{duration}">
        <failure message="{step_name} failed">{errors_text}</failure>
    </testcase>"""
        elif status == "skipped":
            test_cases += f"""
    <testcase name="{step_name}" time="{duration}">
        <skipped/>
    </testcase>"""
        else:
            test_cases += f"""
    <testcase name="{step_name}" time="{duration}"/>"""

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="openforge" tests="{total}" failures="{failures}" timestamp="{results.get('timestamp', '')}">
    {test_cases}
  </testsuite>
</testsuites>"""

    output.write_text(xml)
    return output
