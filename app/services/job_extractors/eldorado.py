import json
import logging
import re
from typing import Any

import httpx

from app.services.job_extractors.base import (
    BaseExtractor,
    ExtractionCandidate,
    cleaned_soup,
    first_text,
    normalized_text,
)
from app.services.job_extractors.security import PublicUrlGuard

logger = logging.getLogger(__name__)

MCP_ENDPOINT = "https://czyjesteldorado.pl/_mcp"

ID_PATTERNS = (
    re.compile(r"/(?:praca|oferta|job|jobs)/(\d+)", re.I),
    re.compile(r"[?&]id=(\d+)", re.I),
    re.compile(r"/(\d{5,8})(?:-[a-z0-9-]+)?(?:[/?#]|$)", re.I),
    re.compile(r"#(\d+)", re.I),
)


def extract_job_id(url_or_phrase: str) -> str | None:
    for pattern in ID_PATTERNS:
        match = pattern.search(url_or_phrase)
        if match:
            return match.group(1)
    return None


def candidate_from_job_data(job_data: dict[str, Any]) -> ExtractionCandidate:
    role = str(job_data.get("title") or "").strip()
    company = str(job_data.get("company") or "").strip()

    raw_keywords = job_data.get("keywords") or []
    if isinstance(raw_keywords, str):
        raw_keywords = [k.strip() for k in raw_keywords.split(",") if k.strip()]
    keywords = [str(k).strip() for k in raw_keywords if str(k).strip()]

    raw_cities = job_data.get("cities") or []
    if isinstance(raw_cities, str):
        raw_cities = [c.strip() for c in raw_cities.split(",") if c.strip()]
    cities = [str(c).strip() for c in raw_cities if str(c).strip()]

    raw_modes = job_data.get("work_modes") or []
    if isinstance(raw_modes, str):
        raw_modes = [m.strip() for m in raw_modes.split(",") if m.strip()]
    work_modes = [str(m).strip() for m in raw_modes if str(m).strip()]

    raw_contracts = job_data.get("contract_types") or []
    if isinstance(raw_contracts, str):
        raw_contracts = [t.strip() for t in raw_contracts.split(",") if t.strip()]
    contract_types = [str(t).strip() for t in raw_contracts if str(t).strip()]

    raw_workloads = job_data.get("workload_types") or []
    if isinstance(raw_workloads, str):
        raw_workloads = [w.strip() for w in raw_workloads.split(",") if w.strip()]
    workload_types = [str(w).strip() for w in raw_workloads if str(w).strip()]

    seniority = str(job_data.get("seniority") or "").strip()
    salary_from = job_data.get("salary_from")
    salary_to = job_data.get("salary_to")
    posted_at = str(job_data.get("posted_at") or "").strip()

    sections: list[str] = []

    if keywords:
        sections.append("PORTAL TECHNOLOGY TAGS\n" + "\n".join(keywords))

    conditions: list[str] = []
    if seniority and seniority.lower() not in {"null", "none"}:
        conditions.append(f"Poziom doświadczenia: {seniority}")
    if cities:
        conditions.append(f"Lokalizacja: {', '.join(cities)}")
    if work_modes:
        conditions.append(f"Tryb pracy: {', '.join(work_modes)}")
    if contract_types:
        conditions.append(f"Forma zatrudnienia: {', '.join(contract_types)}")
    if workload_types and workload_types != ["other"]:
        conditions.append(f"Wymiar pracy: {', '.join(workload_types)}")
    if salary_from is not None and salary_to is not None:
        conditions.append(f"Wynagrodzenie: {salary_from} - {salary_to} PLN")
    elif salary_from is not None:
        conditions.append(f"Wynagrodzenie: od {salary_from} PLN")
    elif salary_to is not None:
        conditions.append(f"Wynagrodzenie: do {salary_to} PLN")
    if posted_at:
        conditions.append(f"Data publikacji: {posted_at[:10]}")

    if conditions:
        sections.append("EMPLOYMENT CONDITIONS\n" + "\n".join(conditions))

    return ExtractionCandidate(
        company=company,
        role=role,
        job_description="\n\n".join(sections),
    )


ELDORADO_HEADINGS = {
    "tech stack / keywords": "PORTAL TECHNOLOGY TAGS",
    "tech stack": "PORTAL TECHNOLOGY TAGS",
    "technologie": "PORTAL TECHNOLOGY TAGS",
    "keywords": "PORTAL TECHNOLOGY TAGS",
    "portal technology tags": "PORTAL TECHNOLOGY TAGS",
    "firma i stanowisko": "OFFER DESCRIPTION",
    "o firmie": "OFFER DESCRIPTION",
    "o projekcie": "OFFER DESCRIPTION",
    "offer description": "OFFER DESCRIPTION",
    "wymagania": "REQUIREMENTS",
    "nasze wymagania": "REQUIREMENTS",
    "requirements": "REQUIREMENTS",
    "obowiązki": "RESPONSIBILITIES",
    "twój zakres obowiązków": "RESPONSIBILITIES",
    "twoje zadania": "RESPONSIBILITIES",
    "responsibilities": "RESPONSIBILITIES",
    "employment conditions": "EMPLOYMENT CONDITIONS",
    "warunki zatrudnienia": "EMPLOYMENT CONDITIONS",
    "mile widziane": "NICE TO HAVE",
    "nice to have": "NICE TO HAVE",
    "benefity": None,
    "co oferujemy": None,
    "to oferujemy": None,
    "inne informacje": None,
}

ELDORADO_UI_NOISE = {
    "zapisz",
    "udostępnij",
    "aplikuj teraz",
    "aplikuj szybko",
    "aplikuj",
    "quick apply",
    "new",
    "nowość",
    "·",
    "brak informacji o wynagrodzeniu",
    "0",
    "/ mies.",
    "/ mies",
    "/ m-c",
    "miesiąc",
    "b2b (netto)",
    "uop (brutto)",
    "(netto)",
    "(brutto)",
}

ROLE_WORDS = re.compile(
    r"\b(?:engineer|specialist|developer|architect|consultant|administrator|manager|lead|tester|qa|devops|support|inżynier|specjalista|programista|architekt|administrator|kierownik|konsultant|analityk|analyst)\b",
    re.I,
)
COMPANY_SUFFIXES = re.compile(
    r"(?:\bsp\.?\s*z\s*o\.?\s*o\.?|\bspółka|\bs\.a\.?|\bsa\b|\bgmbh\b|\bltd\b|\binc\b|\bcorp\b|\bllc\b|\blab\b|\blabs\b|\bsoftware\b|\btechnologies\b|\bservices\b)",
    re.I,
)
EMPLOYMENT_WORDS = re.compile(
    r"\b(?:zdalnie|remote|hybrydowo|hybrid|stacjonarnie|office|b2b|uop|umowa o pracę|zlecenie|pełny etat|część etatu|full-time|part-time|inne|polska|poland|kraków|warszawa|wrocław|poznań|gdańsk|katowice|łódź|lublin|szczecin)\b",
    re.I,
)
SENIORITY_WORDS = re.compile(
    r"^(?:intern|stażysta|junior|mid|regular|senior|lead|principal|c-level)$",
    re.I,
)
SALARY_PATTERN = re.compile(r"\b\d[\d\s]*(?:-\s*\d[\d\s]*)?\s*(?:pln|zł|eur|usd|gbp)\b", re.I)
NUMERIC_BADGE = re.compile(r"^\d+$")


class EldoradoExtractor(BaseExtractor):
    domains = ("czyjesteldorado.pl",)
    prefer_over_jsonld = True
    allow_generic_fallback = False
    mcp_endpoint = MCP_ENDPOINT

    def extract(self, html: str) -> ExtractionCandidate:
        soup = cleaned_soup(html)
        role = first_text(soup, ("h1", "[data-test*='title']", ".offer-title", ".job-title", "header h1"))
        company = first_text(soup, ("[data-test*='company']", ".company-name", "a[href*='/firma/']", "h1 + h2", "h2"))

        cloned_soup = cleaned_soup(html)
        for node in list(cloned_soup.select("h1,h2,h3,h4,p,li")):
            if node.decomposed or node.find_parent(["p", "li"]):
                continue
            text = node.get_text(" ", strip=True)
            node.replace_with("\n" + text + "\n")

        candidate = self.extract_text(normalized_text(cloned_soup))
        if role:
            candidate.role = role
        if company:
            candidate.company = company

        headings = {node.get_text(" ", strip=True).casefold().rstrip(":") for node in soup.select("h2,h3,h4")}
        if any(ELDORADO_HEADINGS.get(heading) in {"REQUIREMENTS", "RESPONSIBILITIES", "OFFER DESCRIPTION"}
               for heading in headings):
            return candidate

        tags: list[str] = []
        for tag_node in soup.select("[data-test*='keyword'], [class*='badge'], [class*='tag'], [class*='tech'], [class*='skill']"):
            if tag_node.find(class_=re.compile(r"badge|tag|keyword|tech|skill")):
                continue
            t = normalized_text(tag_node).strip()
            if t and len(t) < 50 and t not in tags:
                tags.append(t)

        description_node = soup.select_one("#job-description, .job-description, article")
        desc_text = normalized_text(description_node) if description_node else ""
        if not desc_text:
            return ExtractionCandidate(company=company, role=role)

        sections: list[str] = []
        if tags:
            sections.append("PORTAL TECHNOLOGY TAGS\n" + "\n".join(tags))
        if desc_text:
            sections.append(f"OFFER DESCRIPTION\n{desc_text}")

        if sections:
            return ExtractionCandidate(
                company=company,
                role=role,
                job_description="\n\n".join(sections),
            )

        return candidate

    def extract_text(self, text: str) -> ExtractionCandidate:
        # Markdown copies may include literal icon names glued to text.
        text = re.sub(r"\bsvg|svg(?=[A-ZĄĆĘŁŃÓŚŹŻ]|$)", "\n", text, flags=re.M)
        raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not raw_lines:
            return ExtractionCandidate()

        # Check if text is JSON
        if text.strip().startswith("{") and text.strip().endswith("}"):
            try:
                data = json.loads(text)
                if isinstance(data, dict) and "title" in data:
                    return candidate_from_job_data(data)
            except Exception:
                pass

        if raw_lines and re.match(r"^to jest opis\b", raw_lines[0], re.I):
            raw_lines.pop(0)

        prelude: list[str] = []
        sections: dict[str, list[str]] = {}
        active: str | None = None
        started = False

        for raw_line in raw_lines:
            clean_line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", raw_line)
            clean_line = re.sub(r"^\s*(?:#{1,6}\s+|[-*•]\s+)", "", clean_line).strip()
            clean_line = clean_line.strip("* ").rstrip("\\").strip()
            if not clean_line or clean_line in {"-", "*", "•"}:
                continue

            folded = clean_line.casefold().rstrip(":")
            if folded in ELDORADO_HEADINGS:
                active = ELDORADO_HEADINGS[folded]
                started = True
                continue

            if not started:
                prelude.append(clean_line)
                continue

            if active and folded not in ELDORADO_UI_NOISE and not folded.startswith("źródło:"):
                section_lines = sections.setdefault(active, [])
                if clean_line not in section_lines:
                    section_lines.append(clean_line)

        clean_prelude = [
            p
            for p in prelude
            if p.casefold() not in ELDORADO_UI_NOISE
            and not p.startswith("#")
            and not NUMERIC_BADGE.match(p)
            and not p.casefold().startswith(("dodano", "źródło:", "#"))
            and "(image)" not in p.casefold()
        ]

        candidate_names: list[str] = []
        emp_conditions: list[str] = []

        for item in clean_prelude:
            if SENIORITY_WORDS.match(item):
                emp_conditions.append(f"Poziom doświadczenia: {item}")
            elif SALARY_PATTERN.search(item):
                if not any(item in cond for cond in emp_conditions):
                    emp_conditions.append(f"Wynagrodzenie: {item}")
            elif EMPLOYMENT_WORDS.search(item):
                if item not in emp_conditions:
                    emp_conditions.append(item)
            else:
                candidate_names.append(item)

        unique_names: list[str] = []
        for name in candidate_names:
            if name not in unique_names:
                unique_names.append(name)
        candidate_names = unique_names

        company = ""
        role = ""

        # First, check if role/company can be extracted from an inline summary line
        for line in raw_lines:
            m = re.search(r"Oferta pracy na stanowisko (.+?) w firmie (.+?)(?:\s*\(|\.|$)", line, re.I)
            if m:
                role = role or m.group(1).strip()
                company = company or m.group(2).strip()
                break

        role_candidates = [n for n in candidate_names if ROLE_WORDS.search(n)]
        company_candidates = [n for n in candidate_names if not ROLE_WORDS.search(n)]

        if not company:
            for name in company_candidates:
                if COMPANY_SUFFIXES.search(name):
                    company = name
                    break
            if not company and company_candidates:
                company = company_candidates[0]

        if not role:
            if role_candidates:
                role = role_candidates[0]
            elif candidate_names:
                role = next((n for n in candidate_names if n != company), candidate_names[0])

        remaining_tags = [item for item in candidate_names if item != company and item != role]
        if remaining_tags:
            current_tags = sections.setdefault("PORTAL TECHNOLOGY TAGS", [])
            for t in remaining_tags:
                if t not in current_tags:
                    current_tags.append(t)

        if emp_conditions:
            current_emp = sections.setdefault("EMPLOYMENT CONDITIONS", [])
            for c in emp_conditions:
                if c not in current_emp:
                    current_emp.append(c)

        if "OFFER DESCRIPTION" in sections:
            real_desc = [
                line
                for line in sections["OFFER DESCRIPTION"]
                if not line.startswith("[UWAGA:") and not line.startswith("Oferta pracy na stanowisko")
            ]
            if real_desc:
                sections["OFFER DESCRIPTION"] = real_desc

        if "OFFER DESCRIPTION" not in sections or not sections["OFFER DESCRIPTION"]:
            if role or company or sections:
                summary = f"Oferta pracy na stanowisko {role}" if role else "Oferta pracy"
                if company:
                    summary += f" w firmie {company}"
                summary += " (serwis Czy Jest Eldorado)."
                sections["OFFER DESCRIPTION"] = [summary]

        order = (
            "EMPLOYMENT CONDITIONS",
            "PORTAL TECHNOLOGY TAGS",
            "OFFER DESCRIPTION",
            "RESPONSIBILITIES",
            "REQUIREMENTS",
            "NICE TO HAVE",
        )

        formatted_sections = [
            f"{heading}\n" + "\n".join(sections[heading])
            for heading in order
            if sections.get(heading)
        ]

        if not formatted_sections:
            formatted_sections.append(f"OFFER DESCRIPTION\nOferta pracy: {role} w {company} (Czy Jest Eldorado).")

        return ExtractionCandidate(
            company=company,
            role=role,
            job_description="\n\n".join(formatted_sections),
        )

    def _extract_json_script(self, html: str) -> ExtractionCandidate | None:
        soup = cleaned_soup(html)
        for script in soup.find_all("script", attrs={"type": re.compile(r"json", re.I)}):
            raw = script.string or script.get_text()
            if not raw or "title" not in raw:
                continue
            try:
                payload = json.loads(raw)
                job = self._find_job_in_obj(payload)
                if job:
                    return candidate_from_job_data(job)
            except Exception:
                continue
        return None

    def _find_job_in_obj(self, obj: Any) -> dict[str, Any] | None:
        if isinstance(obj, dict):
            if "title" in obj and ("company" in obj or "keywords" in obj):
                return obj
            for val in obj.values():
                res = self._find_job_in_obj(val)
                if res:
                    return res
        elif isinstance(obj, list):
            for item in obj:
                res = self._find_job_in_obj(item)
                if res:
                    return res
        return None

    async def fetch_remote(
        self,
        url: str,
        guard: PublicUrlGuard,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> ExtractionCandidate | None:
        job_id = extract_job_id(url)
        if not job_id:
            logger.info("Could not extract job ID from Eldorado URL: %s", url)
            return None

        await guard.validate(self.mcp_endpoint)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "CVTailor/1.0 (+eldorado-mcp-integration)",
        }
        client_timeout = httpx.Timeout(timeout, connect=min(timeout, 5.0))

        async with httpx.AsyncClient(timeout=client_timeout, headers=headers, transport=transport) as client:
            init_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "cv-tailor", "version": "1.0.0"},
                },
            }
            init_resp = await client.post(self.mcp_endpoint, json=init_payload)
            init_resp.raise_for_status()
            session_id = init_resp.headers.get("mcp-session-id")
            if not session_id:
                logger.warning("No mcp-session-id received from Eldorado MCP")
                return None

            call_payload = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "search_jobs",
                    "arguments": {"phrase": f"#{job_id}"},
                },
            }
            call_resp = await client.post(
                self.mcp_endpoint,
                json=call_payload,
                headers={"mcp-session-id": session_id},
            )
            call_resp.raise_for_status()
            data = call_resp.json()

            jobs: list[dict[str, Any]] = []
            structured = data.get("result", {}).get("structuredContent")
            if isinstance(structured, dict) and isinstance(structured.get("jobs"), list):
                jobs = structured["jobs"]
            elif "result" in data and "content" in data["result"]:
                content_list = data["result"]["content"]
                if content_list and isinstance(content_list, list):
                    text_val = content_list[0].get("text", "")
                    if text_val:
                        try:
                            parsed_content = json.loads(text_val)
                            if isinstance(parsed_content, dict) and isinstance(parsed_content.get("jobs"), list):
                                jobs = parsed_content["jobs"]
                        except json.JSONDecodeError:
                            pass

            for job in jobs:
                if isinstance(job, dict) and extract_job_id(str(job.get("url", ""))) == job_id:
                    return candidate_from_job_data(job)

        return None
