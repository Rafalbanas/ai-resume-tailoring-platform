"""Documented evidence strength, not inferred technology proficiency."""

import re

CI = re.compile(
    r"\b(?:ci/cd|continuous (?:integration|delivery|deployment)|github actions|gitlab ci|jenkins|build pipeline|ci pipeline)\b",
    re.I,
)
ARTIFACT = re.compile(
    r"\.github/workflows/|\bworkflow (?:file|definition|configuration)\b|\b(?:file|artifact|implementation) (?:exists|present)|\bci\.ya?ml\b",
    re.I,
)
EXECUTION = re.compile(
    r"\b(?:runs?|executes?|passed|passing|successful(?:ly)?)\b.{0,100}\b(?:tests?|lint|builds?|pipeline|workflow|deploy\w*)\b|\b(?:tests?|builds?|pipeline|workflow)\b.{0,80}\b(?:passed|passing|successful(?:ly)?|runs?)\b",
    re.I,
)
NEGATION = re.compile(
    r"\b(?:not|never|no|unverified|untested|planned|experimental|failed|failing|hasn.t|doesn.t)\b", re.I
)
USE = re.compile(r"\b(?:uses?|used|using|maintains?|implemented|configured|created|built|developed)\b", re.I)


def evidence_strength(entry):
    text = entry.text
    if CI.search(text) or ARTIFACT.search(text):
        if EXECUTION.search(text) and not NEGATION.search(text):
            return "operational_result"
        if ARTIFACT.search(text):
            return "implementation"
        if USE.search(text) and entry.kind != "skill":
            return "documented_use"
    if re.search(r"theoretical (?:knowledge|understanding)|(?:completed|attended|studied).*(?:training|course)|awareness of", text, re.I):
        return "theoretical_knowledge"
    if entry.kind == "skill" or ":technology:" in entry.source_id:
        return "declaration"
    return "documented_use"


def ci_ceiling(name, entries):
    if not CI.search(name):
        return None
    relevant = [e for e in entries if CI.search(e.text) or ARTIFACT.search(e.text)]
    if not relevant:
        return "missing", "No CI/CD evidence is cited; unrelated technology facts cannot establish pipeline experience."
    strengths = {evidence_strength(e) for e in relevant}
    needs_execution = bool(re.search(r"working|running|operat\w*|successful|deploy\w*|ci/cd|pipeline", name, re.I))
    if "operational_result" in strengths:
        return (
            "strong",
            "The cited facts explicitly attest pipeline execution; this is documented evidence, not an independent live verification.",
        )
    if not needs_execution and "documented_use" in strengths:
        return "strong", "Documented use supports familiarity; successful pipeline execution is not inferred."
    return (
        "partial",
        "Evidence establishes declared knowledge or an implementation artifact, not confirmed pipeline execution. A workflow file alone does not prove working CI/CD.",
    )
