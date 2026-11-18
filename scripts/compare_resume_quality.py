"""Compare deterministic, source-checked CVs with identical fictional inputs."""
import argparse
import asyncio
import json
import re
from itertools import combinations
from pathlib import Path

from bs4 import BeautifulSoup
from docx import Document
from pypdf import PdfReader

from app.models.job import JobAnalysis, JobRequest
from app.services.analysis_validator import AnalysisValidator
from app.services.content_quality import concepts, project_sentences
from app.services.docx_generator import _generate_docx_local
from app.services.fact_validator import FactValidator
from app.services.html_resume import render_html_resume
from app.services.ollama_draft_review import valid_bullet_attestation
from app.services.pdf_generator import PDFGenerator
from app.services.professional_summary import summary_contains_clause
from app.services.resume_export import prepare_resume
from scripts.resume_quality_scenarios import SCENARIOS, layout_profile, profile, sparse_draft


def scenario(role, candidate):
    spec = SCENARIOS[role]
    job = JobRequest(company='Fictional Employer', role=role, job_description=spec['description'],
                     tailoring_level=0.5)
    pending = JobAnalysis(company=job.company, role=role, strong_matches=[], partial_matches=[],
                          missing_requirements=[], recommendation='REVIEW', match_level='LOW')
    return job, AnalysisValidator(candidate).validate(pending, job.job_description, semantic=False)


def bullet_texts(resume):
    return [b.text for owner in resume.experience for b in owner.bullets]


def coverage(resume, expected):
    return sum(any(normalize(fact) in normalize(bullet) for bullet in bullet_texts(resume)) for fact in expected)


def normalize(text):
    return re.sub(r'\s+', ' ', text.replace('\u00ad', '')).strip().casefold()


def evidence_errors(resume, validator):
    errors = []
    for owner in resume.experience:
        for bullet in owner.bullets:
            facts = validator.catalog.valid(bullet.source_fact_ids, kind='experience')
            if (not facts or any((source := validator.profile.experience[e.owner_index]).company != owner.company
                                 or source.title != owner.title for e in facts)):
                errors.append('Employment owner/citation mismatch')
            elif not (validator.catalog.supports_paraphrase(bullet.text, [e.source_id for e in facts])
                      or bullet.text in {validator._experience_wording(e.text) for e in facts}
                      or valid_bullet_attestation(bullet, resume, validator.profile, validator.review_key)):
                errors.append('Employment bullet lacks exact source or review approval')
    for project in resume.projects:
        facts = validator.catalog.valid(project.source_fact_ids, kind='project')
        if not facts or any(e.owner_name != project.name for e in facts):
            errors.append('Project owner/citation mismatch')
        fragments = {normalize(s).rstrip('.') for e in facts for s in project_sentences(e.text)}
        if any(normalize(s).rstrip('.') not in fragments for s in project_sentences(project.description)):
            errors.append('Unexpected non-source project clause in this fixture')
    if not all(validator.catalog.get(i) for i in resume.summary_source_fact_ids):
        errors.append('Unknown citation in summary')
    if re.search(r'\b(?:Kubernetes|Terraform)\b', ' '.join([
        resume.headline, resume.professional_summary, *resume.core_skills, *bullet_texts(resume),
        *(p.description for p in resume.projects), *(tech for p in resume.projects for tech in p.technologies)]), re.I):
        errors.append('Offer-only skill in candidate content')
    return errors


def export_and_check(generator, output, slug, fitted, candidate, guide, template):
    pdf = output / f'{slug}.pdf'
    docx = output / f'{slug}.docx'
    html = output / f'{slug}.html'
    generator.generate(fitted, candidate, pdf, guide, template_name=template)
    # Match PDF/HTML's in-process benchmark mode: the same renderer used by
    # the worker, without including worker startup/deadlines in quality scores.
    _generate_docx_local(fitted, candidate, docx, template_name=template)
    html.write_text(render_html_resume(fitted, candidate, generator=generator,
                    template_name=template, layout_guide=guide), encoding='utf-8')
    reader = PdfReader(pdf)
    pdf_lines = [p.extract_text() for p in reader.pages]
    doc = Document(docx)
    docx_lines = [''.join(node.text or '' for node in p.xpath('.//w:t')) for p in doc.element.xpath('.//w:p')]
    soup = BeautifulSoup(html.read_text(encoding='utf-8'), 'html.parser')
    for node in soup(['script', 'style', 'head']):
        node.decompose()
    required = list(dict.fromkeys([fitted.headline, fitted.professional_summary, *fitted.core_skills,
                                 *(owner.company for owner in fitted.experience), *bullet_texts(fitted),
                                 *(p.name for p in fitted.projects), *(p.description for p in fitted.projects)]))
    result = {}
    for ext, text in {'pdf': ' '.join(pdf_lines), 'docx': ' '.join(docx_lines),
                      'html': soup.get_text(' ', strip=True)}.items():
        result[ext] = {'required': len(required), 'found': sum(normalize(s) in normalize(text) for s in required)}
    return len(reader.pages), result


def compare(outputs, key):
    pairs = []
    for a, b in combinations(outputs, 2):
        left, right = set(a[key]), set(b[key])
        pairs.append(len(left & right) / max(1, len(left | right)))
    return round(sum(pairs) / max(1, len(pairs)), 3)


async def benchmark(output, *, exports=False, model=None, only=None):
    output.mkdir(parents=True, exist_ok=True)
    candidate = profile()
    generator = PDFGenerator(Path('templates'), Path('static'), output, isolated=False)
    provider = None
    if model:
        from app.core.config import Settings
        from app.services.ollama_provider import OllamaProvider
        # Loopback only, no .env, private profiles, model download or fallback.
        provider = OllamaProvider(Settings(
            _env_file=None, ollama_model=model, ollama_base_url='http://127.0.0.1:11434',
            ollama_max_concurrency=1, ollama_num_ctx=12288, ollama_num_predict=3072,
            ollama_connect_timeout_seconds=5, ollama_read_timeout_seconds=180,
            hybrid_retrieval_enabled=False, csrf_secret='synthetic-benchmark-key'))
    outputs = []
    for role, spec in SCENARIOS.items():
        if only and role != only:
            continue
        job, analysis = scenario(role, candidate)
        draft = await provider.tailor_resume(job, candidate, analysis) if provider else sparse_draft(candidate)
        validator = FactValidator(candidate, analysis=analysis, review_key=provider.summary_review_key if provider else '')
        result = validator.validate(draft, job)
        prepared = prepare_resume(result.resume, candidate)
        guide = {}
        fitted, warnings = generator.fit_resume(prepared, candidate, guide, template_name='ats_classic',
            job_text=f'{job.role}\n{job.relevance_text}', prefer_one_page=True, fact_validator=validator)
        pages, extraction = (export_and_check(generator, output, re.sub(r'\W+', '-', role.lower()),
                        fitted, candidate, guide, 'ats_classic') if exports else (None, {}))
        bullets = bullet_texts(fitted)
        required = spec['employment']
        outputs.append({
            'role': role, 'expected': len(required), 'matched_before_fit': coverage(prepared, required),
            'matched_export': coverage(fitted, required), 'employment_before_fit': len(bullet_texts(prepared)),
            'verified_source_facts': sum(b in {f for e in candidate.experience for f in e.facts} for b in bullets),
            'generic_bullets': sum(b == owner.facts[0] for b in bullets for owner in candidate.experience),
            'repeated_bullets_in_summary': sum(summary_contains_clause(fitted.professional_summary, b) for b in bullets),
            'unique_bullet_concepts': len({tuple(sorted(concepts(b))) for b in bullets}),
            'scale_visible': any('170 users' in b and 'five locations' in b for b in bullets),
            'expected_project': spec['project'], 'projects': [p.name for p in fitted.projects],
            'errors': evidence_errors(fitted, validator),
            'headline': fitted.headline, 'summary': fitted.professional_summary, 'experience': bullets,
            'recent_experience': [b.text for b in fitted.experience[0].bullets],
            'skills': fitted.core_skills, 'warnings': result.warnings + warnings, 'pages': pages, 'extraction': extraction,
        })
    report = {'model': model, 'mean_pairwise_bullet_jaccard': compare(outputs, 'experience'),
              'recent_job_jaccard': compare(outputs, 'recent_experience'), 'resumes': outputs}
    (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def benchmark_layout(output):
    output.mkdir(parents=True, exist_ok=True)
    candidate = layout_profile()
    job, _ = scenario('Technical Support Engineer', candidate)
    validator = FactValidator(candidate)  # Test evidence not cited by requirements.
    prepared = validator.validate(sparse_draft(candidate), job).resume
    generator = PDFGenerator(Path('templates'), Path('static'), output, isolated=False)
    report = {}
    for template in ('ats_classic', 'modern_sidebar'):
        guide = {}
        fitted, warnings = generator.fit_resume(prepared, candidate, guide, template_name=template,
            job_text=f'{job.role}\n{job.relevance_text}', prefer_one_page=True, fact_validator=validator)
        pages, extraction = export_and_check(generator, output, template, fitted, candidate, guide, template)
        report[template] = {
            'pages': pages, 'extraction': extraction,
            'scoped_facts': sum('users' in b for b in bullet_texts(fitted)),
            'scoped_facts_before_fit': sum('users' in b for b in bullet_texts(prepared)),
            'warnings': warnings,
        }
    (output / 'layout.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--exports', action='store_true')
    parser.add_argument('--ollama-model', help='Opt-in, already installed on localhost.')
    parser.add_argument('--only', choices=SCENARIOS)
    parser.add_argument('--rich-layout', action='store_true', help='Also compare both themes with a longer employment history.')
    args = parser.parse_args()
    if args.ollama_model and not args.only:
        parser.error('Choose one scenario with --only for the real-model smoke test.')
    report = asyncio.run(benchmark(args.output, exports=args.exports, model=args.ollama_model, only=args.only))
    for row in report['resumes']:
        print(f"{row['role']}: {row['matched_export']}/{row['expected']} target facts; "
              f"{len(row['errors'])} evidence audit flags; {row['pages']} PDF pages")
    if args.rich_layout:
        print(json.dumps(benchmark_layout(args.output), indent=2))
