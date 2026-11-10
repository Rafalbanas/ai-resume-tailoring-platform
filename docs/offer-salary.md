# Salary ranges in History

Job offers have an optional **Salary range / Widełki** field. Enter the employer's
terms, including currency, period, gross/net and contract type, e.g.
`10 000–15 000 PLN netto + VAT / mies. · B2B`.
The form and History editor accept multiple lines, so separate contracts/rates
remain separate when autofilled, reviewed and submitted.
Synthetic editor previews: [mobile](images/offer-salary-multiline-mobile.png) ·
[desktop](images/offer-salary-multiline-desktop.png).

The app attempts local, text-based extraction from the saved offer description
when no field is supplied. URL extraction and pasted-text cleaning expose the
same field. Extraction is conservative, not a guarantee: review the value and
correct it if needed. All recognized variants are retained, rather than choosing
one contract: for example, both gross employment pay and net B2B pay plus VAT.
Pracuj header widgets are retained even when amounts and contract/tax/period
labels occupy separate lines. Rates in different currencies or periods remain
separate; the app does not convert or compare them. The field still has a
500-character limit, so unusually long sets of terms need manual review. Terms
available only in unsupported portal widgets or structured data outside the
extracted description may need manual entry.

History shows the terms directly, for generated CVs and saved analyses. Expand
**Edit salary / Edytuj widełki** to update them after a recruiter call or clear the
field. Reports also display the field. Editing saved salary metadata does not
rewrite reports, CV content or exports. Demo accounts cannot edit it.

Legacy offers are read from their saved descriptions without a migration or AI
call. No amounts, currencies, tax terms or periods are inferred when absent.
An explicitly cleared saved field remains blank. Custom CVs have no offer salary.
