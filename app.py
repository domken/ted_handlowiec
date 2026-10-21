#!/usr/bin/env python3
"""Lokalna aplikacja TED dla handlowca. Tylko Python standard library."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
import html
import io
import json
import os
import re
import shutil
import socket
import sqlite3
import sys
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

API_URL = "https://api.ted.europa.eu/v3/notices/search"
TED_XML_URL = "https://ted.europa.eu/en/notice/{}/xml"
APP_NAME = "TED Handlowiec"
USER_AGENT = "TED-Handlowiec-Prototype/0.1"
FIELDS = [
    "publication-number", "publication-date", "notice-type", "notice-title",
    "description-proc", "buyer-name", "buyer-country", "classification-cpv",
    "place-of-performance", "deadline-receipt-tender-date-lot",
    "deadline-receipt-request-date-lot", "deadline-receipt-expressions-date-lot",
    "estimated-value-proc", "estimated-value-cur-proc", "contract-nature",
    "procedure-type", "form-type", "links",
]


def data_dir() -> Path:
    override = os.environ.get("TED_HANDLOWIEC_DATA")
    if override:
        path = Path(override).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path
    if sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    elif os.name == "nt":
        path = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
    else:
        path = Path.home() / ".local" / "share" / "ted-handlowiec"
    path.mkdir(parents=True, exist_ok=True)
    return path


DB_PATH = data_dir() / "handlowiec.sqlite3"


def connect_db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""CREATE TABLE IF NOT EXISTS notices (
        number TEXT PRIMARY KEY, data TEXT NOT NULL, selected INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'Nowe', note TEXT NOT NULL DEFAULT '',
        updated TEXT NOT NULL)""")
    con.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    return con


def output_folder() -> str:
    with connect_db() as con:
        row = con.execute("SELECT value FROM app_settings WHERE key='output_folder'").fetchone()
    return row["value"] if row else ""


def choose_output_folder() -> str | None:
    """Otwiera systemowy wybór folderu bez zależności od tkinter."""
    if sys.platform == "darwin":
        result = subprocess.run(
            ["osascript", "-e", 'POSIX path of (choose folder with prompt "Wybierz folder na metryczki TED")'],
            capture_output=True, text=True, check=False)
        if result.returncode:
            # Anulowanie okna wyboru również kończy osascript kodem != 0.
            return None
        return result.stdout.strip().rstrip("/") or "/"
    if os.name == "nt":
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$d=New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$d.Description='Wybierz folder na metryczki TED'; "
            "if($d.ShowDialog() -eq 'OK'){Write-Output $d.SelectedPath}"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", script],
            capture_output=True, text=True, check=False)
        if result.returncode:
            raise RuntimeError("Nie udało się otworzyć wyboru folderu w Windows.")
        return result.stdout.strip() or None
    picker = next((shutil.which(name) for name in ("zenity", "kdialog") if shutil.which(name)), None)
    if picker == "zenity":
        result = subprocess.run([picker, "--file-selection", "--directory", "--title=Wybierz folder na metryczki TED"], capture_output=True, text=True)
        return result.stdout.strip() or None
    if picker == "kdialog":
        result = subprocess.run([picker, "--getexistingdirectory", os.getcwd(), "Wybierz folder na metryczki TED"], capture_output=True, text=True)
        return result.stdout.strip() or None
    raise RuntimeError("W tym systemie nie znaleziono systemowego okna wyboru folderu.")


def text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def lname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def direct(el: ET.Element | None, name: str) -> ET.Element | None:
    if el is None:
        return None
    return next((c for c in list(el) if lname(c.tag) == name), None)


def descendants(el: ET.Element | None, name: str) -> list[ET.Element]:
    return [x for x in el.iter() if lname(x.tag) == name] if el is not None else []


def values(el: ET.Element | None, name: str) -> list[str]:
    return [text(x) for x in descendants(el, name) if text(x)]


def uniq(values_: list[str]) -> list[str]:
    return list(dict.fromkeys(x for x in values_ if x))


def scalar(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(x) for x in value if x)
    if isinstance(value, dict):
        return ", ".join(str(x) for x in value.values() if x)
    return "" if value is None else str(value)


def lang(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(map(str, value))
    if isinstance(value, dict):
        for key in ("pol", "eng"):
            if value.get(key):
                v = value[key]
                return "\n".join(map(str, v)) if isinstance(v, list) else str(v)
        v = next((x for x in value.values() if x), "")
        return "\n".join(map(str, v)) if isinstance(v, list) else str(v)
    return ""


def norm_notice(item: dict[str, Any]) -> dict[str, Any]:
    number = scalar(item.get("publication-number"))
    cpv_raw = item.get("classification-cpv", [])
    if not isinstance(cpv_raw, list):
        cpv_raw = [cpv_raw]
    links = item.get("links") if isinstance(item.get("links"), dict) else {}
    xml_url = ""
    for key, value in links.items():
        if str(key).lower() == "xml" and isinstance(value, str):
            xml_url = value
        if isinstance(value, dict):
            for fmt, link in value.items():
                if str(fmt).lower() == "xml" and isinstance(link, str):
                    xml_url = link
    if not xml_url and re.fullmatch(r"\d+-\d{4}", number):
        xml_url = TED_XML_URL.format(number)
    return {
        "number": number,
        "publication_date": scalar(item.get("publication-date"))[:10],
        "notice_type": scalar(item.get("notice-type")),
        "title": lang(item.get("notice-title")),
        "description": lang(item.get("description-proc")),
        "buyer": lang(item.get("buyer-name")),
        "buyer_country": scalar(item.get("buyer-country")),
        "cpv": ", ".join(uniq([scalar(x) for x in cpv_raw])),
        "place": scalar(item.get("place-of-performance")),
        "deadline": scalar(item.get("deadline-receipt-tender-date-lot") or item.get("deadline-receipt-request-date-lot") or item.get("deadline-receipt-expressions-date-lot")),
        "value": scalar(item.get("estimated-value-proc")),
        "currency": scalar(item.get("estimated-value-cur-proc")),
        "contract_nature": scalar(item.get("contract-nature")),
        "procedure_type": scalar(item.get("procedure-type")),
        "form_type": scalar(item.get("form-type")),
        "xml_url": xml_url,
        "ted_url": "https://ted.europa.eu/en/notice/-/detail/" + number,
    }


def results_from(data: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("notices", "results", "documents"):
        if isinstance(data.get(key), list):
            return [x for x in data[key] if isinstance(x, dict)]
    return []


def do_search(params: dict[str, Any]) -> dict[str, Any]:
    clauses: list[str] = []
    phrase = re.sub(r"\s+", " ", str(params.get("search_text", "")).strip())
    if phrase:
        if len(phrase) > 500:
            raise ValueError("Fraza wyszukiwania może mieć maksymalnie 500 znaków.")
        clauses.append('FT~"' + phrase.replace('\\', '\\\\').replace('"', '\\"') + '"')

    cpv_raw = str(params.get("cpv", "72*, 48*")).strip()
    if cpv_raw:
        cpv_codes = [part.strip() for part in re.split(r"[,;\s]+", cpv_raw) if part.strip()]
        if any(not re.fullmatch(r"\d{2,8}\*?", code) for code in cpv_codes):
            raise ValueError("Kody CPV wpisz jako 2–8 cyfr, opcjonalnie z * (np. 72*, 48*, 7226*). Oddziel kilka kodów przecinkiem.")
        cpv_codes = uniq(cpv_codes)
        cpv_clauses = ["classification-cpv=" + code for code in cpv_codes]
        clauses.append(cpv_clauses[0] if len(cpv_clauses) == 1 else "(" + " OR ".join(cpv_clauses) + ")")

    def country_clause(field: str, raw_value: Any) -> None:
        tokens = re.findall(r"[A-Za-z]{2,3}", str(raw_value or "").upper())
        if str(raw_value or "").strip() and not tokens:
            raise ValueError("Wybierz poprawny kod kraju.")
        if any(len(code) != 3 and code != "EU" for code in tokens):
            raise ValueError("Kody krajów wpisuj jako ISO-3 (np. POL); dozwolone jest też EU.")
        if tokens:
            unique = uniq(tokens)
            clauses.append(field + " IN (" + " ".join(unique) + ")" if len(unique) > 1 else field + "=" + unique[0])

    country_clause("buyer-country", params.get("buyer_country"))
    country_clause("place-of-performance", params.get("place_country"))

    type_filter = str(params.get("notice_types", "all"))
    type_map = {
        "tenders": "cn-standard cn-social cn-desg",
        "awards": "can-standard can-social can-desg",
    }
    if type_filter in type_map:
        clauses.append("notice-type IN (" + type_map[type_filter] + ")")
    elif type_filter != "all":
        raise ValueError("Nieznany rodzaj ogłoszenia.")

    start_raw = str(params.get("date_from", "")).strip()
    end_raw = str(params.get("date_to", "")).strip()
    start = dt.date.fromisoformat(start_raw) if start_raw else None
    end = dt.date.fromisoformat(end_raw) if end_raw else None
    if start and end and start > end:
        raise ValueError("Data początkowa nie może być późniejsza niż końcowa.")
    if start:
        clauses.append("publication-date>=" + start.strftime("%Y%m%d"))
    if end:
        clauses.append("publication-date<=" + end.strftime("%Y%m%d"))

    sort_field = str(params.get("sort_field", "publication-number"))
    sort_order = str(params.get("sort_order", "DESC")).upper()
    allowed_sorts = {"publication-number", "publication-date", "deadline-receipt-tender-date-lot", "estimated-value-proc"}
    if sort_field not in allowed_sorts or sort_order not in ("ASC", "DESC"):
        raise ValueError("Niepoprawne sortowanie.")
    scope = str(params.get("scope", "LATEST")).upper()
    if scope not in ("LATEST", "ACTIVE", "ALL"):
        raise ValueError("Nieznany zakres wyszukiwania.")
    try:
        limit = max(10, min(250, int(params.get("limit", 100))))
        page = max(1, min(1000, int(params.get("page", 1))))
    except (TypeError, ValueError) as exc:
        raise ValueError("Niepoprawny numer strony lub liczba wyników.") from exc
    latest_versions = bool(params.get("only_latest_versions", False))
    payload = {"query": " AND ".join(clauses), "fields": FIELDS, "limit": limit, "page": page,
               "scope": scope, "onlyLatestVersions": latest_versions,
               "sortColumn": sort_field, "sortOrder": sort_order,
               "paginationMode": "PAGE_NUMBER"}
    request = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        raise RuntimeError("TED API HTTP " + str(exc.code) + ": " + detail) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Brak połączenia z TED API. Sprawdź internet i spróbuj ponownie.") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("TED API zwróciło nieoczekiwaną odpowiedź.") from exc
    notices = [norm_notice(x) for x in results_from(data)]
    notices = [x for x in notices if x["number"] and x["title"]]
    now = dt.datetime.now().isoformat(timespec="seconds")
    with connect_db() as con:
        for item in notices:
            con.execute("""INSERT INTO notices(number,data,updated) VALUES(?,?,?)
            ON CONFLICT(number) DO UPDATE SET data=excluded.data,updated=excluded.updated""",
                        (item["number"], json.dumps(item, ensure_ascii=False), now))
        for item in notices:
            saved = con.execute("SELECT selected,status,note FROM notices WHERE number=?", (item["number"],)).fetchone()
            item.update({"selected": bool(saved["selected"]), "status": saved["status"], "note": saved["note"]})
    return {"total": data.get("total", len(notices)), "notices": notices, "page": page, "limit": limit}


def fetch_xml(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/xml,text/xml,*/*"})
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            content = response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError("Nie udało się pobrać XML z TED (HTTP " + str(exc.code) + ").") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Nie można połączyć się z TED. Sprawdź internet.") from exc
    if not content.strip() or content.lstrip().lower().startswith((b"<!doctype html", b"<html")):
        raise RuntimeError("TED zwróciło stronę HTML zamiast XML.")
    return content


def parse_xml(raw: bytes, number: str, api: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("Plik ogłoszenia nie jest poprawnym XML-em.") from exc

    project = direct(root, "ProcurementProject")
    tendering = direct(root, "TenderingProcess")
    terms = direct(root, "TenderingTerms")
    party = direct(direct(root, "ContractingParty"), "Party")
    buyer_id = text(direct(direct(party, "PartyIdentification"), "ID"))
    buyer = ""
    buyer_orgs: dict[str, str] = {}
    address: dict[str, str] = {"ulica": "", "miasto": "", "kod": "", "kraj": ""}
    contact: dict[str, str] = {"osoba": "", "email": "", "telefon": "", "strona": ""}
    for org in descendants(root, "Organization"):
        company = direct(org, "Company")
        ident = text(direct(direct(company, "PartyIdentification"), "ID"))
        names = values(direct(company, "PartyName"), "Name")
        if ident and names:
            buyer_orgs[ident] = names[0]
        if ident != buyer_id:
            continue
        buyer = names[0] if names else ""
        addr = direct(company, "PostalAddress")
        address = {
            "ulica": text(direct(addr, "StreetName")),
            "miasto": text(direct(addr, "CityName")),
            "kod": text(direct(addr, "PostalZone")),
            "kraj": next(iter(values(addr, "IdentificationCode")), ""),
        }
        c = direct(company, "Contact")
        contact = {"osoba": text(direct(c, "Name")), "email": text(direct(c, "ElectronicMail")),
                   "telefon": text(direct(c, "Telephone")),
                   "strona": next(iter(values(company, "WebsiteURI")), "")}

    def cpv_codes(procurement: ET.Element | None) -> tuple[str, str]:
        if procurement is None:
            return "", ""
        main: list[str] = []
        additional: list[str] = []
        for child in list(procurement):
            tag = lname(child.tag)
            if tag == "MainCommodityClassification":
                main.extend(values(child, "ItemClassificationCode"))
            elif tag == "AdditionalCommodityClassification":
                additional.extend(values(child, "ItemClassificationCode"))
        main, additional = uniq(main), uniq(additional)
        if not main and not additional:
            fallback = uniq(values(procurement, "ItemClassificationCode"))
            main, additional = fallback[:1], fallback[1:]
        return ", ".join(main), ", ".join(additional)

    def place_data(procurement: ET.Element | None) -> tuple[str, str]:
        if procurement is None:
            return "", ""
        places: list[str] = []
        nuts = uniq(values(procurement, "CountrySubentityCode"))
        for location in descendants(procurement, "RealizedLocation"):
            loc_address = direct(location, "Address")
            city = text(direct(loc_address, "CityName"))
            country = text(direct(loc_address, "Country"))
            country_name = text(direct(country, "Name"))
            if city:
                places.append(", ".join(x for x in (city, country_name) if x))
        return "; ".join(uniq(places)), ", ".join(nuts)

    main_cpv, other_cpv = cpv_codes(project)
    place, nuts = place_data(project)
    lots = []
    lot_elements = [x for x in list(root) if lname(x.tag) == "ProcurementProjectLot"]
    for lot in [x for x in list(root) if lname(x.tag) == "ProcurementProjectLot"]:
        p = direct(lot, "ProcurementProject")
        lot_main_cpv, lot_other_cpv = cpv_codes(p)
        lot_place, lot_nuts = place_data(p)
        tendering = direct(lot, "TenderingProcess")
        dates = values(tendering, "EndDate")
        times = values(tendering, "EndTime")
        amount = next(iter(descendants(p, "EstimatedOverallContractAmount")), None)
        funding = uniq(values(p, "FundingProgramCode"))
        lots.append({
            "id": text(direct(lot, "ID")), "title": text(direct(p, "Name")),
            "description": text(direct(p, "Description")),
            "deadline": dates[0] if dates else "", "time": times[0] if times else "",
            "value": text(amount), "currency": amount.attrib.get("currencyID", "") if amount is not None else "",
            "main_cpv": lot_main_cpv, "other_cpv": lot_other_cpv,
            "cpv": ", ".join(uniq([x for x in (lot_main_cpv, lot_other_cpv) if x])),
            "place": lot_place or place, "nuts": lot_nuts or nuts,
            "funding": ", ".join(funding),
        })
    amount = next(iter(descendants(project, "EstimatedOverallContractAmount")), None)
    deadlines = [x["deadline"] for x in lots if x["deadline"]]
    deadline_times = [lot["time"] for lot in lots if lot.get("time")]
    publication = direct(root, "Publication")
    publication_date = text(direct(publication, "PublicationDate")) or text(direct(root, "IssueDate"))
    planned = direct(project, "PlannedPeriod")
    duration_measure = next(iter(descendants(planned, "DurationMeasure")), None)
    duration = text(duration_measure)
    if duration and duration_measure is not None and duration_measure.attrib.get("unitCode"):
        duration += " " + duration_measure.attrib["unitCode"]
    funds = uniq(values(project, "FundingProgramCode") + [x for lot in lots for x in lot.get("funding", "").split(", ")])
    criteria: list[dict[str, str]] = []
    awards: list[dict[str, str]] = []
    for lot_element, lot_data in zip(lot_elements, lots):
        criterion_number = 0
        # W eForms kryteria są zwykle węzłem nadrzędnym AwardingCriterion,
        # a właściwe pola (nazwa, typ, opis i waga) należą do jego dzieci.
        # Preferuj więc węzły podrzędne, aby nie tworzyć pustego duplikatu.
        criterion_elements = descendants(lot_element, "SubordinateAwardingCriterion")
        if not criterion_elements:
            criterion_elements = descendants(lot_element, "AwardingCriterion")
        for criterion in criterion_elements:
            criterion_number += 1
            criterion_type = text(direct(criterion, "AwardingCriterionTypeCode"))
            criterion_name = text(direct(criterion, "Name"))
            criterion_description = text(direct(criterion, "Description"))
            numeric = next(iter(values(criterion, "ParameterNumeric")), "")
            unit = next(iter(values(criterion, "ParameterCode")), "")
            is_weight = unit == "per-exa"
            criteria.append({
                "lot_id": lot_data["id"], "type": criterion_type,
                "name": criterion_name, "description": criterion_description,
                "weight": numeric if is_weight else "", "unit": unit,
                "value": "" if is_weight else numeric, "order": str(criterion_number),
            })

        lot_result_codes = values(lot_element, "TenderResultCode")
        tender_count = ""
        for statistic in descendants(lot_element, "ReceivedSubmissionsStatistics"):
            stat_code = direct(statistic, "StatisticsCode")
            if text(stat_code) == "tenders":
                tender_count = text(direct(statistic, "StatisticsNumeric"))
                break
        settled = descendants(lot_element, "SettledContract")
        for contract in settled:
            signatory = direct(contract, "SignatoryParty")
            org_id = text(direct(direct(signatory, "PartyIdentification"), "ID"))
            contract_ref = text(direct(direct(contract, "ContractReference"), "ID"))
            contract_amount = next((e for name in ("PayableAmount", "TotalAmount") for e in descendants(contract, name)), None)
            awards.append({
                "lot_id": lot_data["id"], "status": next(iter(lot_result_codes), ""),
                "date": text(direct(contract, "AwardDate")),
                "supplier": buyer_orgs.get(org_id, ""), "supplier_id": org_id,
                "contract": contract_ref,
                "value": text(contract_amount),
                "currency": contract_amount.attrib.get("currencyID", "") if contract_amount is not None else "",
                "offers": tender_count,
            })
        if not settled and (lot_result_codes or tender_count):
            awards.append({
                "lot_id": lot_data["id"], "status": next(iter(lot_result_codes), ""),
                "date": "", "supplier": "", "supplier_id": "", "contract": "",
                "value": "", "currency": "", "offers": tender_count,
            })

    main_project_cpv, other_project_cpv = main_cpv, other_cpv
    if not main_project_cpv and lots:
        main_project_cpv = uniq([lot.get("main_cpv", "") for lot in lots if lot.get("main_cpv")])[:1]
        main_project_cpv = ", ".join(main_project_cpv)
    if not other_project_cpv and lots:
        other_project_cpv = ", ".join(uniq([lot.get("other_cpv", "") for lot in lots if lot.get("other_cpv")]))
    system = ", ".join(uniq(values(tendering, "ContractingSystemTypeCode")))
    submission = ", ".join(uniq(values(terms, "SubmissionMethodCode")))
    start_dates = uniq(values(planned, "StartDate"))
    end_dates = uniq(values(planned, "EndDate"))
    return {
        "number": number, "notice_family": "Ogłoszenie o udzieleniu" if lname(root.tag) == "ContractAwardNotice" else "Ogłoszenie o zamówieniu",
        "contract_folder_id": text(direct(root, "ContractFolderID")),
        "publication_date": publication_date,
        "notice_type": text(direct(root, "NoticeTypeCode")),
        "title": text(direct(project, "Name")) or (api or {}).get("title", ""),
        "buyer": buyer or (api or {}).get("buyer", ""),
        "buyer_id": buyer_id, "buyer_country": address.get("kraj", ""),
        "address": address, "contact": contact, "buyer_orgs": buyer_orgs,
        "procedure": ", ".join(uniq(values(tendering, "ProcedureCode"))),
        "contract_type": ", ".join(uniq(values(project, "ProcurementTypeCode"))),
        "main_cpv": main_project_cpv, "other_cpv": other_project_cpv,
        "cpv": ", ".join(uniq([x for x in (main_project_cpv, other_project_cpv) if x])),
        "place": place, "nuts": nuts,
        "deadline": min(deadlines) if deadlines else (api or {}).get("deadline", ""),
        "deadline_time": deadline_times[0] if deadline_times else "",
        "estimated_value": text(amount) or (api or {}).get("value", ""),
        "currency": amount.attrib.get("currencyID", "") if amount is not None else (api or {}).get("currency", ""),
        "description": text(direct(project, "Description")) or (api or {}).get("description", ""),
        "start_date": start_dates[0] if start_dates else "", "end_date": end_dates[0] if end_dates else "",
        "duration": duration, "funding": ", ".join(funds),
        "submission_method": submission, "contracting_system": system,
        "lots": lots, "criteria": criteria, "awards": awards,
        "source_url": TED_XML_URL.format(number),
        "ted_url": "https://ted.europa.eu/en/notice/-/detail/" + number,
    }


def column(n: int) -> str:
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def make_xlsx(notice: dict[str, Any]) -> bytes:
    """Wypełnia firmowy, pusty skoroszyt danymi jednego ogłoszenia TED."""
    template = Path(__file__).with_name("ogloszenia_TED_uslugi_IT_szablon.xlsx")
    if not template.is_file():
        raise RuntimeError("Brakuje szablonu metryczki obok aplikacji: " + template.name)

    xml_url = notice.get("source_url") or TED_XML_URL.format(notice.get("number", ""))
    address = notice.get("address") if isinstance(notice.get("address"), dict) else {}
    lots = notice.get("lots", []) if isinstance(notice.get("lots"), list) else []
    main_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    q = "{" + main_ns + "}"
    ET.register_namespace("x", main_ns)

    def date_serial(value: Any) -> int | None:
        raw = "" if value is None else str(value)
        if not re.match(r"^\d{4}-\d{2}-\d{2}", raw):
            return None
        try:
            return (dt.date.fromisoformat(raw[:10]) - dt.date(1899, 12, 30)).days
        except ValueError:
            return None

    def number_text(value: Any) -> str | None:
        if value is None or not str(value).strip():
            return None
        try:
            return format(Decimal(str(value).strip().replace(" ", "").replace(",", ".")), "f")
        except InvalidOperation:
            return None

    def col_index(ref: str) -> int:
        match = re.match(r"[A-Z]+", ref)
        if not match:
            raise ValueError("Niepoprawny adres komórki w szablonie: " + ref)
        result = 0
        for char in match.group(0):
            result = result * 26 + ord(char) - 64
        return result

    def write_cell(cell: ET.Element, value: Any, kind: str) -> None:
        for child in list(cell):
            cell.remove(child)
        if value is None or value == "":
            cell.attrib.pop("t", None)
            return
        numeric: str | int | None = None
        if kind == "date":
            numeric = date_serial(value)
        elif kind == "number":
            numeric = number_text(value)
        if numeric is not None:
            cell.set("t", "n")
            ET.SubElement(cell, q + "v").text = str(numeric)
            return
        cell.set("t", "inlineStr")
        inline = ET.SubElement(cell, q + "is")
        text_node = ET.SubElement(inline, q + "t")
        raw = "" if value is None else str(value)
        raw = "".join(ch for ch in raw if ch in "\t\n\r" or ord(ch) >= 32)
        if raw != raw.strip():
            text_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        text_node.text = raw

    def fill_sheet(raw: bytes, entries: list[dict[str, Any]]) -> bytes:
        root = ET.fromstring(raw)
        sheet_data = root.find(q + "sheetData")
        if sheet_data is None:
            raise ValueError("Szablon nie zawiera arkusza danych.")
        header_row = next((row for row in sheet_data.findall(q + "row") if row.get("r") == "4"), None)
        if header_row is None:
            raise ValueError("W szablonie nie znaleziono wiersza nagłówków.")
        columns = {}
        for cell in header_row.findall(q + "c"):
            v = cell.find(q + "v")
            if v is not None and v.text:
                columns[v.text] = col_index(cell.get("r", ""))
        data_rows = {int(row.get("r", "0")): row for row in sheet_data.findall(q + "row")}
        for offset, entry in enumerate(entries):
            row_number = 5 + offset
            row = data_rows.get(row_number)
            if row is None:
                raise ValueError("Ogłoszenie ma więcej danych niż przygotowano w szablonie.")
            cells = {col_index(cell.get("r", "")): cell for cell in row.findall(q + "c")}
            for header, value in entry.items():
                col = columns.get(header)
                if col is None:
                    continue
                cell = cells.get(col)
                if cell is None:
                    raise ValueError("Brakuje komórki " + column(col) + str(row_number) + " w szablonie.")
                date_headers = {"Data publikacji TED", "Termin składania", "Data rozpoczęcia", "Data zakończenia", "Data udzielenia"}
                number_headers = {"Wartość szacunkowa", "Wartość umowy", "Liczba części", "Waga (%)", "Kolejność", "Liczba otrzymanych ofert", "Liczba ofert dopuszczonych"}
                kind = "date" if header in date_headers else "number" if header in number_headers else "text"
                write_cell(cell, value, kind)
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def joined(*values_: Any) -> str:
        return "; ".join(str(value).strip() for value in values_ if value is not None and str(value).strip())

    list_entry = {
        "Nr TED": notice.get("number"),
        "Rodzaj ogłoszenia": joined(notice.get("notice_family"), notice.get("notice_type")),
        "Data publikacji TED": notice.get("publication_date"),
        "Termin składania": notice.get("deadline"),
        "Zamawiający": notice.get("buyer"), "Tytuł ogłoszenia": notice.get("title"),
        "Rodzaj zamówienia": notice.get("contract_type"), "Kody CPV": notice.get("cpv"),
        "Miejsce realizacji / NUTS": joined(notice.get("place"), notice.get("nuts")),
        "Wartość szacunkowa": notice.get("estimated_value"), "Waluta": notice.get("currency"),
        "Liczba części": len(lots), "Link do TED": notice.get("ted_url"), "Link do XML": xml_url,
        "Status handlowca": notice.get("status", ""), "Notatka handlowca": notice.get("note", ""),
    }
    proceeding_entry = {
        "Nr TED": notice.get("number"), "ID postępowania": notice.get("contract_folder_id"),
        "Tytuł": notice.get("title"), "Pełny opis zamówienia": notice.get("description"),
        "Tryb postępowania": notice.get("procedure"), "Rodzaj zamówienia": notice.get("contract_type"),
        "Główny CPV": notice.get("main_cpv"), "Dodatkowe CPV": notice.get("other_cpv"),
        "Miejsce realizacji / NUTS": joined(notice.get("place"), notice.get("nuts")),
        "Data rozpoczęcia": notice.get("start_date"), "Data zakończenia": notice.get("end_date"),
        "Okres realizacji": notice.get("duration"), "Finansowanie UE / program": notice.get("funding"),
        "Sposób składania ofert": notice.get("submission_method"),
        "System zamówień": notice.get("contracting_system"), "Link do XML": xml_url,
    }
    buyer_entry = {
        "Nr TED": notice.get("number"), "Nazwa zamawiającego": notice.get("buyer"),
        "ID zamawiającego": notice.get("buyer_id"), "Ulica": address.get("ulica"),
        "Kod pocztowy": address.get("kod"), "Miasto": address.get("miasto"),
        "Kraj": address.get("kraj"), "Osoba kontaktowa": notice.get("contact", {}).get("osoba"),
        "E-mail": notice.get("contact", {}).get("email"), "Telefon": notice.get("contact", {}).get("telefon"),
        "Strona internetowa": notice.get("contact", {}).get("strona"),
    }
    lot_entries = [{
        "Nr TED": notice.get("number"), "ID części": lot.get("id"),
        "Nazwa części": lot.get("title"), "Opis części": lot.get("description"),
        "Główny CPV": lot.get("main_cpv"), "Dodatkowe CPV": lot.get("other_cpv"),
        "Miejsce realizacji": lot.get("place"), "NUTS": lot.get("nuts"),
        "Termin składania": lot.get("deadline"), "Godzina składania": lot.get("time"),
        "Wartość szacunkowa": lot.get("value"), "Waluta": lot.get("currency"),
        "Finansowanie UE / program": lot.get("funding"),
    } for lot in lots]
    criteria_entries = [{
        "Nr TED": notice.get("number"), "ID części": criterion.get("lot_id"),
        "Typ kryterium": criterion.get("type"), "Nazwa kryterium": criterion.get("name"),
        "Opis / sposób oceny": criterion.get("description"), "Waga (%)": criterion.get("weight"),
        "Jednostka parametru": criterion.get("unit"), "Wartość / próg": criterion.get("value"),
        "Kolejność": criterion.get("order"),
    } for criterion in notice.get("criteria", [])]
    award_entries = [{
        "Nr TED": notice.get("number"), "ID części": award.get("lot_id"),
        "Status wyniku": award.get("status"), "Data udzielenia": award.get("date"),
        "Wybrany wykonawca": award.get("supplier"), "ID wykonawcy": award.get("supplier_id"),
        "Numer umowy": award.get("contract"), "Wartość umowy": award.get("value"),
        "Waluta": award.get("currency"), "Liczba otrzymanych ofert": award.get("offers"),
        "Liczba ofert dopuszczonych": award.get("eligible_offers"), "Link do TED": notice.get("ted_url"),
    } for award in notice.get("awards", [])]
    replacements = {
        "xl/worksheets/sheet1.xml": [list_entry],
        "xl/worksheets/sheet2.xml": [proceeding_entry],
        "xl/worksheets/sheet3.xml": [buyer_entry],
        "xl/worksheets/sheet4.xml": lot_entries,
        "xl/worksheets/sheet5.xml": criteria_entries,
        "xl/worksheets/sheet6.xml": award_entries,
    }
    output = io.BytesIO()
    with zipfile.ZipFile(template, "r") as source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            raw = source.read(item.filename)
            if item.filename in replacements:
                raw = fill_sheet(raw, replacements[item.filename])
            target.writestr(item, raw)
    return output.getvalue()


PAGE = r'''<!doctype html>
<html lang="pl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TED — szanse handlowe</title><style>
:root{--navy:#193b64;--blue:#1769aa;--blue2:#eaf3fb;--line:#d9e1e8;--bg:#f3f6f8;--ink:#192632;--muted:#687785;--green:#26764d;--orange:#fff2d7}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{height:68px;background:#fff;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 max(22px,calc((100vw - 1420px)/2))}
h1{font-size:21px;margin:0;color:var(--navy)}h2{font-size:18px;margin:0;color:var(--navy)}h3{font-size:14px;margin:18px 0 9px;color:var(--navy)}.brandline{display:flex;align-items:center;gap:12px}.logo{font-size:12px;font-weight:800;letter-spacing:.08em;color:var(--blue);border:2px solid var(--blue);padding:5px 7px;border-radius:4px}.hint,.muted{color:var(--muted);font-size:12px}.hint{margin-top:3px}
.layout{max-width:1420px;margin:20px auto;padding:0 18px;display:grid;grid-template-columns:310px minmax(0,1fr);gap:18px;align-items:start}.card{background:white;border:1px solid var(--line);border-radius:8px;box-shadow:0 1px 2px #193b6408}.filters{padding:17px;position:sticky;top:14px}.results-card{padding:18px}.field{margin:11px 0}.field label,.label{display:block;font-size:12px;font-weight:650;color:#425467;margin-bottom:5px}input,select{width:100%;height:36px;border:1px solid #b9c5d0;border-radius:5px;padding:6px 9px;background:#fff;color:var(--ink);font:inherit}input[type=checkbox]{width:16px;height:16px;vertical-align:middle;accent-color:var(--blue)}.date-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.checkline{display:flex;align-items:flex-start;gap:8px;font-size:12px;color:#425467;margin:12px 0;line-height:1.4}.btn{height:37px;border:0;border-radius:5px;padding:0 13px;background:var(--blue);color:white;font:inherit;font-weight:650;cursor:pointer}.btn.secondary{background:#eef3f7;color:var(--navy);border:1px solid var(--line)}.btn.green{background:var(--green)}.btn:disabled{opacity:.5;cursor:not-allowed}.search-actions{display:flex;gap:8px;margin-top:16px}.search-actions button{flex:1}.folder{border-top:1px solid var(--line);margin-top:17px;padding-top:14px}.folder-path{font-size:11px;color:var(--muted);word-break:break-all;margin-top:7px}.folder-result{font-size:11px;color:var(--green);line-height:1.4;margin-top:8px}
.results-head{display:flex;justify-content:space-between;align-items:center;gap:12px}.results-sub{margin-top:5px}.chosen{font-weight:700;color:var(--green);white-space:nowrap}.chips{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0 3px}.chip{display:inline-block;background:var(--blue2);color:#28567d;border-radius:20px;padding:5px 9px;font-size:11px}.result-list{margin-top:10px}.notice-card{border-top:1px solid var(--line);padding:16px 2px;display:grid;grid-template-columns:minmax(0,1fr) 150px;gap:14px}.notice-card:first-child{border-top:0}.notice-title{font-size:15px;line-height:1.4;font-weight:680;color:var(--navy);text-decoration:none}.notice-title:hover{text-decoration:underline}.notice-meta{display:flex;flex-wrap:wrap;gap:5px 14px;color:var(--muted);font-size:11px;margin:7px 0}.notice-desc{font-size:12px;line-height:1.5;color:#34424e;margin:8px 0;white-space:pre-wrap;max-height:110px;overflow:auto}.notice-actions{display:flex;flex-direction:column;align-items:stretch;gap:7px}.notice-actions .btn{height:31px;font-size:11px}.notice-actions select{height:31px;font-size:11px}.notice-actions a{font-size:11px;color:var(--blue);text-align:right}.notice-check{display:flex;justify-content:flex-end;align-items:center;gap:6px;color:var(--blue);font-weight:650;font-size:12px}.notice-check input{width:18px;height:18px}.note{width:100%;height:52px;margin:6px 0}.error{background:#fff0ef;color:#7c2725;padding:11px;border-radius:5px;margin-top:12px;font-size:12px}.empty{padding:45px 12px;text-align:center;color:var(--muted)}.pagination{display:flex;align-items:center;justify-content:center;gap:14px;border-top:1px solid var(--line);padding-top:16px;margin-top:9px}.page-label{font-size:12px;color:var(--muted)}.foot{font-size:11px;color:var(--muted);margin:15px 2px}
@media(max-width:900px){.layout{grid-template-columns:1fr}.filters{position:static}.filter-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 12px}.folder{margin-top:10px}}@media(max-width:580px){header{padding:0 14px}.layout{padding:0 10px;margin:10px auto}.filter-grid{grid-template-columns:1fr}.notice-card{grid-template-columns:1fr}.notice-actions{flex-direction:row;flex-wrap:wrap}.notice-actions>*{flex:1}.results-card{padding:13px}.logo{display:none}}
</style></head><body>
<header><div class="brandline"><span class="logo">TED</span><div><h1>Szanse handlowe</h1><div class="hint">Wyszukiwarka ogłoszeń TED</div></div></div><button class="btn green" id="export" disabled onclick="exportFiles()">Zapisz metryczki</button></header>
<main class="layout"><aside class="card filters"><h2>Wyszukiwanie</h2>
<div class="field"><label for="scope">Zakres ogłoszeń</label><select id="scope"><option value="LATEST" selected>Najnowsze wydanie TED</option><option value="ACTIVE">Aktywne postępowania</option><option value="ALL">Całe archiwum</option></select></div>
<div class="filter-grid"><div class="field"><label for="text-query">Słowa w ogłoszeniu</label><input id="text-query" placeholder="np. usługi informatyczne"></div>
<div class="field"><label for="cpv">Kody CPV</label><input id="cpv" value="72*, 48*" placeholder="np. 72*, 48*, 7226*"><div class="muted">* szuka całej gałęzi kodów. Wpisz kilka kodów po przecinku. Puste pole wyłącza filtr.</div></div>
<div class="field"><label for="buyer-country">Kraj zamawiającego</label><select id="buyer-country"><option value="EU POL" selected>UE i Polska (jak w TED)</option><option value="POL">Polska</option><option value="EU">Instytucje UE</option><option value="">Wszystkie kraje</option></select></div>
<div class="field"><label for="place-country">Miejsce realizacji</label><select id="place-country"><option value="">Dowolne</option><option value="POL">Polska</option><option value="DEU">Niemcy</option><option value="CZE">Czechy</option><option value="SVK">Słowacja</option><option value="LTU">Litwa</option></select></div>
<div class="field"><label for="notice-types">Rodzaj ogłoszenia</label><select id="notice-types"><option value="all" selected>Wszystkie</option><option value="tenders">Ogłoszenia o zamówieniu</option><option value="awards">Ogłoszenia o udzieleniu</option></select></div>
<div class="field"><label>Data publikacji</label><div class="date-grid"><input id="from" type="date" aria-label="Data publikacji od"><input id="to" type="date" aria-label="Data publikacji do"></div></div>
<div class="field"><label for="sort">Sortuj według</label><select id="sort"><option value="publication-number|DESC" selected>Numer publikacji — malejąco</option><option value="publication-date|DESC">Data publikacji — najnowsze</option><option value="deadline-receipt-tender-date-lot|ASC">Termin składania — najbliższy</option><option value="estimated-value-proc|DESC">Wartość — najwyższa</option></select></div>
<div class="field"><label for="limit">Wyników na stronę</label><select id="limit"><option>25</option><option>50</option><option selected>100</option><option>250</option></select></div></div>
<label class="checkline"><input id="latest-versions" type="checkbox"><span>Pokazuj tylko najnowsze wersje ogłoszeń</span></label>
<div class="search-actions"><button class="btn" onclick="search(1)">Szukaj w TED</button><button class="btn secondary" onclick="resetFilters()">Wyczyść</button></div>
<div style="margin-top:9px"><button class="btn secondary" style="width:100%" onclick="showSelected()">Pokaż zapisane wybory</button></div>
<div class="folder"><button class="btn secondary" id="choose-folder" style="width:100%" onclick="chooseOutputFolder()">Wybierz folder zapisu</button><div class="muted" style="margin-top:8px">Folder metryczek:</div><div id="output-folder" class="folder-path">Nie wybrano</div><div id="export-result" class="folder-result"></div></div><div id="err"></div></aside>
<section class="card results-card"><div class="results-head"><div><h2>Wyniki wyszukiwania</h2><div id="count" class="muted results-sub">Ustaw filtry i rozpocznij wyszukiwanie.</div></div><span id="chosen" class="chosen"></span></div><div id="active-filters" class="chips"></div><div id="results" class="result-list"><div class="empty">Wyniki pojawią się tutaj.</div></div><div class="pagination" id="pages" style="display:none"><button id="prev-page" class="btn secondary" onclick="search(currentPage-1)">Poprzednia</button><span class="page-label" id="page-label"></span><button id="next-page" class="btn secondary" onclick="search(currentPage+1)">Następna</button></div><div class="foot">Przed decyzją potwierdź aktualność terminu i dokumentów na stronie TED.</div></section></main>
<script>
let rows=[],chosen=new Set(),currentPage=1,total=0,pageLimit=100,outputFolder='';
const el=x=>document.getElementById(x);
function esc(x){return String(x==null?'':x).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function error(x){el('err').innerHTML=x?'<div class="error">'+esc(x)+'</div>':''}
function upd(){el('chosen').textContent=chosen.size?'Wybrane: '+chosen.size:'';el('export').disabled=!chosen.size||!outputFolder}
function renderFilters(){let names=['scope','buyer-country','place-country','notice-types','limit','sort'];let tags=[];if(el('text-query').value)tags.push('Tekst: '+el('text-query').value);if(el('cpv').value)tags.push('CPV '+el('cpv').value);names.forEach(function(id){let node=el(id),label=node.options?node.options[node.selectedIndex].text:'';if(label&&!(id==='limit'&&label==='100'))tags.push(label)});if(el('from').value||el('to').value)tags.push('Publikacja: '+(el('from').value||'…')+' – '+(el('to').value||'…'));el('active-filters').innerHTML=tags.map(x=>'<span class="chip">'+esc(x)+'</span>').join('')}
function requestData(page){let sort=el('sort').value.split('|');return {search_text:el('text-query').value,cpv:el('cpv').value,buyer_country:el('buyer-country').value,place_country:el('place-country').value,notice_types:el('notice-types').value,date_from:el('from').value,date_to:el('to').value,sort_field:sort[0],sort_order:sort[1],limit:Number(el('limit').value),page:page,scope:el('scope').value,only_latest_versions:el('latest-versions').checked}}
async function loadOutputFolder(){try{let r=await fetch('/api/output-folder'),d=await r.json();outputFolder=d.folder||'';el('output-folder').textContent=outputFolder||'Nie wybrano';upd()}catch(e){}}
async function chooseOutputFolder(){let b=el('choose-folder');b.disabled=true;b.textContent='Otwieram…';error('');try{let r=await fetch('/api/output-folder',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}),d=await r.json();if(!r.ok)throw Error(d.error||'Nie udało się wybrać folderu');if(d.folder){outputFolder=d.folder;el('output-folder').textContent=outputFolder;el('export-result').textContent=''}upd()}catch(e){error(e.message)}finally{b.disabled=false;b.textContent='Wybierz folder zapisu'}}
async function search(page){error('');el('results').innerHTML='<div class="empty">Pobieram wyniki z TED…</div>';el('count').textContent='Łączenie z TED Search API…';el('pages').style.display='none';renderFilters();try{let response=await fetch('/api/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(requestData(page))}),d=await response.json();if(!response.ok)throw Error(d.error||'Wyszukiwanie nie powiodło się');rows=d.notices||[];rows.forEach(n=>{if(n.selected)chosen.add(n.number)});total=Number(d.total)||rows.length;currentPage=page;pageLimit=Number(d.limit)||Number(el('limit').value);render();el('count').textContent='Znaleziono: '+total.toLocaleString('pl-PL')+' · strona '+currentPage+' · '+rows.length+' wyników';let pages=Math.ceil(total/pageLimit);el('pages').style.display=pages>1?'flex':'none';el('page-label').textContent='Strona '+currentPage+' z '+pages;el('prev-page').disabled=currentPage<=1;el('next-page').disabled=currentPage>=pages}catch(e){error(e.message);el('results').innerHTML='<div class="empty">Nie udało się pobrać wyników.</div>';el('count').textContent=''}}
function render(){if(!rows.length){el('results').innerHTML='<div class="empty">Brak wyników dla wybranych filtrów.</div>';return upd()}el('results').innerHTML=rows.map(function(n){let id=esc(n.number),checked=chosen.has(n.number),status=['Nowe','Do sprawdzenia','Interesujące','Odrzucone'];let desc='<div class="notice-desc '+(n.description?'':'muted')+'" id="desc-'+id+'">'+esc(n.description||'Pełny opis można wczytać z XML.')+'</div>';return '<article class="notice-card"><div><a class="notice-title" target="_blank" rel="noreferrer" href="'+esc(n.ted_url)+'">'+esc(n.title||'(brak tytułu)')+'</a><div class="notice-meta"><span>'+id+'</span><span>'+esc(n.publication_date)+'</span><span>'+esc(n.buyer||'Zamawiający niepodany')+'</span><span>Kraj zamawiającego: '+esc(n.buyer_country||'—')+'</span><span>Miejsce realizacji: '+esc(n.place||'—')+'</span><span>Termin: '+esc(n.deadline||'—')+'</span><span>CPV: '+esc(n.cpv||'—')+'</span>'+(n.value?'<span>Wartość: '+esc(n.value)+' '+esc(n.currency)+'</span>':'')+(n.contract_nature?'<span>'+esc(n.contract_nature)+'</span>':'')+'</div>'+desc+'<details><summary class="muted">Notatka handlowca</summary><textarea class="note" id="note-'+id+'" placeholder="Komentarz do ogłoszenia">'+esc(n.note||'')+'</textarea><button class="btn secondary" onclick="saveNote(\''+id+'\')">Zapisz notatkę</button></details></div><div class="notice-actions"><label class="notice-check">Wybierz <input type="checkbox" '+(checked?'checked':'')+' onchange="toggle(\''+id+'\',this.checked)"></label><select onchange="setStatus(\''+id+'\',this.value)">'+status.map(s=>'<option '+(n.status===s?'selected':'')+'>'+s+'</option>').join('')+'</select><button class="btn secondary" onclick="loadDescription(\''+id+'\')">Wczytaj pełny opis</button><a target="_blank" rel="noreferrer" href="'+esc(n.ted_url)+'">Szczegóły w TED ↗</a></div></article>'}).join('');upd()}
function resetFilters(){el('scope').value='LATEST';el('text-query').value='';el('cpv').value='72*, 48*';el('buyer-country').value='EU POL';el('place-country').value='';el('notice-types').value='all';el('from').value='';el('to').value='';el('sort').value='publication-number|DESC';el('limit').value='100';el('latest-versions').checked=false;renderFilters()}
async function toggle(number,value){try{let r=await fetch('/api/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({number:number,selected:value})});if(!r.ok)throw Error();if(value)chosen.add(number);else chosen.delete(number);upd()}catch(e){error('Nie udało się zapisać wyboru.')}}
async function setStatus(number,status){await fetch('/api/status',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({number:number,status:status})});let n=rows.find(x=>x.number===number);if(n)n.status=status}
async function saveNote(number){let r=await fetch('/api/note',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({number:number,note:el('note-'+number).value})});if(r.ok){let n=rows.find(x=>x.number===number);if(n)n.note=el('note-'+number).value}}
async function loadDescription(number){let target=el('desc-'+number);if(target)target.textContent='Pobieram XML…';try{let r=await fetch('/api/notice/'+number),d=await r.json();if(!r.ok)throw Error(d.error);if(target)target.textContent=d.notice.description||'W XML nie ma opisu głównego.'}catch(e){if(target)target.textContent=e.message}}
async function showSelected(){error('');try{let r=await fetch('/api/selected'),d=await r.json();rows=d.notices||[];chosen=new Set(rows.map(n=>n.number));total=rows.length;currentPage=1;el('count').textContent='Zapisane wybory: '+rows.length;el('pages').style.display='none';render()}catch(e){error('Nie udało się odczytać zapisanych wyborów.')}}
async function exportFiles(){let b=el('export');b.disabled=true;b.textContent='Zapisuję…';error('');el('export-result').textContent='';try{let r=await fetch('/api/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({numbers:Array.from(chosen)})}),d=await r.json();if(!r.ok)throw Error(d.error||'Nie udało się zapisać metryczek');el('export-result').textContent='Zapisano '+d.files.length+' metryczek w folderze wskazanym powyżej.'}catch(e){error(e.message)}finally{b.textContent='Zapisz metryczki';upd()}}
['text-query','cpv','buyer-country','place-country','notice-types','from','to','scope','sort','limit','latest-versions'].forEach(id=>el(id).addEventListener('change',renderFilters));renderFilters();loadOutputFolder();
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    server_version = "TEDHandlowiec/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        print("[TED Handlowiec] " + fmt % args)

    def send_json(self, obj: dict[str, Any], status: int = 200) -> None:
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("Żądanie jest zbyt duże.")
        return json.loads(self.rfile.read(length).decode()) if length else {}

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            raw = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            return self.wfile.write(raw)
        if path.startswith("/api/notice/"):
            number = path.rsplit("/", 1)[-1]
            if not re.fullmatch(r"\d+-\d{4}", number):
                return self.send_json({"error": "Niepoprawny numer ogłoszenia."}, 400)
            with connect_db() as con:
                row = con.execute("SELECT data FROM notices WHERE number=?", (number,)).fetchone()
            if not row:
                return self.send_json({"error": "Najpierw wyszukaj to ogłoszenie."}, 404)
            item = json.loads(row["data"])
            try:
                detail = parse_xml(fetch_xml(item.get("xml_url") or TED_XML_URL.format(number)), number, item)
                return self.send_json({"notice": detail})
            except (RuntimeError, ValueError) as exc:
                return self.send_json({"error": str(exc)}, 502)
        if path == "/api/selected":
            with connect_db() as con:
                records = con.execute("SELECT data,selected,status,note FROM notices WHERE selected=1 ORDER BY updated DESC").fetchall()
            items = []
            for row in records:
                item = json.loads(row["data"])
                item.update({"selected": True, "status": row["status"], "note": row["note"]})
                items.append(item)
            return self.send_json({"notices": items})
        if path == "/api/output-folder":
            return self.send_json({"folder": output_folder()})
        self.send_json({"error": "Nie znaleziono strony."}, 404)

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        try:
            payload = self.body()
            if path == "/api/search":
                result = do_search(payload)
                return self.send_json(result)
            if path == "/api/output-folder":
                folder = choose_output_folder()
                if folder is None:
                    return self.send_json({"cancelled": True, "folder": output_folder()})
                selected_folder = Path(folder).expanduser()
                if not selected_folder.is_dir():
                    return self.send_json({"error": "Wybrany folder nie jest dostępny."}, 400)
                with connect_db() as con:
                    con.execute("INSERT INTO app_settings(key,value) VALUES('output_folder',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(selected_folder),))
                return self.send_json({"folder": str(selected_folder)})
            if path in ("/api/select", "/api/status", "/api/note"):
                number = str(payload.get("number", ""))
                if not re.fullmatch(r"\d+-\d{4}", number):
                    return self.send_json({"error": "Niepoprawny numer ogłoszenia."}, 400)
                with connect_db() as con:
                    row = con.execute("SELECT number FROM notices WHERE number=?", (number,)).fetchone()
                    if not row:
                        return self.send_json({"error": "Ogłoszenia nie ma na liście wyników."}, 404)
                    if path == "/api/select":
                        con.execute("UPDATE notices SET selected=?,updated=? WHERE number=?", (int(bool(payload.get("selected"))), dt.datetime.now().isoformat(timespec="seconds"), number))
                    elif path == "/api/status":
                        status = str(payload.get("status", "Nowe"))
                        if status not in ("Nowe", "Do sprawdzenia", "Interesujące", "Odrzucone"):
                            return self.send_json({"error": "Nieznany status."}, 400)
                        con.execute("UPDATE notices SET status=?,updated=? WHERE number=?", (status, dt.datetime.now().isoformat(timespec="seconds"), number))
                    else:
                        note = str(payload.get("note", ""))[:5000]
                        con.execute("UPDATE notices SET note=?,updated=? WHERE number=?", (note, dt.datetime.now().isoformat(timespec="seconds"), number))
                return self.send_json({"ok": True})
            if path == "/api/export":
                numbers = [str(n) for n in payload.get("numbers", []) if re.fullmatch(r"\d+-\d{4}", str(n))]
                selected = []
                with connect_db() as con:
                    for number in numbers[:50]:
                        row = con.execute("SELECT data,selected,status,note FROM notices WHERE number=?", (number,)).fetchone()
                        if row and row["selected"]:
                            item = json.loads(row["data"])
                            item.update({"status": row["status"], "note": row["note"]})
                            selected.append(item)
                if not selected:
                    return self.send_json({"error": "Zaznacz co najmniej jedno ogłoszenie."}, 400)
                folder_value = output_folder()
                if not folder_value:
                    return self.send_json({"error": "Najpierw wybierz folder zapisu metryczek."}, 400)
                destination = Path(folder_value).expanduser()
                if not destination.is_dir():
                    return self.send_json({"error": "Folder zapisu jest niedostępny. Wybierz go ponownie."}, 400)
                files = []
                for item in selected:
                    try:
                        notice = parse_xml(fetch_xml(item.get("xml_url") or TED_XML_URL.format(item["number"])), item["number"], item)
                        notice.update({"status": item.get("status", ""), "note": item.get("note", "")})
                        files.append((item["number"] + "_metryczka.xlsx", make_xlsx(notice)))
                    except (RuntimeError, ValueError) as exc:
                        return self.send_json({"error": "Ogłoszenie " + item["number"] + ": " + str(exc)}, 502)
                saved = []
                for filename, raw in files:
                    target = destination / filename
                    stem, suffix = target.stem, target.suffix
                    counter = 2
                    while target.exists():
                        target = destination / (stem + "_" + str(counter) + suffix)
                        counter += 1
                    try:
                        with target.open("xb") as output:
                            output.write(raw)
                    except OSError as exc:
                        completed = ", ".join(path.name for path in saved)
                        detail = (" Zapisano już: " + completed + ".") if completed else ""
                        return self.send_json({"error": "Nie udało się zapisać plików w wybranym folderze: " + str(exc) + detail}, 500)
                    saved.append(target)
                return self.send_json({"ok": True, "folder": str(destination), "files": [path.name for path in saved]})
            self.send_json({"error": "Nie znaleziono endpointu."}, 404)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"error": "Błąd aplikacji: " + str(exc)}, 500)


def main() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = "http://127.0.0.1:" + str(port)
    print(APP_NAME + " działa: " + url)
    print("Zamknięcie: naciśnij Ctrl+C w tym oknie.")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Zamykanie aplikacji…")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
