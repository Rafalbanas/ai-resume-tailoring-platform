# Audyt kontekstu Ollamy — 23 października 2026

Audyt nie zmienia modelu produkcyjnego, aktywnej konfiguracji ani danych użytkownika. Prototypy w tym katalogu nie są importowane przez aplikację.

## Metoda

Użyto rzeczywistych żądań `/api/chat` z tego samego profilu i polskiej oferty Specjalista / Specjalistka IT. Profil zawiera 4 zatrudnienia, 3 wpisy edukacji i 3 projekty. Analiza otrzymuje 203 rekordy dowodów. RAG kontrolnego generowania wybrał 29 faktów, a lista dopuszczonych umiejętności miała 41 pozycji.

Tokeny policzono oficjalnym tokenizerem Qwen3.8. Jego słownik zgadza się ze słownikami obu modeli; różnice dotyczą wyłącznie nieużywanych tokenów `[PAD...]`. Dla zaakceptowanych żądań liczba tokenów wiadomości plus obudowa czatu zgadza się z `prompt_eval_count`. Udziały pól policzono przez przypisanie offsetów tokenów do pól rzeczywiście wysłanego JSON-u. Token przekraczający granicę pól przypisano do pola obejmującego największą część jego zakresu. Liczby sumują się do całego promptu; nie użyto przelicznika znaków.

Każde żądanie ma tylko dwie wiadomości: systemową i użytkownika. Historia wcześniejszych rozmów zajmuje 0 tokenów. Kolejne etapy ponownie przesyłają fakty w nowych żądaniach. `review_notes` są danymi kolejnego promptu, nie historią czatu.

Schemat przekazany w `format` jest gramatyką odpowiedzi. W tych żądaniach nie jest dodawany do promptu. Jego rozmiar jako tekstu podano osobno. Rezerwa odpowiedzi również nie jest zużytym wejściem. Przy błędach HTTP przed uruchomieniem modelu rozróżniamy dokładną tokenizację przygotowanej treści od braku pomiaru API.

W trakcie benchmarku zewnętrzne wdrożenie wymieniło pod i przerwało jedną próbę. Nie była to awaria modelu. Dalsze testy wykonano w oddzielnych podach z przypiętymi obrazami i wszystkimi wolumenami danych tylko do odczytu. Starszy obraz: `d5691c0d0bb594a2e834c14ae28cb8e6fcc47ad11c31fc441ddb91cd39da4139`; aktualny: `acd3c69a486be1add9716e2c98717f92193989126a631949e140ba8895b82196`. Ich wyników nie należy łączyć w średnią. `fact_retrieval.py` i `ai_provider.py` nie zmieniły się; zmieniły się m.in. analiza, provider i walidacja.

## Rzeczywiste 11 485 tokenów generowania

| Składnik | Tokeny | Udział |
|---|---:|---:|
| Instrukcje systemowe, w tym Truth Lock | 1005 | 8,75% |
| Oferta | 743 | 6,47% |
| Rola i firma | 29 | 0,25% |
| Polityka dopasowania | 96 | 0,84% |
| Wymagania, dowody i oceny `analysis_summary` | 2087 | 18,17% |
| `candidate_facts` | 1790 | 15,59% |
| `source_catalog` | 1583 | 13,78% |
| Diagnostyka `retrieval` | 2290 | 19,94% |
| `eligible_skills` | 1751 | 15,25% |
| Pusta lista referencyjnych CV | 7 | 0,06% |
| Dwie kopie wskazówek układu | 80 | 0,70% |
| Znacznik etapu | 7 | 0,06% |
| Obudowa czatu | 17 | 0,15% |
| **Razem** | **11 485** | **100%** |

Historia: 0. Schemat: 2479 tokenów tekstu na poziomie protokołu, ale 0 tokenów kontekstu. Limit odpowiedzi kontrolnego żądania: 4096, oddzielnie od wejścia. W pełnym przebiegu po nowej analizie oferta wygenerowała prompt CV mający 12 290 tokenów; przyrost dotyczył głównie wymagań i uzasadnień. 11 485 nie jest stałą wielkością wszystkich żądań.

### Powielenia i zbędne pola

* Wszystkie 29 wybranych rekordów występuje dosłownie w `source_catalog` i grupach `candidate_facts`. Osobna chronologia zatrudnienia i linki projektów nie są tymi kopiami i muszą zostać.
* `retrieval.selected` ponownie podaje ID, właścicieli i typy tych samych źródeł oraz dodaje wyniki BM25, przyczyny wyboru i rankingi. Samo `selected` ma 1721 tokenów przy niezależnej tokenizacji wartości, a `queries` kolejne 446. To potrzebna diagnostyka serwerowa, nie źródło faktów dla generatora.
* `analysis_summary.key_requirements` jest dokładną kopią nazw z `requirements_with_evidence`. Prototyp usuwa ją tylko po sprawdzeniu równości obu list. Pełne wymagania, priorytety, oceny, cytaty, poziomy, uzasadnienia i dowody pozostają.
* `layout_guide` i `layout_constraints` są identyczne.
* Etykiety `evidence` przy 41 dopuszczonych umiejętnościach powtarzają opisy źródeł. Prototyp zachowuje każde ID, nazwę, dokładne dopuszczone sformułowanie i poziom. Pełny bank oraz kontrola dopuszczalności pozostają na serwerze.

## Rzeczywiste 10 156 tokenów analizy

| Składnik | Tokeny | Udział |
|---|---:|---:|
| Instrukcje | 717 | 7,06% |
| Wszystkie fragmenty oferty i ich metadane | 1963 | 19,33% |
| 203 rekordy `evidence` | 6142 | 60,48% |
| Tabela właścicieli | 1157 | 11,39% |
| Daty i tożsamości zatrudnienia | 154 | 1,52% |
| Znacznik etapu | 6 | 0,06% |
| Obudowa czatu | 17 | 0,17% |
| **Razem** | **10 156** | **100%** |

Schemat: osobno 1913 tokenów tekstu, 0 tokenów wejścia modelu. 203 rekordy zawierają 192 różne teksty faktów. Nie wolno deduplikować ich tylko po tekście: ten sam tekst może mieć innego właściciela lub inną siłę dowodu. Teksty faktów tokenizowane niezależnie mają 3212 tokenów; pozostały koszt tabel to struktura, identyfikatory i etykiety. 3212 nie jest kolejną addytywną pozycją powyższej tabeli.

Analiza nie używa RAG generowania. W prototypie zachowano wszystkie 203 rekordy, pełne teksty, właścicieli, siłę dowodów, daty i wszystkie 46 fragmentów oferty. Każda partia nadal ma pełen katalog dowodów.

### Dlaczego planner odrzucał 16 384

`estimate_tokens` liczy bajty UTF-8 podzielone przez dwa. `plan_batches` dodaje tak oszacowany schemat, stałe 1536 i limit odpowiedzi. Dla kontrolnego żądania daje:

```text
18 368 szacunek payloadu, chociaż tokenizer nalicza 9422
 2 347 szacunek schematu, który nie jest wejściem modelu
 1 536 stała rezerwa
 8 192 maksymalna odpowiedź
------
30 443 wynik planera, a nie rzeczywisty prompt
```

Przy odpowiedzi 8192 faktyczne `10 156 + 8192` także przekracza 16 384: sama wymiana przelicznika nie wystarcza. Przy 4096 faktyczne żądanie mieści się, ale stary planner wciąż je odrzuca. Ponadto stary model wygenerował w analizie 4832 tokeny, więc stałe 4096 może oznaczać ucięcie i dodatkowe wywołania naprawcze.

## Przeglądy też ponownie przesyłają profil

Kontrolny `review_draft_thinking` miał 8437 tokenów: pełne fakty 6532 (77,42%), oferta 743 (8,81%), luki 431 (5,11%), bullety 344 (4,08%), instrukcje 201 (2,38%), daty 112 (1,33%), rola 13, znacznik etapu 8 i obudowa z prefiksem reasoning 53. Historii czatu nie było.

Nowy model zużywał całe 1024 tokeny thinking; końcowy werdykt nie kończył się przed wspólnym limitem 90 s. W dwóch pełnych próbach nie dał podpisanych akceptacji bulletów. W kontrolnej próbie starego modelu przegląd zaakceptował 8 bulletów, lecz walidator nadal musiał przywrócić m.in. zakres „Assisted”. Nie dowodzi to, że thinking zawsze poprawia jakość.

`review_summary` ma kosztowny bezpieczny fallback: stary model pominął `summary_source_fact_ids`, więc przegląd otrzymał 130 faktów i 6322 tokeny. Przy 9 poprawnych ID nowego modelu miał 1384 tokeny. Nie wolno oszczędzać przez zaakceptowanie brakujących cytowań. Należy poprawić kontrakt cytowań i zachować weryfikację.

## Prototypy i zachowane zabezpieczenia

V1 (`prototype_v1.py`) usuwa tylko udowodnione powielenia generowania i liczy dokładny budżet przy odpowiedzi 4096. Tokenizacja dokładnie tego samego przechwyconego żądania po przebudowie daje **6592 zamiast 11 485 tokenów, o 42,6% mniej**; sam payload spada z 10 463 do 5570. 6592 jest dokładnym wynikiem tokenizera przygotowanej treści, a nie zmyślonym pomiarem czasu inferencji. W rzeczywistych pełnych przebiegach zmieniały się wyniki analizy: API naliczyło 7356 tokenów wejścia generowania nowego modelu i 7668 starego. Zachowano dokładnie ten sam katalog, edukację, chronologię, linki, wymagania i dopuszczone umiejętności. Test sprawdza też, że nieznany, niedublowany fakt nie zostaje usunięty i że wejście nie jest mutowane.

V1 ujawnia koszt uboczny: niższy limit odpowiedzi tworzy dodatkowe partie analizy, które znowu wysyłają wszystkie fakty. Mniejszy prompt CV nie musi oznaczać tańszego całego zadania.

V2 (`prototype.py`) dodatkowo koduje właścicieli jako wiersze z jawnymi nazwami kolumn, a siłę dowodów jako odwracalne aliasy z jawnym słownikiem. Testowana jest dokładna rekonstrukcja wszystkich rekordów i właścicieli. `context_only` zostaje na serwerze; model nadal dostaje pełny tekst, sekcję, wskazówki i `requires_assessment`. Instrukcje wyjaśniają nowy zapis.

Kontrolny prompt analizy V2 ma **9373 tokeny**, a budżet wynosi `9373 + 6144 odpowiedź + 512 margines = 16 029`. Limit CV pozostaje 4096. Każde żądanie ma dokładny preflight. Przekroczenie budżetu kończy się odmową wymagającą przeglądu, a nie obcięciem faktów. Pokrycie oferty, obsługa ucięcia odpowiedzi, kanoniczne ID, bank umiejętności, Truth Lock i podpisy pozostają aktywne.

Oddzielna naprawa testowa obsługuje `enum: []`, gdy RAG nie wybrał projektu: schemat wymusza wtedy pustą listę i usuwa nieużywaną definicję. Nie dodaje fikcyjnej nazwy, technologii ani źródła. To naprawa poprawności, nie oszczędność tokenów.

## Konkretne miejsca zmian

* `fact_retrieval.py`: zachować kotwice edukacji i chronologii, wybór faktów oraz ślad na serwerze. Nie obniżać `TOP_K` ani `MAX_CONTEXT_CHARS`, aby ukryć koszt serializacji. Limit znaków tekstów faktów nie ogranicza tokenów całego żądania.
* `ai_provider.py:201–214, 255–292`: jeden katalog faktów, osobno chronologia i linki, diagnostyka poza wejściem modelu. Usunąć dokładne kopie nazw wymagań i układu. Builder współdzieli Gemini; jego kontrakt wymaga oddzielnej weryfikacji przed wdrożeniem.
* `ollama_analysis.py`: dokładny tokenizer zgodny z modelem, rzeczywiste instrukcje, osobny limit odpowiedzi i margines; gramatyki nie doliczać do promptu. Zachować pełny katalog dowodów i pokrycie każdej partii.
* `ollama_provider.py`: poprawić puste zbiory dozwolonych wartości; nie utożsamiać poprawnego JSON-u z poprawnym powiązaniem wymagania ze źródłem.

Ważne są również pola opcjonalne schematu: samo `minItems` nie wymusza obecności `education` ani `summary_source_fact_ids`, jeżeli pola nie znajdują się w `required`. Gdy profil zawiera edukację, należy wymagać jej źródeł oraz cytowań podsumowania i nadal niezależnie sprawdzać kompletność. To poprawia kontrakt modelu; nie zastępuje odbudowy danych i Truth Lock.

Zapisano tylko materiały audytu. Pełne przechwycone CV i dane kontaktowe nie trafiają do repozytorium. Wyniki pomiarów i rozbicie każdego przechwyconego żądania są zapisane w towarzyszących plikach wynikowych.

## Wyniki na aktualnym kodzie: bazowy kontra V2

Wszystkie cztery próby wykorzystywały ten sam profil i ofertę, aktualny przypięty obraz oraz wyłączony opcjonalny przegląd draftu. Nie obniżano progów walidacji. Kolumna czasu oznacza czas **do odmowy**, nie czas wytworzenia poprawnego CV. Ładowanie to suma `load_duration` zakończonych odpowiedzi API i jest już zawarte w czasie całkowitym.

| Model | Wariant | Kontekst | Wejście analizy: kolejne wywołania API | Czas do wyniku | W tym ładowanie | Walidacja aplikacji / eksport |
|---|---|---:|---|---:|---:|---|
| Qwen3.5 9B | Bazowy | 32 768 | 10 187 | 105,08 s | 4,49 s | Odmowa: brak etykiety lub wyjaśnienia oceny; bez eksportu |
| Qwen3.5 9B | V2 | 16 384 | 9404 | 102,09 s | 4,02 s | Odmowa: klasyfikacja tagów i niewłaściwe dowody; bez eksportu |
| Qwen3.8 27B IQ2_S | Bazowy | 32 768 | 10 187 + 8636 | 262,47 s | 6,71 s | Odmowa: niepełne interpretacje i dowody; bez eksportu |
| Qwen3.8 27B IQ2_S | V2 | 16 384 | 9404 + 8048 | 246,11 s | 5,04 s | Odmowa: niepełne interpretacje i dowody; bez eksportu |

Pierwsze wejście analizy zmniejszyło się o 783 tokeny, **7,69%**. Stary model zwrócił w V2 4406 tokenów przy limicie 6144. Nowy zwrócił 3469, następnie 519 w próbie uzupełnienia. Cały katalog 203 faktów pozostał w każdym żądaniu. Budżet pierwszej analizy to `9404 + 6144 + 512 = 16 060`, czyli poniżej 16 384. Żaden wynik nie został zaakceptowany na siłę.

Wszystkie zwrócone tutaj odpowiedzi przechodziły sprawdzenie JSON oraz wysłanego schematu `format`. To nie jest równoznaczne ze spełnieniem pełnego kontraktu aplikacji: np. gałąź schematu dopuszczała ocenę bez etykiety, którą później odrzuca `validate_rows`. Niezależna walidacja źródeł słusznie zatrzymała pozostałe wyniki.

Przykłady nieusuniętych problemów: uznawanie tagów Microsoft 365/Intune/Entra ID za kwalifikacje, niepełne rozstrzygnięcie warunku „minimum 2 lata, najlepiej w środowisku wielu klientów”, nieadekwatne dowody dla praktycznej znajomości produktów oraz pominięte rozstrzygnięcia edukacji, PowerShella i dokumentowania pracy. Tego nie naprawia większa liczba tokenów.

## Dodatkowe próby i jakość CV na starszym obrazie

Ta tabela dokumentuje poprzednią wersję walidacji; nie dowodzi wiarygodności analizy w aktualnym kodzie. Czasy ukończonych prób obejmują analizę, generowanie, walidację, testowy eksport PDF/DOCX oraz odczyt tekstu. Nie obejmują interaktywnej akceptacji użytkownika. Używano wyłącznie Ollamy, bez Gemini i fallbacku, bez zapisów w historii.

| Model / wariant | Kontekst | Wynik i rzeczywiste czasy |
|---|---:|---|
| Qwen3.5 9B, bazowy, 3 próby | 32 768 | Odmowy po 110,60 / 98,69 / 99,00 s: `enum: []` dla projektów, nie awaria modelu |
| Qwen3.8 27B, bazowy bez przeglądu | 32 768 | 311,92 s; testowe PDF/DOCX powstały, lecz audyt znalazł złe powiązania wymagań z cytatami |
| Qwen3.8 27B, bazowy z przeglądem | 32 768 | 326,44 s; przegląd przekroczył 90 s, bez akceptacji bulletów |
| Qwen3.5 9B, V1 bez przeglądu | 16 384 | 210,34 s; PDF/DOCX po walidacji; pierwsza odpowiedź analizy ucięta przy 4096, potrzebne odzyskiwanie i dodatkowe wywołania |
| Qwen3.8 27B, V1 bez przeglądu | 16 384 | 352,01 s; PDF/DOCX po walidacji; dodatkowe partie i uzupełnienia analizy |

Trzeciej bazowej próby nowego modelu nie zaliczono jako porażki: przerwało ją zewnętrzne wdrożenie. Łącznie zapisano 11 prób pełnego pipeline'u oraz dodatkowe kontrole generowania i budżetu. Szczegóły dotyczące wszystkich zakończonych prób są w `measurements.json`.

Kontrola surowych CV V1 wykazała:

* Oba modele zachowały cztery rzeczywiste pary pracodawca/stanowisko; problemem były zakres twierdzeń i przypisanie faktów, nie zmyślenie nowej firmy.
* Stary model dopisał w podsumowaniu „Proven expertise ... Exchange Online, Entra ID, and Intune”, mimo braku takiej praktyki w profilu. Walidator odbudował podsumowanie. Jeden bullet używał dowodów innego pracodawcy.
* Nowy model miał trzy bullety z dowodami niewłaściwego pracodawcy. W starszej analizie wiązał „minimum 2 lata wsparcia IT” z cytatem o Comarch Optima. Formalny JSON był poprawny; semantyka źródła była błędna.
* Stary model podał 3 wpisy edukacji, nowy 0. Końcowy walidator przywrócił w obu przypadkach pełne 4 zatrudnienia i 3 edukacje. Wybrał 2 projekty; nie ma wymogu umieszczania wszystkich 3 w każdym CV.
* W końcowych testowych dokumentach zachowano 7 sprawdzonych, potwierdzonych słów kluczowych: Microsoft 365, Windows, PowerShell, DNS, VPN, MikroTik i FortiGate. Nie pozostały niepotwierdzone deklaracje Exchange Online, Entra ID i Intune. To sprawdzenie określonej listy, **nie procentowy wynik ATS** ani potwierdzenie wszystkich możliwych twierdzeń.

Na starszej walidacji dokument mógł więc technicznie powstać mimo błędu analizy. Aktualna walidacja odmawia; audyt nie omija tej ochrony.

V1 nowego modelu zużył w zakończonych wywołaniach API 35 579 tokenów wejścia wobec 30 843 w bazowym przebiegu bez przeglądu. Czas wzrósł z 311,92 do 352,01 s. Powodem były dodatkowe partie i uzupełnienia analizy oraz dodatkowy przegląd poprawnie cytowanego podsumowania. To dowód, że **nie należy po prostu ustawiać globalnie 4096 i obiecywać oszczędności całego procesu**.

## Rekomendacja

**Pozostawić produkcyjny `qwen3.5:9b` i obecną aktywną konfigurację.** Nowy model nie wykazał przewagi uzasadniającej zmianę: jest wolniejszy, mylił powiązania źródeł i nie rozwiązał problemów walidacji. Stary również potrafi dopisać niepotwierdzoną praktykę; nie należy używać jego surowego CV bez Truth Lock.

**16 384 jest wykonalnym budżetem wejścia i odpowiedzi na tych danych, lecz niezawodność całego pipeline'u przy tym limicie nie została potwierdzona.** Aktualny kod nie zakończył eksportu ani w bazowym 32 768, ani w V2 16 384. Nie ma podstaw do produkcyjnego obniżenia kontekstu na podstawie samego zmniejszenia promptu.

Kolejność dalszych zmian: poprawić kontrakt i powiązania ocen ze źródłami, rozróżnienie kwalifikacji od tagów oraz puste enum; wymagać edukacji i cytowań; następnie wprowadzić bezstratny payload i dokładne planowanie. Zachować obecne niezależne odmowy walidacji. Parametry do dalszych izolowanych testów: kontekst 16 384, analiza do 6144, CV do 4096, temperatura 0, jedno równoczesne żądanie i `keep_alive=15m`. To cele prototypu, nie zmieniona konfiguracja produkcji. Większe profile muszą otrzymać jawne dzielenie pracy lub odmowę zamiast usuwania dowodów.

Materiały: `token-breakdown.csv` i `token-breakdown.json` zawierają składniki **32 przechwyconych żądań**; `measurements.json` — próby, czasy, schema errors i walidację; `environment.json` — wersję biblioteki i sumę SHA256 tokenizera. Sumy wszystkich składników zostały uzgodnione z promptem, a wszystkie dostępne pomiary API zgadzają się z dokładnym tokenizerem. Pełne prywatne przechwycenia pozostają w `/tmp/cvtailor-*.json`, poza repozytorium. Tymczasowe pody usunięto; `/health` zwrócił 200, domyślny model pozostał `qwen3.5:9b`.
