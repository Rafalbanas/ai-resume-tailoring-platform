# CVTailor: produkcyjny K3s

Wdrożono 15 października 2026 na obecnym VPS. Główna aplikacja i demo działają
w namespace `cvtailor-prod`. Pierwsze przełączenie trwało **44 sekundy**.
Snapshot dysku użytkownika nie był odczytywany, zmieniany ani przywracany.

## Architektura

```mermaid
flowchart LR
    U[Użytkownik HTTPS] --> N[Nginx na hoście]
    N -->|127.0.0.1:18000| A[Deployment cvtailor]
    N -->|/demo/ → 127.0.0.1:18001| D[Deployment cvtailor-demo]
    A --> P[Lokalny PVC: profil, sesje SQLite, zadania, dokumenty]
    D --> Q[Oddzielny lokalny PVC demo]
    A --> O[Istniejący tunel SSH → Ollama]
    D --> O
    A --> G[Gemini API]
    D --> G
    B[Backup dobowy] --> S[/storage: kopie, archiwa, magazyn obrazów K3s]
    P --> B
    Q --> B
```

- K3s **v1.36.5+k3s1**, jeden węzeł `cvtailor-prod`, Traefik i ServiceLB wyłączone.
- `hostNetwork` i nasłuch wyłącznie na loopback zachowują istniejący Nginx oraz
  dostęp do tunelu Ollamy. Service nie uczestniczy w tej ścieżce ruchu.
- Nginx, certyfikaty, nagłówki, limity, timeouty i prefiks demo pozostają zgodne
  z wcześniejszym wdrożeniem. `/demo` nadal przekierowuje do `/demo/login`.
- Po jednej replice, strategia `Recreate`, grace period 120 sekund.
  Aplikacja z zadaniami w plikach i SQLite nie jest przygotowana do wielu replik.
- Dane: `/var/lib/cvtailor/production/main` i `demo`, osobne PV/PVC, polityka
  `Retain`, UID/GID 10001. Zadeklarowane 4 GiB i 1 GiB nie stanowią limitu dysku.
- Requests RAM: 256 MiB / 192 MiB; limity: 1 GiB / 768 MiB. Sondy HTTP sprawdzają
  `/health`, bez wywołań modeli. Readiness nie odcina hostowego Nginx od loopback.
- Konfiguracja w ConfigMap, dane poufne w Secret; szyfrowanie Secret w K3s włączone.
  API 6443 i kubelet 10250 blokowane na zewnętrznym interfejsie przez UFW.
- VPS wymaga `KubeletInUserNamespace=true`. Utrwalona konfiguracja:
  `deploy/k8s/production/k3s-config.yaml`.

## Rozmieszczenie na storage

Na dodatkową prośbę użytkownika magazyn obrazów i warstw K3s przeniesiono do
`/storage/cvtailor-k3s-runtime/containerd`. Dotychczasowa ścieżka
`/var/lib/rancher/k3s/agent/containerd` jest symlinkiem. Zwykły Docker nadal używa
`/var/lib/docker`; pozostałe cztery usługi Docker nie były restartowane.

Końcową synchronizację wykonano po zatrzymaniu wyłącznie kontenerów K3s,
przez rsync z kontrolą sum plików i zachowaniem uprawnień, ACL i xattr.
Przełączenie trwało **344 sekundy**. Obie aplikacje uruchomiły się ponownie,
a test sesji i hashy 136 pobranych dokumentów przeszedł także po tej zmianie.
Pierwotną lokalną kopię cache usunięto po sprawdzeniu nowych kontenerów.

`/etc/systemd/system/k3s.service.d/cvtailor-storage.conf` wymaga zamontowanego
`/storage` oraz prawidłowego symlinka przed startem K3s. Przy braku tego dysku
klaster nie powinien wystartować z pustym magazynem na partycji systemowej.
K3s zależy od dostępności storage także w trakcie działania. Baza control plane
oraz oba aktywne katalogi aplikacji z SQLite pozostają na lokalnym dysku.

Archiwa wcześniejszych obrazów, materiałów migracji i testów są w:

- `/storage/cvtailor-k3s-backups/` — prywatne kopie oraz pakiet migracji;
- `/storage/cvtailor-k3s-archives/` — obrazy Docker CVTailor i laboratorium;
- `/storage/cvtailor-k3s-archives/working-files/` — wcześniejsze pliki lab,
  staging i validation; dotychczasowe ścieżki są symlinkami.

Archiwum `docker-cvtailor-history.tar` sprawdzono przez identyfikatory konfiguracji
oraz SHA256 wszystkich warstw. Usunięto 8 lokalnych referencji do 6 rozpoznanych
nieużywanych obrazów CVTailor. Nie stosowano globalnego `prune` ani wymuszonego
usuwania obrazów używanych przez kontenery. Zachowany zatrzymany kontener starej
produkcji nadal ma swój obraz w Docker do ewentualnego powrotu.

## Zachowane wersje i dane

Główna aplikacja używa dokładnie wcześniejszego obrazu, rewizji
`4ab82e71cb7a00a04114fbb49eb0f18536f61841`:

```text
ghcr.io/rafalbanas/ai-resume-tailoring-platform@sha256:49010a5914ed6b3d65513a020bddcaf35195d61490ff35fb4b05172166ece5a2
```

Demo spakowano oddzielnie z przechwyconych `app/`, `templates/`, `static/`, ponieważ
wcześniej działało z lokalnego kodu, różniącego się od obrazu głównej aplikacji:

```text
docker.io/library/cvtailor-demo@sha256:116618b16403879e49f5b47aeda756b15be241db94e0333acc3c43c095c2a67d
```

Obraz demo jest zaimportowany lokalnie do K3s i zarchiwizowany na `/storage`.
Nie zakładamy, że ten adres jest dostępny w publicznym Docker Hub.
`Dockerfile.demo` opisuje sposób budowy z prywatnego, zamrożonego kontekstu.

Przeniesiono 1185 plików głównej aplikacji i 60 plików demo, w tym nowe pliki
blokady wdrażania. Każdy plik końcowej kopii porównano przez SHA256 przed startem.
Po starcie jedyną zmianą względem kopii był plik SQLite sesji użyty podczas
kontrolowanego testu uwierzytelnienia. Profil, bank umiejętności, hasła, sekrety
CSRF i zapisane ustawienia AI pozostały identyczne. Zachowano dotychczasowe sesje
i normalne TTL; nie regenerowano kont.

## Obsługa

Polecenia dla administratora VPS:

```bash
k3s kubectl -n cvtailor-prod get deploy,pods,pvc
k3s kubectl -n cvtailor-prod logs deployment/cvtailor --tail=100
k3s kubectl -n cvtailor-prod logs deployment/cvtailor-demo --tail=100
k3s kubectl top pods -n cvtailor-prod
systemctl status k3s cvtailor-backup.timer cvtailor-monitor.timer
journalctl -u cvtailor-backup.service -u cvtailor-monitor.service --since today
```

W skryptach używamy jawnie `k3s kubectl`. Administrator root ma także
`~/.kube/config` wskazujący konfigurację K3s, więc działa zwykłe `kubectl`.
Oryginalny kubeconfig laboratorium zachowano w prywatnym archiwum na storage.
Publiczne manifesty są w `deploy/k8s/production/resources.json`, uprawnienia CD
w `rbac.yaml`. Manifesty nie zawierają Secret. Samo ich zastosowanie na nowym
serwerze wymaga wcześniejszego odtworzenia danych, obrazów i sekretów.

## Kontrolowane wdrażanie

Zainstalowany, należący do roota `/usr/local/sbin/cvtailor-deploy` pochodzi z
`deploy/k8s/production/deploy.py`. Zachowuje kontrakt dotychczasowego ograniczonego
klucza SSH: `status` oraz `deploy <40-znakowy SHA> <sha256:digest>`.

Przed wdrożeniem skrypt weryfikuje repozytorium, digest i etykietę rewizji obrazu.
Token rejestru przychodzi przez stdin. Krótkotrwały kubeconfig jest usuwany po
wywołaniu; workflow nie dostaje konta administratora klastra. ServiceAccount
może get/patch/watch wyłącznie Deployment `cvtailor`. Nie może czytać Secret,
wykonywać `pods/exec` ani modyfikować demo. Rootowy wrapper odpowiada za stały
zakres zmian: obraz, dane wersji i wskazany pull Secret.

Blokada pliku serializuje wdrożenia. Middleware ASGI przyjmuje współdzieloną
blokadę na czas mutujących żądań. Skrypt CD przyjmuje blokadę wyłączną, odmawia
nowych zapisów kodem 503 z `Retry-After`, czeka na HTTP i zadania queued/running,
a dopiero potem wymienia pod. Odczyty działają. Przekroczenie limitu przerywa
wdrożenie i zwalnia blokadę. Błąd odbioru przywraca poprzedni obraz i ustawienia
wersji. Ponowne wskazanie już działającego obrazu sprawdza stan bez restartu.

Przećwiczono zmianę obrazu, wymuszony błąd odbioru i automatyczny rollback w
odrębnym namespace na tym samym K3s. Produkcyjny wrapper, komenda `status` przez
ograniczonego użytkownika i idempotentne wdrożenie przypiętego obrazu także przeszły.
Nie wykonywano nowego wydania kodu aplikacji.

Workflow `.github/workflows/cd.yml` uruchamia się automatycznie po pushu do `main` (również po merge'u PR); zachowuje ręczne wyzwalanie i kontrakt SSH.
Jego wcześniejsza gałąź `codex/vps-cd` nie jest jeszcze scalona do `main`.
Ta migracja nie scala pozostałych zmian repozytorium i nie deklaruje zakończonego
uruchomienia workflow GitHub Actions. Serwerowa ścieżka wdrażania jest już K3s.

## Kopie i odzyskiwanie

`/storage` jest osobnym zamontowanym wolumenem około 123 GiB, udostępnionym przez
dostawcę VPS. Nie utożsamiamy go ze snapshotem dysku ani kopią u innego dostawcy.

- `cvtailor-backup.timer`: codziennie 04:15 UTC, z opóźnieniem do 5 minut.
  Retencja 7 kopii dobowych i 4 tygodniowych; archiwum migracji jest poza tą retencją.
- Kopia wymaga zamontowanego `/storage`. Przy aktywnych analizach jest odkładana
  o 15 minut. Podczas krótkiej spójnej kopii blokuje zapisy; później zwalnia je
  przed kompresją. Blokada CD zapobiega zmianie wersji w czasie kopiowania.
- SQLite kopiowana przez API backup. Uwzględniono oba katalogi danych, DB K3s,
  token serwera, konfigurację szyfrowania, certyfikaty, Secret i manifesty.
- Każda kopia jest rozpakowywana do osobnego katalogu kontrolnego. Sprawdzane są
  hashe wszystkich plików i `PRAGMA integrity_check` trzech baz.
- Katalogi backupu mają dostęp tylko dla roota, archiwa tryb 0600. Zawierają dane
  osobowe i klucze; nie wolno dołączać ich do repozytorium ani publicznego zgłoszenia.

Pierwsza zweryfikowana kopia produkcyjna:
`/storage/cvtailor-k3s-backups/daily-20261015T211624Z.tar.gz`, 1324 pliki.
Informacja o najnowszej: `/var/lib/cvtailor-operations/last-backup.json`.
Materiały migracji są dostępne przez `/var/lib/cvtailor-migration/current`
i katalog, który ten plik wskazuje; zachowany stary adres prowadzi przez symlink.

Odtwarzanie aplikacji wykonuje się po zamknięciu zapisów i zatrzymaniu obu podów:
zachować aktualne dane osobno, rozpakować wybrane archiwum do katalogu roboczego,
sprawdzić `hashes.json` i SQLite, odtworzyć `main/` i `demo/` z UID/GID 10001,
następnie uruchomić pojedyncze repliki. Nie rozpakowywać kopii na działający PVC.
Odtworzenie aplikacji na świeżym PVC i pobranie PDF/DOCX zostało przetestowane.

Odtwarzanie całego K3s wymaga zatrzymania serwera, tej samej wersji K3s i węzła,
odtworzenia `cluster/state.db`, tokenu i `cred/` oraz konfiguracji. Archiwum tokenu
jest potrzebne do odszyfrowania danych. Kopię bazy klastra zweryfikowano; nie
uruchamiano drugiego control plane z kopią tożsamości działającego klastra.

## Powrót do Compose po migracji

Stary kontener `cv-tailor` jest zatrzymany z `restart=no`, a jednostka
`cvtailor-recording-demo.service` wyłączona. Ich dane i definicje zachowano.

Jeśli produkcja przyjęła zapisy po przełączeniu, **nie uruchamiać starej kopii
danych**. Najpierw:

1. Włączyć przerwę serwisową dla domeny, zablokować nowe zapisy i opróżnić zadania.
2. Zatrzymać oba Deploymenty i potwierdzić zakończenie podów.
3. Zarchiwizować aktualne PVC oraz dotychczasowe katalogi Compose/demo.
4. Przenieść najnowsze dane z PVC do dawnych katalogów, potwierdzić hashe i SQLite.
5. Odtworzyć właściwy wrapper CD z prywatnego pakietu, uruchomić zachowane procesy,
   sprawdzić sesje, dokumenty i modele, a następnie otworzyć ruch.

Przy późniejszych wydaniach aplikacji trzeba dodatkowo ocenić zgodność danych
z wcześniejszym kodem. Pierwsza migracja zachowała dokładny obraz i schemat.
Snapshot użytkownika pozostaje poza tą procedurą.

## Monitoring i ograniczenia

Lekki timer co 5 minut sprawdza gotowość, restarty/OOM, PVC, miejsce, pamięć,
długie zadania, HTTPS oraz dostępność metadanych Ollamy i Gemini. Stan prywatny:
`/var/lib/cvtailor-operations/monitor.json`. Zmiany trafiają do journald.
Nie skonfigurowano jeszcze zewnętrznego kanału alarmów ani stałego monitora
spoza VPS. Publiczne HTTPS i sesje sprawdzono przez domenę z VPS; dodatkowa
próba z narzędzia przeglądania poza VPS nie udostępniła odpowiedzi.

Pierwszy pomiar po migracji: oba pody bez restartów, około 88 i 83 MiB RAM,
około 2,8 GiB dostępnej pamięci hosta. W próbie 15 żądań zdrowia średnia wyniosła
7 ms, maksimum 76 ms; nie jest to test obciążenia produkcyjnego.

Jedna maszyna nie zapewnia HA. Utrata VPS zatrzyma aplikację. Dostęp do Ollamy
nadal zależy od istniejącego tunelu SSH. Readiness przy loopback nie zastępuje
zewnętrznego monitoringu.

## Wyniki prób

| Próba na docelowym K3s | Wynik |
| --- | --- |
| Ollama: analiza → dopasowanie → PDF/DOCX, fikcyjny profil | PASS |
| Demo na zamrożonym własnym obrazie: pełny przepływ | PASS |
| Awaria Ollamy → Gemini i poprawne eksporty | PASS |
| Awaria obu: widoczny błąd, aplikacja zdrowa | PASS |
| SIGKILL w trakcie zadania → informacja o przerwaniu → udany retry | PASS |
| Nowy PVC: 49 zgodnych plików i odzyskane dokumenty HTTP | PASS |
| CD: nowy obraz, błąd odbioru, rollback obrazu i zmiennych wersji | PASS |
| Drain: zapisy 503, odczyty 200, ponowne zapisy po zwolnieniu | PASS |
| Produkcyjne i demo PDF/DOCX: 130 + 6 zgodnych hashy | PASS |
| Sesje, CSRF, cookies HTTPS, profil, historia, referencje, umiejętności | PASS |
| Chromium: uruchomienie i ekstrakcja DOM z fikcyjnej strony | PASS |
| Pierwszy backup rzeczywistej produkcji i kontrolne odtworzenie | PASS |

Pozostałe domeny zachowały wcześniejsze statusy HTTP. `lanari.pl` i `www.lanari.pl`
nie były osiągalne już przed migracją; działającego kontenera tej aplikacji nie zmieniano.

Materiały prób pozostają prywatne na `/storage`. Obserwację produkcji należy
prowadzić przez 7 dni. Na późniejszą prośbę użytkownika archiwizujemy na storage
i usuwamy wyłącznie rozpoznane nieużywane zasoby CVTailor; zwykły Docker zostaje.


Po weryfikacji archiwów usunięto również klaster kind `cvtailor-lab`, jego
anonimowy wolumen, obraz bazowy oraz własny most Ollamy i jego jedną regułę UFW.
Wolumen porównano z archiwum `kind-node-var.tar` bajt po bajcie; zachowano także
obraz bazowy, eksport systemu plików węzła i jego konfigurację. Namespace
`cvtailor-stage` i `cvtailor-validation` wraz z ich obiektami zarchiwizowano
prywatnie i usunięto z K3s. Ich katalogi danych nadal są na storage.

Po zmianie ścieżki magazynu wykonano kolejną poprawną kopię z konfiguracją
startu wymagającą storage: `daily-20261015T214031Z.tar.gz`, 1325 plików.
Ostatni pomiar dysku systemowego po sprzątaniu: około 22 GiB zajęte, 21 GiB wolne;
na storage około 75 GiB wolne. To pomiar z chwili prac, wartości będą się zmieniać.
