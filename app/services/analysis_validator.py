import re
from copy import deepcopy

from app.models.candidate import CandidateProfile
from app.models.job import (
    JobAnalysis,
    JobRequirement,
    MatchLevel,
    Recommendation,
    RequirementPriority,
    RequirementStatus,
)
from app.services.fact_catalog import FactCatalog
from app.services.skills_bank import SkillsBank


def _append_unique(values: list[str], value: str) -> None:
    if value.casefold() not in {item.casefold() for item in values}:
        values.append(value)


def is_internal_identifier(
    val: str,
    catalog: FactCatalog | None = None,
    skills_bank: SkillsBank | None = None,
) -> bool:
    """Detect raw internal IDs from FactCatalog or SkillsBank."""
    v = val.strip().lower()
    prefixes = (
        "skill:",
        "summary:",
        "experience:",
        "education:",
        "project:",
        "interest:",
        "certification:",
        "skill_",
    )
    if any(v.startswith(p) for p in prefixes):
        return True
    if re.match(r"^[a-f0-9]{10,64}$", v):
        return True
    if catalog and v in catalog.entries:
        return True
    if skills_bank and skills_bank.get(val.strip()):
        return True
    return False


def is_grounded_in_job(text: str, job_text: str) -> bool:
    """Check if requirement has textual or conceptual grounding in the job description."""
    if not job_text.strip():
        return True
    jt = job_text.casefold()
    t = text.strip().casefold()
    if t in jt:
        return True

    from app.services.fact_catalog import STOP_WORDS

    stop = set(STOP_WORDS) | {
        "experience",
        "knowledge",
        "ability",
        "skills",
        "skill",
        "required",
        "preferred",
        "must",
        "have",
        "candidate",
        "understanding",
        "work",
        "team",
        "environment",
        "tools",
        "years",
        "plus",
        "such",
        "including",
        "good",
        "strong",
        "proficient",
        "proficiency",
        "essential",
        "demonstrated",
        "degree",
        "diploma",
        "standards",
        "profile",
        "systems",
        "system",
    }

    words = [w for w in re.findall(r"[a-z0-9+#.]+", t) if len(w) > 2 and w not in stop]
    if not words:
        return True
    return any(re.search(r"\b" + re.escape(w) + r"\b", jt) for w in words)


def extract_source_quote(claim: str, job_text: str) -> str:
    """Find the best matching sentence or fragment from the job description for a claim."""
    if not job_text.strip():
        return ""
    # Split job_text into lines/sentences
    lines = [line.strip() for line in re.split(r"[\r\n]+", job_text) if len(line.strip()) > 10]
    claim_words = [w for w in re.findall(r"[a-z0-9+#.]+", claim.casefold()) if len(w) > 2]
    if not claim_words:
        return ""

    best_line = ""
    best_overlap = 0
    for line in lines:
        line_cf = line.casefold()
        overlap = sum(1 for w in claim_words if w in line_cf)
        if overlap > best_overlap:
            best_overlap = overlap
            best_line = line

    if best_overlap >= 1:
        return best_line[:200]
    return ""


def detect_priority(claim: str, quote: str, job_text: str) -> RequirementPriority:
    """Detect whether requirement is mandatory or preferred."""
    text_to_check = f"{claim} {quote}".casefold()
    preferred_markers = (
        "preference will be given",
        "preferred",
        "preference",
        "nice to have",
        "considered an asset",
        "plus",
        "optional",
    )
    if any(m in text_to_check for m in preferred_markers):
        return RequirementPriority.PREFERRED

    # Also check if quote occurs in a preferred section of job_text
    if quote and job_text:
        idx = job_text.find(quote)
        if idx != -1:
            preceding_text = job_text[max(0, idx - 500) : idx].casefold()
            if any(m in preceding_text for m in preferred_markers):
                return RequirementPriority.PREFERRED

    return RequirementPriority.MANDATORY


class AnalysisValidator:
    """Makes match classifications provable against the active master profile."""

    def __init__(self, profile: CandidateProfile, skills_bank: SkillsBank | None = None):
        self.catalog = FactCatalog(profile)
        self.skills_bank = skills_bank

    def _is_candidate_only_fact(self, claim: str, job_text: str) -> bool:
        """Check if claim is an unused candidate interest, thesis, or project not in job."""
        claim_cf = claim.casefold().strip()
        jt = job_text.casefold()
        for interest in self.catalog.profile.interests:
            name_cf = interest.name.casefold()
            id_cf = interest.id.casefold()
            if (name_cf in claim_cf or id_cf in claim_cf) and name_cf not in jt:
                return True
        for edu in self.catalog.profile.education:
            thesis = getattr(edu, "thesis_title", None)
            if thesis and thesis.casefold() in claim_cf and thesis.casefold() not in jt:
                return True
        return False

    def _matches_cs_education(self, claim: str) -> tuple[bool, str, list[str]]:
        """Verify if degree requirement is satisfied by candidate's MSc in Computer Science."""
        claim_cf = claim.casefold()
        cs_terms = ("computer science", "informatyk")
        deg_terms = (
            "degree",
            "diploma",
            "wykształcenie",
            "bachelor",
            "master",
            "msc",
            "bsc",
            "inżynier",
            "magister",
            "studia",
        )
        if any(c in claim_cf for c in cs_terms) and (any(d in claim_cf for d in deg_terms) or "education" in claim_cf):
            for edu in self.catalog.profile.education:
                edu_str = f"{edu.qualification} {getattr(edu, 'degree', '')} {getattr(edu, 'specialisation', '')}".casefold()
                if any(term in edu_str for term in ("computer science", "informatyk")):
                    src_ids = [
                        e.source_id
                        for e in self.catalog.entries.values()
                        if e.kind == "education" and "computer science" in e.text.casefold()
                    ]
                    return True, f"{edu.qualification} — {edu.institution}", src_ids
        return False, "", []

    def _matches_crm(self, claim: str) -> tuple[bool, str, list[str]]:
        """Verify if CRM requirement is satisfied by candidate's Salesforce experience."""
        claim_cf = claim.casefold()
        words = re.findall(r"\b[a-z0-9]+\b", claim_cf)
        if "crm" in words:
            sf_entries = [e.source_id for e in self.catalog.entries.values() if "salesforce" in e.text.casefold()]
            if sf_entries or (
                self.skills_bank and any("salesforce" in s.name.casefold() for s in self.skills_bank.skills)
            ):
                return True, "Salesforce CRM", sf_entries
        return False, "", []

    def _matches_or_alternatives(self, claim: str) -> tuple[bool, str, list[str]]:
        """Verify if a requirement with OR alternatives is satisfied by any confirmed branch."""
        claim_cf = claim.casefold()
        if " or " not in claim_cf and "/" not in claim_cf:
            return False, "", []

        parts = [p.strip() for p in re.split(r",?\s+or\s+|/|,\s*", claim) if len(p.strip()) > 2]
        matched_labels = []
        all_ids = []

        for part in parts:
            p_cf = part.casefold()
            direct = self.catalog.direct_sources(part)
            if direct:
                matched_labels.append(part)
                all_ids.extend(direct)
            elif self.skills_bank:
                sk = self.skills_bank.find(part)
                if sk and self.skills_bank.eligible(sk):
                    matched_labels.append(sk.name)
                    all_ids.append(f"skill_{sk.id}")
            if any(w in p_cf for w in ("telecommunication", "telekomunikac", "telecom")):
                entries = [
                    e.source_id
                    for e in self.catalog.entries.values()
                    if any(w in e.text.casefold() for w in ("telecom", "wave ptx"))
                ]
                if entries:
                    matched_labels.append(f"Telecommunications ({part})")
                    all_ids.extend(entries)
            if "linux" in p_cf:
                entries = [e.source_id for e in self.catalog.entries.values() if "linux" in e.text.casefold()]
                if entries:
                    matched_labels.append("Linux")
                    all_ids.extend(entries)
            if "windows" in p_cf:
                entries = [e.source_id for e in self.catalog.entries.values() if "windows" in e.text.casefold()]
                if entries:
                    matched_labels.append("Windows")
                    all_ids.extend(entries)

        if matched_labels:
            unique_labels = list(dict.fromkeys(matched_labels))
            unique_ids = list(dict.fromkeys(all_ids))
            return True, ", ".join(unique_labels), unique_ids

        return False, "", []

    def validate(self, candidate: JobAnalysis, job_text: str = "") -> JobAnalysis:
        if job_text.strip():
            from app.services.grounded_requirements import validate_grounded
            return validate_grounded(self, candidate, job_text)
        result = deepcopy(candidate)
        strong: list[str] = []
        partial: list[str] = []
        missing: list[str] = []
        sources: dict[str, list[str]] = {}
        evidence: dict[str, list[str]] = {}
        missing_reasons: dict[str, str] = {}

        # 1. Process skills_bank skills if present
        if self.skills_bank:
            classifications: dict[str, str] = {}
            claimed_skill_ids = result.strong_skill_ids + result.partial_skill_ids + result.learning_skill_ids
            for skill_id in claimed_skill_ids:
                skill = self.skills_bank.get(skill_id)
                if not skill or not skill.enabled:
                    continue
                if skill.level == "learning" or not skill.verified:
                    classifications[skill.name] = "learning"
                elif self.skills_bank.eligible(skill) and skill.level == "basic":
                    classifications[skill.name] = "partial"
                elif self.skills_bank.eligible(skill):
                    classifications[skill.name] = "strong"
                evidence[skill.name] = self.skills_bank.evidence_labels(skill)

            for skill in self.skills_bank.skills:
                if skill.name in classifications or not self.skills_bank.mentioned(skill, job_text):
                    continue
                if skill.level == "learning" or not skill.verified:
                    classifications[skill.name] = "learning"
                elif self.skills_bank.eligible(skill) and skill.level == "basic":
                    classifications[skill.name] = "partial"
                elif self.skills_bank.eligible(skill):
                    classifications[skill.name] = "strong"
                evidence[skill.name] = self.skills_bank.evidence_labels(skill)

            for claim in result.strong_matches + result.partial_matches + result.missing_requirements:
                if is_internal_identifier(claim, self.catalog, self.skills_bank):
                    continue
                skill = self.skills_bank.find(claim)
                if not skill or skill.name in classifications:
                    continue
                if skill.level == "learning" or not skill.verified:
                    classifications[skill.name] = "learning"
                elif self.skills_bank.eligible(skill) and skill.level == "basic":
                    classifications[skill.name] = "partial"
                elif self.skills_bank.eligible(skill):
                    classifications[skill.name] = "strong"
                evidence[skill.name] = self.skills_bank.evidence_labels(skill)

            for name, classification in classifications.items():
                if classification == "strong":
                    _append_unique(strong, name)
                elif classification == "partial":
                    _append_unique(partial, name)
                else:
                    _append_unique(result.learning_matches, name)
                    _append_unique(missing, f"{name} (Learning)")
                    missing_reasons[f"{name} (Learning)"] = "Learning (not confirmed as professional experience)"

        # 2. Process strong matches
        for claim in result.strong_matches:
            if is_internal_identifier(claim, self.catalog, self.skills_bank):
                continue
            if self._is_candidate_only_fact(claim, job_text):
                continue
            if self.skills_bank and (self.skills_bank.find(claim) or self.skills_bank.get(claim)):
                continue

            # Check domain rules
            deg_match, deg_label, deg_ids = self._matches_cs_education(claim)
            if deg_match:
                _append_unique(strong, claim)
                sources[claim] = deg_ids
                evidence[claim] = [deg_label]
                continue

            crm_match, crm_label, crm_ids = self._matches_crm(claim)
            if crm_match:
                _append_unique(strong, claim)
                sources[claim] = crm_ids
                evidence[claim] = [crm_label]
                continue

            or_match, or_branch, or_ids = self._matches_or_alternatives(claim)
            if or_match:
                _append_unique(strong, claim)
                sources[claim] = or_ids
                evidence[claim] = [f"Confirmed alternative: {or_branch}"]
                continue

            claimed_ids = result.match_sources.get(claim, [])
            direct_ids = self.catalog.direct_sources(claim)
            valid_ids = [entry.source_id for entry in self.catalog.valid(claimed_ids)]
            supporting_ids = direct_ids or (valid_ids if self.catalog.supports(claim, valid_ids) else [])
            if supporting_ids:
                _append_unique(strong, claim)
                sources[claim] = supporting_ids
            elif valid_ids and self.catalog.related(claim, valid_ids):
                _append_unique(partial, claim)
                sources[claim] = valid_ids
            else:
                if not (job_text and not is_grounded_in_job(claim, job_text)):
                    _append_unique(missing, claim)
                    missing_reasons[claim] = "Not confirmed in profile"

        # 3. Process partial matches
        for claim in result.partial_matches:
            if is_internal_identifier(claim, self.catalog, self.skills_bank):
                continue
            if self._is_candidate_only_fact(claim, job_text):
                continue
            if self.skills_bank and (self.skills_bank.find(claim) or self.skills_bank.get(claim)):
                continue

            deg_match, deg_label, deg_ids = self._matches_cs_education(claim)
            if deg_match:
                _append_unique(strong, claim)
                sources[claim] = deg_ids
                evidence[claim] = [deg_label]
                continue

            crm_match, crm_label, crm_ids = self._matches_crm(claim)
            if crm_match:
                _append_unique(strong, claim)
                sources[claim] = crm_ids
                evidence[claim] = [crm_label]
                continue

            or_match, or_branch, or_ids = self._matches_or_alternatives(claim)
            if or_match:
                _append_unique(strong, claim)
                sources[claim] = or_ids
                evidence[claim] = [f"Confirmed alternative: {or_branch}"]
                continue

            direct_ids = self.catalog.direct_sources(claim)
            claimed_ids = [entry.source_id for entry in self.catalog.valid(result.match_sources.get(claim, []))]
            if direct_ids:
                _append_unique(strong, claim)
                sources[claim] = direct_ids
            elif claimed_ids and self.catalog.related(claim, claimed_ids):
                _append_unique(partial, claim)
                sources[claim] = claimed_ids
            else:
                if not (job_text and not is_grounded_in_job(claim, job_text)):
                    _append_unique(missing, claim)
                    missing_reasons[claim] = "Not confirmed in profile"

        # 4. Process missing requirements
        for claim in result.missing_requirements:
            if is_internal_identifier(claim, self.catalog, self.skills_bank):
                continue
            if self._is_candidate_only_fact(claim, job_text):
                continue
            if job_text and not is_grounded_in_job(claim, job_text):
                continue
            if self.skills_bank and (self.skills_bank.find(claim) or self.skills_bank.get(claim)):
                continue

            # Check if mistakenly marked missing but actually satisfied
            deg_match, deg_label, deg_ids = self._matches_cs_education(claim)
            if deg_match:
                _append_unique(strong, claim)
                sources[claim] = deg_ids
                evidence[claim] = [deg_label]
                continue

            crm_match, crm_label, crm_ids = self._matches_crm(claim)
            if crm_match:
                _append_unique(strong, claim)
                sources[claim] = crm_ids
                evidence[claim] = [crm_label]
                # If claim also mentioned KCS, keep KCS separately in missing
                if "kcs" in claim.casefold():
                    kcs_req = "KCS (Knowledge Centered Service methodology)"
                    _append_unique(missing, kcs_req)
                    missing_reasons[kcs_req] = "Not confirmed in profile"
                continue

            or_match, or_branch, or_ids = self._matches_or_alternatives(claim)
            if or_match:
                _append_unique(strong, claim)
                sources[claim] = or_ids
                evidence[claim] = [f"Confirmed alternative: {or_branch}"]
                continue

            direct_ids = self.catalog.direct_sources(claim)
            if direct_ids:
                _append_unique(strong, claim)
                sources[claim] = direct_ids
            else:
                _append_unique(missing, claim)
                missing_reasons[claim] = "Not confirmed in profile"

        result.strong_matches = strong
        result.partial_matches = partial
        # Ensure missing items never contain strong or partial matches
        matched_set = {item.casefold() for item in strong + partial}
        result.missing_requirements = [
            value for value in missing if value.casefold() not in matched_set
        ]
        result.match_sources = sources
        result.match_evidence = evidence

        # Supported keywords
        supported_keywords = []
        unsupported_keywords = []
        for keyword in result.supported_keywords:
            if is_internal_identifier(keyword, self.catalog, self.skills_bank):
                continue
            if self.catalog.direct_sources(keyword):
                _append_unique(supported_keywords, keyword)
            else:
                _append_unique(unsupported_keywords, keyword)
        for keyword in result.unsupported_keywords:
            if is_internal_identifier(keyword, self.catalog, self.skills_bank):
                continue
            if self.catalog.direct_sources(keyword):
                _append_unique(supported_keywords, keyword)
            else:
                _append_unique(unsupported_keywords, keyword)
        result.supported_keywords = supported_keywords
        result.unsupported_keywords = unsupported_keywords

        # Build structured JobRequirement objects
        requirements_list: list[JobRequirement] = []
        req_counter = 1

        for item in result.strong_matches:
            quote = extract_source_quote(item, job_text)
            prio = detect_priority(item, quote, job_text)
            ev = evidence.get(item, [])
            requirements_list.append(
                JobRequirement(
                    id=f"req_{req_counter}",
                    name=item,
                    source_quote=quote,
                    priority=prio,
                    status=RequirementStatus.STRONG,
                    evidence=ev,
                    reason="Potwierdzone dowodami z profilu kandydata",
                )
            )
            req_counter += 1

        for item in result.partial_matches:
            quote = extract_source_quote(item, job_text)
            prio = detect_priority(item, quote, job_text)
            ev = evidence.get(item, [])
            requirements_list.append(
                JobRequirement(
                    id=f"req_{req_counter}",
                    name=item,
                    source_quote=quote,
                    priority=prio,
                    status=RequirementStatus.PARTIAL,
                    evidence=ev,
                    reason="Partially supported by transferable skills",
                )
            )
            req_counter += 1

        for item in result.missing_requirements:
            quote = extract_source_quote(item, job_text)
            prio = detect_priority(item, quote, job_text)
            reason = missing_reasons.get(item, "Not confirmed in profile")
            requirements_list.append(
                JobRequirement(
                    id=f"req_{req_counter}",
                    name=item,
                    source_quote=quote,
                    priority=prio,
                    status=RequirementStatus.MISSING,
                    evidence=[],
                    reason=reason,
                )
            )
            req_counter += 1

        result.requirements = requirements_list

        # Scoring & Reliability calculation
        total = len(strong) + len(partial) + len(result.missing_requirements)

        # Detect corrupted/unreliable analysis
        if total == 0:
            result.is_reliable = False
            result.match_level = MatchLevel.UNRELIABLE
            result.recommendation = Recommendation.RETRY
            result.reasoning_summary = (
                "Incomplete analysis — review required — review required. "
                "Could not reliably extract requirements from the job description."
            )
            return result

        result.is_reliable = True
        score = (len(strong) + 0.5 * len(partial)) / max(1, total)

        if score >= 0.7:
            result.match_level = MatchLevel.HIGH
            result.recommendation = Recommendation.APPLY
        elif score >= 0.4:
            result.match_level = MatchLevel.MEDIUM
            result.recommendation = Recommendation.REASONABLE_STRETCH
        else:
            result.match_level = MatchLevel.LOW
            result.recommendation = Recommendation.SKIP

        strong_text = ", ".join(strong[:6]) or "no directly confirmed requirements"
        partial_text = ", ".join(partial[:4]) or "no transferable requirements"
        missing_text = ", ".join(result.missing_requirements[:5]) or "no significant unconfirmed conditions"
        result.reasoning_summary = (
            f"Profile facts directly confirm: {strong_text}. "
            f"Partially confirmed: {partial_text}. "
            f"Requirements not confirmed in profile: {missing_text}."
        )[:600]
        # Legacy callers without the advertisement cannot verify source or priority.
        result.is_reliable = False
        result.match_level = MatchLevel.UNRELIABLE
        result.recommendation = Recommendation.RETRY
        result.reasoning_summary = "Job description missing: requirements and priorities need source review."
        return result
