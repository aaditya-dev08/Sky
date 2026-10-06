import json
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging
import xml.etree.ElementTree as ET

from sky.tools.registry import register_tool, RiskTier

logger = logging.getLogger(__name__)

def _detect_test_framework(project_root: Path) -> Optional[str]:
    """Detect the testing framework used in the project."""
    # Check for pytest
    if (project_root / "pytest.ini").exists():
        return "pytest"
    if (project_root / "pyproject.toml").exists():
        content = (project_root / "pyproject.toml").read_text()
        if "[tool.pytest]" in content:
            return "pytest"
    if (project_root / "setup.cfg").exists():
        content = (project_root / "setup.cfg").read_text()
        if "[tool:pytest]" in content:
            return "pytest"
    
    # Check for pytest or unittest in tests/
    tests_dir = project_root / "tests"
    if tests_dir.exists() and tests_dir.is_dir():
        for file in tests_dir.glob("test_*.py"):
            content = file.read_text()
            if "pytest" in content:
                return "pytest"
            if "unittest" in content:
                return "unittest"
        return "unittest" # Default if tests/test_*.py exist but no specific imports

    # Check for npm
    if (project_root / "package.json").exists():
        content = json.loads((project_root / "package.json").read_text())
        if "test" in content.get("scripts", {}):
            return "npm"
            
    # Check for cargo
    if (project_root / "Cargo.toml").exists():
        return "cargo"
        
    # Check for go
    if (project_root / "go.mod").exists():
        return "go"

    return None

def _detect_linter(project_root: Path) -> Optional[str]:
    """Detect the linter used in the project."""
    # Check for ruff
    if (project_root / "ruff.toml").exists():
        return "ruff"
    if (project_root / "pyproject.toml").exists():
        content = (project_root / "pyproject.toml").read_text()
        if "[tool.ruff]" in content:
            return "ruff"

    # Check for flake8
    if (project_root / ".flake8").exists():
        return "flake8"
    if (project_root / "setup.cfg").exists():
        content = (project_root / "setup.cfg").read_text()
        if "[flake8]" in content:
            return "flake8"
    if (project_root / "tox.ini").exists():
        content = (project_root / "tox.ini").read_text()
        if "[flake8]" in content:
            return "flake8"

    # Check for eslint
    if (project_root / "package.json").exists():
        content = json.loads((project_root / "package.json").read_text())
        if "eslint" in content.get("devDependencies", {}) or "eslint" in content.get("dependencies", {}):
            return "eslint"
    if any(project_root.glob(".eslintrc*")):
        return "eslint"

    return None

def _parse_junitxml(xml_path: Path) -> Dict[str, Any]:
    """Parse pytest JUnit output."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    
    testsuite = root if root.tag == "testsuite" else root.find("testsuite")
    if testsuite is None:
        return {"error": "Invalid JUnit XML format"}

    errors_list = []
    for testcase in testsuite.findall("testcase"):
        failure = testcase.find("failure")
        if failure is not None:
            errors_list.append(failure.text or failure.get("message", "Unknown error"))
        error = testcase.find("error")
        if error is not None:
            errors_list.append(error.text or error.get("message", "Unknown error"))

    return {
        "passed": int(testsuite.get("tests", 0)) - int(testsuite.get("failures", 0)) - int(testsuite.get("errors", 0)) - int(testsuite.get("skipped", 0)),
        "failed": int(testsuite.get("failures", 0)) + int(testsuite.get("errors", 0)),
        "skipped": int(testsuite.get("skipped", 0)),
        "total": int(testsuite.get("tests", 0)),
        "errors": errors_list
    }

def _parse_pytest_output(stdout: str) -> Dict[str, Any]:
    """Fallback parser if JUnitXML unavailable."""
    passed = 0
    failed = 0
    skipped = 0
    
    # Look for the summary line: e.g. "== 1 passed, 2 failed in 0.12s =="
    summary_match = re.search(r'==.*?(\d+)\s+passed.*?==', stdout)
    if summary_match:
        passed = int(summary_match.group(1))
        
    failed_match = re.search(r'==.*?(\d+)\s+failed.*?==', stdout)
    if failed_match:
        failed = int(failed_match.group(1))

    skipped_match = re.search(r'==.*?(\d+)\s+skipped.*?==', stdout)
    if skipped_match:
        skipped = int(skipped_match.group(1))

    return {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "total": passed + failed + skipped,
        "errors": [line for line in stdout.split('\n') if "FAILED" in line or "ERROR" in line]
    }

def _truncate(text: str, max_len: int = 2000) -> str:
    """Truncate long output."""
    if len(text) <= max_len:
        return text
    return text[:max_len//2] + "\n...[truncated]...\n" + text[-max_len//2:]

@register_tool(
    name="run_tests",
    description="Auto-detect and run the project's test suite, returning structured results",
    risk_tier=RiskTier.SAFE,
)
def run_tests(target: Optional[str] = None, timeout: int = 120) -> Dict[str, Any]:
    """Run tests and return structured results."""
    project_root = Path.cwd()
    framework = _detect_test_framework(project_root)
    
    if not framework:
        return {"framework": "none", "error": "No test framework detected", "success": False}

    target_str = target if target else ""
    start_time = time.time()
    result = {
        "framework": framework,
        "passed": 0,
        "failed": 0,
        "errors": [],
        "skipped": 0,
        "total": 0,
        "success": False,
        "duration_seconds": 0.0,
        "output": ""
    }

    try:
        if framework == "pytest":
            with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
                xml_path = tmp.name
            
            cmd = f"python -m pytest {target_str} --junitxml={xml_path} -q"
            process = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            
            if Path(xml_path).exists() and Path(xml_path).stat().st_size > 0:
                parsed = _parse_junitxml(Path(xml_path))
                if "error" not in parsed:
                    result.update(parsed)
                else:
                    parsed_fallback = _parse_pytest_output(process.stdout + process.stderr)
                    result.update(parsed_fallback)
            else:
                parsed_fallback = _parse_pytest_output(process.stdout + process.stderr)
                result.update(parsed_fallback)
                
            try:
                Path(xml_path).unlink(missing_ok=True)
            except Exception:
                pass
                
        elif framework == "unittest":
            cmd = f"python -m unittest discover {target_str}"
            process = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            out = process.stdout + process.stderr
            # Unittest output is hard to parse structure-wise simply, doing basic search
            runs = re.search(r'Ran (\d+) tests', out)
            if runs:
                result["total"] = int(runs.group(1))
            failures = re.search(r'failures=(\d+)', out)
            errors = re.search(r'errors=(\d+)', out)
            result["failed"] = (int(failures.group(1)) if failures else 0) + (int(errors.group(1)) if errors else 0)
            result["passed"] = result["total"] - result["failed"]
            
        elif framework == "npm":
            cmd = "npm test"
            process = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            
        elif framework == "cargo":
            cmd = "cargo test"
            process = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            
        elif framework == "go":
            cmd = "go test ./..."
            process = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            
        if framework in ("npm", "cargo", "go"):
            # Generic fallback for non-python frameworks since detailed parsing isn't specified
            result["success"] = process.returncode == 0
            
        result["output"] = _truncate(process.stdout + "\n" + process.stderr)
        result["success"] = process.returncode == 0
        
    except subprocess.TimeoutExpired as e:
        result["error"] = f"Command timed out after {timeout} seconds"
        if e.stdout:
            result["output"] = _truncate(e.stdout.decode(errors='replace'))
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Test run failed: {e}")

    result["duration_seconds"] = round(time.time() - start_time, 2)
    return result


@register_tool(
    name="lint",
    description="Run the project's linter and return structured issues",
    risk_tier=RiskTier.SAFE,
)
def lint(path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Run linter and return structured issues."""
    project_root = Path.cwd()
    linter = _detect_linter(project_root)
    
    if not linter:
        return []

    target_str = path if path else "."
    issues = []

    try:
        if linter == "ruff":
            cmd = f"ruff check {target_str} --output-format=json"
            process = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if process.stdout.strip():
                try:
                    data = json.loads(process.stdout)
                    for item in data:
                        issues.append({
                            "file": item.get("filename", ""),
                            "line": item.get("location", {}).get("row", 0),
                            "column": item.get("location", {}).get("column", 0),
                            "code": item.get("code", ""),
                            "message": item.get("message", ""),
                            "severity": "error"
                        })
                except json.JSONDecodeError:
                    pass
                    
        elif linter == "flake8":
            cmd = f"flake8 {target_str}"
            process = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            for line in process.stdout.splitlines():
                match = re.match(r'(.*?):(\d+):(\d+):\s+([A-Z0-9]+)\s+(.*)', line)
                if match:
                    issues.append({
                        "file": match.group(1),
                        "line": int(match.group(2)),
                        "column": int(match.group(3)),
                        "code": match.group(4),
                        "message": match.group(5),
                        "severity": "error"
                    })
                    
        elif linter == "eslint":
            cmd = f"npx eslint {target_str} --format=json"
            process = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if process.stdout.strip():
                try:
                    data = json.loads(process.stdout)
                    for file_item in data:
                        for msg in file_item.get("messages", []):
                            severity = "error" if msg.get("severity") == 2 else "warning"
                            issues.append({
                                "file": file_item.get("filePath", ""),
                                "line": msg.get("line", 0),
                                "column": msg.get("column", 0),
                                "code": msg.get("ruleId", ""),
                                "message": msg.get("message", ""),
                                "severity": severity
                            })
                except json.JSONDecodeError:
                    pass

    except Exception as e:
        logger.warning(f"Linter execution failed: {e}")
        
    return issues
