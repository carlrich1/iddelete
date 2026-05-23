"""Deterministic mock scanners — always available.

We register one ``MockScanner`` per name in a curated list so that signing
up generates a realistic-looking exposure report (dozens of brokers, mixed
statuses) without making any external HTTP calls. Once you set
``EY_REAL_SCANNERS=1`` and configure the real-pattern wrappers, the mock
results coexist (use a different broker_slug namespace) but are filtered
out in :func:`backend.scanners.list_scanners` output if you prefer — see
the comment there.
"""

from __future__ import annotations

import hashlib
import random
from typing import Iterable

from .base import BaseScanner
from . import register

# The same broker list the frontend ships with, kept in sync.
BROKERS: list[tuple[str, str, str]] = [
    # (slug, name, homepage)
    ("spokeo", "Spokeo", "https://www.spokeo.com"),
    ("whitepages", "WhitePages", "https://www.whitepages.com"),
    ("beenverified", "BeenVerified", "https://www.beenverified.com"),
    ("intelius", "Intelius", "https://www.intelius.com"),
    ("peoplefinder", "PeopleFinder", "https://www.peoplefinder.com"),
    ("radaris", "Radaris", "https://radaris.com"),
    ("truthfinder", "TruthFinder", "https://www.truthfinder.com"),
    ("mylife", "MyLife", "https://www.mylife.com"),
    ("peoplelooker", "PeopleLooker", "https://www.peoplelooker.com"),
    ("instantcheckmate", "InstantCheckmate", "https://www.instantcheckmate.com"),
    ("publicrecordsnow", "PublicRecordsNow", "https://www.publicrecordsnow.com"),
    ("fastpeoplesearch", "FastPeopleSearch", "https://www.fastpeoplesearch.com"),
    ("ussearch", "USSearch", "https://www.ussearch.com"),
    ("peekyou", "PeekYou", "https://www.peekyou.com"),
    ("classmates", "ClassMates", "https://www.classmates.com"),
    ("acxiom", "Acxiom", "https://www.acxiom.com"),
    ("lexisnexis", "LexisNexis", "https://risk.lexisnexis.com"),
    ("epsilon", "Epsilon", "https://www.epsilon.com"),
    ("oracle-data-cloud", "Oracle Data Cloud", "https://www.oracle.com"),
    ("experian-marketing", "Experian Marketing", "https://www.experian.com"),
    ("peoplesmart", "PeopleSmart", "https://www.peoplesmart.com"),
    ("zabasearch", "ZabaSearch", "https://www.zabasearch.com"),
    ("privateeye", "PrivateEye", "https://www.privateeye.com"),
    ("pipl", "Pipl", "https://pipl.com"),
    ("searchpeoplefree", "SearchPeopleFREE", "https://www.searchpeoplefree.com"),
    ("backgroundreport360", "BackgroundReport360", "https://www.backgroundreport360.com"),
    ("infotracer", "InfoTracer", "https://www.infotracer.com"),
    ("peoplebyname", "PeopleByName", "https://www.peoplebyname.com"),
    ("usphonebook", "USPhoneBook", "https://www.usphonebook.com"),
    ("blockshopper", "BlockShopper", "https://blockshopper.com"),
    ("courtcasefinder", "CourtCaseFinder", "https://www.courtcasefinder.com"),
    ("nuwber", "Nuwber", "https://nuwber.com"),
    ("checkpeople", "CheckPeople", "https://www.checkpeople.com"),
    ("searchquarry", "SearchQuarry", "https://www.searchquarry.com"),
    ("411info", "411.info", "https://411.info"),
    ("anywho", "AnyWho", "https://www.anywho.com"),
    ("peopleconnect", "PeopleConnect", "https://peopleconnect.us"),
    ("familytreenow", "FamilyTreeNow", "https://www.familytreenow.com"),
    ("thatsthem", "ThatsThem", "https://thatsthem.com"),
    ("advancedbackgroundchecks", "AdvancedBackgroundChecks", "https://www.advancedbackgroundchecks.com"),
    ("cubib", "Cubib", "https://cubib.com"),
    ("yasni", "Yasni", "https://www.yasni.com"),
    ("publicdata", "PublicData", "https://publicdata.com"),
    ("opencorporates", "OpenCorporates", "https://opencorporates.com"),
]

POSSIBLE_FIELDS = [
    "Full name", "Home address", "Phone number", "Email",
    "Date of birth", "Relatives", "Property value", "Employer",
]


def _make_scanner_class(slug: str, display: str, homepage: str):
    """Build a MockScanner subclass for a single broker."""
    class _Mock(BaseScanner):
        # NB: prefixed slug so it doesn't clash with the real scanner.
        # If you want a unified report, drop the "mock-" prefix here.
        slug_ = f"mock-{slug}"
        name_ = display
        homepage_ = homepage

        # These would normally be class attrs — patched below.
        rate_limit_seconds = 0.0

        def search(self, identifiers: dict):
            # Deterministic hash so the same user always gets the same exposures.
            seed_src = f"{identifiers.get('email','')}|{identifiers.get('name','')}|{self.slug}"
            seed = int(hashlib.sha256(seed_src.encode()).hexdigest()[:8], 16)
            rnd = random.Random(seed)
            # ~75% of brokers list a typical user. Tweak as desired.
            if rnd.random() > 0.78:
                return []
            n_fields = rnd.randint(2, 5)
            fields = rnd.sample(POSSIBLE_FIELDS, n_fields)
            return [{
                "profile_url": f"{homepage}/p/{rnd.randrange(10**6, 10**8):x}",
                "exposed_fields": fields,
                "match_confidence": round(0.7 + rnd.random() * 0.3, 2),
            }]

        def submit_removal(self, exposure_row, identifiers):
            return {
                "status": "submitted",
                "reference": f"MOCK-{exposure_row['id']:08d}",
                "details": "Mock scanner: pretend opt-out request sent.",
            }

        def check_removal_status(self, exposure_row, reference):
            # Random walk: 30% chance of "removed" per check.
            return "removed" if random.random() < 0.3 else "pending"

    _Mock.slug = _Mock.slug_
    _Mock.name = _Mock.name_
    _Mock.homepage = _Mock.homepage_
    _Mock.removal_url = f"{homepage}/opt-out"
    _Mock.__name__ = f"Mock_{slug}"
    return _Mock


# Register one mock class per broker.
for slug, name, homepage in BROKERS:
    cls = _make_scanner_class(slug, name, homepage)
    register(cls)
