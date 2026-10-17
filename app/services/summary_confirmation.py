"""A model verdict and the account user's confirmation are distinct decisions."""
import hashlib
import hmac
import json
import secrets

from fastapi import HTTPException

from app.services.fact_catalog import FactCatalog
from app.services.summary_review import sign_summary, valid_source_summary, valid_summary_attestation


def account_context(username, kind, identity):
    # Do not rely on operators choosing distinct CSRF secrets for every account.
    return json.dumps([username, kind, identity], separators=(',', ':'))


def confirmation_token(resume, profile, key, context):
    message = f'summary-user-confirmation-v1:{context}:{sign_summary(resume, profile, key)}'
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()


def summary_review(resume, profile, key, context, receipt=''):
    catalog = FactCatalog(profile)
    sources = catalog.valid(resume.summary_source_fact_ids)
    exact = (catalog.supports_paraphrase(resume.professional_summary, resume.summary_source_fact_ids)
             or valid_source_summary(resume, profile, key))
    token = confirmation_token(resume, profile, key, context)
    confirmed = isinstance(receipt, str) and receipt.isascii() and secrets.compare_digest(receipt, token)
    return {'text': resume.professional_summary, 'sources': sources,
            'model_reviewed': valid_summary_attestation(resume, profile, key),
            'source_text': exact, 'confirmed': confirmed, 'required': not (exact or confirmed), 'token': token}


def require_confirmation(review, checked, supplied):
    if review['required'] and (checked != 'on' or not isinstance(supplied, str) or not supplied.isascii()
            or not secrets.compare_digest(supplied, review['token'])):
        raise HTTPException(409, 'Review the professional summary and its sources, then explicitly confirm it before exporting.')
