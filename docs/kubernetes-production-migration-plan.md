# Plan migracji CVTailor do Kubernetes

Status: migracja wykonana 15 października 2026 po późniejszej zgodzie użytkownika.
Raport wdrożenia i aktualna obsługa: [kubernetes-production.md](kubernetes-production.md).
Poniższy tekst zachowuje historyczne założenia planowania; późniejsza prośba
użytkownika obejmuje przeniesienie archiwów i magazynu K3s na `/storage` oraz
usunięcie sprawdzonych lokalnych zasobów laboratorium. Zwykły Docker pozostaje.
Ustalenia z 15 października 2026: obecny VPS, obecna SQLite i wszystkie pliki,
zachowanie działania aplikacji, dopuszczona kilkunastominutowa przerwa na końcowe
przeniesienie danych i przełączenie ruchu.

Cel doprecyzowany po przeglądzie opinii Antigravity: projekt Kubernetes do
portfolio, praktyka wdrażania, obsługi awarii i monitorowania, przy zachowaniu
obecnych funkcji CVTailor. Migracja pozostaje wyborem edukacyjnym z dodatkowym
kosztem utrzymania; nie zakładamy poprawy HA na jednym VPS ani automatycznego
uproszczenia obecnego CD. Instalacja produkcyjna wymaga przejścia poniższych prób.

## 1. Zakres i stan obecny

| Element | Ustalenie | Postępowanie |
| --- | --- | --- |
| Główna aplikacja | Docker Compose, kontener `cv-tailor`, backend `127.0.0.1:18000` | Jeden Deployment produkcyjny |
| Domena | `https://cv.banas.dev`, Nginx na hoście, obecne certyfikaty TLS | Zachować adres, certyfikaty, nagłówki, timeouty i limity uploadu |
| Demo | `/demo/` → `127.0.0.1:18001`, `cvtailor-recording-demo.service` | Oddzielny Deployment i Service; zachować przekierowanie `/demo` i obsługę prefiksu |
| Kod demo | `scripts/recording_demo.py`, uruchamiany z lokalnego środowiska Python | Zamrozić i spakować także ten wariant; nie zakładać, że jest identyczny z obrazem produkcji |
| Dane główne | `/root/ai-resume-tailoring-platform/data`, około 106 MB w chwili odczytu | Przenieść cały katalog, włącznie z plikami ukrytymi |
| Dane demo | `/root/.local/share/cvtailor-recording-demo` | Oddzielny wolumen i oddzielna konfiguracja; przejąć istniejące zachowanie inicjalizacji demo |
| Baza aplikacji | SQLite `sessions.sqlite3`, używana do sesji | Zachować SQLite, jej zawartość i uprawnienia; żadnej konwersji na PostgreSQL |
| Pozostały stan | Profile i bank umiejętności w JSON, zadania w plikach, dokumenty na dysku | Wszystko objąć kopią i migracją |
| Ollama | `qwen3.5:9b`, tunel SSH na `127.0.0.1:11434` | Zachować model i tunel; przygotować dostęp z docelowego klastra |
| Gemini | `gemini-3.1-flash-lite`, istniejący klucz | Przenieść klucz do Secret produkcji, zachować wybór dostawcy i ustawienie fallbacku |
| Inne integracje | Konfiguracja n8n występuje w uruchomionej aplikacji | Przejąć komplet efektywnej konfiguracji, sprawdzić faktycznie aktywne integracje |
| Wdrażanie | Istniejący workflow i skrypt CD kierują do Compose | Przygotować docelową ścieżkę CD do Kubernetes |
| Pozostałe usługi VPS | Inne domeny, n8n, inne kontenery i usługi systemowe | Nie obejmować ich migracją CVTailor ani czyszczeniem jego obrazów |

Produkcja ma obecnie etykietę rewizji
`4ab82e71cb7a00a04114fbb49eb0f18536f61841` i lokalny identyfikator obrazu
`sha256:32ab7e0e4ddebbb0df3924c037be324d20b5179fbbfdf47377893e232ddd41f9`.
To odczyt z planowania: przy wykonaniu ponownie sprawdzimy aktualny stan.
Obraz laboratorium jest inny; nie wolno użyć go jako zamiennika produkcji.

Repozytorium zawiera wcześniejsze zmiany oraz konflikt w README. Migracja ma
wykorzystać zamrożony działający obraz; porządkowanie zmian i publikacja nowych
wersji wymaga osobnego przeglądu, aby przypadkiem nie zmienić funkcjonalności.

W kopii danych uwzględniamy w szczególności `auth.json`, `sessions.sqlite3`
i istniejące pliki pomocnicze SQLite, `master_profile.json`, `skills.json`,
`ai_settings.json`, `generated/` wraz z wersjami dokumentów, `tasks/`,
`reference_cvs/`, `profile_photo/`, `.drafts/` oraz `.diagnostics/`.

## 2. Docelowy układ

Jeden węzeł K3s na obecnym VPS i osobny namespace `cvtailor-prod`.
Kind pozostaje środowiskiem ćwiczeniowym do czasu zakończenia migracji.
K3s jest propozycją docelowego klastra; kind projektowano głównie do testów,
lokalnego developmentu i CI ([dokumentacja kind](https://kind.sigs.k8s.io/)).

```text
Użytkownik → obecny Nginx / HTTPS
                ├─ /       → wejście wewnętrzne → CVTailor → lokalny PVC z SQLite i plikami
                └─ /demo/  → wejście wewnętrzne → demo     → oddzielny lokalny PVC

CVTailor → dostęp do loopback hosta lub prywatny most → istniejący tunel SSH → Ollama
         → HTTPS → Gemini / inne faktycznie skonfigurowane integracje
```

Założenia docelowe:

- Jedna replika głównej aplikacji, strategia `Recreate`; plikowe zadania i SQLite
  nie są obecnie przygotowane do dowolnego skalowania poziomego.
- Oddzielna konfiguracja, sekrety, dane i cookies demo; brak współdzielenia
  produkcyjnego katalogu danych z demo lub laboratorium.
- Dane na lokalnym dysku VPS, np. pod `/var/lib/cvtailor/`, przez jawnie opisane
  PV/PVC z polityką `Retain` i przypisaniem do węzła. Usunięcie Deployment nie może
  usuwać danych. Sam zapis `1Gi` w żądaniu nie jest gwarancją limitu dysku.
- Dotychczasowy Nginx kończy TLS. Komunikacja z aplikacją ma działać bez stałego
  `port-forward` i bez otwierania nowego publicznego portu aplikacji.
- W wariancie CNI wybrać i utrwalić adresy Service w docelowym zakresie sieci,
  sprawdzić dostęp z hostowego Nginx; nie wpisywać przypadkowego IP aktualnego poda.
- Przy instalacji K3s wyłączyć Traefik i ServiceLB, aby nie przejęły portów 80/443
  zajętych przez obecne wejście HTTPS. Domyślne zajmowanie tych portów opisuje
  [dokumentacja sieci K3s](https://docs.k3s.io/networking/networking-services).
- Zachować API klastra jako usługę administracyjną, bez publicznego otwarcia
  kubeconfig lub tokenów. Reguły UFW ograniczyć do faktycznie potrzebnego ruchu.

Przed przygotowaniem manifestów trzeba rozstrzygnąć wariant wejścia sieciowego
przez próbę na tym VPS. Prostym kandydatem jest `hostNetwork: true`, odtwarzający
obecne Compose `network_mode: host`: główna aplikacja nasłuchuje wyłącznie na
`127.0.0.1:18000`, demo na `127.0.0.1:18001`, a Ollama pozostaje dostępna jako
`127.0.0.1:11434`. Usuwa to potrzebę pośrednika Ollamy w tym wariancie. Ceną jest
współdzielenie sieci hosta i konieczność kontroli konfliktów portów. Nie wolno
przy tej konfiguracji zmienić nasłuchiwania aplikacji na `0.0.0.0` bez odrębnej oceny.

Dla hostNetwork sondy HTTP muszą sprawdzać właściwy port na `127.0.0.1` zgodnie
z [dokumentacją sond](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/).
Bezpośrednie połączenie Nginx z loopback pomija wybór gotowych endpointów Service:
readiness będzie warunkiem odbioru wdrożenia, lecz sama nie odetnie ruchu z Nginx.
To ograniczenie należy jawnie udokumentować i przetestować.

Alternatywą pozostają pody w CNI z kontrolowanym wejściem do aplikacji i prywatnym
mostem do Ollamy. Sam ExternalName lub EndpointSlice nie udostępni tunelu, który
nasłuchuje wyłącznie na loopback hosta. `host.k3s.internal` nie jest założeniem,
na którym można oprzeć wdrożenie bez jego skonfigurowania i sprawdzenia.
NodePort nie jest automatycznym zamiennikiem portu 18000: domyślny zakres to
30000–32767, a obsługa localhost zależy od trybu i konfiguracji kube-proxy.
Sam `hostPort` również wymaga jawnego ograniczenia adresu hosta i testu CNI.
Sprawdzone wejście sieciowe jest warunkiem przejścia do migracji, a nie szczegółem
do ustalenia podczas końcowego okna.

SQLite aplikacji i wewnętrzna baza samego K3s to dwie różne rzeczy. Kopia PVC
CVTailor nie zastępuje kopii konfiguracji i danych klastra.

## 3. Przygotowanie i zamrożenie wersji

Przed jakimikolwiek zmianami wykonawczymi:

1. Odczytać ponownie obraz, digest rejestru, rewizję kodu, polecenie uruchomienia,
   wszystkie efektywne ustawienia i montowania produkcji. Wartości sekretów
   przechowywać wyłącznie w prywatnym materiale migracyjnym.
2. Zamrozić oddzielnie bieżący kod, ustawienia i sposób startu demo.
3. Zinwentaryzować wszystkie pliki obu katalogów danych: liczby, rozmiary,
   uprawnienia, hashe, dowiązania oraz dodatkowe ścieżki używane przez konfigurację.
4. Zachować konfigurację Nginx dla domeny CVTailor, Compose, jednostkę demo,
   konfigurację tunelu i aktualną ścieżkę CD. Nie kopiować do publicznego raportu
   haseł, kluczy API ani kluczy prywatnych.
5. Zatrzymać możliwość uruchomienia starego deploymentu CD w trakcie migracji.
   Samo zbudowanie obrazu w CI nie może niechcący uruchomić starego kontenera.
6. Zdefiniować kryteria odbioru i moment powrotu: brak utraty plików, prawidłowe
   logowanie, główna strona oraz demo, eksporty i obaj dostawcy AI.

Wynik etapu: jednoznacznie wiadomo, co przenosimy i do czego możemy wrócić.

## 4. Przygotowanie klastra i zasobów bez przełączania domeny

1. Sprawdzić nakładanie podsieci Docker, kind, K3s, VPN i routingu VPS.
   Zarezerwować porty oraz adresy przed instalacją.
2. Zarchiwizować wyniki laboratorium i zatrzymać jego obciążenie, bez kasowania
   danych i obrazów. VPS ma 4352 MB RAM; nie planować jednoczesnego utrzymywania
   pełnego laboratorium, nowego klastra i wszystkich próbnych aplikacji.
3. Zainstalować przypiętą, wspieraną wersję K3s z wyłączonym Traefik/ServiceLB.
   Zweryfikować ponownie działanie istniejących stron, Docker i reguł UFW.
4. Przygotować manifesty produkcyjne: namespace, PV/PVC, ConfigMap, Secret,
   Deployment, Service, sondy oraz minimalne uprawnienia. Nie używać manifestów
   laboratorium z `PROFILE_MODE=sample` jako konfiguracji produkcyjnej.
5. Przenieść wartości konfiguracyjne z działającej instancji, nie tylko wartości
   przykładowe z repozytorium. Zachować sekrety sesji/CSRF, ustawienia cookies,
   TTL, limity uploadu, timeouty, modele i zapisane ustawienia AI.
6. Skonfigurować obrazy po niezmiennym digest. Sprawdzić możliwość pobrania przez
   runtime K3s, również autoryzację GHCR, jeśli obraz jest prywatny. Docker i
   containerd K3s mają oddzielne magazyny obrazów.
7. Dopasować demo do kontenera: parametryzować jego katalog danych i adres
   nasłuchiwania, zachowując domyślne zachowanie dotychczasowego uruchomienia.
   Obecny wrapper ma ścieżkę pod `/root` i nasłuch na loopback; nie można go
   bez sprawdzenia uruchomić jako zwykłego nieuprzywilejowanego poda za Service.
8. Przygotować połączenie do Ollamy zgodnie z wybranym wariantem sieciowym.
   Przy hostNetwork sprawdzić bezpośredni dostęp do tunelu. Przy CNI przygotować
   prywatny most i ograniczyć źródła ruchu. Reguły z kind nie są automatycznie
   poprawne dla CNI K3s; trzeba je dobrać i sprawdzić ponownie.
9. Przygotować i przetestować nowy wariant skryptu wdrożeniowego i workflow CD.
   Prace prowadzić w izolowanym checkout, bez nadpisywania wcześniejszych zmian
   w bieżącym repozytorium. Nowa ścieżka musi być gotowa przed przełączeniem;
   jej aktywacja produkcyjna jest częścią odbioru migracji.

Początkowe requests/limits oprzeć na pomiarach aplikacji i generowania PDF,
pozostawiając zapas dla systemu i innych usług. Sprawdzić pamięć widoczną przez
scheduler względem realnego limitu VPS. Nie dodawać na tym etapie ciężkiego
stosu monitoringu ani dodatkowego serwera bazy danych.

Wykonać pomiary szczytowego RAM i czasu odpowiedzi `/health` podczas eksportu
PDF oraz pobierania ofert przez Playwright. PDF w tej aplikacji generuje
WeasyPrint; Playwright/Chromium dotyczy ekstrakcji stron. Oczekiwanie przez
asynchronicznego klienta na Ollamę nie oznacza samo w sobie zablokowania pętli
zdarzeń. Ciężkie synchroniczne etapy trzeba zmierzyć osobno. Parametrów sond
nie kopiować z propozycji bez testu obciążenia i obserwacji fałszywych restartów.

Swap jest możliwością do oceny po pomiarach, a nie obowiązkowym warunkiem ani
gwarancją uniknięcia OOM. Sprawdzić możliwości VPS, kernel, cgroups i ustawienia
kubeleta. Dopuszczenie swap wymaga m.in. `failSwapOn: false`; używanie go przez
workloady ma osobną politykę. Opisuje to [dokumentacja swap Kubernetes](https://kubernetes.io/docs/concepts/cluster-administration/swap-memory-management/).
Jeśli po zatrzymaniu kind zabraknie rzeczywistego zapasu RAM lub dysku na próbę,
wstrzymać instalację i zmienić zasoby albo miejsce docelowe. Nie usuwać kopii
powrotu w celu zmieszczenia migracji.

## 5. Próba migracji na kopii

Przygotować spójną kopię danych produkcyjnych i oddzielną kopię danych demo.
Dla SQLite użyć poprawnego mechanizmu kopii lub zatrzymania zapisów; nie kopiować
w ciemno pojedynczego pliku aktywnej bazy. Roboczy snapshot może powstać w krótkim
wcześniejszym oknie lub przez zweryfikowaną procedurę backupu online.

Kopię produkcyjną traktować jako prywatną. Nie uruchamiać na niej automatycznie
generacji wysyłających dane kandydata do Google. Próby AI i awarii nadal wykonywać
na fikcyjnych danych w odrębnym zestawie testowym.

Sprawdzić przed końcowym oknem:

- Uruchomienie dokładnego obrazu produkcji z kopią danych, bez zmiany schematu.
- `PRAGMA integrity_check` SQLite, obecność sesji i poprawne uprawnienia UID/GID.
- Odczyt profilu, umiejętności, zdjęcia, referencyjnych CV, historii, wersji
  dokumentów, diagnostyki i utrwalonych ustawień.
- Dostęp do istniejących PDF/DOCX i zgodność hashy plików z kopią źródłową.
- Odtworzenie hosta/prefiksów i nagłówków HTTPS; zaufanie do forwarded headers
  tylko z faktycznego proxy, bez ogólnego `*`.
- Demo: `/demo` → `/demo/`, logowanie, zasoby statyczne, cookies, formularze,
  generowanie i ograniczenia demo zgodne z dotychczasowym działaniem.
- Pełny przepływ na fikcyjnej ofercie, Ollama, Gemini, fallback, błąd obu
  dostawców, restart zadania, odtwarzanie danych i rollback obrazu — tym razem
  w docelowym klastrze oraz na docelowych obrazach.

Przygotować docelową zmianę upstreamów Nginx i przeprowadzić test konfiguracji.
Próba ma zakończyć się protokołem odbioru, zanim domena zostanie przełączona.

## 6. Jedno końcowe okno przełączenia

Zakładane okno to kilkanaście minut po zakończeniu wszystkich przygotowań;
czas doprecyzujemy po próbie kopiowania i testach. Około 10. minuty sprawdzamy
postęp; jeśli bezpieczne zakończenie przed końcem uzgodnionego okna jest
niepewne, rozpoczynamy powrót. Budowania obrazów i instalacji klastra nie
wykonujemy w tym oknie.

1. Włączyć komunikat serwisowy dla aplikacji i demo. Zamknąć dopływ nowych
   zapisów i analiz, zaczekać na zakończenie aktywnych zadań. Jeśli zadanie nie
   kończy się w uzgodnionym czasie, przesunąć migrację zamiast przerywać je po cichu.
2. Zatrzymać `cv-tailor` i `cvtailor-recording-demo.service`. Potwierdzić, że nie
   pozostał żaden proces zapisujący do przenoszonych danych.
3. Wykonać końcową, datowaną kopię obu katalogów, konfiguracji, sekretów i
   informacji o obrazach. Potwierdzić integralność SQLite i zapisać manifest hashy.
4. Przenieść końcowe dane na przygotowane docelowe wolumeny. Zachować pliki
   ukryte, komplet dokumentów i sesje; uprawnienia zmieniać tylko w docelowej kopii.
5. Uruchomić główną aplikację i demo w K3s. Nigdy nie uruchamiać starej i nowej
   instancji zapisujących równolegle do tego samego katalogu danych.
6. Sprawdzić gotowość, bazę, liczbę plików i pobranie istniejącego dokumentu.
   Sondy zdrowia nie mogą generować płatnych zapytań AI.
7. Przełączyć oba upstreamy domeny w Nginx. Zachować semantykę obcinania prefiksu
   `/demo/`, nagłówki Host/HTTPS, certyfikaty, redirecty i dotychczasowe limity.
   Test konfiguracji, następnie reload Nginx. DNS domeny nie wymaga zmiany.
8. Zweryfikować zewnętrznie HTTPS, logowanie, CSRF, sesje, panel, historię,
   pobranie PDF/DOCX i `/demo/`. Sprawdzić oba modele i pełny przepływ na
   kontrolowanym, fikcyjnym zadaniu bez podmieniania prawdziwego profilu.
9. Zdjąć komunikat serwisowy po pozytywnym odbiorze. Zapisać godzinę, digest,
   konfigurację i lokalizację kopii sprzed przełączenia.

Obecnych sekretów i `auth.json` nie regenerujemy. To warunek zachowania konta
i sesji, w granicach ich normalnego TTL i dotychczasowych ustawień cookies.

## 7. Powrót do wcześniejszego wdrożenia

Przyczyny powrotu: problem z integralnością danych, logowaniem, eksportami,
demo, dostępem do modeli lub stabilnością pamięci, którego nie da się szybko
usunąć w oknie przełączenia.

Jeśli nowa instancja nie przyjęła jeszcze zapisów, wracamy do zachowanych danych
i procesów Compose/systemd oraz poprzednich upstreamów Nginx.

Jeśli po przełączeniu pojawiły się nowe CV, zmiany profilu lub inne zapisy:

1. Zablokować nowy ruch zapisujący i zatrzymać docelowe pody.
2. Zachować kopię aktualnych danych Kubernetes i kopię starego katalogu.
3. Przenieść najnowsze dane z PVC do starego miejsca uruchomienia, sprawdzić
   SQLite i hashe. Dopiero wtedy wznowić Compose/systemd i przełączyć Nginx.

Samo przełączenie proxy do starej, nieaktualnej kopii mogłoby zgubić nowe dane.
Migracja bez zmiany schematu i logiki aplikacji upraszcza ten powrót. Oba sposoby
rollbacku należy przećwiczyć przed właściwą migracją na danych testowych.

## 8. Wdrażanie i kopie po migracji

- Przełączyć mechanizm CD na namespace produkcyjny, zachowując ręczne
  wyzwalanie, testy, kontrolę rewizji, blokadę równoległych wdrożeń, kontrolę
  aktywnych zadań i weryfikację uruchomionego digestu.
- Użyć dedykowanych, ograniczonych uprawnień wdrożeniowych. Nie przekazywać
  workflow pełnego kubeconfig administratora klastra.
- Ograniczyć tożsamość wdrożeniową do wskazanych zasobów namespace produkcyjnego.
  Standardowe RBAC nie ogranicza `patch` Deployment do samego pola obrazu;
  walidację digestu i dozwolonych zmian zapewnić kontrolowanym skryptem
  wdrożeniowym lub odpowiednią polityką. Nie nadawać zbędnego dostępu do Secret,
  `pods/exec`, ról ani zasobów innych aplikacji. Uwzględnić ryzyko zmiany szablonu
  poda opisane w [zaleceniach RBAC](https://kubernetes.io/docs/concepts/security/rbac-good-practices/).
- Zachować blokadę równoległych wdrożeń i dodać sprawdzony protokół drain:
  zablokować przyjmowanie nowych zadań, poczekać na już przyjęte operacje HTTP
  oraz zadania `queued/running`, a dopiero potem wymienić pod. Blokada przyjęć
  musi obejmować analizę, porównania i retry oraz zapobiegać wyścigowi z enqueue.
  Testem odbioru jest równoczesne zlecenie zadania i rozpoczęcie wdrożenia.
  Przy przekroczeniu limitu oczekiwania odmówić wdrożenia i bezpiecznie zdjąć drain.
  Obecny `stop_worker()` anuluje worker; samo dłuższe `terminationGracePeriodSeconds`
  lub oczekujący `preStop` bez blokady nowych przyjęć nie rozwiązuje tego problemu.
  Budżet zamykania musi uwzględniać czas hooka i zakończenia procesu.
- Sprawdzić nowy release i rollback już przez docelową ścieżkę CD. Wykluczyć
  możliwość ponownego wdrożenia do starego Compose.
- Przechować co najmniej bieżący i poprzedni zatwierdzony obraz oraz manifesty.
- Przygotować zabezpieczoną kopię danych aplikacji, danych demo, sekretów,
  manifestów i konfiguracji wejścia HTTPS. Zachować możliwość odtworzenia bez
  lokalnego rejestru i bez pamięci podręcznej obrazów.
- Uzupełnić kopię stanu K3s i tokenu serwera zgodnie z użytym datastore.
  [Dokumentacja K3s](https://docs.k3s.io/datastore/backup-restore) wskazuje także
  konieczność zachowania tokenu przy odtwarzaniu. Kopię sprawdzić przez odtworzenie.
- Zweryfikować podłączenie dysku sieciowego 125 GB lub innego miejsca poza VPS.
  W odczycie planistycznym nie znaleziono zamontowanego NFS/CIFS/SSHFS; nie
  traktujemy więc tej przestrzeni jako gotowego miejsca backupu bez sprawdzenia.
  SQLite aplikacji pozostaje na lokalnym dysku.
- Ustalić harmonogram spójnych kopii i retencję. Przykładowy punkt wyjścia:
  kopie dobowe przez 7 dni oraz 4 tygodniowe, po sprawdzeniu faktycznej przestrzeni.
  Procedura musi uwzględniać zapisy aplikacji i SQLite, a nie tylko pakować aktywny
  katalog. Kopia sprzed migracji i pierwsza kopia po migracji są obowiązkowe.

Na jednym VPS Kubernetes nie zapewni odporności na awarię całego serwera.

Monitoring ma obejmować osobno: dostępność HTTPS z zewnątrz VPS, brak gotowego
poda, wzrost restartów i OOM, stan PVC, wolne miejsce, pamięć hosta, długie kolejki
i błędy zadań oraz dostępność modeli. `Running` ani HTTP `200` z `/health` nie
potwierdzają działania całego przepływu AI. Na początek wykorzystać bieżące
metryki klastra, ograniczone logi i lekki monitoring poza VPS, bez zakładania
konkretnego zużycia pamięci całego stosu Prometheus/Grafana. Kanał i progi alertów
uzgodnić przed uruchomieniem. Sondy liveness nie powinny restartować aplikacji
wyłącznie z powodu chwilowej awarii dostawcy AI.

Materiały do portfolio mają zawierać diagram, uzasadnienie wyborów, manifesty
bez sekretów, kontrolowany CI/CD, procedurę backupu i wyniki odtwarzania oraz
raporty prób awarii. Opis CV musi oddzielać ukończone laboratorium kind od
planowanego wdrożenia produkcyjnego K3s; nie deklarować wdrożenia przed odbiorem.

## 9. Obserwacja i sprzątanie

Proponowany okres obserwacji: 7 dni od odbioru, z możliwością wcześniejszego
przeglądu po 24–48 godzinach. Sprawdzić nowe CV, logowanie, uploady, demo,
zużycie dysku/RAM, restarty, połączenie tunelu i wykonanie backupu.
Sprzątanie zaczyna się dopiero po pozytywnym odbiorze, sprawdzeniu kopii poza VPS
i potwierdzeniu, że docelowy CD działa.

Kolejność sprzątania:

1. Sporządzić listę kontenerów, obrazów, referencji i wolumenów w Docker oraz
   osobno w containerd K3s. Uwzględnić wspólne warstwy; suma rozmiarów obrazów
   nie odpowiada ilości miejsca możliwej do odzyskania.
2. Wyłączyć automatyczny start starego Compose i jednostki demo, zachowując ich
   opis, konfigurację i pakiet powrotu do czasu końca retencji.
3. Zarchiwizować potrzebne wyniki laboratorium. Usunąć jego sekrety, własny most
   i regułę UFW, a dopiero potem klaster kind i jego dane.
4. Usunąć wyłącznie rozpoznane obrazy testowe CVTailor, np. wariant
   `lab-e2e-v2` i później zbędny `lab`, po sprawdzeniu referencji w kontenerach.
5. Warianty historyczne typu `before-*`, `currently-learning` lub `exact-token-usage`
   ocenić osobno. Nazwa nie jest dowodem, że obraz można usunąć — część może być
   zachowanym rollbackiem wcześniejszych zmian produkcyjnych.
6. Usunąć nieużywany cache budowania i zbędne artefakty dopiero po inwentaryzacji.
   Usuwanie ma wskazywać konkretne zasoby; nie stosować globalnego czyszczenia
   Docker ani usuwania wolumenów obejmującego inne aplikacje VPS.
7. W K3s zachować bieżące i poprzednie zatwierdzone wydanie. Obrazy usług
   współdzielonych, w tym Nginx, n8n oraz innych aplikacji, wyłączyć z tej operacji.
8. Sprawdzić wszystkie dotychczasowe domeny, stan klastra i wolne miejsce.
   Zapisać, które identyfikatory usunięto i ile miejsca faktycznie odzyskano.

## 10. Warunki zakończenia

- Główna aplikacja i demo obsługują dotychczasowe adresy w Kubernetes.
- Profil, umiejętności, zdjęcia, referencyjne CV, historia, dokumenty, zadania
  i ustawienia są kompletne; SQLite przechodzi sprawdzenie integralności.
- Dotychczasowe konto, zasady cookies/CSRF i normalne zachowanie sesji są zachowane.
- Ollama, Gemini, fallback i aktywne integracje działają z docelowego klastra.
- Istniejące dokumenty dają się pobrać, a nowe dają się wygenerować i otworzyć.
- Kopia i odtwarzanie są sprawdzone, w tym dostęp do kopii poza tym VPS.
- Nowa ścieżka CD wdraża przypięty obraz i pozwala wrócić do poprzedniej wersji.
- Pozostałe usługi VPS działają poprawnie po instalacji, przełączeniu i sprzątaniu.
- Zasoby testowe usunięto dopiero po obserwacji, z zachowaniem ustalonej retencji.

Historycznie plan wymagał osobnej zgody na wykonanie. Użytkownik udzielił jej
w kolejnej wiadomości; wykonane działania opisuje raport wdrożenia. Sam etap
sporządzania tego planu nie zmieniał infrastruktury.
