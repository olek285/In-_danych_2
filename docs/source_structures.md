# Rzeczywiste struktury źródeł danych

Stan na **2026-11-08**. Wszystko poniżej sprawdzono na prawdziwych odpowiedziach API zapisanych w `data/bronze/`.
Można to odtworzyć bez nowych zapytań:

```bash
uv run python scripts/inspect_sources.py --source krs_current --flat
uv run python scripts/inspect_sources.py --source vat_whitelist --depth 6
uv run python scripts/inspect_sources.py --source opensanctions --rows 3
```

W przykładach pokazujemy wyłącznie dane spółek (nazwy, numery rejestrowe). Wartości dotyczące osób są w bronze
zastąpione przez `[REDACTED]` (patrz sekcja 4). W tym dokumencie występują tylko jako opis kształtu, np. „pierwsza litera + `*`”.

Legenda werdyktów dla punktów oznaczonych ❓ w `KYB_projekt_kontekst.md`:
**POTWIERDZONE** / **OBALONE** / **NADAL NIEJASNE** / **NOWE** (rzecz, której koncepcja nie przewidywała).

---

## 1. KRS – `OdpisAktualny` (i `OdpisPelny`)

**Zapytanie:** `GET https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{krs}?rejestr=P&format=json` (bez klucza).

| Odpowiedź | Kiedy | Ciało |
|---|---|---|
| `200`, `content-type: application/json` (bez `charset`, treść w UTF-8) | spółka istnieje | odpis, JSON sformatowany z wcięciem 2 spacji |
| `404` | poprawny numer, którego nie ma w rejestrze (np. `0009999999`) | `{"type": "...", "title": "Not Found", "status": 404, "traceId": "..."}` |
| `400` | numer niepoprawny (np. `0000000000`) | `{"type": "...rfc7231#section-6.5.1", "title": "Bad Request", "status": 400, "traceId": "..."}` |

W bronze zapisujemy 200 i 404 (wynik biznesowy). Kod 400 jest jawnym błędem, a przebieg kończy się kodem wyjścia 1.

### Ścieżki pól (zweryfikowane na 13 odpisach z watchlisty)

| Potrzeba | Ścieżka | Format / uwagi |
|---|---|---|
| Numer KRS | `odpis.naglowekA.numerKRS` | `"0000635012"` |
| Stan odpisu na dzień | `odpis.naglowekA.stanZDnia` | `"DD.MM.RRRR"` |
| Data rejestracji | `odpis.naglowekA.dataRejestracjiWKRS` | `"DD.MM.RRRR"`; **dla spółek sprzed 2001 r. to data przeniesienia do KRS** (ORLEN: `19.07.2001`), nie data powstania; wtedy `dzial1.danePodmiotu.daneOWczesniejszejRejestracji` = `{nazwaPoprzedniegoRejestru: "RHB", numerWPoprzednimRejestrze, sadProwadzacyRejestr}` (u młodszych spółek pusty obiekt) |
| Nazwa | `odpis.dane.dzial1.danePodmiotu.nazwa` | tekst wielkimi literami; sufiks `W LIKWIDACJI` / `W UPADŁOŚCI` |
| Forma prawna | `…danePodmiotu.formaPrawna` | `"SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ"`, `"SPÓŁKA AKCYJNA"` |
| NIP | `…danePodmiotu.identyfikatory.nip` | 10 cyfr, tekst |
| REGON | `…danePodmiotu.identyfikatory.regon` | **14 cyfr** (9-cyfrowy REGON + `00000`); Biała Lista podaje 9 cyfr |
| Kapitał zakładowy | `odpis.dane.dzial1.kapital.wysokoscKapitaluZakladowego.wartosc` + `.waluta` | tekst z przecinkiem dziesiętnym: `"40000000,00"`, `"PLN"` |
| Organ reprezentacji | `odpis.dane.dzial2.reprezentacja.nazwaOrganu`, `.sposobReprezentacji`, `.sklad[]` | w `sklad[]`: `funkcjaWOrganie` (np. `"PREZES ZARZĄDU"`), `czyZawieszona`, dane osoby (zredagowane) |
| Rada nadzorcza (S.A.) | `odpis.dane.dzial2.organNadzoru[].nazwa`, `.sklad[]` | |
| Prokurenci | `odpis.dane.dzial2.prokurenci[]` | `rodzajProkury` + dane osoby (zredagowane) |
| Wspólnicy sp. z o.o. | `odpis.dane.dzial1.wspolnicySpzoo[]` | **spółka:** `nazwa`, `krs.krs`, `identyfikator.regon`; **osoba:** `nazwisko`, `imiona`, `identyfikator.pesel` (zredagowane); zawsze `posiadaneUdzialy` (tekst wolny) i `czyPosiadaCaloscUdzialow` (bool) |
| Jedyny akcjonariusz (S.A.) | `odpis.dane.dzial1.jedynyAkcjonariusz[]` | `nazwa`, `krs.krs`, `identyfikator`, `czyPosiadaCaloscAkcji` |
| PKD przeważające | `odpis.dane.dzial3.przedmiotDzialalnosci.przedmiotPrzewazajacejDzialalnosci[]` | `opis`, `kodDzial`, `kodKlasa`, `kodPodklasa` (np. `63`, `12`, `Z` → 63.12.Z) |
| Likwidacja | `odpis.dane.dzial6.likwidacja[]` | `otwarcieLikwidacji` (tekst wolny z datą uchwały), `sposobReprezentacjiPodmiotuPrzezLikwidatorow`, `likwidatorzy[]` (zredagowane) |
| Rozwiązanie | `odpis.dane.dzial6.rozwiazanieUniewaznienie` | `okreslenieOkolicznosci` (`"ROZWIĄZANIE"`), `informacjaORozwiazaniuUniewaznieniu` |
| Upadłość | `odpis.dane.dzial6.postepowanieUpadlosciowe[]` | `informacjaOOgloszeniuUpadlosci.{data, sygnatura, organWydajacy}`, `sposobProwadzeniaPostepowania`, `daneSyndyka[]` (u nas syndykiem jest spółka), `opisZakonczeniaProcesuUpadlosci` |
| Restrukturyzacja | `odpis.dane.dzial6.postepowanieRestrukturyzacyjneNaprawczePrzymusowaRestrukturyzacjaUporzadkowanaLikwidacja[]` | np. `rodzajPostepowania: "PRZYMUSOWA RESTRUKTURYZACJA"` |
| Zawieszenie działalności | `odpis.dane.dzial6.zawieszenieWznowienie[]` | `dataZawieszenia`, `dataWznowienia` (`DD.MM.RRRR`) |
| Połączenia / podziały | `odpis.dane.dzial6.polaczeniePodzialPrzeksztalcenie[]` | podmioty przejmowane i przejmujące z `krs.krs`, `nazwaSadu` zamaskowana (`*******`) |
| Zaległości, kurator | `odpis.dane.dzial4`, `odpis.dane.dzial5` | we wszystkich 13 odpisach puste obiekty `{}` |

Kluczowe obserwacje:
- **Wspólnik zagraniczny ma `krs.krs = "0000000000"`** (np. `ALLEGRO.EU SA`, `ASAHI POLAND B.V.`). To wartość zastępcza, a nie numer. W łańcuchu własności trzeba ją traktować jak „brak KRS”, a w Białej Liście NIP `0000000000` odrzucamy.
- **Nazwa wspólnika może być nieaktualna.** ORLEN EKO podaje `POLSKI KONCERN NAFTOWY ORLEN SPÓŁKA AKCYJNA` (dawna nazwa) z poprawnym KRS `0000028860`. Wniosek: wspólników łączymy po numerze KRS, nie po nazwie.
- `OdpisPelny` działa (`odpis.rodzaj = "Pełny"`, nagłówek `naglowekP` z listą `wpis`). Pola są w nim **listami z historią** oznaczoną `nrWpisuWprow` / `nrWpisuWykr`, np. kapitał SIMPLE INVEST: 50 000 → 67 700 → 72 700 PLN. To dobry materiał na SCD2 w tygodniu 4. W bronze zapisujemy go jako źródło `krs_full`.

### Werdykty dla KRS

| Założenie z koncepcji | Werdykt |
|---|---|
| API bez klucza, JSON zagnieżdżony | **POTWIERDZONE** |
| „Dokładna struktura JSON pisana z pamięci” | **POTWIERDZONE (z poprawkami):** ścieżki jak w tabeli powyżej |
| PESEL w API jest anonimizowany | **POTWIERDZONE:** PESEL ma postać „pierwsza cyfra + 10 × `*`”, a imiona i nazwiska „pierwsza litera + `*`” |
| Reguła `OLD_PRESIDENT` (wiek z PESEL) | **OBALONE:** z PESEL nie da się wyliczyć wieku. Wytyczne (sekcja 9) i tak zabraniają danych osobowych, więc nie korzystamy też z `dataUrodzenia` |
| **NOWE:** `identyfikator.dataUrodzenia` | Dla części osób bez PESEL (prokurent, członek RN, zarząd) API podaje **pełną datę urodzenia jawnym tekstem**. Redagujemy ją przed zapisem do bronze |
| Nazwy pól wspólników zależą od formy prawnej | **POTWIERDZONE** dla sp. z o.o. (`wspolnicySpzoo`) i S.A. (`jedynyAkcjonariusz` tylko przy jednym akcjonariuszu). **NADAL NIEJASNE** dla sp.k., sp.j. i innych form (brak próbki) |
| Dla S.A. akcjonariusze zwykle nie są w KRS | **POTWIERDZONE:** 3 z 5 S.A. z watchlisty nie mają żadnej sekcji akcjonariuszy; 2 mają `jedynyAkcjonariusz` (oba to spółki zagraniczne z `krs.krs = "0000000000"`) |
| Brak udziałów procentowych (tekst wolny) | **POTWIERDZONE:** `posiadaneUdzialy` to tekst, np. `"800.000 UDZIAŁÓW O ŁĄCZNEJ WARTOŚCI 40.000.000 ZŁ"`. 100% wynika z `czyPosiadaCaloscUdzialow = true` |
| Wzmianki o likwidacji / upadłości | **POTWIERDZONE:** `dzial6.likwidacja[]`, `dzial6.postepowanieUpadlosciowe[]` oraz sufiks nazwy |

---

## 2. Biała Lista VAT (MF) – `search/nips`

**Zapytanie:** `GET https://wl-api.mf.gov.pl/api/search/nips/{nip1,…,nip30}?date=RRRR-MM-DD` (bez klucza).
**Odpowiedź:** `200`, JSON w jednej linii (bez wcięć).

```text
result.requestId          "aSHQ9-997gagm"           ← identyfikator sprawdzenia (dowód weryfikacji kontrahenta)
result.requestDateTime    "08-11-2026 13:16:22"     ← format DD-MM-RRRR GG:MM:SS
result.entries[]                                     ← jeden wpis na każdy NIP z zapytania
  .identifier             "5250007738"              ← NIP z zapytania
  .subjects[]                                        ← 0 lub 1 podmiot; PUSTA lista = NIP-u nie ma w wykazie
    .name, .nip, .regon (9 cyfr), .krs, .pesel (null dla spółek)
    .statusVat            "Czynny"
    .residenceAddress     "ŚWIĘTOKRZYSKA 36, 00-116 WARSZAWA"   ← u spółek wypełnione to pole (workingAddress = null)
    .registrationLegalDate "1998-10-01"             ← RRRR-MM-DD
    .registrationDenialDate/Basis, .restorationDate/Basis, .removalDate/Basis, .exemptionSmeDate   ← null w próbkach
    .representatives[], .authorizedClerks[], .partners[]   ← puste dla wszystkich 12 spółek
    .accountNumbers[]     ← numery rachunków firmowych (26 cyfr)
    .hasVirtualAccounts   false
```

Obserwacje na 12 spółkach:
- 11 ma `statusVat = "Czynny"`, także 2 spółki w likwidacji. Status VAT nie zastępuje więc informacji o likwidacji z KRS.
- **OGROL (w likwidacji, NIP 7880009355) ma pustą listę `subjects`**, czyli nie ma go w wykazie. To osobny stan niż „status ≠ Czynny” i silnik reguł musi go rozróżniać.
- `subjects[].krs` pokrywa się z numerem KRS, co daje drugi klucz do kontroli spójności połączenia KRS↔VAT (oprócz NIP).
- REGON ma inne formaty (KRS: 14 cyfr, VAT: 9 cyfr), więc w warstwie silver trzeba go znormalizować.

**Zabezpieczenie przed WAF (NOWE):** API stoi za Imperva Incapsula. Z chmurowego adresu IP dostaliśmy **HTTP 200 z
HTML-em („Request unsuccessful. Incapsula incident ID…”) zamiast JSON-a** w 2 z 3 zapytań. Za pierwszym razem szło domyślne
`User-Agent: python-requests/…`, a za trzecim już nasz identyfikujący się nagłówek, więc przyczyny nie da się przypisać
wyłącznie nagłówkowi (najpewniej chodzi o reputację adresu IP lub ocenę ruchu jako bota). Konsekwencje w kodzie:
odpowiedź 200 bez klucza `result` jest błędem (`InvalidPayloadError`). Nie zapisujemy jej jako poprawnej, nie traktujemy jako
cache, a przebieg kończy się kodem 1. Każda próba liczy się do limitu. Nie próbujemy obchodzić tego zabezpieczenia
(np. podszywać się pod przeglądarkę). Z domowego IP trzeba to sprawdzić w tygodniu 2.

| Założenie z koncepcji | Werdykt |
|---|---|
| Bez klucza, max 30 NIP w zapytaniu | **POTWIERDZONE** (bez klucza; 12 NIP w jednym zapytaniu zadziałało; limitu 30 nie testowaliśmy, przyjmujemy go za dokumentacją) |
| Dzienne limity – konkretne wartości ❓ | **NADAL NIEJASNE na żywo:** celowo nie testujemy przekroczenia. Przyjmujemy 100 zapytań `search` na dobę (z blokadą IP do północy) i zatrzymujemy się przy 95 |
| Status podatnika VAT | **POTWIERDZONE:** `statusVat`. Na żywo widzieliśmy tylko `"Czynny"`; inne wartości (np. `"Zwolniony"`) to hipoteza z dokumentacji |
| **NOWE:** brak NIP w wykazie | `subjects: []` |

---

## 3. OpenSanctions – pliki zbiorcze

**Metadane:** `GET https://data.opensanctions.org/datasets/latest/{zbiór}/index.json` → `307` na wersjonowany adres
`/artifacts/{zbiór}/{wersja}/index.json`. Przydatne klucze:
- `version` (np. `20261108101006-opj`), `updated_at`, `last_export`, `target_count`;
- `resources[]` = `{name, url, checksum, size, mime_type}`, gdzie `checksum` to **SHA-1** pliku, a `url` wskazuje niezmienny artefakt danej wersji.

W `index.json` nie ma pola z licencją. Licencję (CC BY-NC, użytek niekomercyjny, wymagana atrybucja) opisuje strona OpenSanctions.

**Plik:** `targets.simple.csv`, w formacie: nagłówek, separator `,`, wszystkie pola w cudzysłowach, końce linii LF, UTF-8 bez BOM, brak pól
wielowierszowych (sprawdzone na wszystkich 4 plikach). Wiele wartości w jednej komórce rozdziela `;`. `target_count` z `index.json`
zgadza się z liczbą wierszy CSV we wszystkich 4 zbiorach.

Kolumny (identyczne we wszystkich zbiorach):
`id, schema, name, aliases, birth_date, countries, addresses, identifiers, sanctions, phones, emails, program_ids, dataset, first_seen, last_seen, last_change`.

**Rozróżnienie osoba/podmiot: kolumna `schema`.** Rozkład wierszy w wersji z 2026-11-08:

| Zbiór | Wersja | Wiersze | `Person` | Podmioty (zapisane) | Inne (pominięte) |
|---|---|---|---|---|---|
| `pl_mswia_sanctions` (lista MSWiA) | 20261108082607-bee | 555 | 435 | 120 `Company` | – |
| `pl_finanse_sanctions` (lista GIIF/MF) | 20261108062205-gje | 473 | 382 | 91 `LegalEntity` | – |
| `us_ofac_sdn` | 20261108101006-opj | 20 541 | 7 516 | 10 005 `Organization`, 22 `Company`, 2 `LegalEntity` | 1 567 `Vessel`, 1 080 `CryptoWallet`, 342 `Airplane`, 7 `Security` |
| `eu_fsf` (skonsolidowana lista UE) | 20261107065707-cjr | 6 163 | 4 429 | 1 732 `Organization` | 2 `Vessel` |

W żadnym zapisanym wierszu podmiotu kolumna `birth_date` nie jest wypełniona.

Obserwacje:
- **Nazwa zbioru UE: `eu_fsf`** („EU Financial Sanctions Files (FSF)”, typ `source`). `eu_sanctions` to kolekcja łącząca kilka źródeł, a `eu_journal_sanctions` to wpisy z Dziennika Urzędowego.
- Znaczenie kolumny `sanctions` zależy od zbioru: data w `pl_mswia_sanctions` (`"2023-10-03"`), opis programu w UE i OFAC, pusta w `pl_finanse_sanctions`. Kolumna `countries` jest pusta w obu polskich zbiorach.
- `identifiers` **nie ma typów**. Na liście MSWiA polskie spółki mają numery wyglądające na KRS (`0000…`), NIP i REGON (101 ze 120 wierszy), co otwiera drogę do **dopasowania deterministycznego** zamiast samego porównywania nazw. W OFAC i UE 10-cyfrowe identyfikatory to najczęściej rosyjskie INN, więc bez typu nie da się ich odróżnić od NIP. **NADAL NIEJASNE:** typy identyfikatorów są w pełnym formacie FtM (`entities.ftm.json`), który trzeba sprawdzić w tygodniu 2.

| Założenie z koncepcji | Werdykt |
|---|---|
| URL `…/datasets/latest/<zbiór>/<plik>` | **POTWIERDZONE** (z przekierowaniem 307 na wersjonowany artefakt) |
| Kolekcja `sanctions` zawiera polską listę MSWiA | **POTWIERDZONE** (`pl_mswia_sanctions` jest wśród 98 zbiorów kolekcji) |
| `sanctions/targets.simple.csv` ma ~43 MB | **OBALONE (nieaktualne):** dziś ma 78,8 MB (a `entities.ftm.json` 381,8 MB). Nie potrzebujemy go, bo pobieramy 4 małe zbiory (łącznie ~10,5 MB) |
| Lista MSWiA: adres CSV z dane.gov.pl trzeba znaleźć ręcznie | **ZASTĄPIONE:** bierzemy `pl_mswia_sanctions` z OpenSanctions |
| OFAC `sdn.csv` / `alt.csv` bez nagłówka | **NIE DOTYCZY:** OFAC pobieramy jako `us_ofac_sdn` z OpenSanctions (jeden format dla wszystkich list) |

---

## 4. Dane osobowe: co faktycznie przychodzi i co zapisujemy

| Źródło | Co zawiera odpowiedź | Co trafia do bronze |
|---|---|---|
| KRS | imiona i nazwiska (zamaskowane do 1. litery), PESEL (zamaskowany do 1. cyfry), **pełne daty urodzenia** części osób | wartości `imiona`, `nazwisko`, `pesel`, `dataUrodzenia` zamienione na `[REDACTED]`; struktura, role (`funkcjaWOrganie`) i liczba osób zostają; reszta odpowiedzi bez zmian (ten sam układ JSON) |
| Biała Lista | `representatives` / `authorizedClerks` / `partners` (u nas puste) | imiona, nazwiska, PESEL i NIP osób fizycznych w tych listach → `[REDACTED]` |
| OpenSanctions | rekordy osób fizycznych (imię i nazwisko, data urodzenia) | **nie zapisujemy ich wcale:** wiersze filtrujemy w trakcie pobierania, zostają tylko `Company`, `Organization`, `LegalEntity` i `PublicBody`, bajt w bajt; SHA-1 całego oryginału sprawdzamy z `index.json` i zapisujemy w `_metadata.json` |

---

## 5. Propozycje zmian w `KYB_projekt_kontekst.md` (do decyzji zespołu, plik nie był edytowany)

1. **Reguła `OLD_PRESIDENT`:** usunąć. Zamiast niej można wprowadzić np. `SINGLE_BOARD_MEMBER` (jednoosobowy zarząd, liczba elementów `reprezentacja.sklad[]`) albo `BOARD_SUSPENDED` (`czyZawieszona`). W zasadzie 5 usunąć zdanie o wyliczaniu wieku z PESEL.
2. **Nowe reguły z potwierdzonych pól:** `IN_LIQUIDATION` (`dzial6.likwidacja`), `IN_BANKRUPTCY` (`dzial6.postepowanieUpadlosciowe`), `ACTIVITY_SUSPENDED` (`zawieszenieWznowienie` bez `dataWznowienia`) oraz rozdzielenie `VAT_NOT_REGISTERED` (brak w wykazie) od `VAT_NOT_ACTIVE`.
3. **Źródła sankcyjne:** OFAC, MSWiA i UE w jednym formacie z OpenSanctions (`us_ofac_sdn`, `pl_mswia_sanctions`, `eu_fsf`) plus `pl_finanse_sanctions`. Usunąć bezpośrednie pobieranie `sdn.csv`/`alt.csv` i szukanie CSV MSWiA na dane.gov.pl.
4. **Dopasowanie sankcyjne:** dla list z identyfikatorami (MSWiA) najpierw dopasowanie po KRS/NIP, potem rozmyte po nazwie.
5. **Zasada 6 (bronze):** doprecyzować na „bronze = surowa odpowiedź po obowiązkowej minimalizacji danych osobowych; poza tym bez zmian”.
6. **Ryzyka (sekcja 9):** dopisać WAF Białej Listy (HTTP 200 z HTML-em z chmurowego IP), wartość zastępczą `0000000000` dla wspólników zagranicznych, nieaktualne nazwy wspólników i to, że `dataRejestracjiWKRS` u spółek sprzed 2001 r. nie jest datą powstania.
7. **Stos (sekcje 1, 4, 10, 12):** zamiast Databricks/PySpark Python + DuckDB/Polars + Parquet (zgodnie z ustaleniami zespołu i zasadą prostoty z wytycznych).
