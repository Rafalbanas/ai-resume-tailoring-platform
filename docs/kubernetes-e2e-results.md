# Testy integracyjne Kubernetes i AI — 15 października 2026

Testy dotyczą wyłącznie `kind-cvtailor-lab`, namespace `cvtailor-lab`,
fikcyjnego profilu **Alex Example** i fikcyjnej oferty Application Support Engineer.
Wywołania Google korzystają z istniejącego konta API. Aplikacja produkcyjna
uruchomiona przez Docker Compose nie jest celem testów.

## Wyniki

| Scenariusz | Wynik | Sprawdzenie |
| --- | --- | --- |
| Pełne CV przez Ollamę | PASS | Analiza i dopasowanie, podgląd, pobranie oraz parsowanie PDF i DOCX; `provider_used=ollama`, bez fallbacku |
| Niedostępna Ollama | PASS | Automatyczne przełączenie na Gemini, `fallback_used=true`, poprawne PDF i DOCX |
| Niedostępni obaj dostawcy | PASS | Zadanie `failed`, komunikat o obu dostawcach, dostępna strona zadania i HTTP health |
| Przerwanie aktywnej analizy | PASS | SIGKILL kontenera podczas aktywnego zadania; po restarcie stare zadanie `failed` z prośbą o retry; nowe zadanie zakończone PDF i DOCX |
| Backup i odtworzenie | PASS | Odtworzone 51 plików z identycznymi hashami; aplikacja na nowym PVC udostępniła wszystkie 3 zestawy PDF/DOCX przez HTTP |
| Nowy obraz i rollback | PASS | Nowy statyczny artefakt wydania widoczny przez HTTP, inny identyfikator obrazu, powrót do pierwotnego identyfikatora i szablonu Deployment |

PDF wygenerowany przez Ollamę ma 1 stronę i 13 992 bajty; DOCX ma 37 452 bajty.
Wariant po przełączeniu na Gemini ma 1 stronę PDF (13 910 bajtów) i DOCX
o rozmiarze 37 362 bajtów. Eksporty zawierają imię i nazwisko fikcyjnego kandydata.

Przerwane zadanie: `b5721a96e8114fe482d154145c63770e`.
Nowe zadanie po retry: `7565461afc0840dc8c0178203c2aae8b`.
Aplikacja nie wznawia automatycznie przerwanego zadania: zachowuje je jako
nieudane i umożliwia jawne utworzenie nowego przez przycisk Retry.

Kopia: `.k8s-lab/e2e/lab-data-20261015T154936Z.tar.gz`, SHA-256:
`21ca812220b2aae9bf3053debbb9d414fc953ad64b8d28859dedd62caf833717`.
Przed archiwizacją aplikacja była zatrzymana, aby dane, w tym SQLite, nie zmieniały
się w trakcie kopiowania. Porównanie hashy wykonano przed startem odtworzonej
aplikacji. Tymczasowe pody i nowy PVC zostały usunięte po sprawdzeniu odtworzenia.

Identyfikatory obrazów z runtime containerd:

- Pierwotny i przywrócony: `sha256:d7ac9863a0fee15534f8c52ebe1f5e3006749e823df285a0437ca3c79ba038f0`.
- Wydanie `cvtailor:lab-e2e-v2`: `sha256:2fd829cd8e21c9b8272b60874376c7fff250b55253679da2abe75f2496245932`.

Nowy plik statyczny zwrócił `kubernetes-e2e-v2`, a po rollbacku jego URL ponownie
zwracał `404`. Pozostawiono pierwotny obraz oraz konfigurację Ollama → Gemini.

Przykładowe eksporty znajdują się w prywatnym katalogu wyników:

- [PDF z Ollamy](../.k8s-lab/e2e/exports/primary-e2e.pdf), [DOCX z Ollamy](../.k8s-lab/e2e/exports/primary-e2e.docx).
- [PDF po fallbacku na Gemini](../.k8s-lab/e2e/exports/fallback-e2e.pdf), [DOCX po fallbacku](../.k8s-lab/e2e/exports/fallback-e2e.docx).
- [PDF po ponowieniu zadania](../.k8s-lab/e2e/exports/retry-e2e.pdf), [DOCX po ponowieniu](../.k8s-lab/e2e/exports/retry-e2e.docx).

Pliki nie są częścią Git; powyższe linki działają w lokalnym workspace.

## Powtórzenie

Wymagane jest uruchomione laboratorium z integracją `ai`, dostępem do Ollamy
i Gemini. Uruchamiaj scenariusze kolejno, nigdy równolegle: modyfikują konfigurację,
restartują kontener, a backup chwilowo skaluje Deployment do zera.
Skrypty weryfikują namespace i fikcyjny profil przed rozpoczęciem.

Pełna ścieżka HTTP przez Ollamę:

```bash
kubectl --kubeconfig "$HOME/.kube/cvtailor-lab.config" --context kind-cvtailor-lab \
  -n cvtailor-lab exec -i deployment/cvtailor -c app -- \
  python -u - generate primary-e2e --provider ollama --expected-provider ollama --fallback false \
  < scripts/k8s-e2e-http.py
```

Pozostałe scenariusze:

```bash
python3 -u scripts/k8s-e2e-suite.py fallback
python3 -u scripts/k8s-e2e-suite.py outage
python3 -u scripts/k8s-e2e-suite.py crash
python3 -u scripts/k8s-e2e-suite.py backup
```

Przed scenariuszem obrazu przygotuj lokalne wydanie testowe:

```bash
docker build -t cvtailor:lab-e2e-v2 deploy/k8s/exercises/release-v2
kind load docker-image cvtailor:lab-e2e-v2 --name cvtailor-lab
python3 -u scripts/k8s-e2e-suite.py image
```

To wydanie dodaje plik `/static/kubernetes-release.txt`; nie zmienia logiki AI.
Test ma wykazać wdrożenie innej zawartości obrazu i faktyczne przywrócenie
poprzedniego obrazu, a nie tylko zmianę zmiennej środowiskowej.

Scenariusze awarii przywracają konfigurację w `finally`. Wyniki HTTP pozostają
na PVC w `/lab-data/.e2e/`, a wyniki orkiestracji i archiwum w hostowym
`.k8s-lab/e2e/`. Ten katalog jest wykluczony z Git i obrazu aplikacji.
Kopia danych zawiera m.in. sesje i hasło w postaci hasha, więc archiwum ma
uprawnienia `0600` i powinno być traktowane jako prywatne.

## Granice testów

Odtworzenie danych sprawdzamy na osobnym, nowym PVC w istniejącym klastrze.
Oryginalny PVC nie jest usuwany. Odtworzona aplikacja korzysta z istniejących
ConfigMap i Secret. Test nie oznacza odtworzenia całego VPS ani odzyskania
utraconych sekretów, konfiguracji klastra lub tunelu SSH.

Lokalna kopia na tym samym VPS nie chroni przed utratą jego dysku. Docelowo
potrzebna jest również zabezpieczona kopia poza VPS. Testy sprawdzają działanie
przepływu i infrastruktury, a nie jakość dopasowania CV do prawdziwych ofert.
