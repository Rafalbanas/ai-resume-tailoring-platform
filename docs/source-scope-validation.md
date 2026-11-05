# Source Scope Validation

## Overview
This document defines the validation rules for source scope and summary composition. The primary objective is to ensure that logic remains grounded in literal quoted evidence rather than inferred meanings from shortened model titles.

## Forbidden Inferences
The following mappings are strictly prohibited as false positives. Evidence from the source must not be used to validate these cross-domain associations:
- Docker or CI/CD use does not establish AWS experience.
- JSON use does not establish XML use.
- DNS or VPN configuration does not establish NSG, Private Endpoints, or ExpressRoute knowledge.
- Standard API or SQL use does not establish ETL platform experience.
- System healthchecks do not establish LLM observability.
- Administrative tasks do not establish vulnerability assessment or privilege escalation practice.
- Private technical deployments do not establish business outcomes, tight deadlines, or project leadership.

## Contradiction Handling
Demonstrably different subjects in a model label and its quote (e.g., analytical thinking vs. shift availability) require corrected analysis. The indexed response is rejected for bounded recovery; independent validation also blocks a reliable verdict if the mismatch survives. Unknown paraphrases still need semantic interpretation.

## Operational Boundaries
Technical evidence does not verify a candidate's readiness for on-site or shift work. Such decisions require the candidate/account owner's confirmation. The system does not fabricate consent or availability.

## Logic and Constraints
- **Non-Cumulative Logic:** Explicit OR operators and provided examples do not imply a cumulative AND condition.
- **Bounded Guards:** Validation guards are designed as bounded safety checks; they do not constitute a complete semantic proof of the source's intent.

## Summary Composition Rules
Summaries must be constructed under the following constraints:
1. Preserve the true profession of the candidate.
2. Retain full quoted facts from the source.
3. Promote evidence strictly aligned with the role's core objectives.
4. Strictly prohibit changes to the user's project scope or competence levels.
5. Do not imply promotions or professional advancement.

## Review and Integrity
- **Manual Review:** Dubious model summaries or manual overrides still require a human review.
- **No Automated Guarantee:** The system does not promise "review-free correctness."
- **System Stability:** No migrations, external dependencies, or additional AI stages are introduced in this update.
- **Data Integrity:** Existing CVs and user confirmations remain untouched and preserved.
