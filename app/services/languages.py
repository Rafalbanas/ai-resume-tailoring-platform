import re

from app.models.candidate import CandidateProfile

# These are natural languages, not programming languages. Profile declarations
# also cover languages outside this list; JavaScript/Python are never classified here.
PROGRAMMING_LANGUAGES = {"python", "javascript", "typescript", "java", "bash", "powershell", "sql", "t-sql", "c", "c++", "c#", "go", "rust", "ruby", "php"}
NATURAL_LANGUAGES = {"english", "polish", "german", "french", "spanish", "italian", "portuguese", "dutch", "ukrainian", "russian", "arabic", "chinese", "japanese", "korean", "swedish", "norwegian", "danish", "czech", "slovak", "hindi", "turkish", "romanian", "hungarian", "finnish", "greek", "hebrew"}


def is_language_skill(value: str, profile: CandidateProfile) -> bool:
    value = re.sub(r"^(?:hands[- ]on|basic|advanced)\s+", "", value.strip(), flags=re.I)
    names = NATURAL_LANGUAGES | {v.split()[0].casefold() for v in profile.skills.get("languages", []) if v.split()}
    names -= PROGRAMMING_LANGUAGES | {"native", "hands-on", "basic", "advanced"}
    return any(re.search(rf"\b{re.escape(name)}\b", value, re.I) for name in names)


def profile_languages(profile: CandidateProfile) -> list[str]:
    grouped: dict[str, list[str]] = {}
    for raw in profile.skills.get("languages", []):
        value = re.sub(r"^hands[- ]on\s+", "", raw.strip(), flags=re.I)
        if not value or not is_language_skill(value, profile):
            continue
        name = next((word for word in value.split() if word.casefold() in NATURAL_LANGUAGES), value.split()[0])
        if value.split()[0].casefold() == "native":
            value = name + " Native"
        grouped.setdefault(name.casefold(), []).append(value)
    result = []
    for values in grouped.values():
        name = values[0].split()[0]
        # Preserve the highest explicitly stated level, including a literal +.
        levels = re.findall(r"\b[ABC][12]\+?|\bnative\b", " ".join(values), re.I)
        order = ["A1", "A1+", "A2", "A2+", "B1", "B1+", "B2", "B2+", "C1", "C1+", "C2", "C2+", "NATIVE"]
        level = max((v.upper() for v in levels), key=order.index, default="")
        details = []
        for value in values:
            detail = re.sub(r"\b[ABC][12]\+?|\bnative\b", "", value[len(name):], flags=re.I).strip(" /—–-")
            if detail and detail.casefold() not in {d.casefold() for d in details}:
                details.append(detail)
        label = f"{name} {level.title() if level == 'NATIVE' else level}".strip()
        result.append(label + (" — " + "; ".join(details) if details else ""))
    return result
