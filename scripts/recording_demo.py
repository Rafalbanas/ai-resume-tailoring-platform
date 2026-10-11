"""Initialize fictional data or run the loopback-only recording instance.

Connection settings are read from the existing .env; credentials are never copied.
"""
import argparse
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEMO = Path('/root/.local/share/cvtailor-recording-demo')


def initialize():
    from app.models.candidate import CandidateProfile
    from app.models.skills import SkillEvidence, SkillsDocument, VerifiedSkill
    from app.services.auth_store import AuthStore
    DEMO.mkdir(parents=True, mode=0o700, exist_ok=True)
    if (DEMO / 'auth.json').exists():
        raise RuntimeError('Demo already exists; refusing to overwrite it')
    profile = CandidateProfile.model_validate({
        'personal': {'name': 'Alex Example', 'location': 'Katowice', 'email': 'alex@example.com'},
        'summary_facts': ['Technical support specialist at fictional companies.',
                          'Builds small Python tools for support workflows.'],
        'skills': {'Technical': ['Python', 'Git', 'REST API', 'Docker'], 'Support': ['Technical support']},
        'experience': [{'company': 'Fictional Lantern Systems', 'title': 'Technical Support Specialist',
                        'start': '2022', 'end': 'Present', 'facts': [
                            'Investigated application tickets and documented troubleshooting steps.',
                            'Used Python to summarize synthetic support tickets.',
                            'Tested REST API endpoints with sample requests.']},
                       {'company': 'Fictional Pebble Desk', 'title': 'Support Assistant',
                        'start': '2020', 'end': '2022', 'facts': ['Triaged support requests and maintained a knowledge base.']}],
        'projects': [{'name': 'Synthetic Ticket Reporter', 'description': 'A small tool for fictional support data.',
                      'technologies': ['Python', 'Git', 'REST API', 'Docker'], 'facts': [
                          'Built a Python script that reads synthetic tickets from a REST API.',
                          'Tracked changes with Git and packaged the script in Docker.']}],
        'education': [{'institution': 'Fictional Katowice Technical College', 'qualification': 'IT support diploma', 'dates': '2018–2020'}]
    })
    skills = []
    for name, source, kind, description in [
        ('Python', 'project:0:fact:0', 'project', 'Python script reads synthetic tickets.'),
        ('Git', 'project:0:fact:1', 'project', 'Git version control for the script.'),
        ('REST API', 'project:0:fact:0', 'project', 'Reads a fictional ticket REST API.'),
        ('Docker', 'project:0:fact:1', 'project', 'Docker packaging for the script.'),
        ('Technical support', 'experience:0:fact:0', 'employment', 'Ticket investigation and documentation.')]:
        skills.append(VerifiedSkill(id='skill_' + name.lower().replace(' ', '_'), name=name, category='Demo',
                                    level='hands_on', verified=True, allowed_in_cv=True,
                                    evidence=[SkillEvidence(source_type=kind, source_id=source, description=description)]))
    (DEMO / 'master_profile.json').write_text(profile.model_dump_json(indent=2))
    (DEMO / 'skills.json').write_text(SkillsDocument(skills=skills).model_dump_json(indent=2))
    (DEMO / 'ai_settings.json').write_text('{"automatic_fallback": true}')
    (DEMO / 'csrf.secret').write_text(secrets.token_urlsafe(48))
    os.chmod(DEMO / 'csrf.secret', 0o600)
    password = secrets.token_urlsafe(30)
    AuthStore(DEMO / 'auth.json', 'recording-demo', password).initialize()
    print(password)  # One-time handoff to the owner, never emitted by the server.


def run():
    import app.core.config as config
    from app.core.config import Settings
    settings = Settings()
    settings.data_dir = DEMO
    settings.app_username = settings.app_password = None
    settings.demo_mode = True
    settings.profile_mode = 'sample'
    settings.app_root_path = '/demo'
    settings.base_url = 'https://cv.banas.dev/demo'
    settings.csrf_secret = (DEMO / 'csrf.secret').read_text()
    settings.llm_provider = 'ollama'
    settings.llm_fallback_provider = 'gemini'
    config.get_settings = lambda: settings
    import app.main
    app.main.get_settings = lambda: settings
    import uvicorn
    (DEMO / "server.pid").write_text(str(os.getpid()))
    uvicorn.run(app.main.app, host='127.0.0.1', port=18001, root_path=settings.app_root_path,
                proxy_headers=True, forwarded_allow_ips='127.0.0.1')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['init', 'run'])
    args = parser.parse_args()
    initialize() if args.action == 'init' else run()
