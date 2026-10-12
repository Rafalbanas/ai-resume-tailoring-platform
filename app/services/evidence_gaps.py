"""A small, deterministic set of questions; answers require explicit consent."""
import hashlib
import re

from app.models.job import RequirementStatus as Status


def evidence_questions(analysis, limit=5):
    questions, seen = [], set()
    for requirement in analysis.requirements:
        if requirement.duplicate_of:
            continue
        for item in requirement.components or [requirement]:
            if item.status not in {Status.MISSING, Status.PARTIAL}:
                continue
            name = item.name.strip()
            key = ' '.join(name.casefold().split())
            if key in seen:
                continue
            seen.add(key)
            questions.append({'id': hashlib.sha256((requirement.id + '\0' + key).encode()).hexdigest()[:20],
                              'name': name, 'source_quote': requirement.source_quote,
                              'question': f'What knowledge or experience do you have with {name}? Specify what you did, where, and any limits.'})
            if len(questions) >= limit:
                return questions
    return questions


def answer_fact(question, answer, scope, context, details, *, consent):
    if not consent:
        raise ValueError('Explicit consent is required to save profile evidence.')
    if answer not in {'confirm', 'deny'} or scope not in {'theoretical', 'practical', 'professional'} or context not in {'education', 'project', 'employment', 'personal'}:
        raise ValueError('Choose a valid answer, scope and context.')
    details = ' '.join(details.split())
    if not 10 <= len(details) <= 500:
        raise ValueError('Describe the actual evidence or limitation in 10–500 characters.')
    name = question['name']
    # Employer proficiency/tenure words belong to the question, not a claimed
    # candidate level. Persist only the subject plus explicitly selected scope.
    name = re.sub(r'\b\d+(?:\.\d+)?\s*\+?\s*years?(?:\s+of)?\s*', '', name, flags=re.I)
    name = re.sub(r'\b[ABC][12]\+?(?!\w)', '', name, flags=re.I)
    prefix = r'^(?:minimum|at least|advanced|expert|solid|strong|basic|professional|practical|hands.on|awareness|familiarity|knowledge|understanding|experience|proficiency)\b\s*(?:of|with|in)?\s*'
    while re.match(prefix, name, re.I):
        name = re.sub(prefix, '', name, count=1, flags=re.I).strip()
    if not name:
        raise ValueError('A specific competence subject is required.')
    if answer == 'deny':
        prefix = f'No {"knowledge of" if scope == "theoretical" else "practical experience with"} {name}'
    elif scope == 'theoretical':
        prefix = f'Theoretical knowledge of {name}'
    else:
        prefix = f'{"Professional practical" if scope == "professional" else "Practical"} experience using {name}'
    return f'{prefix}. Context: {context}. User-confirmed evidence and limitations: {details}'
