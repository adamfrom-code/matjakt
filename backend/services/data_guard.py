# -*- coding: utf-8 -*-
"""Spärr: en testkörning får aldrig öppna en riktig databas.

Bakgrund 2026-09-02: ett importtest öppnade backend/data/grocery.db via
grocery_api.open_store() och lämnade en 'failed'-rad i grocery_collector_runs
vid varje körning. Att isolera det testet räcker inte - nästa test som glömmer
peka om DB_PATH gör om samma sak. Därför sitter regeln HÄR, i koden som
öppnar databaserna, inte i testerna.

Regeln: när en testkörning pågår får en SQLite-fil bara öppnas om den ligger
under OS:ets tempkatalog (tempfile.gettempdir()) eller är en :memory:-databas.
Allt annat - backend/data, ett MATJAKT_DATA_DIR som pekar på riktig data,
repokatalogen - stoppas med ProductionDatabaseInTestError INNAN filen eller
dess katalog skapas. Hellre ett test som kraschar än ett som skriver i
riktig data.

Testläge upptäcks utan att testerna behöver göra något:
  * MATJAKT_TEST_MODE=1 (sätts av tests/run.py och isolated_test_data_dir())
  * PYTEST_CURRENT_TEST (pytest sätter den under varje test)
  * `python -m unittest ...` (huvudmodulens spec heter unittest.__main__)
  * en testfil körd direkt (`python tests/test_x.py`)
Utanför testläge är spärren helt passiv: servern, skripten och kollektorerna
öppnar sina databaser precis som förut.
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from pathlib import Path

_TRUE = {"1", "true", "yes", "on"}


class ProductionDatabaseInTestError(RuntimeError):
    """En testkörning försökte öppna en databas utanför tempkatalogen."""


def test_mode_active() -> bool:
    """Pågår en testkörning i den här processen?"""
    env = os.environ
    if env.get("MATJAKT_TEST_MODE", "").strip().lower() in _TRUE:
        return True
    if env.get("PYTEST_CURRENT_TEST"):
        return True
    main = sys.modules.get("__main__")
    spec_name = getattr(getattr(main, "__spec__", None), "name", "") or ""
    if spec_name.startswith(("unittest", "pytest")):
        return True
    argv0 = Path(sys.argv[0]).name.lower() if sys.argv and sys.argv[0] else ""
    if argv0.startswith("test_") or argv0 in ("pytest", "pytest.exe", "py.test"):
        return True
    return False


class OutboundCallInTestError(RuntimeError):
    """En testkörning försökte anropa en riktig extern tjänst."""


_outbound_mocked = 0


@contextlib.contextmanager
def mocked_outbound():
    """Används av tester som HAR ersatt transporten (urlopen, smtplib.SMTP)
    och därför ska släppas förbi spärren. Glömmer man den blir anropet
    stoppat - fail closed åt rätt håll."""
    global _outbound_mocked
    _outbound_mocked += 1
    try:
        yield
    finally:
        _outbound_mocked -= 1


def guard_outbound_call(service: str) -> None:
    """Fail closed: under en testkörning når vi aldrig ut på riktigt.

    Nycklar i .env är riktiga - utan den här spärren skapade sviten skarpa
    Stripe-kunder och kunde skicka riktiga mejl bara för att någon körde
    testerna på en maskin där utvecklingsnycklarna låg."""
    if _outbound_mocked:
        return
    if test_mode_active():
        raise OutboundCallInTestError(
            f"Testkörning försökte anropa {service} på riktigt. "
            f"Mocka anropet och kör det i data_guard.mocked_outbound() - "
            f"riktiga anrop är aldrig tillåtna i testläge.")


def allowed_test_roots() -> list[Path]:
    """Kataloger en testkörning får ha databaser i: bara OS:ets tempkatalog."""
    return [Path(tempfile.gettempdir()).resolve()]


def is_test_safe_path(path) -> bool:
    text = str(path)
    if text == ":memory:" or text.startswith("file::memory:"):
        return True
    try:
        resolved = Path(text).expanduser().resolve()
    except (OSError, RuntimeError):
        return False
    for root in allowed_test_roots():
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def check_database_path(path, *, test_mode: bool, purpose: str = "databasen") -> None:
    """Ren kontroll utan sidoeffekter: kastar om testläge + osäker sökväg."""
    if not test_mode or is_test_safe_path(path):
        return
    roots = ", ".join(str(root) for root in allowed_test_roots())
    raise ProductionDatabaseInTestError(
        f"Testkörning försökte öppna {purpose} utanför tempkatalogen: {path}. "
        f"I testläge får bara filer under {roots} eller :memory: öppnas. "
        "Peka om sökvägen i testet (tempfile.TemporaryDirectory + "
        "setattr(grocery_api, 'DB_PATH', ...) med addCleanup) eller anropa "
        "services.data_guard.isolated_test_data_dir() INNAN api_server importeras.")


def guard_database_path(path, purpose: str = "databasen") -> None:
    """Anropas av varje kod som öppnar en SQLite-fil, före mkdir/connect."""
    check_database_path(path, test_mode=test_mode_active(), purpose=purpose)


_ISOLATED_DIR: tempfile.TemporaryDirectory | None = None


def isolated_test_data_dir() -> Path:
    """Ger testprocessen en egen datakatalog under temp och pekar
    MATJAKT_DATA_DIR dit. Anropa INNAN api_server importeras - api_server
    öppnar matjakt.db och prices.db vid import.

    Idempotent: ett redan tempbaserat MATJAKT_DATA_DIR återanvänds (så
    tests/run.py:s katalog gäller). Ett MATJAKT_DATA_DIR som pekar på riktig
    data skrivs över - det är hela poängen. Modulkonstanter som redan hunnit
    räknas ut från den gamla miljön (grocery_api.DB_PATH, recipes DB_PATH)
    pekas om så att sviten inte blir beroende av importordning."""
    global _ISOLATED_DIR
    current = os.environ.get("MATJAKT_DATA_DIR")
    if current and is_test_safe_path(current):
        data_dir = Path(current)
    else:
        if _ISOLATED_DIR is None:
            # ignore_cleanup_errors: butikerna håller sina anslutningar öppna
            # processen ut, och Windows vägrar ta bort öppna filer.
            _ISOLATED_DIR = tempfile.TemporaryDirectory(
                prefix="matjakt-tests-", ignore_cleanup_errors=True)
        data_dir = Path(_ISOLATED_DIR.name)
        os.environ["MATJAKT_DATA_DIR"] = str(data_dir)
    os.environ["MATJAKT_TEST_MODE"] = "1"

    for module_name, filename in (("services.grocery.api", "grocery.db"),
                                  ("services.recipes.api", "recipes.db")):
        module = sys.modules.get(module_name)
        if module is not None and not is_test_safe_path(getattr(module, "DB_PATH", data_dir)):
            module.DB_PATH = data_dir / filename
    return data_dir
