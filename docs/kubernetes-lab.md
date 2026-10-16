# Kubernetes na własnej aplikacji — laboratorium

Wyniki pełnego przepływu AI, awarii, odtwarzania danych oraz zmiany obrazu:
[raport testów integracyjnych](kubernetes-e2e-results.md).

Uruchamiasz CVTailor na jednym węźle Kubernetes w Dockerze (kind).
Aplikacja używa fikcyjnego profilu i dostawcy `mock`: możesz ćwiczyć infrastrukturę
bez Ollamy, kluczy API i prawdziwych danych. Mock daje odpowiedzi testowe, a nie analizę LLM.
Istniejące wdrożenie Docker Compose działa niezależnie.

## 1. Uruchomienie

Wymagane: działający Docker, Python 3, kind i kubectl. Na serwerze, na którym
przygotowano to laboratorium, narzędzia są już zainstalowane. Konfigurację
przygotowano dla kind 0.33.0 i Kubernetes 1.37.0, z kubectl 1.37.1.
Na innym komputerze skorzystaj z oficjalnych instrukcji:
[kind](https://kind.sigs.k8s.io/docs/user/quick-start/) i
[kubectl](https://kubernetes.io/docs/tasks/tools/).
Zostaw kilka GB wolnego RAM i miejsca na obrazy Dockera; aplikacja zawiera Chromium.

Z katalogu repozytorium:

```bash
bash scripts/k8s-lab.sh up
```

Skrypt buduje obraz `cvtailor:lab`, tworzy lub wykorzystuje klaster `cvtailor-lab`,
ładuje do niego obraz i stosuje manifesty z `deploy/k8s/lab/`.
Pierwszy start może potrwać kilka minut.
Wygenerowane hasło trafia bezpośrednio do obiektu Secret, bez zapisywania go w Git.
Skrypt nie odczytuje produkcyjnego `.env` i nie montuje katalogu `data/` z hosta.
Przykładowy profil i bank umiejętności są kopiowane z obrazu tylko przy pierwszym starcie.

Konfiguracja dostępu do klastra jest w osobnym pliku `~/.kube/cvtailor-lab.config`.
Skrypt zawsze podaje ten plik i kontekst jawnie. Opcjonalnie można ustawić inną
ścieżkę zmienną `CVTAILOR_LAB_KUBECONFIG` (wtedy używaj jej także w poleceniach poniżej).

W terminalu, w którym będziesz wykonywać ćwiczenia, zdefiniuj skrót:

```bash
k() {
  kubectl --kubeconfig "$HOME/.kube/cvtailor-lab.config" \
    --context kind-cvtailor-lab -n cvtailor-lab "$@"
}
k get pods
```

Oczekiwany wynik: pod z `READY 1/1` i statusem `Running`.

## 2. Otwórz aplikację

```bash
bash scripts/k8s-lab.sh forward
```

Pozostaw ten terminal otwarty. Przeglądarka: <http://localhost:18080>.
Login to `student`. W drugim terminalu odczytaj wygenerowane hasło:

```bash
k get secret cvtailor-secrets -o jsonpath='{.data.APP_PASSWORD}' | base64 --decode
echo
```

Jeśli klaster działa na VPS, `localhost` oznacza VPS. Na swoim komputerze
otwórz dodatkowy tunel SSH (podmień użytkownika i adres; dla niestandardowego
portu SSH dodaj `-p PORT`):

```bash
ssh -N -L 18080:127.0.0.1:18080 uzytkownik@adres-vps
```

Wtedy otwórz <http://localhost:18080> na swoim komputerze. Port-forward nasłuchuje
wyłącznie na loopback serwera. Laboratorium nie tworzy domeny ani publicznego Ingress.

## 3. Co właśnie zbudowałeś?

```text
przeglądarka → port-forward → Service → Pod aplikacji → PVC (/lab-data)
                                        ↑
                                    Deployment
                              ConfigMap + Secret
```

| Element | Do czego służy tutaj |
| --- | --- |
| Klaster kind | Kubernetes działający w osobnym kontenerze Dockera |
| Namespace | Grupuje zasoby laboratorium pod nazwą `cvtailor-lab` |
| Deployment | Pilnuje jednej działającej kopii aplikacji |
| Pod | Uruchamia kontener aplikacji, wcześniej kontener inicjalizujący dane |
| Service | Daje stały adres aplikacji wewnątrz klastra |
| ConfigMap | Ustawia m.in. dostawcę `mock` i tryb przykładowego profilu |
| Secret | Przekazuje hasło startowe i sekret CSRF |
| PVC | Przechowuje profil, sesje i dokumenty niezależnie od konkretnego poda |
| Sondy | Sprawdzają start, gotowość do ruchu i żywotność aplikacji |

Secret nie oznacza automatycznie szyfrowania danych w spoczynku; nie zapisuj
odkodowanego hasła w repozytorium. Tutaj przechowuje wyłącznie dane laboratorium.
Więcej: [Secrets](https://kubernetes.io/docs/concepts/configuration/secret/).

## 4. Pierwsze ćwiczenie: zobacz, co działa

```bash
k get deployments,pods,svc,pvc
k logs deployment/cvtailor --tail=30
k describe deployment cvtailor
k get events --sort-by=.metadata.creationTimestamp
curl http://localhost:18080/health
```

`get` pokazuje stan, `logs` wyjście aplikacji, a `describe` konfigurację i zdarzenia.
PVC powinien mieć status `Bound`. `Pending`, `ImagePullBackOff` lub `CrashLoopBackOff`
to sygnał, żeby obejrzeć `describe pod NAZWA_PODA`, zdarzenia i logi.
Log inicjalizacji: `k logs NAZWA_PODA -c seed-sample-data`.

## 5. Drugie ćwiczenie: usuń pod i obserwuj odtworzenie

Najpierw zapisz w wolumenie plik testowy i zobacz nazwę poda:

```bash
k exec deployment/cvtailor -- python -c "from pathlib import Path; Path('/lab-data/lesson.txt').write_text('Moj pierwszy PVC')"
k get pods
k delete pod -l app=cvtailor
k rollout status deployment/cvtailor --timeout=180s
k get pods
k exec deployment/cvtailor -- cat /lab-data/lesson.txt
```

Nowy pod powinien mieć inną nazwę, a plik nadal istnieć. Deployment odtworzył
aplikację, a PVC zachował dane. Po wymianie poda uruchom ponownie `forward`, jeśli
połączenie się zakończyło. Jedna replika oznacza krótką przerwę podczas odtwarzania.

## 6. Trzecie ćwiczenie: wdrożenie i cofnięcie zmiany

```bash
k set env deployment/cvtailor APP_BUILD_SHA=lekcja-2
k rollout status deployment/cvtailor --timeout=180s
k exec deployment/cvtailor -- printenv APP_BUILD_SHA
k rollout history deployment/cvtailor
k rollout undo deployment/cvtailor
k rollout status deployment/cvtailor --timeout=180s
k exec deployment/cvtailor -- printenv APP_BUILD_SHA
```

Pierwszy odczyt pokaże `lekcja-2`, a po cofnięciu `kubernetes-lab`.
Rollback przywraca konfigurację kontenera; nie cofa zmian w danych na PVC.
`Recreate` kończy stary pod przed uruchomieniem nowego, ponieważ aplikacja używa
SQLite i plików do obsługi zadań. W tym laboratorium zostaw `replicas: 1`.

## 7. Czwarte ćwiczenie: awaria i diagnostyka

To ćwiczenie celowo zatrzymuje aplikację laboratorium. Używaj skrótu `k`
z punktu 1, wskazującego wyłącznie kontekst `kind-cvtailor-lab` i namespace
`cvtailor-lab`. Zachowaj ten sam terminal do zakończenia ćwiczenia.

Najpierw zapisz numer działającej rewizji i ustaw błędny katalog danych:

```bash
working_revision="$(k get deployment cvtailor -o jsonpath='{.metadata.annotations.deployment\.kubernetes\.io/revision}')"
k set env deployment/cvtailor --containers=app DATA_DIR=/tmp/cvtailor-missing-profile
k get pods --watch
```

Poczekaj, aż nowy pod pokaże `Error` lub `CrashLoopBackOff`, a następnie zakończ
obserwację przez Ctrl+C. Pod może na przemian pokazywać `Running`, `Error` i
`CrashLoopBackOff`: kontener uruchamia się, kończy pracę z błędem i jest ponawiany.
Samo `Running` nie oznacza jeszcze gotowości aplikacji; sprawdzaj też `READY`.

W poleceniach poniżej zastąp `NAZWA_PODA` nazwą nowego, niedziałającego poda:

```bash
k describe pod NAZWA_PODA
k logs NAZWA_PODA -c app --tail=30
k logs NAZWA_PODA -c app --previous --tail=30
k get events --sort-by=.metadata.creationTimestamp
```

`describe` pokaże stan kontenera, przyczynę zakończenia, liczbę restartów i zdarzenia.
`logs --previous` odczytuje logi poprzedniego uruchomienia kontenera w tym samym
podzie; zadziała dopiero po restarcie. W logach szukaj `ProfileConfigurationError`
oraz ścieżki `/tmp/cvtailor-missing-profile/master_profile.json`.
Zdarzenie `BackOff` mówi o odraczaniu kolejnych restartów, a log aplikacji wyjaśnia
przyczynę: profil nie istnieje pod wskazaną ścieżką.

Kubernetes ponawia uruchomienie kontenera, ale błędną konfigurację trzeba poprawić.
Przywróć zapisaną rewizję, poczekaj na zakończenie wdrożenia i sprawdź HTTP:

```bash
k rollout undo deployment/cvtailor --to-revision="$working_revision"
k rollout status deployment/cvtailor --timeout=180s
k get pods
k exec deployment/cvtailor -c app -- python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).status)"
```

Oczekiwany wynik: `1/1 Running` i HTTP `200`. Oryginalne dane pozostają na PVC;
ćwiczenie zmienia jedynie zmienną środowiskową kontenera. Jeżeli utracisz terminal
ze zmienną `working_revision`, sprawdź `k rollout history deployment/cvtailor` i
wybierz rewizję sprzed awarii. Samo usunięcie wadliwego poda odtworzy pod z tą samą
błędną konfiguracją.

## 8. Piąte ćwiczenie: zdrowy pod, ale błędny Service

Service daje stały adres wewnątrz klastra. Selektor `app: cvtailor` wybiera pody,
`port: 8000` to port Service, a `targetPort: http` wskazuje nazwany port kontenera
(`containerPort: 8000`). Nazwa `http` jest tu nazwą portu, nie adresem URL.

Sprawdź DNS oraz połączenie z wnętrza poda:

```bash
k get service cvtailor
k exec deployment/cvtailor -c app -- python -c "import socket; print(socket.gethostbyname('cvtailor.cvtailor-lab.svc.cluster.local'))"
k exec deployment/cvtailor -c app -- python -c "import urllib.request; print(urllib.request.urlopen('http://cvtailor:8000/health', timeout=3).status)"
```

DNS powinien wskazać ClusterIP Service, a HTTP zwrócić `200`. Nazwa `cvtailor`
wystarcza w tym samym namespace; pełna nazwa w naszym klastrze to
`cvtailor.cvtailor-lab.svc.cluster.local`. Ten adres służy połączeniom w klastrze;
przeglądarka na komputerze użytkownika korzysta z opisanego wcześniej tunelu.

Teraz celowo ustaw port docelowy, na którym aplikacja nie nasłuchuje.
To przerwie połączenia przez Service laboratorium. Wykonuj polecenia pojedynczo:

```bash
k patch service cvtailor --type=json -p '[{"op":"replace","path":"/spec/ports/0/targetPort","value":8001}]'
k exec deployment/cvtailor -c app -- python -c "import urllib.request; print(urllib.request.urlopen('http://cvtailor:8000/health', timeout=3).status)"
```

Drugie polecenie powinno zakończyć się błędem połączenia. Aktualizacja reguł
sieciowych może zająć chwilę. Sprawdź stan aplikacji i kierunek ruchu:

```bash
k get pods
k exec deployment/cvtailor -c app -- python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status)"
k describe service cvtailor
k get endpointslices -l kubernetes.io/service-name=cvtailor -o yaml
```

Pod nadal powinien mieć `1/1 Running`, a bezpośrednie HTTP zwracać `200`.
EndpointSlice pokaże adres poda i docelowy port `8001`. Sondy zdrowia sprawdzają
pod bezpośrednio, dlatego błędny Service nie musi zmienić gotowości poda.

Napraw Service, stosując jego zapisany manifest z katalogu repozytorium:

```bash
k apply -f deploy/k8s/lab/service.yaml
k exec deployment/cvtailor -c app -- python -c "import urllib.request; print(urllib.request.urlopen('http://cvtailor:8000/health', timeout=3).status)"
```

Oczekiwany wynik: HTTP `200` przez Service, bez wymiany poda. Jeśli przerwiesz
ćwiczenie, wykonaj tę samą komendę `apply`, aby przywrócić połączenie.
Service nie ma historii rewizji Deployment; jego konfigurację przywracamy
z manifestu. Wniosek: stan poda, DNS i przekazywanie ruchu to osobne elementy
diagnostyki.

## 9. Szóste ćwiczenie: zasoby i pod w stanie Pending

Scheduler wybiera węzeł, na którym może uruchomić pod. Przy tej decyzji
uwzględnia żądania zasobów (`requests`) i już przydzielone żądania innych podów.
Małe bieżące użycie CPU nie wystarczy, jeśli suma żądań przekracza pojemność węzła.

| Ustawienie | Znaczenie |
| --- | --- |
| `requests.cpu: 100m` | Scheduler uwzględnia zapotrzebowanie na 0,1 jednostki CPU |
| `limits.cpu: "1"` | Ogranicza czas CPU kontenera do jednej jednostki; nadmiar jest ograniczany |
| `requests.memory: 256Mi` | Scheduler uwzględnia zapotrzebowanie na 256 MiB RAM |
| `limits.memory: 1Gi` | Przekroczenie limitu pamięci może zakończyć proces przez OOM |

`1000m` oznacza jedną jednostkę CPU, natomiast `"1000"` oznacza tysiąc jednostek.
Request nie jest odczytem aktualnego zużycia zasobów.

Ćwiczenie używa osobnego poda `scheduling-lesson`, bez selektora aplikacji,
sekretów i wolumenu z danymi. Manifesty nie należą do głównego Kustomize,
więc zwykłe `up` nie uruchomi ich automatycznie.

Najpierw zażądaj celowo zbyt dużej liczby CPU:

```bash
k create -f deploy/k8s/exercises/scheduling-pending.yaml
k get pod scheduling-lesson
k describe pod scheduling-lesson
```

Poczekaj chwilę, jeśli zdarzenia jeszcze się nie pojawiły. Oczekiwany wynik:
`Pending`, brak przydzielonego węzła oraz zdarzenie `FailedScheduling` z treścią
`Insufficient cpu`. Kontener nie wystartował, więc nie ma jeszcze logów aplikacji.
Żądanie 1000 CPU nie powoduje ich zużycia — scheduler odmawia przydzielenia poda.

Zastąp pod wersją z żądaniem `10m` (0,01 CPU) i limitem `100m` (0,1 CPU):

```bash
k delete pod scheduling-lesson --wait=true
k create -f deploy/k8s/exercises/scheduling-ready.yaml
k wait --for=condition=Ready pod/scheduling-lesson --timeout=90s
k logs scheduling-lesson
k get pods
```

Powinieneś zobaczyć `1/1 Running` oraz log `Scheduling lesson: container started`.
Tworzymy pod ponownie, aby pokazać dwie konfiguracje bez zależności od obsługi
zmiany zasobów działającego poda. Kontener testowy wypisuje komunikat i czeka
do 10 minut; nie wykonuje obciążającego zadania.

Na koniec usuń tylko pod ćwiczeniowy:

```bash
k delete pod scheduling-lesson
```

Jeśli przerwiesz ćwiczenie, wykonaj tę samą komendę sprzątającą. Samodzielny pod
nie zostanie odtworzony przez Deployment. Aplikacja CVTailor ma swój osobny pod.

## 10. Siódme ćwiczenie: ConfigMap i aktualizacja konfiguracji

ConfigMap `cvtailor-config` przechowuje zwykłą konfigurację aplikacji. Kontener
pobiera ją przez `envFrom`, czyli jako zmienne środowiskowe przy uruchomieniu.
Hasła i sekrety CSRF przekazujemy osobnym obiektem Secret.

Najpierw porównaj oznaczenie wersji w konfiguracji i w działającym kontenerze:

```bash
k get configmap cvtailor-config -o jsonpath='{.data.APP_BUILD_SHA}{"\n"}'
k exec deployment/cvtailor -c app -- printenv APP_BUILD_SHA
k get pods
```

W standardowym laboratorium obie wartości to `kubernetes-lab`. Ćwiczenie zakłada,
że Deployment nie ma bezpośredniego wpisu `env` dla `APP_BUILD_SHA`, który miałby
pierwszeństwo przed `envFrom`. Po wcześniejszych ćwiczeniach z rollbackiem powinien
korzystać z ConfigMap.

Zmień wyłącznie ConfigMap i porównaj wartości ponownie:

```bash
k patch configmap cvtailor-config --type=merge -p '{"data":{"APP_BUILD_SHA":"lekcja-configmap"}}'
k get configmap cvtailor-config -o jsonpath='{.data.APP_BUILD_SHA}{"\n"}'
k exec deployment/cvtailor -c app -- printenv APP_BUILD_SHA
k get pods
```

ConfigMap pokaże `lekcja-configmap`, a działający kontener nadal `kubernetes-lab`.
Pod nie został wymieniony. Sama zmiana ConfigMap nie aktualizuje zmiennych
środowiskowych już uruchomionego kontenera ani nie uruchamia nowego wdrożenia.

Wymień pod, aby aplikacja otrzymała nowe wartości:

```bash
k rollout restart deployment/cvtailor
k rollout status deployment/cvtailor --timeout=180s
k exec deployment/cvtailor -c app -- printenv APP_BUILD_SHA
```

Teraz powinno pojawić się `lekcja-configmap`. Nie przebudowywaliśmy obrazu;
zmieniła się konfiguracja uruchomienia. Strategia `Recreate` oznacza krótką przerwę
w działaniu aplikacji laboratorium.

Przywróć standardową konfigurację z manifestu i wymień pod jeszcze raz:

```bash
k apply -f deploy/k8s/lab/configmap.yaml
k rollout restart deployment/cvtailor
k rollout status deployment/cvtailor --timeout=180s
k exec deployment/cvtailor -c app -- printenv APP_BUILD_SHA
```

Oczekiwany wynik końcowy: `kubernetes-lab` i `1/1 Running`.
Jeśli przerwiesz ćwiczenie, wykonaj powyższe polecenia przywracające konfigurację.

`rollout undo` cofa szablon poda Deployment, ale nie przywraca zawartości osobnego
obiektu ConfigMap. Starsza rewizja odwołująca się do tej samej nazwy ConfigMap
również dostanie jego aktualne dane. Zachowanie opisane w tym ćwiczeniu dotyczy
konfiguracji przekazywanej przez zmienne środowiskowe; montowanie ConfigMap jako
plików ma inne zasady aktualizacji.

## 11. Ósme ćwiczenie: readiness i kierowanie ruchu

| Sonda | Co sprawdza | Skutek niepowodzeń po osiągnięciu progu |
| --- | --- | --- |
| `startupProbe` | Czy aplikacja zakończyła start | Restart kontenera; do pierwszego sukcesu wstrzymuje sondy readiness i liveness |
| `readinessProbe` | Czy aplikacja może przyjmować ruch | Pod traci gotowość; Service przestaje kierować do niego zwykły ruch |
| `livenessProbe` | Czy działająca aplikacja nadal odpowiada | Restart kontenera |

W tym ćwiczeniu sprawdzamy działanie **readiness**. W laboratorium wszystkie trzy
sondy korzystają z `/health`. Celowo ustawimy błędny port wyłącznie dla readiness;
startup i liveness będą nadal sprawdzać poprawny port aplikacji.

Zapisz rewizję przed zmianą, następnie zmień port sondy:

```bash
readiness_revision="$(k get deployment cvtailor -o jsonpath='{.metadata.annotations.deployment\.kubernetes\.io/revision}')"
k patch deployment cvtailor --type=json -p '[{"op":"replace","path":"/spec/template/spec/containers/0/readinessProbe/httpGet/port","value":8001}]'
k get pods --watch
```

Zmiana szablonu Deployment tworzy nowy pod. Po jego uruchomieniu zakończ
obserwację przez Ctrl+C i wykonaj poniższe polecenia, podając nazwę nowego poda:

```bash
k describe pod NAZWA_PODA
k exec NAZWA_PODA -c app -- python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status)"
k get endpointslices -l kubernetes.io/service-name=cvtailor -o yaml
```

Poczekaj na zdarzenie `Readiness probe failed` w `describe`. Pod powinien mieć
`0/1 Running`, a bezpośredni test aplikacji zwracać HTTP `200`. EndpointSlice
nadal może zawierać adres poda, ale z `conditions.ready: false`; domyślny Service
nie kieruje zwykłego ruchu do takiego endpointu. Przy jednej replice aplikacja
przez Service będzie niedostępna.

Po około 20 sekundach sprawdź ponownie `k get pods` i `k describe pod NAZWA_PODA`.
Powtarzające się błędy readiness nie powinny zwiększyć licznika restartów
kontenera. Pod został wymieniony z powodu zmiany konfiguracji sondy, natomiast
samo niepowodzenie readiness nie restartuje kontenera. `rollout status` nie
zakończy się tu sukcesem, dopóki nowa kopia nie osiągnie gotowości.

Przywróć zapisaną konfigurację:

```bash
k rollout undo deployment/cvtailor --to-revision="$readiness_revision"
k rollout status deployment/cvtailor --timeout=180s
k get pods
k exec deployment/cvtailor -c app -- python -c "import urllib.request; print(urllib.request.urlopen('http://cvtailor:8000/health', timeout=3).status)"
```

Oczekiwany wynik: `1/1 Running` i HTTP `200` przez Service. Jeśli przerwiesz
ćwiczenie, przywróć tę samą zapisaną rewizję; jeśli stracisz zmienną terminala,
wybierz właściwy numer przez `k rollout history deployment/cvtailor`.
Przy `Recreate` wymiana poda powoduje krótką przerwę w działaniu laboratorium.

## 12. Dziewiąte ćwiczenie: liveness restartuje kontener

W poprzednim ćwiczeniu błąd readiness odciął ruch bez restartowania kontenera.
Teraz ustawimy niepoprawny port wyłącznie dla liveness. Aplikacja będzie działać,
ale Kubernetes dostanie błędny sygnał, że należy ją zrestartować. To pokazuje,
dlaczego źle dobrana sonda może powodować niepotrzebne restarty.

Zapisz rewizję przed zmianą i ustaw błędny port:

```bash
liveness_revision="$(k get deployment cvtailor -o jsonpath='{.metadata.annotations.deployment\.kubernetes\.io/revision}')"
k patch deployment cvtailor --type=json -p '[{"op":"replace","path":"/spec/template/spec/containers/0/livenessProbe/httpGet/port","value":8001}]'
k get pods --watch
```

Zmiana szablonu Deployment utworzy nowy pod. Zapisz jego nazwę. W tym nowym
podzie obserwuj kolumnę `RESTARTS`: powinna wzrosnąć z `0` do `1`, przy tej samej
nazwie poda. Sonda ma okres 15 sekund i próg 3 niepowodzeń, więc poczekaj około
minuty po zakończeniu startu; dokładny czas zależy od harmonogramu sond i zamykania
kontenera. Następnie zakończ obserwację przez Ctrl+C.

```bash
k describe pod NAZWA_PODA
k logs NAZWA_PODA -c app --previous --tail=15
k get pod NAZWA_PODA -o jsonpath='{.metadata.uid}{"\n"}{.status.containerStatuses[0].containerID}{"\n"}{.status.containerStatuses[0].restartCount}{"\n"}'
```

W zdarzeniach szukaj `Liveness probe failed` oraz `Killing` z informacją
`failed liveness probe, will be restarted`. UID poda pozostaje ten sam,
natomiast identyfikator kontenera zmienia się przy restarcie. Polecenie z
`jsonpath` warto wykonać także przed pierwszym restartem, aby porównać wyniki.
`logs --previous` pokaże logi poprzedniego uruchomienia kontenera w tym podzie.

Startup i readiness nadal wskazują poprawny port. Kontener może więc przez
pewien czas być gotowy i odpowiadać HTTP `200`, a następnie zostać zrestartowany
przez wadliwą liveness. Samo pomyślne `rollout status` nie potwierdza, że aplikacja
pozostanie stabilna. Przy jednej replice restart powoduje przerwę w dostępności.

Po zaobserwowaniu pierwszego restartu od razu przywróć konfigurację:

```bash
k rollout undo deployment/cvtailor --to-revision="$liveness_revision"
k rollout status deployment/cvtailor --timeout=180s
k get pods
k exec deployment/cvtailor -c app -- python -c "import urllib.request; print(urllib.request.urlopen('http://cvtailor:8000/health', timeout=3).status)"
```

Oczekiwany wynik: poprawna sonda, `1/1 Running` i HTTP `200` przez Service.
Jeśli przerwiesz ćwiczenie, wykonaj te same komendy przywracające. Restart
kontenera nie usuwa danych na PVC. W tym ćwiczeniu odróżniamy wymianę poda
po zmianie Deployment od restartu kontenera wywołanego przez liveness.

## 13. Dziesiąte ćwiczenie: startupProbe i czas na start

`startupProbe` sprawdza, czy kontener zakończył uruchamianie. Do jej pierwszego
sukcesu Kubernetes wstrzymuje readiness i liveness. Po osiągnięciu progu kolejnych
niepowodzeń startup restartuje kontener. Gdy startup raz się powiedzie, dalsze
sprawdzanie tego uruchomienia przejmują readiness i liveness.

W laboratorium startup ma okres 2 sekundy i próg 60 niepowodzeń, co daje
orientacyjne okno startu około 120 sekund. Rzeczywisty czas zależy również od
harmonogramu sond, ich czasu wykonania oraz zamykania kontenera.

W ćwiczeniu skracamy próg do 10 i celowo psujemy port startup. Readiness oraz
liveness też skierujemy na niepoprawny port, aby sprawdzić, czy pozostają
wstrzymane. Zmiany dotyczą wyłącznie laboratorium i przerwą jego dostępność.

Zapisz rewizję i zmień sondy:

```bash
startup_revision="$(k get deployment cvtailor -o jsonpath='{.metadata.annotations.deployment\.kubernetes\.io/revision}')"
k patch deployment cvtailor --type=json -p '[
  {"op":"replace","path":"/spec/template/spec/containers/0/startupProbe/httpGet/port","value":8001},
  {"op":"replace","path":"/spec/template/spec/containers/0/startupProbe/failureThreshold","value":10},
  {"op":"replace","path":"/spec/template/spec/containers/0/startupProbe/timeoutSeconds","value":1},
  {"op":"replace","path":"/spec/template/spec/containers/0/readinessProbe/httpGet/port","value":8002},
  {"op":"replace","path":"/spec/template/spec/containers/0/livenessProbe/httpGet/port","value":8002}
]'
k get pods --watch
```

Zmiana Deployment utworzy nowy pod. Obserwuj jego nazwę i licznik restartów;
po pierwszym restarcie zakończ obserwację przez Ctrl+C. W czasie działania
kontenera możesz w drugim terminalu z tym samym skrótem `k` sprawdzić:

```bash
k describe pod NAZWA_PODA
k get pod NAZWA_PODA -o jsonpath='{.status.containerStatuses[0].started}{"\n"}{.status.containerStatuses[0].ready}{"\n"}{.status.containerStatuses[0].restartCount}{"\n"}'
k exec NAZWA_PODA -c app -- python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status)"
```

Po rzeczywistym uruchomieniu aplikacji bezpośredni HTTP może zwracać `200`,
a Kubernetes nadal widzieć `started: false` i `ready: false`, bo startup odpytuje
błędny port. Pod będzie miał `0/1 Running`. W trakcie samego restartu `exec`
może się nie udać — kontener jest wtedy zatrzymany.

Zdarzenia powinny pokazać `Startup probe failed` oraz `Killing` z informacją
`failed startup probe, will be restarted`. W tym czasie nie powinno być zdarzeń
o błędach readiness ani liveness, mimo ich niepoprawnych portów. UID poda
pozostaje ten sam, identyfikator kontenera się zmienia, a licznik restartów rośnie.

Od razu po pierwszym restarcie przywróć wszystkie sondy:

```bash
k rollout undo deployment/cvtailor --to-revision="$startup_revision"
k rollout status deployment/cvtailor --timeout=180s
k get pods
k exec deployment/cvtailor -c app -- python -c "import urllib.request; print(urllib.request.urlopen('http://cvtailor:8000/health', timeout=3).status)"
```

Oczekiwany wynik: `1/1 Running`, `started: true`, `ready: true` oraz HTTP `200`
przez Service. Jeśli przerwiesz ćwiczenie, przywróć tę samą zapisaną rewizję;
jej numer można też znaleźć przez `k rollout history deployment/cvtailor`.

## 14. Ollama i Google Gemini w laboratorium

Laboratorium może używać prawdziwych dostawców AI z fikcyjnym profilem:

```text
pod CVTailor → prywatny most → 127.0.0.1:11434 → tunel SSH → Ollama
             → HTTPS → Google Gemini API
```

Na tym VPS Ollama jest dostępna przez istniejący tunel SSH. Model nie jest
uruchamiany w klastrze ani ładowany do RAM tego VPS. Wymagany jest działający
endpoint `http://127.0.0.1:11434` z modelem `qwen3.5:9b` (lub modelem wskazanym
przez `OLLAMA_MODEL`). Gemini korzysta z `gemini-3.1-flash-lite` lub `GEMINI_MODEL`.

Włączenie integracji, z katalogu repozytorium:

```bash
bash scripts/k8s-lab.sh ai
```

Komenda używa `.venv/bin/python` i pakietu `python-dotenv` z zależności projektu.
Wymaga dostępu do Docker, Kubernetes i UFW na VPS. Skrypt odczytuje z hostowego
`.env` tylko klucz Gemini i opcjonalne nazwy modeli; można je też przekazać przez
zmienne środowiskowe. Nie wpisuj klucza w plikach śledzonych przez Git.

`GEMINI_API_KEY` trafia do istniejącego Secret `cvtailor-secrets`, bez wypisywania
go w terminalu i bez umieszczania w argumentach procesu. Loginy laboratorium
pozostają oddzielne od produkcyjnych. ConfigMap otrzymuje ustawienia z
`deploy/k8s/ai/provider-config.json`: domyślnym dostawcą jest Ollama, zapasowym
Gemini. Ustawienie automatycznego fallbacku w interfejsie aplikacji jest
zapisywane na PVC; jeśli wcześniej je wyłączyłeś, włącz je ponownie w aplikacji.
W formularzu można też jawnie wybrać dostawcę.

Most to osobny kontener `cvtailor-lab-ollama-bridge`, wykorzystujący lokalny obraz
`nginx:1.27-alpine` po identyfikatorze obrazu. Nie pobiera nowego obrazu przy każdym
wywołaniu. Nasłuchuje wyłącznie na bramie sieci Docker `kind`, port `11435`,
i dopuszcza adres węzła `cvtailor-lab-control-plane`. Skrypt wykrywa te adresy.
Gdy UFW jest aktywny, dodaje regułę tylko dla tego źródła, celu i portu.
Ollama na hoście nadal nasłuchuje na loopback. Most ma limit 64 MiB RAM i 0,25 CPU.
Konfiguracja sieciowa trafia do `.k8s-lab/`, wykluczonego z Git i obrazu aplikacji.

Po zmianie Secret i ConfigMap skrypt wymienia pod oraz sprawdza dostępność obu
modeli przez klasy dostawców aplikacji. Jeśli test lub wdrożenie zawiedzie,
przywraca wcześniejsze dane ConfigMap, poprzedni klucz w Secret i uruchamia pod
ponownie. Sam test dostępności nie potwierdza jeszcze limitów generowania Google;
krótka próba generowania może ujawnić np. wyczerpanie quota.

Przy Gemini treść zadań i dane profilu są przesyłane do Google. Tutaj pracujemy
na fikcyjnym profilu. Koszt i limity zależą od konfiguracji konta API.
Opis modelu: [Gemini 3.1 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite).

Powrót do ćwiczeń bez AI:

```bash
bash scripts/k8s-lab.sh mock
```

Komenda przywraca mock, usuwa klucz Gemini z Secret laboratorium, wymienia pod,
zatrzymuje most i usuwa utworzoną regułę UFW. Ponowne `ai` uruchamia most i
przekazuje klucz z hostowego źródła jeszcze raz.

Zwykłe `up` stosuje bazowe manifesty z dostawcą mock. Po przebudowie aplikacji
wykonaj `ai`, jeśli chcesz ponownie używać modeli. Do pełnego wyłączenia integracji
użyj `mock`, ponieważ samo `up` nie zatrzymuje mostu ani nie usuwa klucza.
Przed usunięciem klastra również wykonaj `mock`.

Jeśli odtworzenie klastra zmieni adres węzła lub bramy, skrypt odmówi użycia starej
konfiguracji mostu. Wykonaj `mock`, usuń wyłącznie jego kontener poleceniem
`docker rm cvtailor-lab-ollama-bridge`, a następnie wykonaj `ai`.

## 15. Kolejne zmiany w kodzie

Ponownie wykonaj `bash scripts/k8s-lab.sh up`. Skrypt przebuduje obraz, załaduje
go do klastra i zrestartuje Deployment. Zachowa Secret oraz PVC.
Stały tag i `imagePullPolicy: Never` są celowe w lokalnym ćwiczeniu; obraz musi
zostać załadowany przez kind. Przy pracy nad prawdziwymi wydaniami używa się
odrębnych wersji obrazów lub digestów i rejestru.

Zmiana ConfigMap lub Secret przekazywanych przez zmienne środowiskowe wymaga
restartu poda. Hasło w Secret służy tylko do utworzenia pierwszego `auth.json`;
późniejsze zmiany hasła wykonuj przez aplikację.

## 16. Zakończenie laboratorium

Zatrzymanie `port-forward` przez Ctrl+C zamyka tunel, ale klaster dalej działa.

Poniższa komenda **usuwa całe laboratorium, w tym jego dane i wygenerowane CV**:

```bash
kind delete cluster --name cvtailor-lab
```

PVC zachowuje dane przy wymianie poda, ale magazyn kind jest lokalny dla węzła
i nie przetrwa usunięcia klastra. Usunięcie namespace lub PVC też może usunąć dane.
Żądanie `1Gi` nie jest gwarancją ograniczenia zużycia dysku przez lokalny magazyn kind.
Zachowanie magazynu opisuje dokumentacja
[Persistent Volumes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/).

Następne tematy po tych ćwiczeniach: podłączenie Ollamy, routing HTTP/TLS,
wersjonowane obrazy i wdrażanie z CI/CD. Ten jeden węzeł służy nauce;
nie zapewnia wysokiej dostępności na wypadek awarii hosta.
