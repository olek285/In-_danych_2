# Rejestr decyzji

Format: kontekst → decyzja → rozważane alternatywy → uzasadnienie.
Status: **zaakceptowana** (przez zespół) albo **proponowana**. Propozycje AI z tygodnia 1 czekają na akceptację:
zgodnie z wytycznymi decyzje i ich uzasadnienia należą do autorów projektu.

---

### D1. Stos bez Sparka i Databricks
- **Status:** zaakceptowana (ustalenie zespołu przed tygodniem 1).
- **Decyzja:** Python 3.11+, uv, requests, DuckDB/Polars, Parquet, Streamlit, pytest.
- **Alternatywy:** Databricks + PySpark (pierwotna koncepcja).
- **Uzasadnienie:** wolumen to kilkadziesiąt spółek i ok. 10 MB list sankcyjnych. Wytyczne premiują prostotę i
  uruchomienie na innym komputerze według README, czego Databricks nie zapewnia bez konta.

### D2. Minimalizacja danych osobowych przed zapisem do bronze
- **Status:** proponowana (AI, tydzień 1).
- **Kontekst:** wytyczne zabraniają danych osobowych. API KRS maskuje nazwiska i PESEL, ale zwraca **jawne daty
  urodzenia** części osób. Biała Lista może zwracać imiona i nazwiska reprezentantów. Listy sankcyjne zawierają osoby.
- **Decyzja:** KRS i VAT: wartości pól osobowych zamieniamy na `[REDACTED]`, a strukturę i role zachowujemy.
  OpenSanctions: wiersze osób odrzucamy w trakcie pobierania i zapisujemy tylko podmioty.
- **Alternatywy:** (a) surowe dane w bronze, filtrowanie dopiero w silver; (b) usuwanie całych sekcji z osobami.
- **Uzasadnienie:** (a) oznaczałoby przetwarzanie danych osobowych przez potok, co grozi niespełnieniem wymagania
  minimalnego; (b) traci strukturę potrzebną do parserów (liczba członków zarządu, role). Audytowalność zapewnia
  zapisany SHA-1 oryginału i wersjonowany adres artefaktu OpenSanctions.
- **Konsekwencja:** zasada „bronze niezmieniony” brzmi teraz „bronze = odpowiedź źródła po obowiązkowej minimalizacji,
  poza tym bez zmian”.

### D3. Rezygnacja z reguły wieku prezesa (`OLD_PRESIDENT`)
- **Status:** proponowana (AI, tydzień 1).
- **Kontekst:** PESEL w API KRS jest zamaskowany (pierwsza cyfra + `*`), więc wieku nie da się wyliczyć. Data
  urodzenia występuje tylko u części osób i jest daną osobową.
- **Decyzja:** usunąć regułę. Zamiennik do wyboru w tygodniu 2: np. jednoosobowy zarząd albo zawieszony członek zarządu.
- **Alternatywy:** liczenie wieku z `dataUrodzenia` tam, gdzie jest (odrzucone, bo to dane osobowe i niepełne pokrycie).

### D4. Listy sankcyjne z OpenSanctions zamiast pobierania z każdego źródła osobno
- **Status:** proponowana (AI, tydzień 1).
- **Decyzja:** `pl_mswia_sanctions`, `pl_finanse_sanctions`, `us_ofac_sdn`, `eu_fsf` w formacie `targets.simple.csv`.
- **Alternatywy:** OFAC `sdn.csv`/`alt.csv` z treasury.gov, CSV MSWiA z dane.gov.pl (adres nieustalony), lista UE (wymaga EU Login).
- **Uzasadnienie:** jeden format i schemat dla 4 list, jawne rozróżnienie osoba/podmiot (`schema`), wersjonowanie
  z sumą SHA-1, a lista UE jest dostępna bez logowania. Koszt: licencja CC BY-NC (projekt jest niekomercyjny, więc OK)
  i zależność od pośrednika.

### D5. Ochrona limitu Białej Listy
- **Status:** proponowana (AI, tydzień 1).
- **Decyzja:** licznik na dysku zwiększany przed każdą próbą (także ponowieniem), margines 5 zapytań, ponawianie tylko
  5xx i tylko raz, brak ponowień przy 429, tryb `--dry-run`, cache odpowiedzi w bronze per data statusu, blokada sieci w testach.
- **Uzasadnienie:** przekroczenie limitu blokuje IP do północy. Wolimy zawyżyć licznik niż go zaniżyć.

### D6. Odpowiedź 200, która nie jest JSON-em API, jest błędem
- **Status:** proponowana (AI, tydzień 1); wynika z obserwacji na żywo.
- **Kontekst:** Biała Lista (zapora Incapsula) zwróciła HTTP 200 ze stroną HTML.
- **Decyzja:** wymagamy JSON-a z kluczem `result` (VAT) lub `odpis` (KRS). Inaczej zgłaszamy `InvalidPayloadError`,
  nie zapisujemy wyniku jako poprawnego i nie traktujemy go jako cache.
- **Uzasadnienie:** zasada „brak danych ≠ OK”. Strona zapory potraktowana jako odpowiedź zatrzymałaby ponowne
  pobieranie na stałe.

### D7. Watchlista testowa
- **Status:** proponowana (AI, tydzień 1); zespół miał podać numery, ale zlecił ich wyszukanie.
- **Decyzja:** 13 spółek sprawdzonych na żywym API: 5 sp. z o.o. ze wspólnikami-spółkami (w tym wspólnik zagraniczny
  i wspólnik pod dawną nazwą), 5 S.A. (w tym 2 z jedynym akcjonariuszem zagranicznym, 1 w upadłości), 3 sp. z o.o. w likwidacji.
- **Uzasadnienie:** pokrywa wszystkie przypadki brzegowe potrzebne parserom i regułom w tygodniu 2.
