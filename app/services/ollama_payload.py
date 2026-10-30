"""Lossless wire encoding. Canonical facts and retrieval traces remain server-side."""

import json
from copy import deepcopy


def compact_generation(payload):
    result = deepcopy(payload)
    catalog = {json.dumps(e, sort_keys=True, ensure_ascii=False) for e in payload["source_catalog"]}
    grouped = {}
    for key, value in payload["candidate_facts"].items():
        if isinstance(value, list) and all(isinstance(e, dict) and "source_id" in e for e in value):
            remaining = [e for e in value if json.dumps(e, sort_keys=True, ensure_ascii=False) not in catalog]
            if remaining:
                grouped[key] = remaining
        else:
            grouped[key] = value
    result["candidate_facts"] = grouped
    result.pop("retrieval", None)
    # Eligibility and evidence are still verified by the server-side skills bank.
    # Preserve every candidate choice, its exact ID, wording and documented level.
    result["eligible_skills"] = [{k: v for k, v in s.items() if k != "evidence"} for s in payload["eligible_skills"]]
    summary = result["analysis_summary"]
    if summary.get("key_requirements") == [r["name"] for r in summary.get("requirements_with_evidence", [])]:
        summary.pop("key_requirements", None)
    if result.get("layout_constraints") == result.get("layout_guide"):
        result.pop("layout_constraints", None)
    if not result.get("reference_cvs_style_only"):
        result.pop("reference_cvs_style_only", None)
    assert result["source_catalog"] == payload["source_catalog"]
    assert result["analysis_summary"].get("requirements_with_evidence") == payload["analysis_summary"].get(
        "requirements_with_evidence"
    )
    assert result["analysis_summary"].get("role_competencies") == payload["analysis_summary"].get("role_competencies")
    assert [(s["id"], s.get("wording"), s.get("level")) for s in result["eligible_skills"]] == [
        (s["id"], s.get("wording"), s.get("level")) for s in payload["eligible_skills"]
    ]
    return result


ANALYSIS_LEGEND = "\nIn this wire format, evidence_owners rows use evidence_owner_fields; evidence strength codes resolve through evidence_strengths. These are exact aliases, never competence upgrades."


def compact_analysis(payload):
    result = deepcopy(payload)
    codes = {value: chr(65 + i) for i, value in enumerate(dict.fromkeys(v[-1] for v in payload["evidence"].values()))}
    result["evidence_strengths"] = {code: value for value, code in codes.items()}
    result["evidence"] = {fid: row[:-1] + [codes[row[-1]]] for fid, row in payload["evidence"].items()}
    result["evidence_owner_fields"] = ["name", "employment_index"]
    result["evidence_owners"] = {
        oid: [value["name"], value["employment_index"]] for oid, value in payload["evidence_owners"].items()
    }
    # This is a server-side assessment guard, not job text or candidate evidence.
    # Keep the explicit requires_assessment flag and all actual section hints.
    result["passages"] = [{k: v for k, v in p.items() if k != "context_only"} for p in payload["passages"]]
    assert {
        fid: row[:-1] + [result["evidence_strengths"][row[-1]]] for fid, row in result["evidence"].items()
    } == payload["evidence"]
    assert {
        oid: dict(zip(result["evidence_owner_fields"], row, strict=True))
        for oid, row in result["evidence_owners"].items()
    } == payload["evidence_owners"]
    assert result["employment_dates"] == payload["employment_dates"]
    assert result["passages"] == [{k: v for k, v in p.items() if k != "context_only"} for p in payload["passages"]]
    return result
