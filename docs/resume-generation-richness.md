# Pełniejsza generacja CV — diagnoza i porównanie

## Przyczyny

Przepływ: profil → katalog faktów → retrieval → payload i schemat LLM →
recenzja podsumowania/bulletów → `FactValidator` → dopasowanie strony →
ponowna kontrola treści → PDF/DOCX i zapis.

Problemy nie sprowadzały się do prompta:

- Retrieval wybierał pojedyncze dopasowane fragmenty, bez metod/wyników tego
  samego projektu, gdy nie powtarzały słów z oferty.
- Walidator projektów narzucał dwuzdaniowy/500-znakowy opis i przypisywał
  **wszystkie** identyfikatory projektu, także niewidoczne w CV.
- Podsumowanie po przekroczeniu 500 znaków automatycznie zastępowano wersją
  kompaktową. Grupowanie kilku faktów projektu w jednym zdaniu maskowało
  skąpą strukturę. Dopasowanie wzorców supportowych pomijało inne obowiązki.
- Istniejący pojedynczy bullet doświadczenia uzupełniano tylko przy wybranych
  priorytetach analizy. Pełniejszy fallback uruchamiał się dopiero przy braku
  całej sekcji.
- Walidator zerował kolejność sekcji CV pod ofertę. Część rankingów i treści
  nie respektowała końca suwaka „oryginalny profil”.
- Starsze aliasy identyfikatorów dowodów w Skills Bank nie zawsze przekazywały
  priorytety do kanonicznych faktów. Kolejność umiejętności podana przez model
  potrafiła wyprzedzić ranking dopasowania do oferty.
- Eksport nowych Modern Sidebar wymuszał jedną stronę, usuwając szczegóły.
  Tekst główny miał 8,7 pt; sama zmiana prompta tego nie naprawiała.
- Domyślny budżet odpowiedzi Ollama dla CV wynosił 4096 tokenów, a retry
  po ucięciu odpowiedzi dodatkowo ograniczał szczegółowość.

## Zmiany

- Ograniczone uzupełnianie kontekstu trafionych projektów, bez pobierania
  niezweryfikowanych treści z sieci ani przekraczania budżetu całych faktów.
- Nagłówek opisuje wyłącznie pełne, dozwolone etykiety kompetencji i prawdziwą
  profesję; może zaczynać się od kierunku aplikacji. Nie zmienia stanowisk.
- Summary: zwykle 3–5 zdań, maksymalnie 1100 znaków, bez sztucznego wypełniania
  limitu. Ważnego podpisu nie nadpisujemy z powodu krótkiej długości;
  kompletność nowych draftów bogatego profilu sprawdzamy przed `review_summary`.
  Podpis modelu nie zastępuje potwierdzenia właściciela dla parafrazy.
- Uzupełnianie skąpego doświadczenia odrębnymi faktami tego samego pracodawcy;
  zwykle 2–4 dla istotnych ról, krócej przy słabszej relewancji.
- Opis istotnego projektu może wykorzystać cel, implementację, metody
  i ewaluację. Budżet zależy od relewancji i suwaka, nie jest minimalną liczbą
  zdań. Pełne zdania, zakres akademicki/osobisty i kwalifikatory pozostają.
  Cytowania opisują wybrany materiał, nie cały ukryty katalog.
- Specjalizacja i zapisane podsumowanie pracy dyplomowej trafiają do katalogu
  jako **edukacja**, nie rzekome obowiązki zawodowe.
- Kolejność sekcji, projekty, kompetencje i szczegółowość reagują na suwak.
  0 = oferta na podstawie faktów, 1 = profil i jego kolejność.
  Ranking i ochrona obowiązkowych dowodów rozwiązują również starsze aliasy
  źródeł; wybór modelu nie wyprzedza już zweryfikowanej relewancji umiejętności.
- Generowane CV silnie preferuje jedną stronę, bez zmniejszania czytelności ani dopisywania faktów; druga strona dopuszczalna przy bogatym profilu. 90–95% to cel udziału CV jednostronicowych, NIE zapełnienie strony i NIE potwierdzona globalna statystyka.
- Eksport najpierw sprawdza pełną treść i odstępy, następnie pomija pojedynczo najmniej istotne, niechronione szczegóły, mierząc dokument po każdej zmianie.
  Zachowuje całe summary, najważny istotny projekt, tożsamości zatrudnienia, edukację, status nauki i dowody obowiązkowych wymagań. Jeśli to nie wystarcza, wraca do pełnej wersji wielostronicowej, bez pozostawienia próbnych usunięć.
- Modern Sidebar ma stały tekst główny 10 pt. Istniejąca jawna, twarda funkcja `one_page=True` jest dostępna i testowana osobno; standardowy eksport używa `prefer_one_page=True`. Preferencja działa również dla ATS Classic. Nie jest automatycznie narzucana przy indywidualnych instrukcjach Custom CV.
- Domyślny budżet CV Ollama: 6144 tokeny, nadal ograniczony konfiguracją
  `ollama_num_predict`. Jawne ustawienia użytkownika nie są nadpisywane.
- Ręcznie zachowywane opisy i kolejność nie są automatycznie rozbudowywane.

## Porównanie przed/po

Ten sam fikcyjny profil, te same trzy oferty, ten sam celowo ubogi draft.
Pomiar wykonano przed zmianami i po zmianach. **To test deterministycznej
selekcji/walidacji i prawdziwego renderowania, nie ocena odpowiedzi żywego LLM.**

Wyniki dla `tailoring_level=0`:

| Miara | ML Engineer | Technical Support Engineer | DevOps Engineer |
|---|---:|---:|---:|
| Zdania summary | 3 → 4 | 2 → 4 | 3 → 4 |
| Znaki summary | 254 → 248 | 177 → 239 | 174 → 297 |
| Bullety doświadczenia, kolejno pracodawcy | 1/1 → 2/1 | 2/1 → 4/1 | 2/1 → 4/3 |
| Odrębne widoczne fakty doświadczenia/projektów | 7 → 11 | 6 → 9 | 7 → 14 |
| Znaki opisów projektów łącznie | 175 → 452 | 123 → 249 | 185 → 369 |
| Koniec widocznego tekstu / wysokość obszaru A4 | 51% → 64% | 51% → 60% | 51% → 69% |
| Strony Modern Sidebar | 1 → 1 | 1 → 1 | 1 → 1 |

Nie zwiększano tekstu sztucznie: ML summary jest nieco krótsze, ale zamiast
dwóch faktów projektu w jednym zdaniu łączy profesję, transferowalną automatyzację
Python, akademicki pipeline i wykształcenie. Szczegółowe metody i ewaluacja są
w projekcie. W docelowej treści rozpoznawane jest odpowiednio 11, 9 i 14
odrębnych faktów doświadczenia/projektów (bez liczenia etykiet umiejętności,
tożsamości i dyplomu jako dodatkowych osiągnięć).

„Koniec tekstu” to geometria rzeczywistych wierszy, **nie procent powierzchni
pokrytej tuszem** ani wymóg wypełnienia strony. Krótki profil nie jest rozdymany
do 90–100%.

Przykładowe nagłówki:

- ML: `Technical Support Engineer (L2)` →
  `Python & Machine Learning | Technical Support Engineer (L2)`.
- Support: pozostaje faktyczna, zgodna z celem profesja.
- DevOps: `Technical Support Engineer (L2)` →
  `Linux & Docker | Technical Support Engineer (L2)`.

Dla ML projekty i edukacja poprzedzają zatrudnienie; dla Support doświadczenie
jest przed projektami; dla DevOps najsilniejszy projekt to osobiste laboratorium
operacyjne. Przy 1.0 wraca nagłówek profesji, źródłowa kolejność projektów i
sekcji. Parametry 0, 0.5, 1 są testowane.

## Odtworzenie i ograniczenia

```bash
PYTHONPATH=. .venv/bin/python scripts/compare_resume_richness.py \
  --output /tmp/opencode/resume-richness-after.json
.venv/bin/python -m pytest -q tests/test_resume_richness.py \
  tests/test_fact_retrieval.py tests/test_retrieval_owner_context.py
```

JSON zawiera treść summary i projektów, liczniki, kolejność, poziom suwaka,
cytowania i geometrię. Pomiar bazowy z tej sesji:
`/tmp/opencode/resume-richness-before.json`; aktualny:
`/tmp/opencode/resume-richness-after.json`. Są to wyłącznie dane fikcyjne.

Testy obejmują oba szablony, PDF i DOCX, pełne fakty, właścicieli cytowań,
chronologię, brak niepotwierdzonych Kubernetes/Terraform, poziomy Basic,
learning oraz zachowanie ręcznych zmian i idempotencję.
Dziewięć fikcyjnych kombinacji rola/suwak mieści się na jednej stronie.
Nie jest to statystyczny dowód osiągnięcia 90–95% dla dowolnego profilu/oferty.

Nie wykonywano płatnych/zdalnych generacji ani wdrożenia. Nie znaleziono
lokalnie zapisanego CV/oferty Remodevs, więc nie przedstawiamy tego benchmarku
jako ponownej generacji dokładnie tej aplikacji. Osobny odczyt aktywnego
profilu sprawdzono offline; danych osobowych ani CV nie dołączono do repo.
Surowy README repozytorium nie staje się automatycznie zweryfikowanym faktem:
bogatsze techniczne twierdzenia muszą już istnieć w dozwolonym katalogu.

## Walidacja integracji z aktualnym main

- Środowisko Python 3.14.8 zgodne z przypiętymi zależnościami:
  `check_environment.py --dev` i `pip check` przechodzą.
- Benchmark powtórzony po integracji: **9/9** fikcyjnych kombinacji
  rola/suwak na jednej stronie. Wyniki widocznych faktów dla poziomu 0
  pozostają 11 / 9 / 14. To nie dowodzi globalnego odsetka 90–95%.
- Szerszy przebieg: 260 zaliczonych, 3 niezaliczone testy.
  Poprawiono dwa błędne oczekiwania potwierdzenia dla dosłownych źródeł
  oraz stare oczekiwanie nagłówka. Kolejny przebieg wykrył fixture kolejki,
  którego krótki tekst celowo podlegał rozbudowie; fixture dostosowano
  do testowania izolacji kolejki, bez wyłączania kontroli treści.
- Pełna walidacja zamrożonej rewizji i CI są wymagane przed scaleniem.
  W tej sekcji nie deklarujemy jeszcze zielonego pełnego przebiegu.
- `ruff check .`, `git diff --check` i synchronizacja README przechodzą
  w czystym worktree; cudze artefakty nie są częścią tej zmiany.

## Historyczne wyniki wcześniejszego drzewa roboczego

- Wcześniejszy czysty przebieg selekcji, Truth Lock, obu eksportów, dopasowania A4,
  podsumowań i retrieval: **190 passed, 1 skipped**.
  Polecenie: `pytest -q tests/test_preferred_one_page.py
  tests/test_rendered_source_fragments.py tests/test_fact_validator.py
  tests/test_fact_retrieval.py tests/test_hybrid_retrieval.py
  tests/test_retrieval_owner_context.py tests/test_resume_richness.py
  tests/test_content_quality.py tests/test_*summary*.py`.
- Szerszy powtórny przebieg regresji, obejmujący również wszystkie testy
  niezaliczone w pierwszym pełnym uruchomieniu, zaliczył 290 testów.
  Cztery pozostałe przypadki naprawiono i ponownie sprawdzono:
  6/6 ukierunkowanych testów przeszło, następnie cały moduł content quality
  przeszedł również w powyższym końcowym przebiegu.
- Pierwsze pełne `pytest -q`: 2513 passed, 21 failed, 8 errors, 1 skipped.
  Były wśród nich błędy implementacji/oczekiwań poprawione powyżej oraz timeouty
  Chromium i procesora PDF przy równoległym obciążeniu hosta (4,2 GiB RAM,
  bez swapu). **Pełnego zestawu nie powtórzono po końcowych poprawkach**;
  nie przedstawiamy go jako zielonego.
- `ruff check app tests scripts`, `git diff --check`,
  `python scripts/sync_readme.py --check`: OK.
  Globalny `ruff check .` zgłasza 50 problemów w istniejącym, niezmienianym
  `artifacts/emfire-demo/scripts`; nie poprawiano cudzych artefaktów poza zakresem.
