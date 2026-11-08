# Postęp prac

## Tydzień 1 (do 2026-11-08): pozyskanie danych do warstwy bronze

### Co zrobiono
- Szkielet repozytorium: `uv` (`pyproject.toml` + `uv.lock`), konfiguracja w `config/settings.yaml`, `.env.example`
  bez sekretów, `data/` poza Gitem.
- Wspólny klient HTTP (`src/kyb/http.py`): retry z backoffem 2/4/8/16 s dla błędów sieci, 5xx i 429, obsługa
  `Retry-After`, 404 jako wynik biznesowy, jawne wyjątki dla pozostałych błędów, walidacja ciała JSON,
  strumieniowe pobieranie ze sprawdzeniem długości i SHA-1, zapis atomowy.
- Bronze (`src/kyb/storage.py`): koperta `{source, key, url, http_status, ingested_at, payload}`, partycje
  `ingest_date=RRRR-MM-DD`, wyłącznie dopisywanie nowych plików.
- Ingest **KRS** (`OdpisAktualny`, opcjonalnie `OdpisPelny`), **Białej Listy VAT** (paczki po 30 NIP, dzienny licznik
  zapytań na dysku, `--dry-run`, cache) oraz **4 list sankcyjnych z OpenSanctions** (tylko podmioty, pobieranie nowych wersji).
- Minimalizacja danych osobowych przed zapisem (`src/kyb/pii.py`).
- Skrypt podglądu surowych danych `scripts/inspect_sources.py` (offline).
- 76 testów jednostkowych (offline, z blokadą sieci): klient HTTP (retry, 404, 400, WAF, sumy kontrolne), NIP
  (suma kontrolna, paczki po 30), licznik limitu, bronze, redakcja danych osobowych, każdy ingest na atrapach.
- Dokumentacja: `docs/source_structures.md` (prawdziwe struktury i werdykty dla założeń ❓), `docs/decisions.md`, README.

### Co sprawdzono na żywo (2026-11-08)
- **KRS:** 13 odpisów (200), nieistniejący numer daje 404, niepoprawny 400. Potwierdzone ścieżki: nazwa, NIP, REGON,
  kapitał, data rejestracji, forma, zarząd, wspólnicy sp. z o.o., jedyny akcjonariusz S.A., likwidacja, upadłość,
  zawieszenie działalności. `OdpisPelny` działa i zawiera historię zmian.
- **Biała Lista:** 4 zapytania (limit 100): 1 poprawna odpowiedź dla 12 NIP-ów, 3 zablokowane przez zaporę
  Incapsula (HTTP 200 z HTML-em; ostatnie 2 dla jednego brakującego NIP-u, bez ponowień w pętli). Brak NIP-u w wykazie to pusta lista `subjects`.
- **OpenSanctions:** 4 zbiory (`pl_mswia_sanctions`, `pl_finanse_sanctions`, `us_ofac_sdn`, `eu_fsf`). SHA-1 jest zgodne
  z `index.json`, a z 27 732 wierszy zapisano 11 972 wiersze podmiotów (osoby odrzucone). Drugie uruchomienie nic nie pobiera
  (ta sama wersja).
- Instalacja od zera ze świeżego klonu (`uv sync`, `uv run pytest`, ingest) zgodnie z README działa.

### Problemy i jak je rozwiązaliśmy
- **PESEL zamaskowany** (wieku prezesa nie da się policzyć), a **daty urodzenia jawne**. Redagujemy je przed zapisem
  (D2) i proponujemy usunąć regułę wieku prezesa (D3).
- **Zapora Incapsula przy Białej Liście:** HTTP 200 ze stroną HTML zamiast JSON-a. Pierwsza wersja kodu zapisała ją jako
  poprawną odpowiedź. Naprawione: walidacja treści, takie odpowiedzi nie są cache'em (D6). Przy okazji wyszedł błąd:
  `User-Agent` projektu nie był wysyłany (`setdefault` nie nadpisywał domyślnego). Przyczyna blokady nie jest jednoznaczna.
- Pierwsza wersja redakcji zapisywała JSON w zwartej postaci. Teraz zachowujemy układ źródła, więc od oryginału różnią się tylko
  zamaskowane wartości.

### Plan na tydzień 2
- Akceptacja przez zespół decyzji D2–D7 i zmian w `KYB_projekt_kontekst.md` zaproponowanych w `docs/source_structures.md` (sekcja 5).
- Sprawdzenie Białej Listy z domowego IP; dopytanie brakującego NIP-u (Getin Noble Bank).
- Warstwa **silver** (Polars/DuckDB → Parquet): `company`, `board_role` (bez danych osobowych), `shareholder`,
  `vat_status`, `sanctioned_entity`; typowanie dat i kwot, normalizacja REGON, nazw i wartości `0000000000`.
- Sprawdzenie typów identyfikatorów w formacie FtM (`entities.ftm.json`) dla listy MSWiA (dopasowanie po KRS/NIP).
- Pierwsze testy jakości danych (unikalność KRS, suma kontrolna NIP, zakresy dat i kapitału, dozwolone wartości statusu VAT).
