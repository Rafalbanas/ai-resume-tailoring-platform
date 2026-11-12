# Offline HTML resume export

The saved-CV preview offers **Download HTML**, **Download HTML + CSS ZIP** and
**Preview offline HTML** alongside the unchanged PDF/DOCX exports.

- `/download/{slug}/html`: UTF-8 self-contained HTML with embedded print CSS.
- `/download/{slug}/zip`: named HTML document plus a local `style.css`.
- `/html-preview/{slug}`: authenticated browser preview of that same HTML.

These are read-only views of the current saved CV, including saved edits,
section ordering/exclusions and learning labels. They do not call AI, update the
master profile, change evidence references, create history versions or replace
existing PDF/DOCX files. Contact/language values come from the active account
profile, as in existing exports; this does not introduce historical contact
snapshots. Truth Lock's existing saved-record validation and summary review
remain the boundary. Internal evidence IDs are retained in storage, not printed.

Open the single HTML directly from disk. For ZIP, extract both members to the
same directory; edit text in VS Code and appearance in `style.css`. There are
no JavaScript, web-font or server dependencies. Print A4 at 100%, disabling
browser headers/footers. Long CVs break across pages instead of losing content.
The offline single-column layout intentionally differs from the PDF sidebar.

Regression coverage: `pytest -q tests/test_html_resume.py` (escaping, exact
statements, non-mutation, ZIP, access/review checks, PDF extraction and layout).
