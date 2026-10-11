import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models.candidate import CandidateProfile
from app.models.skills import SkillEvidence, SkillsDocument, VerifiedSkill
from app.services.fact_catalog import FactCatalog
from app.services.profile_enrichment import apply_enrichment


def files(tmp_path, profile):
    (tmp_path / 'master_profile.json').write_text(profile.model_dump_json())
    (tmp_path / 'skills.json').write_text(SkillsDocument(skills=[]).model_dump_json())
    return tmp_path


def test_additive_enrichment_is_idempotent_and_preserves_source_ids(tmp_path, profile):
    data = files(tmp_path, profile)
    old_ids = set(FactCatalog(profile).entries)
    plan = {'skills': {'languages': ['Polish Native']}, 'summary_facts': ['Investigates technical tickets.']}
    backup = apply_enrichment(data, plan)
    assert backup and (backup / 'master_profile.json').is_file()
    updated = CandidateProfile.model_validate_json((data / 'master_profile.json').read_text())
    assert old_ids <= set(FactCatalog(updated).entries)
    assert updated.experience == profile.experience
    assert apply_enrichment(data, plan) is None
    assert updated.summary_facts.count('Investigates technical tickets.') == 1


def test_enrichment_rejects_unknown_evidence_before_writing(tmp_path, profile):
    data = files(tmp_path, profile)
    original = (data / 'master_profile.json').read_bytes()
    skill = VerifiedSkill(id='skill_sql', name='SQL', category='Databases', level='hands_on', verified=True,
                          evidence=[SkillEvidence(source_type='employment', source_id='missing:source', description='Invalid')])
    with pytest.raises(Exception, match='Unknown evidence'):
        apply_enrichment(data, {'summary_facts': ['New fact.'], 'bank_skills': [skill.model_dump()]})
    assert (data / 'master_profile.json').read_bytes() == original


def test_enrichment_restores_both_files_if_second_replace_fails(tmp_path, profile):
    data = files(tmp_path, profile)
    originals = {p: p.read_bytes() for p in (data / 'master_profile.json', data / 'skills.json')}
    import os
    real_replace = os.replace

    def fail_skills(source, target):
        if Path(target).name == 'skills.json':
            raise OSError('simulated write failure')
        real_replace(source, target)

    with patch('app.services.profile_enrichment.os.replace', side_effect=fail_skills), pytest.raises(OSError):
        apply_enrichment(data, {'skills': {'languages': ['Polish Native']}})
    assert all(p.read_bytes() == text for p, text in originals.items())


def test_dry_run_never_changes_files(tmp_path, profile):
    data = files(tmp_path, profile)
    before = json.loads((data / 'master_profile.json').read_text())
    apply_enrichment(data, {'skills': {'languages': ['Polish Native']}}, dry_run=True)
    assert json.loads((data / 'master_profile.json').read_text()) == before
