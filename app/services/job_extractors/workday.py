from app.services.job_extractors.base import BaseExtractor, ExtractionCandidate, cleaned_soup, first_text, longest_text


class WorkdayExtractor(BaseExtractor):
    domains = ("myworkdayjobs.com", "workday.com")

    def extract(self, html: str) -> ExtractionCandidate:
        soup = cleaned_soup(html)
        return ExtractionCandidate(
            company=first_text(
                soup,
                ("[data-automation-id='company']", "[data-automation-id='jobPostingCompany']", "meta[property='og:site_name']"),
            ),
            role=first_text(soup, ("[data-automation-id='jobPostingHeader']", "[data-automation-id='jobPostingTitle']", "h1")),
            job_description=longest_text(
                soup,
                ("[data-automation-id='jobPostingDescription']", "[data-automation-id='job-posting-details']", "main"),
            ),
        )
