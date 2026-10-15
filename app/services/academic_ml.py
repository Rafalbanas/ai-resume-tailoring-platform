"""Library knowledge is not proof of commercial or advanced ML training."""

import re

LIBRARIES = re.compile(r"\b(?:pytorch|torch|numpy)\b", re.I)
TRAINING = re.compile(
    r"\b(?:train\w*|fine.tun\w*|trenow\w*|dostraj\w*|uczeni\w*)\b.{0,100}\b(?:models?|model\w*|neural|neurono\w*|AI|ML)\b|\b(?:models?|model\w*|neural|neurono\w*|AI|ML)\b.{0,100}\b(?:train\w*|fine.tun\w*|trenow\w*|dostraj\w*|uczeni\w*)\b",
    re.I,
)
COMMERCIAL = re.compile(
    r"\b(?:commercial|professional|production|industry|komercyjn\w*|zawodow\w*|produkcyjn\w*)\b", re.I
)
ADVANCED = re.compile(r"\b(?:advanced|expert|extensive|senior|zaawansowan\w*|eksper[ct]\w*|biegł\w*)\b", re.I)
ACTIVITY = re.compile(
    r"\b(?:used|uses|using|trained|developed|implemented|built|fine.tun\w*|używa\w*|użył\w*|wykorzysta\w*|trenowa\w*|wytrenowa\w*)\b",
    re.I,
)
ACADEMIC = re.compile(
    r"\bacademic\b|\buniversity\b|\bthesis\b|\bcoursework\b|\bstudies\b|\bakademic\w*\b|\bstudi(?:a|ach|ów|om|ami)\b",
    re.I,
)
NEGATED = re.compile(r"\b(?:no|not|never|without|unconfirmed)\b", re.I)


def academic_entry(entry):
    return entry.kind == "education" or bool(ACADEMIC.search(entry.text + " " + entry.owner_name))


def ml_entries(name, entries):
    libraries = {"pytorch" if v.casefold() == "torch" else v.casefold() for v in LIBRARIES.findall(name)}
    return [
        entry
        for entry in entries
        if (
            any(
                re.search((r"\b(?:pytorch|torch)\b" if library == "pytorch" else r"\bnumpy\b"), entry.text, re.I)
                for library in libraries
            )
            if libraries
            else LIBRARIES.search(entry.text) or TRAINING.search(entry.text)
        )
    ]


def ml_ceiling(name, entries, bank=None, *, operator="all"):
    """Return a conservative scope ceiling, or None for unrelated requirements."""
    libraries = {"pytorch" if v.casefold() == "torch" else v.casefold() for v in LIBRARIES.findall(name)}
    training = bool(TRAINING.search(name))
    if not libraries and not training:
        return None
    relevant = ml_entries(name, entries)
    if not relevant:
        return "missing", "The cited facts do not establish the requested library or model-training scope."
    if (
        operator != "any"
        and libraries
        and not all(
            any(
                re.search((r"\b(?:pytorch|torch)\b" if lib == "pytorch" else r"\bnumpy\b"), e.text, re.I)
                for e in relevant
            )
            for lib in libraries
        )
    ):
        return "partial", "Only part of the requested library combination is documented."
    partial = "partial"
    if COMMERCIAL.search(name):
        commercial = [
            entry
            for entry in relevant
            if not academic_entry(entry)
            and ACTIVITY.search(entry.text)
            and not NEGATED.search(entry.text)
            and (
                entry.kind == "experience"
                or entry.kind == "verified_skill"
                and COMMERCIAL.search(entry.text)
                and not NEGATED.search(entry.text)
            )
        ]
        if (
            not commercial
            or libraries
            and operator != "any"
            and not all(
                any(
                    re.search((r"\b(?:pytorch|torch)\b" if lib == "pytorch" else r"\bnumpy\b"), entry.text, re.I)
                    for entry in commercial
                )
                for lib in libraries
            )
        ):
            return partial, "Academic/library knowledge is documented; commercial or production use is not confirmed."
    if ADVANCED.search(name):
        basic_levels = [bool((skill := bank.find(lib)) and skill.level == "basic") for lib in libraries] if bank else []
        basic = bool(basic_levels) and (all(basic_levels) if operator == "any" else any(basic_levels))
        advanced = [
            entry
            for entry in relevant
            if not academic_entry(entry)
            and ADVANCED.search(entry.text)
            and ACTIVITY.search(entry.text)
            and not NEGATED.search(entry.text)
        ]
        if basic or not advanced:
            return (
                partial,
                "Basic academic library use does not establish advanced proficiency or advanced model training.",
            )
    if training:
        trained = [
            entry
            for entry in relevant
            if TRAINING.search(entry.text)
            and ACTIVITY.search(entry.text)
            and entry.kind != "skill"
            and ":technology:" not in entry.source_id
            and not NEGATED.search(entry.text)
        ]
        if not trained:
            return (
                partial,
                "Using a library does not establish training or fine-tuning models; that activity needs explicit evidence.",
            )
    if libraries and re.search(r"\bexperience\b|hands.on|\bpractical\b|doświadczen\w*|praktyczn\w*", name, re.I):
        actual_use = [
            entry
            for entry in relevant
            if ACTIVITY.search(entry.text)
            and entry.kind != "skill"
            and ":technology:" not in entry.source_id
            and not NEGATED.search(entry.text)
        ]
        basic_academic = ACADEMIC.search(name) or re.search(r"\b(?:basic|podstawow\w*)\b", name, re.I)
        workplace = [entry for entry in actual_use if entry.kind == "experience" and not academic_entry(entry)]
        if not actual_use or not basic_academic and not workplace:
            return (
                partial,
                "Academic knowledge/use is distinct from the requested practical/professional scope; use and its context need explicit evidence.",
            )
    if re.search(r"\b\d+(?:\.\d+)?\s*\+?\s*(?:years?|lat(?:a)?|rok(?:u)?)\b", name, re.I):
        return (
            "partial",
            "Requested tenure needs dated, relevant employment evidence; library knowledge and degree dates do not establish years of professional use.",
        )
    return (
        "strong",
        "Library knowledge is supported by the cited facts; academic evidence remains academic and does not establish commercial tenure.",
    )
