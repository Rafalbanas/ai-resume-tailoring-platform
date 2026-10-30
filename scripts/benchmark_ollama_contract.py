"""Read-only full-pipeline benchmark. Outputs PRIVATE CV data under /tmp only.

Run with the application's test dependencies and a verified tokenizer file:
python scripts/benchmark_ollama_contract.py --job-dir /path/to/existing/job \
  --tokenizer /path/to/tokenizer.json --model qwen3.5:9b
Never writes history, profiles, bank files, deployment settings or model files.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from jsonschema import Draft202012Validator

from app.core.config import Settings
from app.models.job import JobRequest
from app.services.analysis_validator import AnalysisValidator
from app.services.comparison_capture import capture_comparison
from app.services.docx_generator import generate_docx
from app.services.fact_validator import FactValidator
from app.services.ollama_provider import OllamaProvider
from app.services.pdf_generator import PDFGenerator
from app.services.processing import encoded, process
from app.services.profile_loader import load_master_profile
from app.services.reference_cvs import ReferenceCVLibrary
from app.services.skills_bank import SkillsBank
from app.services.summary_confirmation import summary_review


async def benchmark(args):
    settings = Settings()
    settings.ollama_model = args.model
    settings.ollama_num_ctx = args.context
    settings.ollama_tokenizer_path = args.tokenizer
    profile, _ = load_master_profile(settings)
    job = JobRequest.model_validate_json((args.job_dir / "job.json").read_text())
    bank = SkillsBank(settings.data_dir / "skills.json", profile, settings.profile_mode)
    output = Path(tempfile.mkdtemp(prefix="cvtailor-contract-"))
    output.chmod(0o700)
    result = dict(model=args.model, context=args.context, output=str(output), stages={}, calls=[])
    result["profile_sha256"] = hashlib.sha256(profile.model_dump_json().encode()).hexdigest()
    result["job_sha256"] = hashlib.sha256(job.model_dump_json().encode()).hexdigest()
    for key, expected in [("profile_sha256", args.profile_sha256), ("job_sha256", args.job_sha256)]:
        if expected and result[key] != expected:
            raise RuntimeError(f"{key} changed; comparison refused")

    class Observe(httpx.AsyncHTTPTransport):
        async def handle_async_request(self, request):
            body = json.loads(request.content)
            start = time.monotonic()
            response = await super().handle_async_request(request)
            envelope = json.loads(await response.aread())
            raw = envelope.get("message", {}).get("content", "")
            errors = list(Draft202012Validator(body["format"]).iter_errors(json.loads(raw))) if raw else []
            result["calls"].append(
                dict(
                    stage=json.loads(body["messages"][1]["content"]).get("stage"),
                    seconds=time.monotonic() - start,
                    input_tokens=envelope.get("prompt_eval_count"),
                    output_tokens=envelope.get("eval_count"),
                    load_seconds=(envelope.get("load_duration") or 0) / 1e9,
                    schema_errors=[e.message for e in errors],
                    request=body,
                    response=envelope,
                )
            )
            if errors:
                raise RuntimeError("Raw model output violates the transmitted JSON schema")
            return response

    provider = OllamaProvider(
        settings,
        transport=Observe(),
        skills_bank=bank,
        reference_library=ReferenceCVLibrary(settings.data_dir / "reference_cvs"),
    )
    start = time.monotonic()

    async def stage(name, operation):
        tick = time.monotonic()
        try:
            return await operation()
        finally:
            result["stages"][name] = time.monotonic() - tick

    with capture_comparison() as captures:
        try:
            analysis = await stage("analysis", lambda: provider.analyze_job(job, profile))
            analysis = AnalysisValidator(profile, bank).validate(analysis, f"{job.role}\n{job.job_description}")
            if not analysis.is_reliable:
                raise RuntimeError("Analysis rejected on independent revalidation")
            resume = await stage("generation_and_review", lambda: provider.tailor_resume(job, profile, analysis))
            result["analysis"] = analysis.model_dump(mode="json")
            result["raw_resume"] = resume.model_dump(mode="json")
            tick = time.monotonic()
            validated = FactValidator(profile, bank, analysis, review_key=provider.summary_review_key).validate(
                resume, job
            )
            result["stages"]["truth_lock"] = time.monotonic() - tick
            result["truth_lock_warnings"] = validated.warnings
            result["final_resume"] = validated.resume.model_dump(mode="json")
            gate = summary_review(validated.resume, profile, provider.summary_review_key, "isolated-benchmark")
            result["summary_confirmation_required"] = gate["required"]
            if gate["required"]:
                raise RuntimeError(
                    "Interactive summary confirmation required; benchmark will not approve on the user's behalf"
                )
            root = Path(__file__).resolve().parents[1]
            tick = time.monotonic()
            PDFGenerator(root / "templates", root / "static", settings.data_dir).generate(
                validated.resume, profile, output / "resume.pdf", {}, template_name="ats_classic", photo_enabled=False
            )
            result["stages"]["pdf"] = time.monotonic() - tick
            tick = time.monotonic()
            generate_docx(
                validated.resume, profile, output / "resume.docx", template_name="ats_classic", photo_enabled=False
            )
            result["stages"]["docx"] = time.monotonic() - tick
            for name, magic in [("resume.pdf", b"%PDF"), ("resume.docx", b"PK")]:
                data = (output / name).read_bytes()
                assert data.startswith(magic)
                result.setdefault("export_text", {})[name] = process(
                    "reference", {"suffix": Path(name).suffix, "content": encoded(data)}
                )
            result["ok"] = True
        except Exception as exc:
            result.update(ok=False, error=str(exc), error_type=type(exc).__name__)
        result["captures"] = captures
    result["wall_seconds"] = time.monotonic() - start
    result["metrics"] = provider.call_metrics
    (output / "private-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        json.dumps({k: result.get(k) for k in ["ok", "error", "output", "model", "wall_seconds"]}, ensure_ascii=False)
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", type=Path, required=True)
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--model", default="qwen3.5:9b")
    parser.add_argument("--context", type=int, default=16384)
    parser.add_argument("--profile-sha256")
    parser.add_argument("--job-sha256")
    raise SystemExit(asyncio.run(benchmark(parser.parse_args())))
