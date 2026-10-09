import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from app.models.candidate import CandidateProfile
from app.models.skills import SkillEvidence, SkillsDocument, VerifiedSkill
from app.services.fact_catalog import FactCatalog


class SkillsConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class SkillsStatus:
    source: str
    bank_kind: str
    valid: bool
    total: int
    verified: int
    learning: int

    def public(self) -> dict[str, str | bool | int]:
        return self.__dict__.copy()


def _normal(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()
    return " ".join(re.findall(r"[a-z0-9+#]+", value))


class SkillsBank:
    """Private, deterministic trust boundary for CV skills and their evidence."""

    def __init__(self, path: Path, profile: CandidateProfile, profile_mode: str = "production"):
        self.path = path
        self.profile = profile
        self.catalog = FactCatalog(profile)
        self.profile_mode = profile_mode
        self.document = self._load()
        self._validate_evidence()
        self.status = SkillsStatus(
            source=str(path),
            bank_kind="example" if path.name.endswith(".example.json") else "production",
            valid=True,
            total=len(self.document.skills),
            verified=sum(skill.verified for skill in self.document.skills),
            learning=sum(skill.level == "learning" for skill in self.document.skills),
        )
        if profile_mode == "production" and self.status.bank_kind != "production":
            raise SkillsConfigurationError("Production cannot use an example skills bank")

    def _load(self) -> SkillsDocument:
        if not self.path.exists():
            raise SkillsConfigurationError(
                f"Skills bank is missing at {self.path}. Create the private production skills.json first."
            )
        try:
            return SkillsDocument.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            raise SkillsConfigurationError(f"Skills bank at {self.path} is invalid") from exc

    def _validate_evidence(self) -> None:
        expected = {"employment": "experience", "project": "project", "education": "education"}
        for skill in self.document.skills:
            for evidence in skill.evidence:
                if evidence.source_type == "manual_verified":
                    continue
                entry = self.catalog.get(evidence.source_id)
                if not entry:
                    raise SkillsConfigurationError(f"Unknown evidence source for {skill.id}: {evidence.source_id}")
                required_kind = expected.get(evidence.source_type)
                if required_kind and entry.kind != required_kind:
                    raise SkillsConfigurationError(f"Wrong evidence type for {skill.id}: {evidence.source_id}")

    @property
    def skills(self) -> list[VerifiedSkill]:
        return self.document.skills

    def get(self, skill_id: str) -> VerifiedSkill | None:
        return next((skill for skill in self.skills if skill.id == skill_id), None)

    def eligible(self, skill: VerifiedSkill) -> bool:
        return skill.enabled and skill.verified and skill.allowed_in_cv and skill.level != "learning" and bool(skill.evidence)

    def aliases_for(self, skill: VerifiedSkill) -> list[str]:
        return list(dict.fromkeys([skill.name, *skill.aliases]))

    def find(self, value: str) -> VerifiedSkill | None:
        raw_key = _normal(value)
        for skill in self.skills:
            if raw_key == _normal(skill.name):
                return skill
        for skill in self.skills:
            if raw_key in {_normal(item) for item in skill.aliases}:
                return skill
            if skill.cv_wording and raw_key == _normal(skill.cv_wording):
                return skill

        stripped = value
        for prefix in ("Hands-on ", "Basic ", "Advanced ", "hands-on ", "basic ", "advanced "):
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix):]
                break
        stripped_key = _normal(stripped)
        if stripped_key != raw_key:
            for skill in self.skills:
                if stripped_key == _normal(skill.name):
                    return skill
            for skill in self.skills:
                if stripped_key in {_normal(item) for item in skill.aliases}:
                    return skill
                if skill.cv_wording and stripped_key == _normal(skill.cv_wording):
                    return skill
        return None

    def mentioned(self, skill: VerifiedSkill, text: str) -> bool:
        haystack = f" {_normal(text)} "
        return any(f" {_normal(alias)} " in haystack for alias in self.aliases_for(skill) if _normal(alias))

    def evidence_labels(self, skill: VerifiedSkill) -> list[str]:
        labels = []
        for evidence in skill.evidence:
            entry = self.catalog.get(evidence.source_id)
            label = entry.owner_name if entry and entry.owner_name else evidence.description
            if label and label not in labels:
                labels.append(label)
        return labels

    def wording(self, skill: VerifiedSkill) -> str:
        if skill.cv_wording:
            return skill.cv_wording
        if skill.level == "basic":
            return f"Basic {skill.name}"
        if skill.level == "hands_on":
            return f"Hands-on {skill.name}"
        if skill.level == "advanced":
            return f"Advanced {skill.name}"
        return skill.name

    def select_for_job(
        self, requested_ids: list[str], job_text: str, *, minimum: int = 8, maximum: int = 16
    ) -> list[VerifiedSkill]:
        requested = {value for value in requested_ids}
        eligible = [skill for skill in self.skills if self.eligible(skill)]
        normalized_job = _normal(job_text)
        category_terms = {
            "Windows / Microsoft": ("windows", "microsoft", "active directory", "desktop", "workstation"),
            "Automation / Scripting": ("automation", "scripting", "platform", "devops", "python", "powershell"),
            "Linux": ("linux", "unix", "platform", "devops", "server", "vps"),
            "Networking": ("network", "tcp", "dns", "dhcp", "vpn", "support", "platform"),
            "Virtualisation": ("virtual", "vmware", "hyper v", "proxmox", "platform", "infrastructure"),
            "Data / Databases": ("data", "database", "sql", "etl", "analytics"),
            "Support / Operations": ("support", "operations", "incident", "troubleshoot", "service desk"),
            "Tools": ("tools", "jira", "salesforce", "docker", "devops", "platform"),
            "AI / ML": ("ai", "machine learning", "llm", "model", "ollama", "data", "python"),
        }

        generic_names = {
            "troubleshooting",
            "technical troubleshooting",
            "network troubleshooting",
            "windows troubleshooting",
            "technical documentation",
            "documentation",
            "runbooks",
            "operational runbooks",
            "incident handling",
            "tier 2 support",
            "tier 1 support",
            "user support",
            "customer support",
        }

        def technical_specificity(skill: VerifiedSkill) -> int:
            name_norm = skill.name.casefold()
            if name_norm in generic_names or skill.category == "Support / Operations":
                return 10
            spec_map = {
                "Linux": 55,
                "Automation / Scripting": 55,
                "Data / Databases": 50,
                "Windows / Microsoft": 45,
                "Virtualisation": 45,
                "Networking": 40,
                "Tools": 40,
                "AI / ML": 35,
            }
            return spec_map.get(skill.category, 25)

        def evidence_strength(skill: VerifiedSkill) -> int:
            score_val = 0
            for ev in skill.evidence:
                if ev.source_type == "employment":
                    score_val += 12
                elif ev.source_type == "project":
                    score_val += 10
                else:
                    score_val += 6
            level_score = {"advanced": 15, "hands_on": 10, "intermediate": 8, "basic": 4}.get(skill.level, 5)
            return score_val + level_score

        def score(skill: VerifiedSkill) -> tuple[int, int, str]:
            direct = self.mentioned(skill, job_text)
            category_score = 35 if any(term in normalized_job for term in category_terms.get(skill.category, ())) else 0
            relevance = (200 if skill.id in requested else 0) + (100 if direct else 0) + category_score
            spec = technical_specificity(skill)
            ev = evidence_strength(skill)
            prio = skill.priority * 3
            total = relevance + spec + ev + prio
            return (
                total,
                skill.priority,
                skill.name,
            )

        ranked = sorted(eligible, key=score, reverse=True)
        chosen: list[VerifiedSkill] = []
        ai_dev_count = 0
        for skill in ranked:
            relevant = skill.id in requested or self.mentioned(skill, job_text)
            if not relevant and len(chosen) >= minimum:
                continue
            if skill.subcategory == "AI-Assisted Development":
                if ai_dev_count >= 3:
                    continue
                ai_dev_count += 1
            chosen.append(skill)
            if len(chosen) >= maximum:
                break
        return chosen

    def for_prompt(self) -> list[dict]:
        return [
            {
                "id": skill.id,
                "name": skill.name,
                "category": skill.category,
                "subcategory": skill.subcategory,
                "level": skill.level,
                "verified": skill.verified,
                "allowed_in_cv": skill.allowed_in_cv,
                "enabled": skill.enabled,
                "aliases": skill.aliases,
                "evidence_count": len(skill.evidence),
            }
            for skill in self.skills
        ]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".skills-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(self.document.model_dump_json(indent=2))
                handle.write("\n")
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        self.__init__(self.path, self.profile, self.profile_mode)

    def add(self, skill: VerifiedSkill) -> None:
        self.document = SkillsDocument(skills=[*self.skills, skill])
        self._validate_evidence()
        self.save()

    def update(self, skill_id: str, replacement: VerifiedSkill) -> None:
        if not self.get(skill_id):
            raise KeyError(skill_id)
        self.document = SkillsDocument(skills=[replacement if skill.id == skill_id else skill for skill in self.skills])
        self._validate_evidence()
        self.save()

    def delete(self, skill_id: str) -> None:
        if not self.get(skill_id):
            raise KeyError(skill_id)
        self.document = SkillsDocument(skills=[skill for skill in self.skills if skill.id != skill_id])
        self.save()

    def toggle(self, skill_id: str) -> None:
        skill = self.get(skill_id)
        if not skill:
            raise KeyError(skill_id)
        self.update(skill_id, skill.model_copy(update={"enabled": not skill.enabled}))

    def add_evidence(self, skill_id: str, evidence: SkillEvidence) -> None:
        skill = self.get(skill_id)
        if not skill:
            raise KeyError(skill_id)
        self.update(skill_id, skill.model_copy(update={"evidence": [*skill.evidence, evidence]}))

    def remove_evidence(self, skill_id: str, index: int) -> None:
        skill = self.get(skill_id)
        if not skill or index < 0 or index >= len(skill.evidence):
            raise KeyError(skill_id)
        evidence = [item for position, item in enumerate(skill.evidence) if position != index]
        verified = skill.verified and bool(evidence)
        self.update(skill_id, skill.model_copy(update={"evidence": evidence, "verified": verified}))
