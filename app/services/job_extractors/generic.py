from app.services.job_extractors.base import (
    BaseExtractor,
    ExtractionCandidate,
    cleaned_soup,
    first_text,
    longest_text,
    normalized_text,
)


class GenericHtmlExtractor(BaseExtractor):
    def extract(self, html: str) -> ExtractionCandidate:
        soup = cleaned_soup(html)
        role = first_text(
            soup,
            (
                "[itemprop='title']",
                "[data-testid*='job-title']",
                "[class*='job-title']",
                "[class*='jobTitle']",
                "main h1",
                "h1",
            ),
        )
        company = first_text(
            soup,
            (
                "[itemprop='hiringOrganization'] [itemprop='name']",
                "[itemprop='hiringOrganization']",
                "[data-testid*='company']",
                "[class*='company-name']",
                "[class*='companyName']",
                "meta[property='og:site_name']",
            ),
        )
        if not company:
            meta = soup.select_one("meta[property='og:site_name']")
            company = normalized_text(meta.get("content", "") if meta else "")
        description = longest_text(
            soup,
            (
                "[itemprop='description']",
                "[data-testid*='description']",
                "[data-test*='description']",
                "[class*='job-description']",
                "[class*='jobDescription']",
                "[id*='job-description']",
                "[id*='jobDescription']",
                "main",
                "article",
            ),
        )
        return ExtractionCandidate(company=company, role=role, job_description=description)
