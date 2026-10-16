"""Run inside the sample-profile lab pod; exercise authenticated HTTP and exports."""

import argparse
import io
import json
import os
import time
import zipfile
from html import unescape
from pathlib import Path

import httpx
from pypdf import PdfReader

ROOT = Path(os.environ.get("DATA_DIR", "/lab-data"))
DESCRIPTION = """Fictional laboratory vacancy: Application Support Engineer.
Responsibilities: automate repeatable support workflows with Python; maintain
operational documentation for containerized services; implement health checks
and structured event reporting for a service dashboard.
Mandatory requirements:
- Python scripting for support automation.
- Docker for containerized applications.
- Maintaining operational documentation.
Preferred requirements:
- FastAPI and REST APIs.
This vacancy is fictional and is used only for a Kubernetes integration test.
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["generate", "fail", "submit", "inspect", "retry", "artifacts"])
    parser.add_argument("label")
    parser.add_argument("--task-id")
    parser.add_argument("--provider", default="auto")
    parser.add_argument("--expected-provider")
    parser.add_argument("--fallback", choices=["true", "false"])
    args = parser.parse_args()
    assert os.environ.get("PROFILE_MODE") == "sample"
    profile = json.loads((ROOT / "master_profile.json").read_text())
    assert profile["personal"]["name"] == "Alex Example"
    evidence = ROOT / ".e2e"
    evidence.mkdir(exist_ok=True)
    record = {"test": args.label, "mode": args.mode}
    client = httpx.Client(base_url=os.environ.get("CVTAILOR_E2E_BASE_URL", "http://127.0.0.1:8000"), timeout=180, follow_redirects=False)

    def get(path):
        response = client.get(path)
        response.raise_for_status()
        return response

    def post(path, data):
        response = client.post(path, data={**data, "csrf_token": client.cookies["csrf_token"]}, headers={"Accept": "application/json"})
        assert response.status_code < 400, (response.status_code, response.text[:500])
        return response

    def wait(task_id):
        started = time.monotonic()
        last = None
        while time.monotonic() - started < 960:
            task = get("/tasks/" + task_id).json()
            marker = (task["status"], task["stage"], int((time.monotonic() - started) // 20))
            if marker != last:
                print(json.dumps({"task_id": task_id, "status": task["status"], "stage": task["stage"], "elapsed_seconds": round(time.monotonic()-started)}), flush=True)
                last = marker
            if task["status"] in {"completed", "failed"}:
                return task
            time.sleep(2)
        raise TimeoutError("Task did not reach a terminal state")

    try:
        get("/health")
        get("/login")
        response = post("/login", {"username": os.environ["APP_USERNAME"], "password": os.environ["APP_PASSWORD"]})
        assert response.status_code == 303
        get("/")
        if args.mode == "artifacts":
            entries = list((ROOT / "generated").glob("*/metadata.json"))
            record["generated_count"] = len(entries)
            for path in entries:
                slug = path.parent.name
                assert get(f"/download/{slug}/pdf").content.startswith(b"%PDF")
                assert zipfile.is_zipfile(io.BytesIO(get(f"/download/{slug}/docx").content))
            assert entries, "No restored exports to verify"
            record["result"] = "PASS"
            return
        if args.mode == "inspect":
            task = get("/tasks/" + args.task_id).json()
        else:
            if args.mode == "retry":
                submitted = post(f"/tasks/{args.task_id}/retry", {}).json()
            else:
                submitted = post("/analyze", {"company": "Kubernetes Fictional " + args.label, "role": "Application Support Engineer", "job_description": DESCRIPTION, "llm_provider": args.provider}).json()
            record["task_id"] = submitted["task_id"]
            print("SUBMITTED " + json.dumps(record), flush=True)
            if args.mode == "submit":
                record["result"] = "SUBMITTED"
                return
            task = wait(submitted["task_id"])
        record.update(task_id=task["task_id"], task_status=task["status"], error=task.get("error"), error_status_code=task.get("error_status_code"))
        if args.mode in {"fail", "inspect"}:
            assert task["status"] == "failed", task["status"]
            assert task.get("error"), "Missing user-facing error"
            page = get(f"/tasks/{task['task_id']}/view")
            assert page.status_code == 200
            assert task["error"] in unescape(page.text), "Error was not rendered in the task page"
            assert get("/health").json()["status"] == "ok"
            record["result"] = "PASS"
            return
        assert task["status"] == "completed", task.get("error")
        result = task["result"]
        record.update(provider=result["provider_used"], fallback_used=result["fallback_used"], draft_id=result["draft_id"])
        if args.expected_provider:
            assert result["provider_used"] == args.expected_provider, result
        if args.fallback:
            assert result["fallback_used"] == (args.fallback == "true"), result
        get(result["redirect_url"])
        response = post("/generate/" + result["draft_id"], {"template_name": "ats_classic"})
        assert response.status_code == 303
        slug = response.headers["location"].split("/preview/", 1)[1]
        get(response.headers["location"])
        pdf = get(f"/download/{slug}/pdf").content
        docx = get(f"/download/{slug}/docx").content
        assert pdf.startswith(b"%PDF")
        reader = PdfReader(io.BytesIO(pdf))
        assert len(reader.pages) >= 1
        assert "Alex Example" in " ".join(page.extract_text() for page in reader.pages)
        with zipfile.ZipFile(io.BytesIO(docx)) as archive:
            assert "Alex Example" in archive.read("word/document.xml").decode()
        metadata = json.loads((ROOT / "generated" / slug / "metadata.json").read_text())
        assert metadata["provider_used"] == result["provider_used"]
        record.update(result="PASS", slug=slug, pdf_bytes=len(pdf), docx_bytes=len(docx), pdf_pages=len(reader.pages))
    except Exception as error:
        record.update(result="FAIL", failure=str(error)[:1200])
        raise
    finally:
        (evidence / (args.label + ".json")).write_text(json.dumps(record, indent=2))
        print("RESULT " + json.dumps(record), flush=True)
        client.close()


if __name__ == "__main__":
    main()
