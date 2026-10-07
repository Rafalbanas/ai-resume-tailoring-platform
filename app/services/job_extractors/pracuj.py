from app.services.job_extractors.base import BaseExtractor, ExtractionCandidate, cleaned_soup, first_text, longest_text


class PracujExtractor(BaseExtractor):
    domains = ("pracuj.pl",)

    def extract(self, html: str) -> ExtractionCandidate:
        soup = cleaned_soup(html)
        return ExtractionCandidate(
            company=first_text(soup, ("[data-test='text-employerName']", "[data-test='link-employer']", "[class*='employer']")),
            role=first_text(soup, ("[data-test='text-positionName']", "main h1", "h1")),
            job_description=longest_text(
                soup,
                ("[data-test='section-responsibilities']", "[data-test='section-requirements']", "[data-test*='section']", "main"),
            ),
        )
