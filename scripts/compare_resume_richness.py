"""Offline regression benchmark with fictional evidence, never provider calls.

Run before/after code changes with --output /tmp/opencode/<name>.json.
Measures the deterministic generation/Truth Lock/export boundary, not LLM prose.
"""
import argparse
import json
from pathlib import Path

from app.models.candidate import CandidateProfile
from app.models.job import JobAnalysis, JobRequest
from app.models.resume import ResumeBullet, ResumeExperience, TailoredResume
from app.services.fact_catalog import FactCatalog
from app.services.fact_validator import FactValidator
from app.services.pdf_generator import PDFGenerator
from app.services.professional_summary import summary_contains_clause


def rich_profile():
    return CandidateProfile.model_validate({
        "personal": {"name": "Alex Example", "email": "alex@example.com"},
        "summary_facts": ["Provides technical support for business customers."],
        "skills": {"technical": ["Python", "Machine Learning", "scikit-learn", "pandas", "SQL",
                                "Linux", "Docker", "Bash", "Incident investigation", "Technical documentation"]},
        "experience": [
            {"company": "Example Services", "title": "Technical Support Engineer (L2)",
             "start": "2023", "end": "Present", "facts": [
                 "Investigates application incidents using SQL queries and diagnostic logs.",
                 "Collaborates with engineering teams on technical escalations.",
                 "Documents troubleshooting procedures for business customers.",
                 "Automates repetitive diagnostic checks using Python.",
                 "Monitors Linux services and investigates network incidents."]},
            {"company": "Example Systems", "title": "IT Support Technician",
             "start": "2021", "end": "2023", "facts": [
                 "Resolved user support tickets and documented incident resolution.",
                 "Configured Linux workstations and tested backup restoration.",
                 "Wrote Bash scripts for routine system checks."]}],
        "projects": [
            {"name": "Academic ML thesis", "description": "Academic MSc project predicting bicycle power from sensor data.",
             "technologies": ["Python", "Machine Learning", "scikit-learn", "pandas"],
             "facts": ["Built a Python data processing pipeline for the academic MSc thesis.",
                       "Cleaned sensor data and prepared features using pandas.",
                       "Trained regression models using scikit-learn in the academic project.",
                       "Evaluated regression predictions using cross-validation and mean absolute error.",
                       "Compared prediction errors across the trained regression models."]},
            {"name": "Personal operations lab", "description": "Personal Linux lab for containerized service operation.",
             "technologies": ["Linux", "Docker", "Bash"],
             "facts": ["Deployed Docker containers on a Linux host in a personal lab.",
                       "Wrote Bash scripts for container health checks.",
                       "Tested backup restoration and documented recovery steps.",
                       "Configured log collection for the personal container services."]}],
        "education": [{"institution": "Example University", "qualification": "MSc Computer Science",
                       "dates": "2023", "specialisation": "Machine Learning"}],
    })


OFFERS = {
    "ML Engineer": "Python machine learning regression models, pandas, scikit-learn, data processing, model evaluation. Computer Science degree.",
    "Technical Support Engineer": "SQL diagnostic logs, application incidents, technical escalations, troubleshooting documentation, Python automation.",
    "DevOps Engineer": "Linux Docker Bash automation, monitoring, container health checks, backup restoration, network troubleshooting.",
}


def sparse_draft(profile):
    catalog = FactCatalog(profile)
    experience = []
    for index, source in enumerate(profile.experience):
        entry = next(e for e in catalog.prompt_entries
                     if e.kind == "experience" and e.owner_index == index and ":fact:" in e.source_id)
        experience.append(ResumeExperience(company=source.company, title=source.title, dates="",
            bullets=[ResumeBullet(text=entry.text, source_fact_ids=[entry.source_id])]))
    return TailoredResume(headline=profile.experience[0].title,
                          professional_summary="Unsupported generic professional.",
                          core_skills=[], experience=experience)


def visible_facts(profile, summary, projects, experience_text):
    visible = summary + " " + " ".join(projects.values()) + " " + " ".join(experience_text)
    facts = [f for e in profile.experience for f in e.facts]
    facts += [f for p in profile.projects for f in [p.description, *p.facts] if f]
    return sum(fact in visible or summary_contains_clause(summary, fact) for fact in dict.fromkeys(facts))


def measure(output, *, force_one_page=False):
    profile = rich_profile()
    generator = PDFGenerator(Path("templates"), Path("static"), output.parent / "resume-benchmark")
    rows = []
    for role, description in OFFERS.items():
        for level in (0.0, 0.5, 1.0):
            job = JobRequest(company="Fictional Target", role=role,
                             job_description="Requirements\n" + description, tailoring_level=level)
            analysis = JobAnalysis(company=job.company, role=role, strong_matches=[], partial_matches=[],
                                   missing_requirements=[], recommendation="REVIEW", match_level="LOW")
            validator = FactValidator(profile, analysis=analysis)
            resume = validator.validate(sparse_draft(profile), job).resume
            fitted, warnings = generator.fit_resume(resume, profile, template_name="modern_sidebar",
                job_text=role + "\n" + description, one_page=force_one_page,
                prefer_one_page=not force_one_page, fact_validator=validator)
            document = generator._render_document(generator.render_html(fitted, profile))
            ids = set(fitted.summary_source_fact_ids)
            ids.update(i for e in fitted.experience for b in e.bullets for i in b.source_fact_ids)
            ids.update(i for p in fitted.projects for i in p.source_fact_ids)
            # Actual visible text extent (excluding footer/background containers).
            utilization = []
            for page in document.pages:
                box = page._page_box
                lines = [b for b in box.descendants() if type(b).__name__ == "TextBox"
                         and getattr(b, "text", "").strip()
                         and box.content_box_y() <= b.position_y < box.content_box_y() + box.height]
                bottom = max((b.position_y + b.height for b in lines), default=box.content_box_y())
                utilization.append(round((bottom - box.content_box_y()) / box.height, 3))
            experience_text = [b.text for e in fitted.experience for b in e.bullets]
            projects = {p.name: p.description for p in fitted.projects}
            rows.append({"role": role, "level": level, "headline": fitted.headline,
                         "summary_chars": len(fitted.professional_summary),
                         "summary": fitted.professional_summary,
                         "experience_bullets": [len(e.bullets) for e in fitted.experience],
                         "project_chars": {p.name: len(p.description) for p in fitted.projects},
                         "projects": projects, "experience_text": experience_text,
                         "visible_fact_count": visible_facts(profile, fitted.professional_summary, projects, experience_text),
                         "source_ids": len(ids), "section_order": fitted.section_order,
                         "skills": fitted.core_skills, "pages": len(document.pages),
                         "page_text_extent": utilization, "layout_warnings": warnings})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(json.dumps([{k: v for k, v in r.items() if k not in {"summary", "projects", "experience_text", "skills", "layout_warnings"}}
                      for r in rows], indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--force-one-page", action="store_true", help="Exercise explicit legacy one-page selection.")
    args = parser.parse_args()
    measure(args.output, force_one_page=args.force_one_page)
