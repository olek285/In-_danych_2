"""Redaction tests on fictional records shaped like the live API responses."""

from __future__ import annotations

import json

from kyb.pii import REDACTED, redact_krs_payload, redact_vat_payload

# Shape copied from a real KRS extract (values are fictional).
KRS_SAMPLE = {
    "odpis": {
        "dane": {
            "dzial1": {
                "danePodmiotu": {"nazwa": "PRZYKŁAD SPÓŁKA Z O.O.", "identyfikatory": {"nip": "5260250995"}},
                "wspolnicySpzoo": [
                    {"nazwa": "MATKA S.A.", "krs": {"krs": "0000000001"}, "posiadaneUdzialy": "100 UDZIAŁÓW"},
                    {
                        "nazwisko": {"nazwiskoICzlon": "K*******"},
                        "imiona": {"imie": "J***", "imieDrugie": ""},
                        "identyfikator": {"pesel": "8**********"},
                        "posiadaneUdzialy": "50 UDZIAŁÓW",
                    },
                ],
            },
            "dzial2": {
                "reprezentacja": {
                    "sklad": [
                        {
                            "nazwisko": {"nazwiskoICzlon": "N****"},
                            "imiona": {"imie": "A***"},
                            "identyfikator": {"dataUrodzenia": "01.02.1960"},
                            "funkcjaWOrganie": "PREZES ZARZĄDU",
                        }
                    ]
                }
            },
        }
    }
}


def test_krs_person_fields_are_masked_and_structure_kept():
    text, count = redact_krs_payload(json.dumps(KRS_SAMPLE, ensure_ascii=False, indent=2))
    data = json.loads(text)
    shareholder = data["odpis"]["dane"]["dzial1"]["wspolnicySpzoo"][1]
    board = data["odpis"]["dane"]["dzial2"]["reprezentacja"]["sklad"][0]
    assert shareholder["nazwisko"] == {"nazwiskoICzlon": REDACTED}
    assert shareholder["imiona"] == {"imie": REDACTED, "imieDrugie": ""}  # empty stays empty
    assert shareholder["identyfikator"]["pesel"] == REDACTED
    assert board["identyfikator"]["dataUrodzenia"] == REDACTED
    assert count == 6
    # company data and roles are untouched
    assert board["funkcjaWOrganie"] == "PREZES ZARZĄDU"
    assert data["odpis"]["dane"]["dzial1"]["wspolnicySpzoo"][0]["nazwa"] == "MATKA S.A."
    assert data["odpis"]["dane"]["dzial1"]["danePodmiotu"]["identyfikatory"]["nip"] == "5260250995"
    for secret in ("K*******", "J***", "8**********", "01.02.1960"):
        assert secret not in text


def test_redaction_keeps_source_layout():
    pretty = json.dumps(KRS_SAMPLE, ensure_ascii=False, indent=2)
    text, _ = redact_krs_payload(pretty)
    assert text.splitlines()[1].startswith('  "odpis"')
    compact = json.dumps(KRS_SAMPLE, ensure_ascii=False, separators=(",", ":"))
    assert "\n" not in redact_krs_payload(compact)[0]


def test_payload_without_people_is_returned_unchanged():
    original = '{"type": "about:blank", "status": 404}'
    assert redact_krs_payload(original) == (original, 0)
    assert redact_krs_payload("<html>error</html>") == ("<html>error</html>", 0)


def test_vat_people_masked_but_company_representative_nip_kept():
    payload = {
        "result": {
            "subjects": [
                {
                    "name": "PRZYKŁAD SPÓŁKA Z O.O.",
                    "nip": "5260250995",
                    "representatives": [
                        {"companyName": None, "firstName": "JAN", "lastName": "KOWALSKI", "pesel": None, "nip": "1234563218"},
                        {"companyName": "MATKA S.A.", "firstName": None, "lastName": None, "pesel": None, "nip": "5260250995"},
                    ],
                    "authorizedClerks": [],
                    "partners": [],
                }
            ]
        }
    }
    text, count = redact_vat_payload(json.dumps(payload))
    subject = json.loads(text)["result"]["subjects"][0]
    person, company = subject["representatives"]
    assert person["firstName"] == person["lastName"] == person["nip"] == REDACTED
    assert company["companyName"] == "MATKA S.A." and company["nip"] == "5260250995"
    assert subject["nip"] == "5260250995"  # the taxpayer's own NIP is company data
    assert count == 3
