"""Conservative literal PL/EN contract equivalence, not general translation.

Only explicit vocabulary is normalized. Unrecognized substantive words, named
products, numbers, negations and qualification levels remain in the fingerprint.
Unknown paraphrases are intentionally not merged by similarity.
"""
import re
import unicodedata

_PHRASES = [
    (r'przypadkow i scenariuszy testowych', 'testcases testscenarios'),
    (r'narzedzi do testowania api|api testing tools', 'apitestingtools'),
    (r'testowani[aeu] oprogramowania|software testing', 'softwaretesting'),
    (r'systemow analitycznych|analytical systems', 'analyticalsystems'),
    (r'rozwiazan opartych na danych|data.driven solutions', 'datadrivensolutions'),
    (r'przypadkow testowych|test cases', 'testcases'),
    (r'scenariuszy testowych|test scenarios', 'testscenarios'),
    (r'raportowania defektow|defect reports', 'defectreports'),
    (r'projektowania zestawow testowych|design test suites', 'testsuitedesign'),
    (r'oceny jakosci odpowiedzi modeli|evaluating model output quality', 'modeloutputquality'),
    (r'ekstrakcji informacji|information extraction', 'informationextraction'),
    (r'klasyfikacji|classification', 'classification'),
    (r'podstaw dzialania|basic understanding', 'basicunderstanding'),
    (r'ml (?:lub|or) llm', 'mlllm_alternative'),
    (r'testowania systemow niedeterministycznych|testing non.deterministic systems', 'nondeterministictesting'),
    (r'specyfiki|specifics', 'specifics'),
    (r'modeli|models', 'models'),
    (r'oceny wynikow models|evaluate model outputs', 'modelevaluation'),
    (r'zgodnosci ze zrodlem|source consistency', 'sourceconsistency'),
    (r'trafnosci|accuracy', 'accuracy'),
    (r'kompletnosci|completeness', 'completeness'),
    (r'bezpieczenstwa|security', 'security'),
    (r'uzytecznosci|usability', 'usability'),
    (r'testowaniu systemow rag|testing rag systems', 'ragtesting'),
    (r'chatbotow|chatbots', 'chatbots'),
    (r'asystentow ai|ai assistants', 'aiassistants'),
    (r'modeli predykcyjnych|models predykcyjnych|predictive models', 'predictivemodels'),
    (r'narzedzi do automatycznej ewaluacji llm|automated llm evaluation tools', 'llmevaluationtools'),
    (r'testow regresji promptow|prompt regression testing', 'promptregressiontesting'),
    (r'testach bezpieczenstwa rozwiazan genai|testach security rozwiazan genai|genai security testing', 'genaisecuritytesting'),
    (r'w tym|including', 'including'),
    (r'jailbreak testing|jailbreak', 'jailbreaktesting'),
    (r'wymagan dotyczacych|requirements', 'requirements'),
    (r'dostepnosci|accessibility', 'accessibility'),
    (r'prostego jezyka|plain.language', 'plainlanguage'),
]
_IGNORE = {
    'knowledge', 'znajomosc', 'experience', 'doswiadczenie', 'doswiadczenia',
    'minimum', 'at', 'least', 'years', 'year', 'lat', 'lata', 'of', 'in', 'w',
    'and', 'oraz', 'i', 'or', 'lub', 'ability', 'umiejetnosc', 'to', 'do', 'for',
    'creating', 'tworzenia', 'practical', 'praktyczna', 'basic', 'podstawowa',
    'the', 'pod', 'katem', 'based', 'on',
}


def bilingual_contract(text):
    value = unicodedata.normalize('NFKD', text.replace('ł', 'l').replace('Ł', 'L')).encode('ascii', 'ignore').decode().casefold()
    language = 'pl' if re.search(r'znajomo|doswiadczen|umiejetnosc|narzedzi|testowania', value) else 'en'
    original = value
    hits = 0
    for pattern, canonical in _PHRASES:
        value, count = re.subn(r'(?<!\w)(?:' + pattern + r')(?!\w)', canonical, value)
        hits += count
    if not hits:
        return None
    # Multiple numbers can bind to different branches, dates or product versions.
    # A set of translated words cannot safely prove those attachments equivalent.
    if len(re.findall(r'\d+(?:[.,]\d+)?\+?', original)) > 1:
        return None
    terms = frozenset(re.findall(r'[a-z0-9+#.]+', value.replace('.', ' '))) - _IGNORE
    if len(terms) < 2:
        return None
    level = ('advanced' if re.search(r'advanced|expert|bardzo dobr|zaawansowan', original)
             else 'practical' if re.search(r'practical|praktyczn', original)
             else 'basic' if re.search(r'\bbasic\b|podstaw', original) else '')
    logic = ('mixed' if re.search(r'\b(?:or|lub)\b', value) and re.search(r'\b(?:and|oraz|i)\b', value)
             else 'any' if re.search(r'\b(?:or|lub)\b', value) else 'all')
    # Do not interpret complex mixed or example-bearing conditions as equivalent.
    if logic == 'mixed' or re.search(r'such as|for example|\bnp\b|takich jak', original):
        return None
    return language, (terms, level, logic)


def equivalent_translation(left, right):
    a, b = bilingual_contract(left), bilingual_contract(right)
    return bool(a and b and a[0] != b[0] and a[1] == b[1])
