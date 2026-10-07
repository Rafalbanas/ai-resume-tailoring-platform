from app.services.job_extractors.base import BaseExtractor, ExtractionCandidate, cleaned_soup, first_text, longest_text


class NoFluffExtractor(BaseExtractor):
    domains = ("nofluffjobs.com",)

    def extract(self, html: str) -> ExtractionCandidate:
        soup = cleaned_soup(html)
        return ExtractionCandidate(
            company=first_text(soup, ("[data-cy='company-name']", "[class*='company-name']", "nfj-posting-header h2")),
            role=first_text(soup, ("[data-cy='posting-title']", "h1", "nfj-posting-header h1")),
            job_description=longest_text(
                soup,
                ("[data-cy='job-description']", "#posting-description", "[class*='posting-content']", "main"),
            ),
        )
