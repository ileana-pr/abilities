import re
from html import unescape
from typing import Optional

from .base import CivicSource

LIS_BASE = "https://lis.virginia.gov"
TOPIC_QUERIES = ("housing", "education", "zoning")
MAX_BILLS = 8
REQUEST_TIMEOUT = 60


class VirginiaStateSource(CivicSource):
    def get_name(self) -> str:
        return "Virginia General Assembly"

    def get_source_url(self) -> str:
        return "https://lis.virginia.gov/"

    def required_api_key_name(self) -> str:
        return "LIS_API_KEY"

    def _headers(self, api_key: str) -> dict:
        return {
            "WebAPIKey": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "OpenHome-TownHall/1.0",
        }

    async def _fetch_via_api(self, api_key: str) -> tuple[str, list[dict]]:
        url = f"{LIS_BASE}/Session/api/getsessionlistasync"
        resp = await self._http_get(url, headers=self._headers(api_key), timeout=REQUEST_TIMEOUT)
        if resp.status_code in (401, 403):
            raise RuntimeError(
                f"LIS API key rejected (HTTP {resp.status_code}) — verify LIS_API_KEY in Settings"
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"session list HTTP {resp.status_code}")
        data = resp.json() or {}
        sessions = data.get("Sessions") or []
        session_code, label = 20261, "2026 Regular Session"
        if sessions:
            def year_of(s: dict) -> int:
                code = str(s.get("SessionCode") or "0")
                return int(s.get("SessionYear") or code[:4] or 0)

            def is_regular(s: dict) -> bool:
                stype = str(s.get("SessionType") or "").lower()
                code = str(s.get("SessionCode") or "")
                return stype == "regular" or (code.endswith("1") and "special" not in stype)

            def rank(s: dict) -> tuple:
                return (
                    1 if (s.get("IsActive") and is_regular(s)) else 0,
                    1 if (s.get("IsDefault") and is_regular(s)) else 0,
                    1 if s.get("IsActive") else 0,
                    1 if s.get("IsDefault") else 0,
                    1 if is_regular(s) else 0,
                    year_of(s),
                )

            chosen = max(sessions, key=rank)
            code = str(chosen.get("SessionCode") or "20261")
            year = chosen.get("SessionYear") or code[:4]
            stype = chosen.get("SessionType") or "Regular"
            session_code = int(code)
            label = f"{year} {stype} Session"

        list_url = (
            f"{LIS_BASE}/Legislation/api/getlegislationsessionlistasync"
            f"?SessionCode={session_code}"
        )
        resp = await self._http_get(
            list_url, headers=self._headers(api_key), timeout=REQUEST_TIMEOUT
        )
        if resp.status_code == 204 or not resp.text:
            return label, []
        if resp.status_code >= 400:
            raise RuntimeError(f"legislation list HTTP {resp.status_code}")
        payload = resp.json() or {}
        bills = payload.get("Legislations") or payload.get("ListItems") or []
        return label, bills

    @staticmethod
    def _strip_html(text: str) -> str:
        if not text:
            return ""
        cleaned = re.sub(r"<[^>]+>", " ", text)
        cleaned = unescape(cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()

    @staticmethod
    def _bill_number(bill: dict) -> str:
        return (
            bill.get("FullNumber")
            or bill.get("LegislationNumber")
            or f"ID {bill.get('LegislationID', '?')}"
        )

    @staticmethod
    def _bill_description(bill: dict) -> str:
        desc = bill.get("Description") or bill.get("LegislationTitle") or ""
        if not desc:
            desc = VirginiaStateSource._strip_html(bill.get("LegislationSummary") or "")
        desc = desc.strip()
        if len(desc) > 160:
            desc = desc[:157].rstrip() + "..."
        return desc

    @staticmethod
    def _search_text(bill: dict) -> str:
        parts = [
            bill.get("Description") or "",
            bill.get("LegislationTitle") or "",
            VirginiaStateSource._strip_html(bill.get("LegislationSummary") or ""),
        ]
        return " ".join(parts).lower()

    @staticmethod
    def _is_bill(bill: dict) -> bool:
        type_code = (bill.get("LegislationTypeCode") or "").upper()
        number = VirginiaStateSource._bill_number(bill).upper()
        if type_code == "B" or number.startswith(("HB", "SB")):
            return True
        return False

    @staticmethod
    def _patron_name(bill: dict) -> str:
        patrons = bill.get("Patrons") or []

        def clean(p: dict) -> str:
            for field in ("Name", "MemberDisplayName", "PatronDisplayName", "DisplayName"):
                val = (p.get(field) or "").strip()
                if val and val.lower() not in ("chief patron", "(chief patron)"):
                    return val
            return ""

        for p in patrons:
            if p.get("IsIntroducing"):
                name = clean(p)
                if name:
                    return name
        for p in patrons:
            name = clean(p)
            if name:
                return name
        return ""

    @staticmethod
    def _bill_url(bill: dict) -> str:
        lid = bill.get("LegislationID")
        if lid:
            return f"https://lis.virginia.gov/bill-details/{lid}"
        num = VirginiaStateSource._bill_number(bill)
        return f"https://lis.virginia.gov/?bill={num}"

    def _format_bill_line(self, bill: dict) -> str:
        number = self._bill_number(bill)
        desc = self._bill_description(bill)
        status = bill.get("LegislationStatus") or "Unknown"
        patron = self._patron_name(bill)
        meta = f"Status: {status}"
        if patron:
            meta += f" | Patron: {patron}"
        return f"- **{number}** — {desc} | {meta}\n  - {self._bill_url(bill)}"

    def _select_bills(self, bills: list[dict]) -> list[dict]:
        topic_hits: list[dict] = []
        other_bills: list[dict] = []
        seen: set[str] = set()

        for bill in bills:
            if bill.get("_failed"):
                continue
            status = (bill.get("LegislationStatus") or "").lower()
            if "fail" in status:
                continue
            key = str(bill.get("LegislationID") or self._bill_number(bill))
            if key in seen:
                continue
            seen.add(key)
            text = self._search_text(bill)
            if any(topic in text for topic in TOPIC_QUERIES):
                topic_hits.append(bill)
            elif self._is_bill(bill):
                other_bills.append(bill)

        selected = topic_hits[:MAX_BILLS]
        if len(selected) < MAX_BILLS:
            selected.extend(other_bills[: MAX_BILLS - len(selected)])
        return selected

    async def fetch_updates(self) -> str:
        api_key = self._api_key
        if not api_key:
            return (
                "### Virginia General Assembly\n"
                "- Error: LIS_API_KEY not set. "
                "Add a third-party key named 'LIS_API_KEY' in Settings → Third-Party Keys."
            )

        try:
            label, bills = await self._fetch_via_api(api_key)
        except Exception as e:
            return (
                f"### Virginia General Assembly\n"
                f"- Error fetching legislation from LIS API: {e}"
            )

        selected = self._select_bills(bills)
        lines = [f"### Virginia General Assembly ({label})"]
        if not selected:
            lines.append("- No matching legislation found for current focus topics.")
            lines.append(f"- Source: {self.get_source_url()}")
            return "\n".join(lines)

        for bill in selected:
            lines.append(self._format_bill_line(bill))
        return "\n".join(lines)
