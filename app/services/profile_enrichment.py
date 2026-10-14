"""Explicit, additive profile updates with validated evidence and rollback backups."""
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.models.candidate import CandidateProfile
from app.models.skills import SkillsDocument, VerifiedSkill
from app.services.skills_bank import SkillsBank


def _extend(values, additions):
    known = {' '.join(v.casefold().split()) for v in values}
    for value in additions:
        key = ' '.join(value.casefold().split())
        if key not in known:
            values.append(value)
            known.add(key)


def prepare_enrichment(profile: CandidateProfile, document: SkillsDocument, plan: dict):
    updated, bank = profile.model_copy(deep=True), document.model_copy(deep=True)
    allowed = {'summary_facts', 'skills', 'experience_facts', 'project_facts', 'education_facts', 'bank_skills'}
    if set(plan) - allowed:
        raise ValueError('Unknown enrichment fields')
    _extend(updated.summary_facts, plan.get('summary_facts', []))
    for category, values in plan.get('skills', {}).items():
        _extend(updated.skills.setdefault(category, []), values)
    for collection, owner_field, name in ((updated.experience, 'company', 'experience_facts'), (updated.projects, 'name', 'project_facts'), (updated.education, 'institution', 'education_facts')):
        for item in plan.get(name, []):
            matches = [entry for entry in collection if getattr(entry, owner_field) == item['owner']]
            if len(matches) != 1:
                raise ValueError(f'A unique existing owner is required: {item["owner"]}')
            _extend(matches[0].facts, item.get('facts', []))
            if name == 'project_facts':
                _extend(matches[0].technologies, item.get('technologies', []))
    for addition in plan.get('bank_skills', []):
        existing = next((s for s in bank.skills if s.id == addition['id']), None)
        if existing:
            data = existing.model_dump()
            # Preserve existing trust levels, names, notes and source links unless
            # the caller explicitly supplies an update. Evidence is additive.
            for key, value in addition.items():
                if key in {'evidence', 'aliases'}:
                    data[key] += [v for v in value if v not in data[key]]
                else:
                    data[key] = value
            replacement = VerifiedSkill.model_validate(data)
            bank.skills[bank.skills.index(existing)] = replacement
        else:
            bank.skills.append(VerifiedSkill.model_validate(addition))
    return CandidateProfile.model_validate(updated.model_dump()), SkillsDocument.model_validate(bank.model_dump())


def apply_enrichment(data_dir: Path, plan: dict, *, dry_run=False) -> Path | None:
    paths = [data_dir / 'master_profile.json', data_dir / 'skills.json']
    originals = [p.read_bytes() for p in paths]
    profile, bank = prepare_enrichment(CandidateProfile.model_validate_json(originals[0]),
                                      SkillsDocument.model_validate_json(originals[1]), plan)
    payloads = [profile.model_dump_json(indent=2) + '\n', bank.model_dump_json(indent=2) + '\n']
    with tempfile.TemporaryDirectory(prefix='.enrichment-', dir=data_dir) as temp:
        staged = [Path(temp) / p.name for p in paths]
        for p, text in zip(staged, payloads, strict=True):
            p.write_text(text, encoding='utf-8')
        SkillsBank(staged[1], profile)  # Reject dangling/wrongly typed references before any writes.
        if dry_run or all(json.loads(old) == json.loads(new) for old, new in zip(originals, payloads, strict=True)):
            return None
        if any(p.read_bytes() != old for p, old in zip(paths, originals, strict=True)):
            raise RuntimeError('Profile changed during enrichment; no update was applied')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8]
        backup = data_dir / '.drafts' / ('profile-backup-' + stamp)
        backup.mkdir(parents=True, mode=0o700)
        for p in paths:
            shutil.copy2(p, backup / p.name)
        try:
            for target, source in zip(paths, staged, strict=True):
                stat = target.stat()
                os.chmod(source, stat.st_mode & 0o777)
                if os.geteuid() == 0:
                    os.chown(source, stat.st_uid, stat.st_gid)
                os.replace(source, target)
        except Exception:
            for p in paths:
                shutil.copy2(backup / p.name, p)
            raise
    return backup
