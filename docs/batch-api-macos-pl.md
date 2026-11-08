# Paczka ofert → CV Gemmą: macOS i zsh

Jedno wysłanie pliku uruchamia kolejno analizę każdej wskazanej oferty i generowanie CV. Wyniki trafiają do zwykłej Historii. Poniższe polecenia wklejaj do **tej samej karty terminala zsh**; nie zapisuj hasła w poleceniach ani plikach. Nie wymagają `watch`, którego macOS domyślnie nie dostarcza.

## Automatyzacja skryptem batch_api.py
Skrypt [`scripts/batch_api.py`](../scripts/batch_api.py) wysyła paczki i monitoruje postęp. Nie loguje automatycznie ani nie pobiera CV.

**Wymagania:**
- Python3
- curl >=7.76 (wymaga flagi `--fail-with-body`)

**Uruchomienie:**
Po wykonaniu `cv_login` z sekcji logowania poniżej albo własnego logowania przez `curl /login` wyeksportuj zmienne z tej samej karty terminala:
```zsh
export BASE COOKIE_FILE CSRF
```

**Interfejs:**
```zsh
# Dostosuj ścieżkę do miejsca sklonowania repozytorium.
CV_API="$HOME/ai-resume-tailoring-platform/scripts/batch_api.py"

export BASE COOKIE_FILE CSRF

python3 "$CV_API" options

cd "$HOME/Documents/Jobs"

python3 "$CV_API" upload --key-prefix oferty-gemma-modern-20261108 --manifest tasks-20261108.jsonl batch-01-2026-11-08.txt batch-02-2026-11-08.txt batch-03-2026-11-08.txt

python3 "$CV_API" watch --manifest tasks-20261108.jsonl --interval 30

```

Nie wysyłaj ponownie już działających paczek. Dla istniejących zadań użyj bezpośrednio `python3 "$CV_API" watch TASK_ID_1 TASK_ID_2 TASK_ID_3 --interval 30`, zastępując znaczniki własnymi identyfikatorami.

Pojedynczy odczyt: `python3 "$CV_API" status TASK_ID`. Opcjonalne anulowanie: `python3 "$CV_API" cancel TASK_ID`. Zastąp `TASK_ID` własnym identyfikatorem; anulowania nie uruchamiaj, jeśli chcesz tylko sprawdzić postęp.

**Szczegóły:**
- **Opcje domyślne:** `ollama/gemma4:12b-it-q4_K_M/context65536/modern_sidebar/export true/allow_fallback false`.
- **Plik opcji:** `upload --options-file options.json` zastępuje cały domyślny obiekt opcji; pola pominięte w pliku przyjmują domyślne wartości API. Format opisuje [kontrakt API](batch-api.md#json-submission-and-options).
- **Klucze idempotencji:** Skrypt tworzy klucze `prefix-01`, `prefix-02`, `prefix-03` zgodnie z kolejnością plików. Ponawianie musi używać tych samych plików (także zawartości) w tej samej kolejności oraz tego samego prefiksu/opcji. Nowy prefiks oznacza celowe nowe generowanie.
- **Manifest:** Skrypt zapisuje każdą odpowiedź jako wiersz JSONL w pliku manifestu `{file, idempotency_key, task_id, ...pełna odpowiedź}`. Plik jest zapisywany z uprawnieniami `0600`.
- **Monitorowanie (`watch`):**
  - Polecenie `watch` wykonuje GET i kończy się, gdy wszystkie paczki osiągną status `completed`, `failed`, `rejected` lub `cancelled`.
  - `Ctrl+C` przerywa tylko monitorowanie, nie przerywa zadania na serwerze.
- **Kody wyjścia:** `watch` i `status` zwracają `1` dla paczek `failed`, `rejected`, `cancelled` albo dowolnej oferty `manual_required`, `review_required`, `failed`, `cancelled`. Kod `0` dla odczytu trwającej paczki nie oznacza zakończenia. `completed` paczki nie gwarantuje sukcesu każdej oferty. Ctrl+C daje `130`.
- **Błędy sieciowe:** Błąd HTTP lub sieciowy kończy skrypt z błędem, nie pętli się w nieskończoność.
- **Kolejkowanie (`queued`):** Pierwsza paczka `running`, a kolejne `queued` to normalny widok przy jednym workerze. Same statusy nie dowodzą awarii ani konfiguracji wdrożenia.
- **Anulowanie:** `cancel ID` anuluje pozostałe oferty po zakończeniu bieżącej; zapisane wyniki zostają zachowane.
- **Przerwana wysyłka:** Pierwszy błąd zatrzymuje serię bez automatycznego ponawiania. Wcześniejsze odpowiedzi pozostają w manifeście. Jeśli odpowiedź zaginęła lub zapis manifestu się nie udał, powtórz całą serię z identycznymi kluczami i danymi — nie twórz nowego prefiksu. Manifest jest dopisywany; monitor usuwa powtarzające się identyfikatory. Przechowuj go poza repozytorium, ponieważ zawiera prywatne adresy ofert i wyników.

Znajdź instrukcję szybkiego startu w [docs/README.md](README.md).

## Wymagania
- **curl**: do komunikacji z API.
- **python3**: do parsowania odpowiedzi JSON.
- **Aktywny endpoint**: wersja aplikacji z batch API i opisaną polityką `allow_fallback` musi być wdrożona na `https://cv.banas.dev`. Sam PR nie jest wdrożeniem. Dla innej instalacji zmień `BASE` w funkcji.

## Przygotowanie
Utwórz plik `oferty.txt` z listą URL (jeden na linię).

Plik musi mieć kodowanie UTF-8, maksymalnie **64 KiB i 50 wejściowych adresów** (limit przed usunięciem powtórzeń). API usuwa kanoniczne duplikaty; akceptuje też adresy rozdzielone spacjami. Przykład formatu — zastąp fikcyjne adresy rzeczywistymi ofertami:

```text
https://example.com/jobs/support-engineer
https://example.com/jobs/data-engineer
```

```zsh
nano oferty.txt
```
*Wklej listę URL, naciśnij `Ctrl+O`, `Enter`, a następnie `Ctrl+X`.*

## Instrukcja krok po kroku

### 1. Logowanie
Skopiuj i wklej poniższą funkcję do terminala. Zapewnia ona bezpieczne logowanie bez zapisywania hasła do historii.

```zsh
cv_login() {
    BASE=https://cv.banas.dev
    local CV_USER CV_PASS
    local login_ok=0
    unset CSRF
    COOKIE_FILE=$(mktemp) || return 1
    chmod 600 "$COOKIE_FILE" || return 1
    {
        read -r "CV_USER?Login CVTailor: " || return 1
        read -rs "CV_PASS?Hasło: " || return 1
        printf '\n'
        curl -fSs -c "$COOKIE_FILE" "$BASE/login" >/dev/null || return 1
        CSRF=$(awk '$6 == "csrf_token" {print $7}' "$COOKIE_FILE" | tail -1)
        [[ -n "$CSRF" ]] || { printf 'Brak tokenu CSRF.\n'; return 1; }
        curl -fSs -b "$COOKIE_FILE" -c "$COOKIE_FILE" \
          --data-urlencode "csrf_token=$CSRF" \
          --data-urlencode "username=$CV_USER" \
          --data-urlencode "password=$CV_PASS" "$BASE/login" >/dev/null || return 1
        unset CV_PASS
        CSRF=$(awk '$6 == "csrf_token" {print $7}' "$COOKIE_FILE" | tail -1)
        [[ -n "$CSRF" ]] || { printf 'Brak tokenu CSRF po logowaniu.\n'; return 1; }
        curl -fSs -b "$COOKIE_FILE" "$BASE/api/v1/batches/options" >/dev/null || return 1
        login_ok=1
        printf 'Zalogowano.\n'
    } always {
        unset CV_PASS
        if (( ! login_ok )); then
            rm -f "$COOKIE_FILE"
            unset COOKIE_FILE CSRF
        fi
    }
}

# Wywołaj funkcję:
cv_login
```

**Kontynuuj wyłącznie po komunikacie „Zalogowano.”** Przy błędzie zatrzymaj się i sprawdź sekcję rozwiązywania problemów. Zmienne `BASE`, `COOKIE_FILE` i `CSRF` pozostają w tej karcie terminala. Plik cookies daje dostęp do konta: nie udostępniaj go ani tokenu CSRF, nie wklejaj do zgłoszeń, nie używaj `curl -v` do publicznej diagnostyki.

### 2. Odkrywanie opcji (Discovery)
Sprawdź dostępne modele i parametry (należy użyć zainstalowanego modelu):
```zsh
curl -fSs -b "$COOKIE_FILE" "$BASE/api/v1/batches/options" | python3 -m json.tool
```

Wybierz dokładną nazwę z `ollama_models`. Przykłady poniżej używają `gemma4:12b-it-q4_K_M`, ale obecność nazwy w instrukcji **nie oznacza**, że model jest zainstalowany na serwerze. Ollama to silnik lokalny; Gemma to model, a **Gemini** to odrębny dostawca Google.

Ta wersja API domyślnie blokuje fallback dla paczek (`allow_fallback: false`). Z żądaniem `llm_provider: ollama` błąd Gemmy nie wyśle wtedy danych do Gemini. Na starszych wdrożeniach Ollama mogła korzystać z globalnego fallbacku — wyłącz go w ustawieniach UI, jeśli wymagasz pracy wyłącznie lokalnej. Świadome `allow_fallback: true` dopuszcza fallback tylko wtedy, gdy zezwalają też ustawienia globalne; Gemini otrzymuje wówczas dane oferty i fakty kandydata.

### 3. Przesłanie ofert
Użyj poniższej komendy, aby wysłać plik `oferty.txt`. `modern_sidebar` wybiera Modern Sidebar; `ats_classic` wybiera motyw klasyczny. Modern wymaga jednej strony: jeśli chronione fakty nie mieszczą się na niej, eksport wymaga zmiany motywu lub ręcznej korekty. Potwierdzenie podsumowania AI i Truth Lock nie są omijane.

- **tailoring_level**: 0–1 (domyślnie 0). 0 preferuje trafność dla oferty i dopasowane sformułowania, 1 preferuje kolejność profilu i brzmienie źródeł. Nie wpływa na Truth Lock i nie jest temperaturą modelu.

```zsh
curl -fSs -b "$COOKIE_FILE" \
  -H "X-CSRF-Token: $CSRF" \
  -H "Idempotency-Key: oferty-gemma-modern-001" \
  -F "file=@oferty.txt;type=text/plain" \
  -F 'options={"llm_provider":"ollama","ollama_model":"gemma4:12b-it-q4_K_M","ollama_context":65536,"template_name":"modern_sidebar","export":true,"tailoring_level":0,"allow_fallback":false}' \
  "$BASE/api/v1/batches/upload"
```

### 4. Śledzenie statusu
Po otrzymaniu odpowiedzi `202 Accepted` zadanie jest już zapisane. Nie wysyłaj paczki ponownie tylko po to, żeby sprawdzić postęp.

*Przykład odpowiedzi 202:*
```json
{
  "task_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "status": "queued",
  "stage": "Waiting in queue...",
  "status_url": "/api/v1/batches/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "view_url": "/tasks/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/view",
  "result": null,
  "error": null
}
```

Wklej **własne** `task_id` z odpowiedzi w miejsce znacznika poniżej (przykładowe `aaaaaaaa…` nie wskazuje prawdziwego zadania). Status sprawdzaj co kilka sekund; sugerowany odstęp to 3 sekundy:
```zsh
TASK_ID='TU_WKLEJ_TASK_ID_Z_ODPOWIEDZI'
curl -fSs -b "$COOKIE_FILE" "$BASE/api/v1/batches/$TASK_ID" | python3 -m json.tool
open "$BASE/tasks/$TASK_ID/view"
```

`status_url` i `view_url` z API są ścieżkami względnymi serwera — dodaj przed nimi `https://cv.banas.dev`, jeśli otwierasz je ręcznie. Samo wypisanie JSON nie ustawia zmiennych powłoki.

### 5. Wyniki
Sprawdź historię na: [https://cv.banas.dev/history](https://cv.banas.dev/history).
- `queued`: Zadanie czeka na worker. Oferty w paczce przetwarzane są kolejno; jeśli czekanie się przedłuża, sprawdź **Diagnostykę**: czy kolejka nie jest wstrzymana i czy nie trwa inne zadanie. Nie twórz kolejnej kopii paczki.
- `running`: Przetwarzanie w toku.
- `completed` paczki: zakończono iterację — **nie oznacza sukcesu każdej oferty**. Sprawdź wszystkie `result.items`. `completed` pojedynczej oferty oznacza gotowe eksporty z linkami `preview_url`, `pdf_url` i `docx_url`.
- `draft_ready`: Analiza/projekt zapisany; eksport był wyłączony.
- `manual_required`: Wymagana interwencja (sprawdź `error`).
- `review_required`: Eksport wymaga potwierdzenia podsumowania lub poprawy walidacji/układu; otwórz `analysis_url` i przeczytaj błąd.
- `failed`: Błąd przetwarzania; zapisana analiza pozostaje dostępna.

Ten sam `Idempotency-Key` i te same opcje zwracają istniejącą paczkę bez nowej generacji. Zmienione opcje pod starym kluczem dają `409`; wtedy użyj nowego klucza, np. `oferty-gemma-modern-002`. **Nowy klucz to celowe nowe uruchomienie**, więc przy ponawianiu wybierz najlepiej wyłącznie nieudane oferty. W celu sprawdzenia postępu korzystaj z GET, nie POST.

### 6. Czyszczenie
Po zakończeniu pracy usuń lokalny plik ciasteczek:
```zsh
rm -f "$COOKIE_FILE"
unset COOKIE_FILE CSRF
```

To usuwa lokalną kopię, ale nie unieważnia sesji na serwerze. Do unieważnienia wszystkich sesji służy „Sign out everywhere” w aplikacji. Zamknięcie terminala nie przerywa zadania na serwerze, ale tracisz zmienne powłoki, a plik cookies nie usuwa się automatycznie — usuń go przed zamknięciem lub zachowaj jego ścieżkę prywatnie, aby go później usunąć. Po ponownym zalogowaniu możesz wrócić do Historii lub zapisanego adresu postępu.

## Rozwiązywanie problemów (Troubleshooting)
- **read: -p: no coprocess**: `read -p` w poprzednim przykładzie było składnią Basha; zsh interpretuje `-p` inaczej. Użyj powyższej funkcji `cv_login`.
- **awk brak pliku**: Jeśli `awk` zwróci błąd, spróbuj ponownie wykonać logowanie.
- **curl 26**: Sprawdź ścieżkę `pwd` i czy plik ofert istnieje (`ls`).
- **401**: Sesja wygasła, powtórz `cv_login`.
- **403**: Możliwa odmowa CSRF/Origin, konto demo lub blokada proxy. Nie dowodzi błędnego hasła; nie wyłączaj CSRF ani weryfikacji TLS. Upewnij się, że sesja i token pochodzą z tego samego logowania.
- **404**: Endpoint nie jest wdrożony, adres jest błędny albo zadanie nie istnieje w tym koncie.
- **409**: Użyłeś tego samego `Idempotency-Key` dla różnych opcji. Zmień klucz.
- **413/422**: Zbyt duży plik lub błędne parametry w `options`.
- **429**: Limit zapytań lub kolejki przekroczony; poczekaj i sprawdź status istniejących zadań, zamiast tworzyć nowe klucze.
- **507**: Przekroczono limit miejsca na dysku lub liczby plików konta, nie pamięci RAM. Usuń zbędne pliki/historię przez UI.

Bez ujawniania hasła i ciasteczek sprawdź publiczną stronę logowania:

```zsh
curl -sS -o /dev/null -w 'GET /login: HTTP %{http_code}\n' "$BASE/login"
```

`200` potwierdza tylko dostępność publicznej strony logowania — **nie sukces logowania ani dostępność batch API**. Nie publikuj pliku cookies ani pełnych prywatnych analiz w zgłoszeniu. [Kontrakt API i ograniczenia bezpieczeństwa](batch-api.md).
