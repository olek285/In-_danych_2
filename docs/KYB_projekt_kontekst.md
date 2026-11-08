# Automated KYB Screening Tool: kontekst projektu

> Dokument do wklejenia w nowym czacie, żeby od razu mieć pełny kontekst: temat, założenia, stan prac i kolejne kroki.
> Pomija wymogi formalne projektu zaliczeniowego (regulamin, kryteria oceny); opisuje wyłącznie projekt jako taki.
> Status faktów: ✅ = sprawdzone w sieci podczas pracy, ❓ = z pamięci lub nieweryfikowane, 🧪 = zaimplementowane i przetestowane tylko na mockach/demo.

## 1. Czym jest projekt

**Nazwa:** Automated KYB Screening Tool: konfigurowalny silnik reguł AML/Compliance dla spółek (KYB = Know Your Business).

**Temat:** automatyczne, wstępne prześwietlenie firm (spółek z KRS) pod kątem sygnałów ryzyka. System pobiera dane z publicznych źródeł (API i pliki), czyści je, łączy źródła o różnej strukturze i pokazuje analitykowi **jawne alarmy („Red Flags”)**.

**Kluczowa idea:** zamiast „czarnej skrzynki” z jednym sztucznym wynikiem punktowym, **analityk sam ustawia suwakami czułość reguł** (minimalny kapitał zakładowy, maksymalny wiek prezesa, wymóg aktywnego VAT, próg podobieństwa do list sankcyjnych…). Każdy alarm ma uzasadnienie: **wartość vs próg**.

**Odbiorca (założenie):** analityk AML/Compliance w małej instytucji obowiązanej (biuro rachunkowe, firma pożyczkowa, mała fintech), który wstępnie weryfikuje klienta-spółkę.

**Zespół:** 2 osoby. **Stack docelowy:** Python; pipeline w Databricks (PySpark, architektura Medallion: bronze → silver → gold); aplikacja w Streamlit. Dodatkowo powstała lekka wersja MVP w czystym Pythonie (bez Sparka).

## 2. Zasady projektowe (decyzje, które trzymają projekt w kupie)

1. **Fakty osobno, flagi osobno.** Warstwa gold i dane zawierają fakty (kapitał, status VAT, najlepsze dopasowanie sankcyjne…), a flagi liczy silnik reguł (`rules.py`) przy odczycie na podstawie progów z suwaków. Zmiana progu daje natychmiastowy efekt bez ponownego przetwarzania.
2. **Zero sztucznego scoringu.** Lista flag z uzasadnieniem, bez ważonej sumy punktów.
3. **Brak danych ≠ „OK”.** Cztery statusy flagi: 🔴 FLAG, ✅ OK, ⚪ UNKNOWN (brak danych), ⏸️ OFF (reguła wyłączona). Gdy lista sankcyjna się nie załaduje, wynik to UNKNOWN, a nie „brak alarmu”. Jest opcja „tryb ostrożny” (UNKNOWN traktowane jak alarm).
4. **Flaga to sygnał do weryfikacji, nie dowód.** Dopasowanie sankcyjne to podobieństwo nazw, nie potwierdzenie tożsamości.
5. **Minimalizacja danych osobowych.** Nie zapisujemy imion, nazwisk ani PESEL. Z PESEL wyliczany jest wyłącznie wiek (jeśli w ogóle dostępny). Osoby fizyczne z list sankcyjnych są pomijane (dopasowujemy tylko nazwy podmiotów). Liczba osób fizycznych na końcu łańcucha własności jest liczona, bez zapisu tożsamości.
6. **Surowe dane bronze są niezmieniane** (audyt, powtarzalność); parsowanie dopiero w silver.
7. **Idempotentne kroki, jawne błędy.** Retry z backoffem, 404 jako wynik biznesowy, błąd sieci jako wyjątek (nie cichy brak), atomowy zapis plików.

## 3. Źródła danych

### Zaimplementowane w kodzie (🧪)
| Źródło | Kraj | Format | Klucz łączenia | Dostęp | Rola |
|---|---|---|---|---|---|
| **KRS** (odpis aktualny) `https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{krs}?rejestr=P&format=json` | PL | JSON zagnieżdżony | numer KRS | ✅ bez klucza; ❓ dokładna struktura JSON pisana z pamięci | kapitał, data rejestracji, NIP, forma prawna, zarząd, **wspólnicy** (łańcuch własności) |
| **Biała Lista VAT (MF)** `https://wl-api.mf.gov.pl/api/search/nips/{nip,...}?date=YYYY-MM-DD` | PL | JSON paczkowy (max 30 NIP) | NIP | ✅ bez klucza, dzienne limity (konkretne wartości ❓) | status podatnika VAT |
| **OFAC SDN + aliasy** `https://www.treasury.gov/ofac/downloads/sdn.csv` i `alt.csv` | USA | CSV bez nagłówka (12 i 5 kolumn; podmiot = SDN_Type `-0-`) | nazwa (dopasowanie rozmyte) | ❓ domena publiczna; adres może się zmienić | sankcje |
| **Lista MSWiA** (dane.gov.pl) | PL | CSV | nazwa (rozmyte) | ❓ adres pliku CSV trzeba znaleźć ręcznie; licencję sprawdzić | sankcje (polska lista) |
| **GLEIF (LEI)** `https://api.gleif.org/api/v1/` (`/lei-records`, `/lei-records/{lei}/direct-parent`, `/ultimate-parent`) | świat | JSON:API | LEI / pole `registeredAs` (numer KRS) / nazwa | ✅ bez klucza, CC0; filtry `filter[entity.registeredAs]`, `filter[entity.legalName]` | podmioty nadrzędne, wspólnicy zagraniczni |

### Rekomendowane do dodania
| Źródło | Format | Dostęp | Rola |
|---|---|---|---|
| **OpenSanctions** (bulk) | CSV / JSON Lines (FollowTheMoney) | ✅ bez klucza i logowania; **darmowe tylko do użytku niekomercyjnego** (CC BY-NC); URL: `https://data.opensanctions.org/datasets/latest/<dataset>/<format>`, np. `…/sanctions/targets.simple.csv` (~43 MB), `…/default/targets.simple.csv` (~455 MB), `entities.ftm.json` (GB); kolekcja `sanctions` zawiera m.in. **polską listę MSWiA** („Polish List of Persons and Entities Subject to Sanctions”) | sankcje OFAC/UE/ONZ i inne w jednym miejscu; może zastąpić osobne pobieranie OFAC i MSWiA |
| **REGON (GUS, BIR1)** | SOAP/XML | ✅ darmowy klucz po rejestracji (nie natychmiastowy); ❓ szczegóły sesji SOAP | PKD (branże ryzyka), zawieszona/zakończona działalność, niezgodność adresu |
| **NBP API** | JSON | ❓ bez klucza | przeliczanie kapitału w EUR/USD na PLN |

### Opcjonalne / odrzucone
- **BZP / e-Zamówienia** (JSON): ❓ API niezweryfikowane. Reguła `CONTRACT_VS_CAPITAL` (kontrakt publiczny ≫ kapitał) jest gotowa w silniku, ale nie ma ingestii.
- **TED, ICIJ Offshore Leaks, Companies House (UK), VIES**: ❓ opcjonalne, niesprawdzone.
- **dane.gov.pl (API portalu)**: ✅ publiczne JSON:API (wg opisu zewnętrznego), pomocne do znalezienia adresu CSV MSWiA.
- **Odrzucone:** CEIDG (REST z tokenem JWT, głównie osoby fizyczne, ryzyko RODO), lista sankcji UE (FSF) pobierana bezpośrednio (✅ wymaga konta EU Login; dostępna przez OpenSanctions), KRZ (✅ brak oficjalnego darmowego API wg źródeł zewnętrznych), CRBR (dane osobowe beneficjentów), plik płaski Białej Listy (✅ zawiera skróty SHA-512 par NIP+rachunek, nie daje statusu zbiorczo), **listy osób poszukiwanych FBI/Interpol** (✅ techniczne API publiczne bez klucza, ale dotyczą wyłącznie osób, a projekt sprawdza firmy i nie ma wiarygodnych danych osobowych do porównania).

**Uwaga o strukturze:** zestaw daje 5 różnych formatów (JSON zagnieżdżony, JSON paczkowy, CSV, SOAP/XML, JSON Lines) i 4 sposoby łączenia (numer KRS, NIP, LEI/numer rejestrowy, dopasowanie rozmyte po nazwie).

## 4. Architektura i przepływ danych

```
Źródła (KRS, VAT, OFAC/MSWiA/OpenSanctions, GLEIF)
   └─► BRONZE: surowe odpowiedzi (JSONL z kopertą {source,key,http_status,ingested_at,payload-jako-tekst} / surowe CSV), partycja ingest_date
         └─► SILVER: company, board_member (tylko rola + wiek), vat, sanctions (znormalizowane nazwy)
               └─► GOLD: company_screening (1 wiersz = 1 spółka, fakty), sanctions_matches (pary spółka–wpis, score ≥ 0,80)
                     └─► testy jakości ─► eksport parquet ─► aplikacja Streamlit + silnik reguł
```
- **Łączenie KRS↔VAT:** po NIP (z walidacją sumy kontrolnej). **Spółka↔listy sankcyjne:** brak klucza → normalizacja nazw (bez diakrytyków i form prawnych, posortowane tokeny) + podobieństwo `1 − Levenshtein/max_len`, z bezstratnym blockingiem po długości nazwy.
- Dwie wersje implementacji: **Spark/Databricks** (`src/kyb/transform`, `pipeline.py`) oraz **MVP w czystym Pythonie** (`live.py`, `fetchers.py`, `demo_data.py`, `cache.py`; pobieranie na żywo z cache na dysku albo tryb demo offline).

## 5. Reguły (czerwone flagi)

| Kod | Warunek | Dane |
|---|---|---|
| `LOW_CAPITAL` | kapitał zakładowy < próg | KRS |
| `OLD_PRESIDENT` | wiek prezesa > próg | KRS (PESEL; **patrz ryzyka**) |
| `VAT_NOT_ACTIVE` | status ≠ „Czynny” (wyłączalna) | Biała Lista |
| `NEW_COMPANY` | wiek spółki < próg (miesiące) | KRS |
| `SANCTIONS_MATCH` | podobieństwo nazwy spółki do listy ≥ próg | OFAC/MSWiA |
| `OWNER_SANCTIONS` | pośredni właściciel podobny do wpisu sankcyjnego ≥ próg | łańcuch własności |
| `CIRCULAR_OWNERSHIP` | własność kołowa w łańcuchu | łańcuch własności |
| `CONTRACT_VS_CAPITAL` | kontrakt publiczny / kapitał > próg | BZP (aktywna tylko gdy są dane) |

Reguły można włączać/wyłączać; dla każdej generowane jest uzasadnienie tekstowe.

## 6. Łańcuch własności (najtrudniejszy element)

Zamiast pytać „czy ta spółka jest na liście?”, pytamy „czy któryś z jej (pośrednich) właścicieli jest?”.
- BFS w górę łańcucha: wspólnicy z KRS (podmioty z numerem KRS) są pobierani rekurencyjnie (domyślnie głębokość 2–3, limit węzłów).
- Wspólnik zagraniczny bez KRS: dopasowanie do GLEIF po nazwie (rozmyte, próg 0,90); dalej przez `direct-parent` GLEIF. Polski podmiot nadrzędny z GLEIF jest scalany z węzłem KRS.
- Każdy węzeł jest sprawdzany na listach sankcyjnych; wynik zawiera **ścieżkę** (np. `Shadow Parent → Omega Trade → Spółka`).
- Obsługa: cykle, układy rombowe (jeden węzeł, dwie krawędzie), limity głębokości/węzłów, błędy źródeł (`NOT_FOUND`/`FETCH_ERROR`).
- **Ograniczenia:** brak udziałów procentowych (tekst wolny w KRS); łańcuch kończy się na osobach fizycznych (CRBR poza zakresem); GLEIF obejmuje głównie duże podmioty; nazwy pól wspólników w odpisie zależą od formy prawnej (parser tolerancyjny, ❓ do weryfikacji na prawdziwych odpisach; dla S.A. akcjonariusze zwykle nie są w KRS).
- Kierunek skalowania: iteracyjny self-join w Sparku / GraphFrames zamiast pętli po API.

## 7. Aplikacja (Streamlit)

Zakładki MVP: (1) dane i pobieranie (lista numerów KRS lub CSV, tryb **demo offline** vs **dane na żywo**), (2) alarmy (KPI, wykres, tabela z filtrami, eksport CSV z zapisanymi progami), (3) spółka i własność (uzasadnienia reguł, dopasowania sankcyjne, graf właścicieli w Graphviz), (4) jakość danych (wyniki testów, użyte źródła, log), (5) o aplikacji (ograniczenia).
Suwaki: minimalny kapitał, maks. wiek prezesa, wymóg VAT, minimalny wiek spółki, próg podobieństwa sankcyjnego, głębokość łańcucha, przełącznik „tryb ostrożny”.
Uruchomienie: `pip install -r requirements-mvp.txt`, potem `streamlit run app/mvp_app.py` (albo `run.bat` / `run.sh`).

## 8. Jakość danych

Testy automatyczne (w Sparku: 12 reguł; w MVP: odpowiednik w pandas): unikalność (KRS), kompletność (NIP, wiek prezesa, kapitał w PLN, pokrycie watchlisty), reguła dziedzinowa (suma kontrolna NIP), zakresy (kapitał ≥ 0, wiek 18–110, data rejestracji nie z przyszłości), dozwolone wartości (status VAT), integralność referencyjna (dopasowania ↔ spółki), świeżość. Wagi: `error` przerywa pipeline (kod wyjścia 1), `warn` tylko raportuje.

## 9. Znane ryzyka i niewiadome (ważne)

1. **⚠️ PESEL w API KRS jest prawdopodobnie anonimizowany** (źródła zewnętrzne: zanonimizowane imiona, nazwiska i PESEL). Jeśli tak, wiek prezesa jest zawsze nieznany, a reguła `OLD_PRESIDENT` zawsze ⚪. **Do potwierdzenia na prawdziwym odpisie.** Jeśli się potwierdzi: usunąć regułę lub zastąpić dostępnymi faktami (np. zarząd jednoosobowy, liczba członków zarządu).
2. **Struktura odpisu KRS** (ścieżki JSON, nazwy pól wspólników) napisana z pamięci; wymaga weryfikacji na żywo.
3. **Kształt odpowiedzi GLEIF** (`attributes.entity.legalName.name`, `registeredAs`…) odczytany z dokumentacji/opisów, niesprawdzony na żywo; kod rejestru dla KRS w GLEIF nie ustalony.
4. **Adres i kolumny listy MSWiA** nieznane (do ustawienia: URL + nazwa kolumny z nazwą podmiotu). Alternatywa: polska lista jest w OpenSanctions.
5. **Limity API** (Biała Lista, KRS): przy większej liczbie spółek potrzebne ładowanie przyrostowe.
6. **Fałszywe alarmy sankcyjne** przy popularnych nazwach i fałszywe braki przy innej transliteracji.
7. **Licencja OpenSanctions (CC BY-NC)**: tylko użytek niekomercyjny; wymaga atrybucji i wzmianki w dokumentacji prawnej.
8. **Kodowanie polskich CSV**: pliki w Windows-1250 muszą być czytane jako cp1250 (błąd naprawiony w kodzie: kolejność `utf-8-sig → cp1250 → latin-1`).
9. Kapitał w walucie innej niż PLN nie jest przeliczany (status: brak danych), dopóki nie dojdzie NBP.

## 10. Stan prac

**Istnieje (repo `kyb-screening-tool`, ~84 pliki):**
- Ingestia bronze (KRS, VAT, MSWiA, OFAC) i klient GLEIF: kod i testy na mockach 🧪.
- Transformacje silver/gold w PySpark, testy jakości w Sparku, orkiestracja `pipeline.py`, notebook Databricks: skompilowane, **niewykonane na prawdziwym Sparku** 🧪.
- Silnik reguł (8 reguł, uzasadnienia, statusy, wyłączanie reguł), parser KRS (w tym wspólnicy), dopasowanie sankcji, łańcuch własności, przetwarzanie wsadowe, aplikacja MVP z trybem demo, dane demo (fikcyjne), cache na dysku, testy jakości w pandas, CI (GitHub Actions), dokumentacja w `docs/`.
- **58 testów jednostkowych przechodzi** (logika, ingestia na mockach, pełny przebieg w trybie demo, smoke test aplikacji na atrapie Streamlita).
- Skrypty pomocnicze: `check_sources.py` (podsumowanie pobierania z 4 źródeł), `scripts/ownership_demo.py` (łańcuch własności na żywo).

**Nie zostało sprawdzone na prawdziwych API** (brak dostępu do sieci w środowisku, w którym powstał kod): cały tryb „na żywo”, prawdziwa struktura KRS/GLEIF/VAT, przebieg Sparka.

## 11. Plan krok po kroku

**Krok 1 (bieżący): pobieranie surowych danych z każdego źródła osobno i wyświetlanie ich „tak jak zostały dostarczone”.**
Program (CLI i/lub prosta aplikacja z zakładką na źródło) pobiera odpowiedź i pokazuje: adres zapytania, status HTTP, rozmiar, surowe ciało (JSON bez przetwarzania / CSV z podglądem pierwszych wierszy i nazwami kolumn), z możliwością zapisu surowego pliku. Cel: **zobaczyć prawdziwe struktury** przed pisaniem parserów.
Źródła do uwzględnienia w kroku 1: KRS, Biała Lista VAT, OFAC (sdn.csv + alt.csv), GLEIF (po KRS, po nazwie, relacja nadrzędna), NBP, MSWiA (po wklejeniu adresu CSV), OpenSanctions (duże pliki: tylko podgląd początku strumienia albo mały zbiór `sanctions/targets.simple.csv`).
**Co trzeba dołożyć/pobrać ręcznie:**
- adres pliku CSV listy **MSWiA** z dane.gov.pl (albo zamiast niego polska lista przez OpenSanctions);
- **klucz REGON/BIR1** (rejestracja w GUS, wniosek zajmuje czas, więc zaczynać wcześnie; implementacja SOAP dopiero później);
- opcjonalnie plik **OpenSanctions** (`sanctions/targets.simple.csv`);
- własne **numery KRS** do testów, najlepiej kilka spółek z o.o., które mają wspólników będących firmami, oraz jedną spółkę akcyjną.

**Krok 2:** na podstawie prawdziwych odpowiedzi zweryfikować i poprawić parsery (ścieżki pól KRS, pola wspólników, kształt GLEIF/VAT, kolumny MSWiA); rozstrzygnąć kwestię PESEL/wieku prezesa.
**Krok 3:** zapisać surowe dane do warstwy bronze i zbudować silver (czyszczenie, typowanie, deduplikacja, normalizacja nazw).
**Krok 4:** dopasowanie do list sankcyjnych i łączenie źródeł (gold), próg podobieństwa, ocena jakości dopasowania na ręcznie oznaczonej próbce.
**Krok 5:** silnik reguł + aplikacja z suwakami na prawdziwych danych; decyzja o regule wieku prezesa; testy jakości.
**Krok 6:** łańcuch własności na prawdziwych odpisach (weryfikacja pól wspólników, GLEIF).
**Krok 7 (opcjonalnie):** REGON (PKD, status działalności), NBP (waluty), historia zmian spółek (SCD2) i alerty o zmianie statusu, większa watchlista (kilkaset–kilka tysięcy KRS) i ładowanie przyrostowe, wersja Spark/Databricks uruchomiona w praktyce.

## 12. Struktura repozytorium (skrót)

```
src/kyb/ingestion/    pobieranie → bronze (KRS, VAT, listy sankcyjne, GLEIF), retry/backoff
src/kyb/transform/    bronze → silver → gold (PySpark)
src/kyb/quality/      testy jakości (Spark: checks.py; MVP: pandas_checks.py)
src/kyb/rules.py      silnik reguł (czyste pandas)
src/kyb/ownership.py  łańcuch własności; ownership_batch.py (wsad), sanctions_match.py (dopasowanie nazw)
src/kyb/live.py       MVP: KRS → VAT → sankcje → własność; fetchers.py, demo_data.py, cache.py
src/kyb/pipeline.py   orkiestracja (Spark)
app/mvp_app.py        aplikacja MVP (Streamlit); app/streamlit_app.py: wersja czytająca gold z pipeline'u
scripts/              ownership_demo.py, make_sample_data.py
tests/                58 testów jednostkowych
docs/                 kontekst, architektura, słownik danych, rejestr decyzji, ograniczenia, łańcuch własności
```
