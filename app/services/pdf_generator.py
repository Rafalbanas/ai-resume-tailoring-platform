from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import CSS, HTML

from app.models.candidate import CandidateProfile
from app.models.resume import TailoredResume


class PDFGenerator:
    def __init__(self, templates_dir: Path, static_dir: Path):
        self.env = Environment(loader=FileSystemLoader(templates_dir), autoescape=select_autoescape(["html"]))
        self.css_path = static_dir / "resume.css"

    def render_html(self, resume: TailoredResume, profile: CandidateProfile) -> str:
        return self.env.get_template("resume.html").render(resume=resume, personal=profile.personal)

    def generate(self, resume: TailoredResume, profile: CandidateProfile, output: Path) -> None:
        HTML(string=self.render_html(resume, profile), base_url=str(self.css_path.parent)).write_pdf(
            output, stylesheets=[CSS(filename=self.css_path)]
        )
