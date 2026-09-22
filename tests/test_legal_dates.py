from datetime import date

from euaiact.cli import main
from euaiact.legal_dates import load_milestones, unverified
from euaiact.settings import ROOT

EXPECTED = {
    "art5_prohibitions": date(2025, 2, 2),
    "art5_omnibus_prohibitions": date(2026, 12, 2),
    "art4_ai_literacy": date(2025, 2, 2),
    "art4_ai_literacy_amended": date(2026, 7, 27),
    "gpai_obligations": date(2025, 8, 2),
    "gpai_enforcement": date(2026, 8, 2),
    "art50_transparency": date(2026, 8, 2),
    "art50_2_existing_systems": date(2026, 12, 2),
    "high_risk_annex_iii": date(2027, 12, 2),
    "high_risk_annex_i": date(2028, 8, 2),
}


def test_config_has_expected_dates():
    milestones = {m.key: m.applies_from for m in load_milestones(ROOT / "config" / "legal_dates.yaml")}
    assert milestones == EXPECTED


def test_unverified_dates_fail_strict_release_check(capsys):
    assert unverified(load_milestones(ROOT / "config" / "legal_dates.yaml"))
    assert main(["check-legal-dates", "--strict"]) == 1
    assert main(["check-legal-dates"]) == 0
