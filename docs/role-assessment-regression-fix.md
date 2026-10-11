# Qualification assessment and role alignment

The regression in 5ba9f38 conflated a source without formal qualification criteria
with incomplete processing. It also collected role skills only from Tech Stack,
leaving products mentioned in duties invisible. An older JustJoin extractor stopped
at Benefits, losing any qualifications or preferences appearing later in the same
description. Reproducing extraction on the fetched Reply page confirmed that loss;
the historic complete page was not saved, so its exact earlier contents cannot be
certified from the saved short description.

The validator now independently presents explicit qualification evidence and role
alignment. A covered source with only duties/skills gets LIMITED / REVIEW, not an
unreliable analysis or an invented application recommendation. Uncovered actual
requirements and processing failures still yield UNRELIABLE / RETRY. Literal named
products used in duties appear once as unspecified role competencies, with source
quotes, and cannot become mandatory prior-experience blockers. Scope overlap uses
existing experience facts and remains partial; it does not confirm a complete duty.
Declared stack levels are retained and are not asserted as satisfied by generic
competence evidence. Unknown levels remain unknown.

JustJoin resumes at qualification/preference headings after skipping benefits;
stack proficiency labels are retained. Mixed required/preferred language sentences
are separated, and organization context following the organization introduction
is excluded from prerequisite scoring. No provider, skill-bank or Truth Lock
configuration was changed. PDF footer, themes and authentication fixes are retained.

Reproducible synthetic checks are in tests/test_role_assessment.py. Saved-data checks
are private under data/.diagnostics/role-assessment-fix. They include both saved Reply
provider outputs, a newly fetched complete description and saved Motorola data.
Saved Reply: 0 formal qualifications; 4 confirmed role skills and one unconfirmed
product; LIMITED / REVIEW; 9 separately retained duties. Complete current Reply:
8 mandatory and 6 preferred clauses (including optional German), Dynamics and
Microsoft certifications preferred. Saved Motorola: 10 mandatory / 7 preferred;
company text excluded and certifications preferred. No model calls are needed.

An additive validation replay may be saved for UI verification. It is explicitly
labelled as revalidation of saved data, with zero new generation duration. Original
CVs and benchmark results are preserved; a historical task URL keeps its historical
assessment. A new AI benchmark requires a new submission with the complete source.
