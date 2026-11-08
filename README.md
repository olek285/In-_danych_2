# Automated KYB Screening Tool

Projekt zaliczeniowy z przedmiotu Inżynieria danych (zespół 2-osobowy, 4 tygodnie).

**Cel:** wstępne, automatyczne prześwietlenie spółek z KRS pod kątem sygnałów ryzyka AML/KYB (Know Your Business).
Potok pobiera dane z publicznych rejestrów i list sankcyjnych, czyści je i łączy. Analityk dostaje **jawne alarmy
(„red flags”) z uzasadnieniem „wartość vs próg”**, a progi ustawia sam, więc system nie jest czarną skrzynką ze sztucznym wynikiem.

**Odbiorca:** analityk AML/Compliance w małej instytucji obowiązanej (biuro rachunkowe, firma pożyczkowa, mała
fintech), który weryfikuje nowego klienta-spółkę.

**Pytania, na które mają odpowiadać dane** (wersja robocza, do potwierdzenia w karcie projektu):
1. Czy spółka albo jej (pośredni) właściciel jest podobny do podmiotu z listy sankcyjnej PL, UE lub USA?
2. Czy spółka jest czynnym podatnikiem VAT na dzień weryfikacji?
3. Czy spółka jest w likwidacji, upadłości albo ma zawieszoną działalność?
4. Czy kapitał zakładowy i staż spółki pasują do skali planowanej współpracy?

> **Stan: tydzień 1.** Jest pozyskanie danych do warstwy **bronze** (KRS, Biała Lista VAT, 4 listy sankcyjne)
> z obsługą błędów, limitów i ochroną danych osobowych, a także podgląd surowych danych i testy jednostkowe.
> Warstwy silver/gold, testy jakości danych i aplikacja powstaną w kolejnych tygodniach (patrz `PROGRESS.md`).

## Źródła danych (tydzień 1)

| Źródło | Dostęp | Format | Klucz łączenia | Co daje |
|---|---|---|---|---|
| KRS – odpis aktualny (Ministerstwo Sprawiedliwości) | API bez klucza | JSON zagnieżdżony | numer KRS | nazwa, forma, NIP, kapitał, zarząd, wspólnicy, likwidacja/upadłość |
| Biała Lista VAT (Ministerstwo Finansów) | API bez klucza, **100 zapytań/dobę** | JSON paczkowy (≤ 30 NIP) | NIP | status VAT, numer KRS (kontrola spójności) |
| OpenSanctions: `pl_mswia_sanctions`, `pl_finanse_sanctions`, `us_ofac_sdn`, `eu_fsf` | pliki bez klucza, CC BY-NC 4.0 | CSV | nazwa (rozmyte), część list: KRS/NIP | podmioty objęte sankcjami |

Rzeczywiste struktury odpowiedzi (ścieżki pól, kody HTTP, formaty) opisuje [`docs/source_structures.md`](docs/source_structures.md).

## Struktura repozytorium

```
config/
  settings.yaml          adresy źródeł, limity, polityka ponowień, ścieżki
  watchlist.csv          lista spółek do sprawdzenia (kolumna krs, opcjonalnie note)
src/kyb/
  ingest.py              CLI: uv run kyb-ingest <krs|vat|sanctions|quota>
  http.py                wspólny klient HTTP: retry z backoffem, 404 jako wynik, walidacja JSON, strumieniowanie z SHA-1
  storage.py             bronze: koperta, partycje ingest_date=, zapis atomowy, tylko dopisywanie
  pii.py                 minimalizacja danych osobowych przed zapisem do bronze
  nip.py                 suma kontrolna NIP, paczki po 30
  quota.py               dzienny licznik zapytań zapisywany na dysku
  watchlist.py, config.py, logging_setup.py
  ingestion/             krs.py, vat.py, sanctions.py, report.py
scripts/
  inspect_sources.py     podgląd surowych danych z bronze (bez zapytań do sieci)
tests/                   testy jednostkowe (pytest), w pełni offline
docs/                    koncepcja, wytyczne, struktury źródeł, rejestr decyzji
data/                    (poza Gitem) bronze/, state/, logs/; później silver/, gold/, quality/
```

## Instalacja

Wymagania: **Python 3.11+** i **[uv](https://docs.astral.sh/uv/)**. Działa na Linuksie, macOS i Windows.

```bash
git clone <adres-repozytorium>
cd <katalog-repozytorium>
uv sync
```

`uv sync` tworzy środowisko `.venv` z wersjami zablokowanymi w `uv.lock`. Projekt nie wymaga sekretów.
Opcjonalnie skopiuj `.env.example` do `.env`, żeby zmienić katalog danych (`KYB_DATA_DIR`) albo poziom logów (`KYB_LOG_LEVEL`).

## Uruchomienie ingestu krok po kroku

Każde polecenie można powtórzyć: dane już pobrane danego dnia (albo ta sama wersja listy sankcyjnej) nie są
pobierane ponownie. Nowe dane trafiają do nowych plików, a bronze nigdy nie jest nadpisywany.

**1. Odpisy KRS** dla spółek z `config/watchlist.csv` (13 spółek, ok. 15 s):

```bash
uv run kyb-ingest krs
```

**2. Biała Lista VAT.** Najpierw sprawdź, ile zapytań zostanie zużytych (NIP-y są brane z odpisów KRS z kroku 1):

```bash
uv run kyb-ingest vat --dry-run
```

Potem właściwe pobranie i stan licznika:

```bash
uv run kyb-ingest vat
```

```bash
uv run kyb-ingest quota
```

**3. Listy sankcyjne** (4 zbiory, ok. 10 MB pobierania, kilka sekund):

```bash
uv run kyb-ingest sanctions
```

**4. Podgląd surowych danych** (działa tylko na zapisanych plikach i nie wysyła zapytań):

```bash
uv run python scripts/inspect_sources.py
```

Przydatne warianty: `--source krs_current --key 0000028860`, `--flat` (ścieżki pól), `--source opensanctions --rows 5`.

**5. Testy jednostkowe** (bez sieci; połączenia sieciowe są w testach zablokowane):

```bash
uv run pytest
```

Dodatkowe opcje: `kyb-ingest krs --krs 0000028860 0000126258` (wybrane numery), `--force` (ponowne pobranie),
`kyb-ingest krs --endpoint OdpisPelny` (odpis pełny z historią), `kyb-ingest vat --date 2026-11-01` (status na dzień).

**Kody wyjścia:** `0` oznacza sukces, `1` to błąd części zapytań (szczegóły na ekranie i w `data/logs/kyb_RRRR-MM-DD.log`),
a `2` to błędne dane wejściowe (np. pusta watchlista).

## Warstwa bronze

```
data/bronze/krs_current/ingest_date=2026-11-08/part-<czas>-<id>.jsonl      # 1 linia = 1 odpowiedź
data/bronze/vat_whitelist/ingest_date=2026-11-08/part-<czas>-<id>.jsonl    # 1 plik = 1 zapytanie (≤ 30 NIP)
data/bronze/opensanctions/ingest_date=2026-11-08/<zbiór>/<wersja>/targets.simple.csv + _metadata.json
data/state/vat_whitelist_quota.json                                         # licznik zapytań do Białej Listy
```

Każdy rekord to koperta `{source, key, url, http_status, ingested_at, payload, ...}`. `payload` to ciało odpowiedzi
jako tekst, bez parsowania. Dodatkowo zapisujemy `content_type`, liczbę zredagowanych wartości i (dla VAT) `query_date`.
Kod 404 z KRS zapisujemy jako wynik biznesowy. Inne błędy (400, 5xx po ponowieniach, sieć, odpowiedź 200, która nie jest
JSON-em API) są jawne: trafiają do logu, przebieg kończy się kodem 1 i nic błędnego nie jest zapisywane jako poprawna odpowiedź.

## Ochrona danych osobowych

Wytyczne zabraniają danych osobowych, dlatego minimalizacja odbywa się **przed zapisem na dysk**:
- **KRS:** imiona, nazwiska, PESEL i daty urodzenia (API zwraca je częściowo zamaskowane, a daty urodzenia jawne) są
  zastępowane przez `[REDACTED]`. Zostają role (np. „PREZES ZARZĄDU”) i liczba osób.
- **Biała Lista:** jak wyżej dla osób w `representatives`, `authorizedClerks` i `partners`.
- **Listy sankcyjne:** wiersze osób fizycznych są odrzucane w trakcie pobierania. Zapisujemy tylko podmioty
  (`Company`, `Organization`, `LegalEntity`, `PublicBody`). Sumę SHA-1 oryginału weryfikujemy z publikacją OpenSanctions.

Katalog `data/` nie trafia do repozytorium.

## Ograniczenia (stan tygodnia 1)

- **Biała Lista VAT stoi za zaporą Imperva Incapsula.** Z chmurowego IP 3 z 4 zapytań dostały HTTP 200 ze stroną HTML
  zamiast JSON-a. Kod to wykrywa i zgłasza błąd, a ponowne uruchomienie dopytuje tylko brakujące NIP-y.
  Z domowego IP trzeba to sprawdzić.
- Limit 100 zapytań/dobę dotyczy **adresu IP**, a licznik jest prowadzony per katalog danych. Dwie kopie projektu na tym
  samym łączu mają osobne liczniki, dlatego zostawiamy margines 5 zapytań.
- Nie przeliczamy kapitału w walutach obcych. Wspólnicy spółek innych niż sp. z o.o./S.A. nie są jeszcze zweryfikowani.

## Źródła i licencje danych

- KRS: Ministerstwo Sprawiedliwości, API odpisów KRS (dane publiczne).
- Biała Lista VAT: Ministerstwo Finansów, API Wykazu podatników VAT (dane publiczne).
- **OpenSanctions** (opensanctions.org): licencja CC BY-NC 4.0, użytek niekomercyjny z atrybucją. Projekt jest
  edukacyjny i niekomercyjny. Dane pierwotne pochodzą od MSWiA, MF/GIIF, OFAC (US Treasury) i Komisji Europejskiej.

## Wykorzystanie AI

W tygodniu 1 korzystaliśmy z asystenta AI **Claude Code** (Anthropic) w następującym zakresie:
- **Rozpoznanie źródeł:** wyszukanie numerów KRS do watchlisty (sp. z o.o. ze wspólnikami-spółkami, S.A., spółki
  w likwidacji i upadłości) i ich weryfikacja na żywym API; sprawdzenie nazw zbiorów OpenSanctions.
- **Kod i testy:** wygenerowanie klienta HTTP, modułów ingestu, minimalizacji danych osobowych, licznika limitu,
  skryptu podglądu i testów jednostkowych.
- **Dokumentacja:** szkic `docs/source_structures.md`, `docs/decisions.md`, tego README i `PROGRESS.md`.

Jak weryfikujemy wyniki AI: każde twierdzenie o strukturze danych zostało sprawdzone na prawdziwej odpowiedzi API
zapisanej w bronze i da się je odtworzyć skryptem `inspect_sources.py`. Kod przechodzi testy (`uv run pytest`) i jest
przeglądany przez zespół. Decyzje zaproponowane przez AI są wypisane w [`docs/decisions.md`](docs/decisions.md) ze
statusem „do akceptacji”. Za każdy element rozwiązania odpowiadają autorzy projektu.
