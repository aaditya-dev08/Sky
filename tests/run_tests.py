import subprocess
import sys
import os
from pathlib import Path

def main():
    print("Starting Sky Comprehensive Test Suite...\n")
    
    # Ensure tests directory exists
    tests_dir = Path(__file__).parent
    
    # Ensure pytest is installed
    try:
        import pytest
    except ImportError:
        print("pytest is not installed. Installing required test packages...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pytest", "pytest-html"], check=True)
    
    # Log file
    log_file = tests_dir / "sky-test.log"
    html_report = tests_dir / "sky-test-report.html"
    
    # Run pytest
    print(f"Running tests in: {tests_dir / 'test_sky_complete.py'}")
    print(f"Generating HTML report at: {html_report}")
    
    cmd = [
        sys.executable, "-m", "pytest", 
        str(tests_dir / "test_sky_complete.py"),
        "-v",
        f"--html={html_report}",
        "--self-contained-html"
    ]
    
    # Capture output to log file and print to console
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("--- SKY COMPLETE TEST SUITE LOG ---\n\n")
        
    print("\n---------------------------------------------------------")
    
    # Run tests and tee output
    process = subprocess.Popen(
        cmd, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8"
    )
    
    passed = 0
    failed = 0
    
    with open(log_file, "a", encoding="utf-8") as log:
        if process.stdout is not None:
            for line in iter(process.stdout.readline, ''):
                # Print to stdout safely ignoring charmap errors
                try:
                    sys.stdout.write(line)
                except UnicodeEncodeError:
                    sys.stdout.write(line.encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding))
                    
                log.write(line)
                
                if "PASSED" in line:
                    passed += 1
                elif "FAILED" in line or "ERROR" in line:
                    failed += 1
                
    process.wait()
    
    print("\n---------------------------------------------------------")
    print("\n TEST SUMMARY:")
    if process.returncode == 0:
        print(f" All tests passed! ({passed} passed)")
        print(" Ready for v0.0.6 release")
    else:
        print(f" Tests failed. ({passed} passed, {failed} failed/errors)")
        
    print(f"\n Full log available at: {log_file}")
    print(f" HTML report available at: {html_report}")
    
    sys.exit(process.returncode)

if __name__ == "__main__":
    main()
