# Naprawa kontraktu i kontekstu Ollamy — 24 października 2026

**Wynik: Qwen3.5 9B zakończył dwa pełne przebiegi przy 16 384: analiza, ponowna niezależna walidacja, generowanie, Truth Lock, PDF i DOCX. Qwen3.8 27B IQ2_S nadal nie przechodzi kontroli źródeł. Pozostawić produkcyjny model Qwen3.5 9B. Zmian nie wdrożono.**

Gałąź: `codex/ollama-contract-context-fix`. Zastane zmiany robocze zachowano. Raport pierwotnego audytu i `token-breakdown.csv` przeczytano przed poprawkami; poniższe pomiary pochodzą z nowych rzeczywistych żądań, a nie oszacowań znaków. Nie łączymy odmów z ukończonymi generowaniami w jedną średnią.

## Konkretne przyczyny odmów i poprawki

1. **Niepełny kontrakt ocen.** Gałąź `OtherRow` dopuszczała ocenę bez nazwy i uzasadnienia. Obecny podstawowy kontrakt to słownik `assessments`: każde ID fragmentu jest obowiązkowym kluczem dokładnie raz. Rozpoznane nagłówki, tagi i obowiązki mają osobne dyspozycje; nie mogą stać się kwalifikacją przez wybór innej gałęzi schematu. Oceniane warunki wymagają nazwy, statusu, priorytetu, dowodów i uzasadnienia. Zachowano odzyskiwanie wyłącznie zamkniętych wierszy z uciętej odpowiedzi oraz ograniczony retry.
2. **Polskie sekcje i zakres.** Parser nie rozpoznawał „Czego oczekujemy” i „Czym się zajmiesz”. Dopisano nagłówki oraz obsługę „najlepiej” jako opcjonalnego doprecyzowania obowiązkowego minimum. `Windows 10/11` przestaje automatycznie oznaczać niejednoznaczność dwóch różnych produktów. Nie utożsamia to Windows 11 z potwierdzoną praktyką Windows 10.
3. **Zły zakres dowodów.** Matcher nie rozpoznawał frazy `IT support` w regule stażu. Teraz liczy datowane fakty o odpowiednich obowiązkach, z wyłączeniem nakładających się okresów; sam tytuł i fakt o fakturowaniu nie potwierdzają stażu wsparcia. Dodano rozpoznanie polskiego kwalifikatora praktycznej znajomości oraz osobną kontrolę Exchange Online, Entra ID, Intune, Defender for Endpoint i pozostałych nazwanych produktów. Ogólne M365/AD nie potwierdza ich praktycznej administracji. Gdy niezależny matcher nie znajduje dowodów dla takiego zakresu, schemat ogranicza ocenę do `missing` i pustych cytowań. Pełny katalog faktów pozostaje dostępny.
4. **Ograniczenie ignorowane przy `$ref`.** Rzeczywisty test wykazał, że lokalny runtime ignorował dodatkowe `enum: [missing]` obok referencji do ogólnego statusu. Zastąpiono je samodzielnym typem string z enum. Ta odmiana ma osobny test regresyjny; surowe odpowiedzi końcowych pomiarów sprawdzono biblioteką JSON Schema.
5. **Walidacja nie była idempotentna.** Już ocenione tagi trafiały ponownie do walidatora kwalifikacji, który słusznie odrzucał je jako kontekst. Usunięto podwójną ścieżkę. Oceny roli mają jawny tryb weryfikacji źródła: zachowuje on literalne tagi/obowiązki bez przenoszenia ich do obowiązkowych kwalifikacji. Ponowna walidacja nie unieważnia teraz poprawnego raportu. Błędne twierdzenia o benefitach nadal są odrzucane.
6. **Puste enum i kompletność CV.** Puste zbiory projektów, źródeł lub umiejętności wymuszają pustą tablicę, bez `enum: []` i martwych referencji. Cytowania podsumowania, edukacja i wybory są obowiązkowe w schemacie. Każdy pracodawca ma własną gałąź z dozwolonymi ID bulletów; edukacja ma własne źródła. Oprócz długości tablic kod niezależnie sprawdza obecność każdego zatrudnienia i każdego wpisu edukacji dokładnie raz, a także właściciela źródeł. Nie można zastąpić brakującej szkoły duplikatem innej. Zatrudnienie bez wybranych faktów zachowuje tożsamość i może mieć tylko puste bullety.
7. **Powielony prompt.** `ollama_payload.py` usuwa wyłącznie dokładne kopie rekordów z `candidate_facts`, diagnostykę RAG, identyczne nazwy wymagań i wskazówki układu. Zachowuje pełny wybrany `source_catalog`, chronologię, linki, zakres wymagań i wszystkie dopuszczone wybory umiejętności. Ślad RAG i snapshot źródeł pozostają na serwerze. Serializacji Gemini nie przestawiano na nowy format.
8. **Pełne fakty analizy i budżet.** Właściciele i siła dowodów są kodowani odwracalnie z jawną legendą. Każde wywołanie analizy nadal miało **203 rekordy**, a pierwsze obejmowało **46 fragmentów**. Nie zmniejszano RAG ani katalogu analizy. Planner przy skonfigurowanym zweryfikowanym tokenizerze liczy faktyczne instrukcje, JSON wejściowy i 17 tokenów obudowy czatu. Nie dolicza gramatyki `format` do wejścia. Preflight sprawdza wejście + limit odpowiedzi + 512; zbyt duże dane powodują podział lub odmowę, nigdy obcięcie faktów. Bez pliku tokenizera pozostaje jawny ostrożny fallback; nie jest on raportowany jako dokładny pomiar.
9. **Warunki publikowania faktów użytkownika.** Aktualna produkcja miała pole `cv_fact_conditions`, którego brakowało lokalnemu modelowi danych. Zachowano pole i warunki prezentacji faktów w generowaniu/Truth Lock. Analiza nadal widzi także te fakty. Nie zapisywano ani nie migrowano profilu użytkownika.

## Pomiary rzeczywistego pipeline'u

Ten sam profil i oferta co w audycie: 4 zatrudnienia, 3 edukacje, 3 projekty w profilu. Wszystkie próby używały temperatury 0, `think=false`, kontekstu 16 384 i wyłącznie Ollamy, bez Gemini/fallbacku. Opcjonalnego przeglądu draftu nie wykonywano; przegląd podsumowania i Truth Lock pozostają aktywne.

| Próba | Wejście, suma API | Wyjście, suma API | Czas do wyniku | Ładowanie, wliczone w czas | Wynik |
|---|---:|---:|---:|---:|---|
| Qwen3.5 9B, pierwsza poprawna | 24 978 | 2980 | 113,35 s | 0,044 s | Walidacja + PDF/DOCX |
| Qwen3.5 9B, końcowe powtórzenie | 24 876 | 3224 | 166,46 s | 3,204 s | Walidacja + PDF/DOCX |
| Qwen3.8 27B IQ2_S | 41 315 | 2965 | 213,91 s | 5,314 s | Odmowa kontroli źródeł; bez CV i eksportu |

Drugi przebieg 9B miał zimniejsze ładowanie i wolniejsze etapy CPU/eksportu; równolegle trwały testy. Nie jest to kontrolowany pomiar wyłącznego wpływu modelu na czas. Nie obiecujemy produkcyjnej latencji na podstawie dwóch prób. Pierwszy przebieg ma starszy limit przeglądu podsumowania 8192; w końcowym i porównaniu 27B limit tego etapu wynosi 1024. Nie zmieniono budżetu analizy ani generowania między tymi próbami.

| Etap końcowego 9B | Wejście | Wyjście | Czas |
|---|---:|---:|---:|
| Analiza główna, API | 9539 | 1031 | 29,18 s |
| Uzupełnienie stażu, API | 7936 | 183 | 8,85 s |
| Analiza łącznie z przygotowaniem/walidacją | 17 475 | 1214 | 61,45 s |
| Generowanie CV, API | 6371 | 1570 | 34,26 s |
| Przegląd podsumowania, API | 1030 | 440 | 9,27 s |
| Generowanie i przegląd, cała metoda | 7401 | 2010 | 44,75 s |
| Truth Lock | 0 | 0 | 6,69 s |
| PDF | 0 | 0 | 28,39 s |
| DOCX | 0 | 0 | 5,15 s |
| Odczyt tekstu obu eksportów | 0 | 0 | 8,04 s |

Wiersze „cała metoda” zawierają odpowiadające im wywołania API, nie sumują się z nimi. Cały czas obejmuje także końcową kontrolę stanu i narzut harnessu. Ładowanie jest częścią czasu API, nie dodatkowym kosztem do dodania.

**Budżet pierwszej analizy: `9539 + 6144 + 512 = 16 195`, mieści się w 16 384.** Generowanie: `6371 + 4096 + 512 = 10 979`. To nie jest gwarancja dla każdego większego profilu. Schemat pozostaje gramatyką odpowiedzi, a nie dodatkową wiadomością. Żadnej odpowiedzi końcowych trzech prób nie ucięto na limicie.

## Porównanie z audytem sprzed napraw

| Żądanie na tej samej ofercie i profilu | Przed naprawą | Po naprawie |
|---|---:|---:|
| Pierwsze wejście analizy 9B | 10 187 | 9539 |
| Odpowiedź pierwszej analizy 9B | 4728 | 1031 |
| Wejście generowania CV w kontrolnym audycie / końcowym przebiegu | 11 485 | 6371 |
| Niezależna walidacja i eksport przy 16 384 | Odmowa | Dwa poprawne przebiegi 9B |

Pierwszy prompt analizy zmniejszył się o 648 tokenów (6,36%). Pełna naprawiona analiza wymagała jeszcze jednego wywołania z 7936 tokenami; nie twierdzimy więc, że suma wejścia analizy spadła. Liczby generowania dotyczą tej samej oferty/profilu, ale innych wyników analizy i selekcji RAG: końcowy katalog ma 28 źródeł, kontrolny miał 29. Nie jest to izolowany pomiar samej serializacji. Poprzedni audyt osobno wykazał bezstratne przepisanie dokładnie tego samego żądania z 11 485 do 6592; obecne testy ponownie potwierdzają niezmienność katalogu przy kompaktowaniu, chronologii i edukacji. Nie deklarujemy oszczędności całego pipeline'u wobec przebiegu, który kończył się odmową przed CV.

## Jakość i walidacje

- **Surowy schemat:** wszystkie 13 odpowiedzi z trzech końcowych prób są poprawnym JSON-em i przechodzą rzeczywiście wysłany schemat (4 + 4 + 5). To sprawdzono oddzielnie od Pydantic i walidacji semantycznej. Dokładny tokenizer zgadza się z `prompt_eval_count` we wszystkich 13 żądaniach.
- **Dowody:** analiza 9B przechodzi także ponowną niezależną walidację. Praktyczna znajomość Exchange Online/Entra ID/Intune pozostaje `missing`, bez ID potwierdzających. Trzy składniki listy są oceniane oddzielnie jako AND. Minimum stażu jest potwierdzone datowanymi obowiązkami, około 3,4 roku, bez wymuszania opcjonalnego środowiska wielu klientów. Pozostałe częściowe dopasowania nie są przedstawiane jako pełne potwierdzenie.
- **27B:** kolejne odpowiedzi dla stażu ponownie cytowały m.in. ogólne podsumowania i nieadekwatne fakty obok właściwych obowiązków. Niezależna kontrola usuwała te powiązania i pozostawiała odmowę. Cztery naprawy zwracały ten sam wadliwy zakres ID. Schemat był poprawny; semantyczna odmowa pozostaje potrzebna.
- **Doświadczenie i edukacja:** oba poprawne surowe CV mają 4 zatrudnienia i 3 edukacje, końcowe również 4 i 3. Każdy wpis ma odpowiednie źródła; brak bulletów przypisanych innemu pracodawcy. W finalnych dokumentach potwierdzono tekst wszystkich czterech pracodawców i trzech instytucji. Wybrano 2 projekty; nie ma wymogu umieszczania wszystkich 3.
- **Truth Lock:** pierwsza poprawna próba miała 2 korekty (nagłówek i opis projektu); końcowa 3 (dodatkowo odbudowane podsumowanie). Końcowe surowe podsumowanie dopisało `Windows 10/11`, chociaż cytaty potwierdzały Windows 11. Przegląd je odrzucił i Truth Lock zastąpił je zweryfikowanymi zdaniami. **Nie twierdzimy, że surowe CV 9B jest wolne od halucynacji.**
- **ATS:** w obu formatach zachowano Microsoft 365, Windows, PowerShell, DNS, VPN, MikroTik i FortiGate. Nie pozostały deklaracje Exchange Online/Entra ID/Intune. To kontrola konkretnej listy potwierdzonych terminów, nie wymyślony „procent ATS”.
- **Bramka podsumowania:** dla końcowego CV sprawdzono także aktualny mechanizm `summary_review`: `additional_summary_confirmation_required=false`. Podsumowanie odbudowane ze źródeł nie potrzebuje dodatkowego interaktywnego zatwierdzenia. Wcześniejsza ciepła próba obejmowała techniczny eksport bez oddzielnego sprawdzenia tej bramki; nie traktujemy samego pozytywnego werdyktu AI jako zgody użytkownika. Harness odmawia teraz eksportu, jeżeli wymagana jest taka zgoda.
- **Dokumenty:** końcowe PDF ma 22 202 B i **2 strony**, DOCX 38 594 B i 45 akapitów. Oprócz magic bytes oba formaty odczytano parserami; sprawdzono tekst edukacji i pracodawców. Nie deklarujemy CV jednostronicowego. Pliki testowe są zachowane prywatnie w `/tmp/cvtailor-contract-artifacts/`, poza historią.

W toku poprawek wykonano także trzy nieudane próby rozwojowe: wykazały błąd rozpoznania wersji Windows, brak idempotencji oraz ignorowanie enum obok `$ref`. Nie zaliczono ich jako poprawnych generowań i nie włączono do średniej czasu ukończenia.

## Testy i odtworzenie

Nowy zestaw `tests/test_ollama_context_contract.py` zawiera 16 regresji i pokrywa polskie sekcje, opcjonalny zakres stażu, praktyczne AND, pełne pokrycie ID, błędne dowody, puste kolekcje, obowiązkowe cytowania/edukację, cytowania innego pracodawcy, duplikaty szkół, zachowanie chronologii bez faktów, odwracalność kodowania i brak mutacji, preflight, odrzucenie złego tokenizera, idempotencję tagów, warunki publikacji i ignorowane wcześniej ograniczenie enum.

Końcowa regresja usług: **182 testy zaliczone**; oddzielnie **19 testów bramki potwierdzania podsumowania zaliczonych**. Ruff dla zmienionego kodu oraz `git diff --check` przechodzą. Szerszy zestaw początkowych 922 testów sprawdzono partiami: 478 + 288 + 156, ponieważ dwa przebiegi osiągnęły limity czasu. W ostatniej części cztery syntetyczne odpowiedzi Ollamy wymagały aktualizacji do obowiązkowego `selected_skill_ids` i rzeczywistych kanonicznych ID źródeł; po poprawieniu fixture wszystkie 19 testów tego pliku, w tym te cztery, przechodzą. Zachowano test blokowania fałszywego werdyktu AI przed eksportem. Cztery dodatkowe nowe regresje, dodane po początkowej kolekcji, są również pokryte końcowymi 182 testami usług. Nie deklarujemy pojedynczego nieprzerwanego przebiegu całego zestawu.

Reprodukowalny harness: `scripts/benchmark_ollama_contract.py`. Wymaga zależności testowych i pliku tokenizera zgodnego z przypiętym SHA256. Sprawdza również surowy JSON Schema. Domyślnie tworzy prywatny katalog `/tmp/cvtailor-contract-*`; pełne odpowiedzi mogą zawierać dane osobowe i nie wolno dodawać ich do repozytorium. Do powtórzenia należy użyć identycznych sum profilu i oferty, podanych w `repair-measurements.json`, oraz danych tylko do odczytu. Skrypt nie zapisuje historii ani konfiguracji usług.

Pomiary poszczególnych wywołań: `repair-calls.csv`; podsumowania bez treści CV: `repair-measurements.json`; zestawienie weryfikacji: `repair-validation.json`. Pełne prywatne przechwycenia pozostają w `/tmp/cvtailor-fix-*.json`.

## Rekomendacja i granice wdrożenia

Pozostawić **`qwen3.5:9b`**. Nie ma przewagi jakościowej 27B uzasadniającej przełączenie; w tej próbie nie uzyskał nawet wiarygodnej analizy. Zachować Truth Lock i nie eksportować niezweryfikowanego surowego wyniku.

Parametry sprawdzone poza produkcją: kontekst 16 384, temperatura 0, thinking wyłączone, analiza do 6144, CV do 4096, przegląd podsumowania do 1024, równoległość 1, keep_alive 15m. Nowe limity etapów są ograniczane również istniejącym `ollama_num_predict`. Dokładne planowanie wymaga `OLLAMA_TOKENIZER_PATH` do zweryfikowanego pliku z SHA256 `0997f410c57a1f4e53b09e4be8f4a172d90edd9564368fb0847030937229b9f3`. Aplikacja nie pobiera go z sieci przy starcie. Bez tego pliku pozostaje fallback; sama zmiana `OLLAMA_NUM_CTX` nie włącza dokładnego liczenia.

**Nie wdrożono gałęzi, nie zmieniono aktywnego modelu ani konfiguracji SSH/Ollamy/VPS/sterowników. Nie usuwano modeli, CV, historii ani danych.** Izolowane pody miały wszystkie wolumeny danych tylko do odczytu. Sumy profilu, oferty i banku umiejętności pozostały zgodne. Oba własne pody testowe usunięto. Przywrócono do pamięci `qwen3.5:9b` z dotychczasowym kontekstem 32 768; aktywny ConfigMap nadal wskazuje `qwen3.5:9b` i 32 768, a `/health` odpowiedział HTTP 200. 16 384 jest potwierdzone dla tej pary danych; większe profile muszą przejść własny preflight i test, a nie automatyczne obcinanie faktów.
