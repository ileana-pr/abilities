import csv
import re
from html import unescape
from typing import Optional

from .base import CivicSource

LIS_BASE = "https://lis.virginia.gov"
CSV_BASE = "https://lis.blob.core.windows.net/lisfiles"
TOPIC_QUERIES = ("housing", "education", "zoning")
MAX_BILLS = 8
REQUEST_TIMEOUT = 60
# 2026 regular, then special, then 2025 regular
SESSION_CANDIDATES = (
    (20261, "2026 Regular Session"),
    (20262, "2026 Special Session"),
    (20251, "2025 Regular Session"),
)


class VirginiaStateSource(CivicSource):
    def __init__(self, api_key: Optional[str] = None):
        super().__init__()
        self._api_key = api_key

    def set_api_key(self, api_key: Optional[str]) -> None:
        self._api_key = api_key

    def get_name(self) -> str:
        return "Virginia General Assembly"

    def get_source_url(self) -> str:
        return "https://lis.virginia.gov/"

    def _resolve_api_key(self) -> Optional[str]:
        if self._api_key:
            return self._api_key.strip() or None
        return None

    def _headers(self, api_key: str) -> dict:
        return {
            "WebAPIKey": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "OpenHome-TownHall/1.0",
        }

    async def _fetch_bills_csv(self, session_code: int) -> list[dict]:
        """public hourly CSV — no api key required. prefer a byte range for speed."""
        url = f"{CSV_BASE}/{session_code}/BILLS.CSV"
        # partial download keeps the voice session awake (full file is ~1.3MB)
        resp = await self._http_get(
            url,
            headers={"Accept": "text/csv", "Range": "bytes=0-250000"},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code >= 400 or not resp.text:
            # fall back to full file
            resp = await self._http_get(
                url, headers={"Accept": "text/csv"}, timeout=REQUEST_TIMEOUT
            )
        if resp.status_code >= 400 or not resp.text:
            return []
        text = resp.text
        # strip utf-8 bom if present
        if text.startswith("\ufeff"):
            text = text[1:]
        lines = text.splitlines()
        # drop a possibly truncated final line from Range responses
        if len(lines) > 2 and lines[-1].count('"') % 2 == 1:
            lines = lines[:-1]
        reader = csv.DictReader(lines)
        bills: list[dict] = []
        topic_hits = 0
        for row in reader:
            bill_id = (row.get("Bill_id") or row.get("Bill_ID") or "").strip()
            if not bill_id:
                continue
            failed = (row.get("Failed") or "").strip().upper()
            desc = (row.get("Bill_description") or row.get("Bill_Description") or "").strip()
            patron = (row.get("Patron_name") or row.get("Patron_Name") or "").strip()
            status = self._status_from_csv_row(row)
            bill = {
                "LegislationNumber": bill_id,
                "FullNumber": bill_id,
                "Description": desc,
                "LegislationTitle": desc,
                "LegislationStatus": status,
                "LegislationTypeCode": "B" if bill_id.upper().startswith(("HB", "SB")) else "",
                "Patrons": [{"Name": patron, "IsIntroducing": True}] if patron else [],
                "_failed": failed == "Y",
            }
            bills.append(bill)
            lower = desc.lower()
            if any(topic in lower for topic in TOPIC_QUERIES):
                topic_hits += 1
            # enough for a voice briefing — stop scanning early
            if topic_hits >= MAX_BILLS and len(bills) >= MAX_BILLS * 3:
                break
        return bills

    @staticmethod
    def _status_from_csv_row(row: dict) -> str:
        if (row.get("Approved") or "").strip().upper() == "Y":
            return "Approved"
        if (row.get("Vetoed") or "").strip().upper() == "Y":
            return "Vetoed"
        if (row.get("Passed") or "").strip().upper() == "Y":
            return "Passed"
        if (row.get("Failed") or "").strip().upper() == "Y":
            return "Failed"
        if (row.get("Carried_over") or "").strip().upper() == "Y":
            return "Carried Over"
        house = (row.get("Last_house_action") or "").strip()
        senate = (row.get("Last_senate_action") or "").strip()
        if house:
            return house
        if senate:
            return senate
        return "In progress"

    async def _fetch_via_api(self, api_key: str) -> tuple[str, list[dict]]:
        url = f"{LIS_BASE}/Session/api/getsessionlistasync"
        resp = await self._http_get(url, headers=self._headers(api_key), timeout=REQUEST_TIMEOUT)
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

    async def _fetch_via_csv(self) -> tuple[str, list[dict]]:
        for session_code, label in SESSION_CANDIDATES:
            bills = await self._fetch_bills_csv(session_code)
            if bills:
                return label, bills
        return "2026 Regular Session", []

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
        label = "2026 Regular Session"
        bills: list[dict] = []
        errors: list[str] = []

        # public CSV first — works without custom auth headers in the sandbox http helper
        try:
            label, bills = await self._fetch_via_csv()
        except Exception as e:
            errors.append(f"csv: {e}")

        # optional api enrichment if csv empty and key is present
        if not bills:
            api_key = self._resolve_api_key()
            if api_key:
                try:
                    label, bills = await self._fetch_via_api(api_key)
                except Exception as e:
                    errors.append(f"api: {e}")
            else:
                errors.append("api: no lis_api_key available to ability runtime")

        selected = self._select_bills(bills)
        lines = [f"### Virginia General Assembly ({label})"]
        if not selected:
            lines.append("- No matching legislation found for current focus topics.")
            if errors:
                lines.append(f"- Note: fetch issues ({'; '.join(errors)})")
            lines.append(f"- Source: {self.get_source_url()}")
            return "\n".join(lines)

        for bill in selected:
            lines.append(self._format_bill_line(bill))
        return "\n".join(lines)
