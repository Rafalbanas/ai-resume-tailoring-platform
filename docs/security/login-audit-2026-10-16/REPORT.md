# Audyt logowania i izolacji kont

Audyt rozpoczęto 16 października 2026 na wersji `3cb7e3e`; poprawki i wspólny login zweryfikowano 17 października. Testy używały wyłącznie fikcyjnych kont, profili i tymczasowych katalogów. Nie atakowano publicznego konta, nie zmieniano prawdziwych haseł ani sesji i nie wdrażano zmian do działającej infrastruktury.

## Docelowe zachowanie

Rafał i demo używają tego samego `https://cv.banas.dev/login`, bez prefiksu `/demo` i bez dodatkowej subdomeny. Serwer wybiera runtime na podstawie podpisanej sesji oraz wpisu w bazie sesji odpowiedniego konta. Każdy runtime ma osobne dane uwierzytelniające, profil, skills, referencje, pliki, ustawienia AI i worker zadań. Internalny runtime demo nie ma osobnego publicznego listenera.

Jedna przeglądarka ma jedno aktywne konto. Otwarcie logowania unieważnia dotychczasową sesję; po zmianie konta stare formularze nie przechodzą walidacji CSRF. Inne przeglądarki lub profile mogą niezależnie korzystać z obu kont. Interfejs pokazuje bieżący login i oznaczenie fikcyjnych danych demo. Zachowano wklejanie haseł i obsługę menedżerów haseł.

## Ustalenia i poprawki

| Ustalenie z audytu | Waga / warunki | Poprawka |
|---|---|---|
| Uvicorn ufał dowolnemu `X-Forwarded-For` w domyślnym Docker CMD | P2, jeśli backend jest dostępny bezpośrednio lub proxy nie oczyszcza nagłówka | Zaufanie tylko do loopback; przykład Nginx nadpisuje nagłówek. Test rzeczywistego middleware z polityką odczytaną z Dockerfile blokuje szóstą próbę także przy zmienianym nagłówku. |
| Reset hasła między weryfikacją a wydaniem sesji przypisywał stare hasło do nowej wersji danych | P2; wymaga znajomości starego hasła i trafienia w reset | Weryfikacja zwraca wersję sprawdzonego rekordu. Sesja jest wiązana z tą wersją. Stabilny lock plikowy koordynuje CLI, rehash i procesy. Test kontrolowanego przeplotu potwierdza odrzucenie sesji po resecie. |
| Synchroniczny Argon2 blokował event loop (w pierwotnym pomiarze ok. 0,5 s na próbę) | P2, dostępność | Kosztowna weryfikacja/zmiana hasła poza pętlą, maksymalnie dwie operacje uwierzytelniania na proces, bez nieograniczonej kolejki. Test wstrzymuje weryfikator i potwierdza dostępność health probe. |
| Nie-ASCII w loginie lub CSRF powodowało 500 | P3 | Nazwy porównywane jako UTF-8, tokeny mają kontrolowany format ASCII i długość. Unicode w nazwie poprawnego właściciela nadal działa. |
| Limit prób znikał po restarcie i był niezależny dla workerów | P2 przy wielu instancjach | Atomowy SQLite, TTL 300 s, 5 prób na IP i 100 na instancję. Wspólny login i zmiana hasła korzystają z tego samego budżetu. Testy obejmują konkurencyjne instancje i usuwanie wygasłych wpisów. |
| HTML `maxlength` nie ograniczał danych na serwerze; całe body czytano przed limiterem | P2/P3 zależnie od wdrożenia | Limit 16 KiB przed parsowaniem loginu i zmiany hasła, także przy strumieniu bez Content-Length; 150 znaków loginu i 256 hasła na serwerze. Odrzucane zduplikowane pola i nagłówki bezpieczeństwa. |
| CSRF nie był powiązany z konkretną sesją przeglądarki | Dodatkowe wzmocnienie | Token jest podpisany, przechowywany w podpisanej sesji, porównywany z cookie i rotowany po logowaniu. Obcy poprawnie podpisany token nie wystarcza. Origin i Fetch Metadata blokują mutacje z obcych originów. Obsłużono rzeczywiste `Origin: null` z formularza Chromium przy no-referrer wyłącznie dla browser-controlled `same-origin`. |
| Demo pod `/demo` miało wspólny origin z prywatną aplikacją mimo osobnych cookies | Ryzyko przy wykonywalnym skrypcie demo i równoczesnej prywatnej sesji w tej samej przeglądarce | Zamiast dwóch równocześnie aktywnych cookies na jednym originie: jeden wspólny login i jeden aktywny kontekst konta, wybierany przez serwer i sprawdzany w jego bazie. Stary upstream `/demo` musi zostać usunięty przy wdrożeniu. |
| Brak CSP i akceptowanie domyślnego/pustego sekretu | Dodatkowe wzmocnienie | Niebezpieczny sekret blokuje start. Wszystkie HTML UI mają CSP z nonce dla skryptów, bez unsafe-inline dla JavaScript. Inline handlery zastąpiono zewnętrznymi listenerami, polling zadań ma nonce; walidacja formularza używa natywnej nawigacji zamiast document.write. Dodano CORP/COOP. |

## Co sprawdzono

- SQL/NoSQL/XSS w obu polach logowania nie uwierzytelniają; hasła weryfikuje Argon2id, zapytania sesji są parametryzowane.
- Oba konta korzystają z dokładnie tych samych ścieżek; identyczne ID plików zwracają wyłącznie pliki aktywnego konta. Parametry `account`, `user`, `data_dir` i nagłówki `X-Account`/`X-Tenant` nie zmieniają wyboru.
- Zmiana ustawień i hasła wpływa tylko na aktywne konto. Reset drugiego konta nie unieważnia aktywnego konta; reset aktywnego je unieważnia. Obce ID zadania zwraca 404. Workery i katalogi zadań są osobne.
- Równoległe klienty nie mieszają runtime'ów. Manipulacja podpisanym claimem konta nie daje dostępu. Wylogowanie, rotacja, wygaśnięcie i reset unieważniają sesje.
- Brak sesji blokuje strony, API, OpenAPI, pliki i zdrowie szczegółowe. Testowane warianty traversal nie ujawniły danych ani `.env`.
- Cookies pozostają HttpOnly, SameSite=Strict i Secure pod HTTPS. Odpowiedzi UI są no-store; brak CORS udostępniającego dane obcemu originowi.
- Chromium: oba konta logują się na jednym URL po **rzeczywistym wklejeniu hasła ze schowka** i wysłaniu klawiaturą; label pokazuje konto. Skrypt bez nonce jest blokowany także po zalogowaniu. XSS zapisany przez formularz demo jest escapowany. Żądanie demo z `account=owner` zmienia tylko demo. Formularz starej karty nie może mutować konta po przełączeniu loginu.
- Zachowano natywne dialogi potwierdzenia po usunięciu inline handlerów; test przeglądarkowy obejmuje usunięcie fikcyjnego zainteresowania.

## Uruchomienie weryfikacji

Końcowy pełny przebieg: **658/658**. Następnie przeszło 7 nowych przypadków regresyjnych (aliasy plików, metody publicznych endpointów, drain demo i powiązanie claimu konta z bazą sesji): razem **665 odrębnych przypadków**. Ponownie przeszło 12 testów wspólnego loginu, w tym aktualny scenariusz Chromium z klawiaturą, schowkiem i dialogiem potwierdzenia. Ruff, synchronizacja README, `git diff --check`, kompilacja skryptów wdrożeniowych, JSON zasobów i Nginx `-t` na syntetycznym certyfikacie przeszły.

Zrzuty obejmują wyłącznie fikcyjne dane: [demo](shared-demo.png), [właściciel](shared-owner.png).

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/python scripts/sync_readme.py --check
```

Pierwotne 36 prób audytowych dokumentowało podatną wersję; nie są to oczekiwania nowych testów. Regresje bezpiecznego zachowania znajdują się w `tests/test_auth_boundary.py`, `tests/test_shared_login.py`, `tests/test_auth_store.py` i `tests/test_recording_demo.py`. Testy korzystają z izolowanych fixture i mocka AI. Wynik całego końcowego przebiegu jest zapisany w opisie PR.

## Wdrożenie i ograniczenia

[Instrukcja migracji](../../recording-demo.md) opisuje zamontowanie istniejącego demo PVC i pliku jego sekretu do głównego procesu, wygaszenie osobnego demo deploymentu, drain obu kolejek i usunięcie starego upstreamu `/demo`. Nie wymaga zmiany DNS, certyfikatu, haseł ani przenoszenia zawartości PVC. Zwykły image-only rollout CI nie dodaje nowych mountów i ustawień. Te kroki muszą zostać wykonane przy wdrożeniu — sam PR nie zabezpiecza starego działającego routingu.

To izolacja uprawnień aplikacji, a nie izolacja procesowa: server-side RCE może zagrozić obu runtime'om. Wspólny origin nie zapewnia oddzielnych sandboxów przeglądarki; nadal trzeba zapobiegać XSS i nie pozwalać użytkownikowi demo na uruchamianie dowolnych skryptów. CSP, escapowanie, ochrona plików i jedna aktywna sesja ograniczają to ryzyko, nie zastępują dalszych audytów.

Nie testowano ataków na produkcję, wszystkich CVE zależności ani przeciążenia/DDoS. Budżet 100 prób/5 minut może zostać wyczerpany przez rozproszony ruch; jest kompromisem ochrony zasobów. MFA/passkeys pozostają możliwym przyszłym rozszerzeniem. Nie znaleziono bezhasłowego przejęcia konta; testy nie gwarantują braku innych podatności.

## Źródła zaleceń

- [OWASP Authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [OWASP CSRF](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- [Uvicorn: proxy i wdrożenia](https://www.uvicorn.org/deployment/)
- [Python compare_digest](https://docs.python.org/3.10/library/hmac.html)
