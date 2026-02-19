import json
import subprocess
import sys


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise SystemExit(f"FAILED: {' '.join(cmd)}")
    return result.stdout.strip()


def main():
    run([sys.executable, "-m", "app.cli", "ingest", "--input", "sample_docs"])

    in_scope = json.loads(
        run([sys.executable, "-m", "app.cli", "ask", "--question", "What is the main contribution?", "--top-k", "1"])
    )
    assert in_scope["citations"], "Expected citations for in-scope question"

    out_scope = json.loads(
        run([sys.executable, "-m", "app.cli", "ask", "--question", "What is the CEO phone number?", "--top-k", "1"])
    )
    assert out_scope["answer"] in {
        "I can't find this in the uploaded documents.",
        "I can't provide that, and I can't find this in the uploaded documents.",
    }, "Expected no-hallucination refusal"
    assert out_scope["citations"] == [], "Expected empty citations for out-of-scope"

    run([sys.executable, "-m", "app.cli", "sanity"])
    verify = run([sys.executable, "scripts/verify_output.py", "artifacts/sanity_output.json"])
    assert "VERIFY_OK" in verify, "Sanity output must pass schema verification"
    print("SMOKE_OK")


if __name__ == "__main__":
    main()
