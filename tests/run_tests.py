#!/usr/bin/env python3
"""
GigaMind RAG Edge-Case Test Runner
Executes `tests/test_deployed_rag_edgecases.sh` against deployed engine or local fallback.
"""
import os
import sys
import subprocess

def run_suite():
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    bash_script = os.path.join(tests_dir, "test_deployed_rag_edgecases.sh")

    if not os.path.exists(bash_script):
        print(f"❌ Error: Script not found at {bash_script}")
        sys.exit(1)

    os.chmod(bash_script, 0o755)

    env = os.environ.copy()
    env["DEPLOYED_URL"] = env.get("DEPLOYED_URL", "http://localhost:8000")
    env["LOCAL_URL"] = env.get("LOCAL_URL", "http://localhost:8000")

    print(f"🚀 Launching GigaMind Edge-Case Test Suite...")
    print(f"Target URL: {env['DEPLOYED_URL']}\n")

    res = subprocess.run([bash_script], env=env)
    sys.exit(res.returncode)

if __name__ == "__main__":
    run_suite()
