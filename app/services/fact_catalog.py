import hashlib
import re
import unicodedata
from dataclasses import dataclass

from app.models.candidate import CandidateProfile

STOP_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "for",
    "good",
    "in",
    "including",
    "of",
    "on",
    "or",
    "professional",
    "proficiency",
    "strong",
    "the",
    "to",
    "using",
    "with",
    "years",
}


def normalized_tokens(value: str) -> set[str]:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()
    replacements = {
        "bachelor's": "bachelor",
        "bachelors": "bachelor",
        "bsc": "bachelor",
        "master's": "master",
        "masters": "master",
        "msc": "master",
    }
    for source, target in replacements.items():
        ascii_value = ascii_value.replace(source, target)
    return {token for token in re.findall(r"[a-z0-9+#.]+", ascii_value) if len(token) > 1 and token not in STOP_WORDS}


def _digest(value: str) -> str:
    return hashlib.sha256(value.casefold().strip().encode()).hexdigest()[:12]


@dataclass(frozen=True)
class FactEntry:
    source_id: str
    kind: str
    text: str
    owner_index: int | None = None
    owner_name: str = ""


class FactCatalog:
    def __init__(self, profile: CandidateProfile):
        self.profile = profile
        self.entries: dict[str, FactEntry] = {}
        self.prompt_entries: list[FactEntry] = []
        self._build()

    def _add(self, entry: FactEntry, *legacy_ids: str) -> None:
        self.entries[entry.source_id] = entry
        self.prompt_entries.append(entry)
        for legacy_id in legacy_ids:
            self.entries[legacy_id] = entry

    def _build(self) -> None:
        for index, fact in enumerate(self.profile.summary_facts):
            self._add(FactEntry(f"summary:{_digest(fact)}", "summary", fact), f"summary:{index}")
        for values in self.profile.skills.values():
            for skill in values:
                self._add(FactEntry(f"skill:{_digest(skill)}", "skill", skill))
        for index, experience in enumerate(self.profile.experience):
            owner = _digest("|".join([experience.company, experience.title, experience.start, experience.end]))
            for fact_index, fact in enumerate(experience.facts):
                self._add(
                    FactEntry(
                        f"experience:{owner}:fact:{_digest(fact)}",
                        "experience",
                        fact,
                        index,
                        f"{experience.title} — {experience.company}",
                    ),
                    f"experience:{index}:fact:{fact_index}",
                )
        for index, education in enumerate(self.profile.education):
            owner = _digest("|".join([education.institution, education.qualification, education.dates]))
            main_text = " | ".join(filter(None, [education.qualification, education.institution, education.dates]))
            self._add(
                FactEntry(f"education:{owner}", "education", main_text, index, education.institution),
                f"education:{index}",
            )
            for fact_index, fact in enumerate(education.facts):
                self._add(
                    FactEntry(
                        f"education:{owner}:fact:{_digest(fact)}",
                        "education",
                        fact,
                        index,
                        education.institution,
                    ),
                    f"education:{index}:fact:{fact_index}",
                )
        for index, project in enumerate(self.profile.projects):
            owner = _digest(project.name)
            if project.description:
                self._add(
                    FactEntry(
                        f"project:{owner}:description:{_digest(project.description)}",
                        "project",
                        project.description,
                        index,
                        project.name,
                    ),
                    f"project:{index}:description",
                )
            for fact_index, fact in enumerate(project.facts):
                self._add(
                    FactEntry(
                        f"project:{owner}:fact:{_digest(fact)}",
                        "project",
                        fact,
                        index,
                        project.name,
                    ),
                    f"project:{index}:fact:{fact_index}",
                )
            for technology in project.technologies:
                self._add(
                    FactEntry(
                        f"project:{owner}:technology:{_digest(technology)}",
                        "project",
                        technology,
                        index,
                        project.name,
                    )
                )
        for index, certification in enumerate(self.profile.certifications):
            text = " | ".join(filter(None, [certification.name, certification.issuer, certification.date]))
            self._add(
                FactEntry(
                    f"certification:{_digest(text)}",
                    "certification",
                    text,
                    index,
                    certification.name,
                )
            )

    def get(self, source_id: str) -> FactEntry | None:
        return self.entries.get(source_id)

    def valid(self, source_ids: list[str], *, kind: str | None = None) -> list[FactEntry]:
        values = []
        seen = set()
        for source_id in source_ids:
            entry = self.get(source_id)
            if entry and (kind is None or entry.kind == kind) and entry.source_id not in seen:
                seen.add(entry.source_id)
                values.append(entry)
        return values

    def supports(self, claim: str, source_ids: list[str]) -> bool:
        claim_tokens = normalized_tokens(claim)
        if not claim_tokens:
            return False
        source_tokens = set()
        for entry in self.valid(source_ids):
            source_tokens.update(normalized_tokens(entry.text))
        if not source_tokens:
            return False
        return claim_tokens <= source_tokens or len(claim_tokens & source_tokens) / len(claim_tokens) >= 0.6

    def related(self, claim: str, source_ids: list[str]) -> bool:
        claim_tokens = normalized_tokens(claim)
        source_tokens = {token for entry in self.valid(source_ids) for token in normalized_tokens(entry.text)}
        return bool(claim_tokens & source_tokens)

    def direct_sources(self, claim: str) -> list[str]:
        claim_tokens = normalized_tokens(claim)
        if not claim_tokens:
            return []
        matches = []
        for entry in self.prompt_entries:
            entry_tokens = normalized_tokens(entry.text)
            if claim_tokens <= entry_tokens:
                matches.append(entry.source_id)
        return matches

    def supports_paraphrase(self, text: str, source_ids: list[str]) -> bool:
        entries = self.valid(source_ids)
        if not text.strip() or not entries:
            return False
        source_text = " ".join(entry.text for entry in entries)
        source_tokens = normalized_tokens(source_text)
        text_tokens = normalized_tokens(text)
        if not text_tokens:
            return False
        source_numbers = set(re.findall(r"\b\d+(?:[.+-]\d+)*\b", source_text))
        text_numbers = set(re.findall(r"\b\d+(?:[.+-]\d+)*\b", text))
        if not text_numbers <= source_numbers:
            return False
        overlap = len(source_tokens & text_tokens) / max(1, min(len(source_tokens), len(text_tokens)))
        return overlap >= 0.35

    def for_prompt(self) -> list[dict[str, str]]:
        return [
            {
                "source_id": entry.source_id,
                "type": entry.kind,
                "fact": entry.text,
                "owner": entry.owner_name,
            }
            for entry in self.prompt_entries
        ]
