"""Shared, profile-driven presentation checks for PDF and DOCX.

FactValidator remains the content trust boundary. Export preparation never invents
skills, changes employment dates, or uses a job advertisement as candidate data.
"""
import re
from copy import deepcopy
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from email_validator import validate_email

from app.models.candidate import CandidateProfile
from app.models.resume import TailoredResume
from app.services.languages import is_language_skill


@dataclass(frozen=True)
class Contact:
    label: str
    display: str
    target: str = ""


def web_link(value: str) -> str:
    """Reject malformed/active links; encode Unicode paths without double encoding."""
    value = value.strip()
    parsed = urlsplit(value)
    if (parsed.scheme not in {"https", "http"} or not parsed.hostname
            or parsed.username or parsed.password or re.search(r"[\s\x00-\x1f]", value) or re.search(r"%(?![0-9a-fA-F]{2})", value)):
        raise ValueError("Contact/project links must be valid HTTP(S) URLs.")
    try:
        port = parsed.port
        host = parsed.hostname.encode("idna").decode()
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid link host or port.") from exc
    if "." not in host and host != "localhost":
        raise ValueError("Invalid link host.")
    authority = host + (f":{port}" if port else "")
    return urlunsplit((parsed.scheme, authority, quote(parsed.path, safe="%/:@-._~!$&'()*+,;="),
                       quote(parsed.query, safe="%=&/:?@-._~!$'()*+,;"), quote(parsed.fragment, safe="%-._~")))


def contacts(profile: CandidateProfile) -> list[Contact]:
    personal = profile.personal
    if not personal.name.strip():
        raise ValueError("Candidate name is missing from the active master profile.")
    try:
        email = validate_email(str(personal.email), check_deliverability=False, test_environment=True).normalized
    except ValueError as exc:
        raise ValueError("A valid email address is required before exporting a CV.") from exc
    result = []
    if personal.location.strip():
        result.append(Contact("Location", personal.location.strip()))
    result.append(Contact("Email", email, f"mailto:{email}"))
    if personal.phone.strip():
        result.append(Contact("Phone", personal.phone.strip()))
    for label, value in (("LinkedIn", personal.linkedin), ("Website", personal.website), ("GitHub", personal.github)):
        if value.strip():
            target = web_link(value)
            display = link_display(value)
            result.append(Contact(label, display, target))
    return result


def link_display(value: str) -> str:
    """Keep a recognizable host/path; tracking parameters belong only to href."""
    parsed = urlsplit(value.strip())
    return unquote(parsed.netloc.removeprefix('www.') + parsed.path).rstrip('/')


def prepare_resume(resume: TailoredResume, profile: CandidateProfile) -> TailoredResume:
    contacts(profile)
    prepared = deepcopy(resume)
    clean = []
    keys = set()
    for skill in prepared.core_skills:
        value = re.sub(r"^hands[- ]on\s+", "", skill.strip(), flags=re.I)
        if not value or is_language_skill(value, profile):
            continue
        key = re.sub(r"\W+", " ", value.casefold()).strip()
        if key not in keys:
            clean.append(value)
            keys.add(key)
    prepared.core_skills = clean
    for project in prepared.projects:
        if project.url:
            project.url = web_link(project.url)
        project.technologies = list(dict.fromkeys(
            re.sub(r"^hands[- ]on\s+", "", value.strip(), flags=re.I)
            for value in project.technologies if value.strip() and not is_language_skill(value, profile)))
    prepared.projects = [p for p in prepared.projects if p.name.strip() and (p.description.strip() or p.technologies)]
    prepared.experience = [e for e in prepared.experience if e.company.strip() and e.title.strip() and e.bullets]
    prepared.education = [e for e in prepared.education if e.institution.strip() and e.qualification.strip()]
    prepared.certifications = [c for c in prepared.certifications if c.name.strip()]
    return prepared


def validate_layout(document) -> None:
    """Check real paginated text boxes, not guessed character counts.

    Multiple pages are allowed. Running headers/consent are in reserved margins;
    content must stay inside the physical page and its allocated column.
    """
    def boxes(box, column=None):
        element = getattr(box, "element", None)
        classes = element.get("class", "").split() if element is not None else []
        if type(box).__name__ == "BlockBox" and "resume-sidebar" in classes:
            column = (box.content_box_x(), box.content_box_x() + box.width)
        elif type(box).__name__ == "BlockBox" and "resume-main" in classes:
            column = (box.content_box_x(), box.content_box_x() + box.width)
        yield box, column
        for child in getattr(box, "children", []):
            yield from boxes(child, column)

    for page in document.pages:
        text_boxes = []
        for box, column in boxes(page._page_box):
            if type(box).__name__ != "TextBox" or not getattr(box, "text", "").strip():
                continue
            if (box.position_x < -1 or box.position_y < -1
                    or box.position_x + box.width > page.width + 1
                    or box.position_y + box.height > page.height + 1):
                raise ValueError("CV text exceeds the page boundary; adjust layout before exporting.")
            text_boxes.append(box)
            if column and (box.position_x < column[0] - 1 or box.position_x + box.width > column[1] + 1):
                raise ValueError("CV text exceeds its column boundary; adjust layout before exporting.")

        # Compare glyph boxes, not parent section boxes which intentionally
        # enclose their children. Adjacent inline runs share a baseline safely.
        for index, left in enumerate(text_boxes):
            for right in text_boxes[index+1:]:
                overlap_x = min(left.position_x + left.width, right.position_x + right.width) - max(left.position_x, right.position_x)
                overlap_y = min(left.position_y + left.height, right.position_y + right.height) - max(left.position_y, right.position_y)
                if overlap_x > 1.2 and overlap_y > 1.2:
                    raise ValueError("CV text overlaps another text element; export stopped.")


def validate_pdf_output(data: bytes, profile: CandidateProfile) -> None:
    from io import BytesIO

    from pypdf import PdfReader
    reader = PdfReader(BytesIO(data))
    if not reader.pages:
        raise ValueError("PDF has no pages.")
    text = " ".join(p.extract_text() or '' for p in reader.pages)
    def key(value):
        return re.sub(r"\W+", "", value).casefold()
    targets = {str(a.get_object().get('/A', {}).get('/URI', '')) for p in reader.pages for a in p.get('/Annots', [])}
    for contact in contacts(profile):
        if key(contact.display) not in key(text) or (contact.target and contact.target not in targets):
            raise ValueError("A contact value or hyperlink is missing from the PDF.")
    if text.count('I consent to the processing') != 1:
        raise ValueError("Recruitment consent must be present exactly once.")
    for page in reader.pages:
        for reference in page.get('/Annots', []):
            annotation = reference.get_object()
            if annotation.get('/Subtype') != '/Link':
                continue
            left, bottom, right, top = map(float, annotation['/Rect'])
            if left < -1 or bottom < -1 or right > float(page.mediabox.width)+1 or top > float(page.mediabox.height)+1:
                raise ValueError("PDF link extends outside the page.")
