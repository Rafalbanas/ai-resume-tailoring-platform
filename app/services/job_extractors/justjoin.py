from app.services.job_extractors.base import BaseExtractor, ExtractionCandidate, cleaned_soup, first_text, longest_text


class JustJoinExtractor(BaseExtractor):
    domains = ("justjoin.it",)

    def extract(self, html: str) -> ExtractionCandidate:
        soup = cleaned_soup(html)
        return ExtractionCandidate(
            company=first_text(soup, ("[data-test-id*='company']", "[class*='company'] a", "main h2")),
            role=first_text(soup, ("[data-test-id*='title']", "main h1", "h1")),
            job_description=longest_text(
                soup,
                ("[data-test-id*='description']", "[class*='job-description']", "[class*='JobDescription']", "main"),
            ),
        )
