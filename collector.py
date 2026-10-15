import argparse
import base64
import html
import ipaddress
import json
import math
import re
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


BASE = (
    "https://rest.arbeitsagentur.de"
    "/jobboerse/jobsuche-service"
)

SEARCH_ENDPOINTS = (
    "/pc/v6/jobs",
    "/pc/v4/app/jobs",
)

SESSION = requests.Session()
SESSION.headers.update({
    "X-API-Key": "jobboerse-jobsuche",
    "User-Agent": "PersonalMinijobFinder/1.2",
    "Accept": "application/json",
})

SESSION.mount(
    "https://",
    HTTPAdapter(
        max_retries=Retry(
            total=2,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
    ),
)


def plain(value):
    return html.unescape(
        re.sub(r"<[^>]+>", " ", str(value or ""))
    )


def fold(value):
    return (
        plain(value)
        .lower()
        .replace("ü", "ue")
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ß", "ss")
    )


def hits(text, terms):
    normalized = fold(text)
    return [
        term
        for term in terms
        if re.search(
            r"(?<!\w)" + re.escape(fold(term)) + r"(?!\w)",
            normalized,
        )
    ]


def distance(a, b):
    lat1, lon1, lat2, lon2 = map(
        math.radians, [*a, *b]
    )
    value = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin((lon2 - lon1) / 2) ** 2
    )
    return round(
        6371 * 2 * math.asin(min(1, math.sqrt(value))),
        1,
    )


def reference(row):
    if not isinstance(row, dict):
        return ""
    return str(
        row.get("referenznummer")
        or row.get("refnr")
        or ""
    ).strip()


def api(path, params=None):
    time.sleep(0.2)
    response = SESSION.get(
        BASE + path,
        params=params,
        timeout=35,
    )

    print(
        f"API {path}: HTTP {response.status_code}; "
        f"type={response.headers.get('Content-Type', '?')}",
        flush=True,
    )

    if response.status_code in (404, 410):
        return None

    response.raise_for_status()

    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"{path}: odgovor nije validan JSON"
        ) from exc


def extract_rows(payload):
    if not isinstance(payload, dict):
        raise ValueError(
            "Ocekivan JSON objekat; dobijen tip: "
            + type(payload).__name__
        )

    containers = [("root", payload)]

    for key in ("data", "result", "ergebnis"):
        if isinstance(payload.get(key), dict):
            containers.append((key, payload[key]))

    for name, container in containers:
        for key in ("stellenangebote", "jobs"):
            rows = container.get(key)

            if not isinstance(rows, list):
                continue

            if not all(isinstance(row, dict) for row in rows):
                continue

            if rows and not any(reference(row) for row in rows):
                continue

            print(
                f"Format: {name}.{key}; rezultata={len(rows)}",
                flush=True,
            )
            return rows

    raise ValueError(
        "Neprepoznat format. Polja odgovora: "
        + ", ".join(str(key) for key in list(payload)[:25])
    )


def search_jobs(params, preferred=None):
    endpoints = list(SEARCH_ENDPOINTS)

    if preferred in endpoints:
        endpoints.remove(preferred)
        endpoints.insert(0, preferred)

    errors = []

    for endpoint in endpoints:
        try:
            rows = extract_rows(api(endpoint, params))
            return rows, endpoint
        except Exception as exc:
            message = (
                f"{endpoint}: {type(exc).__name__}: {exc}"
            )
            errors.append(message)
            print(message, flush=True)

    raise RuntimeError(" | ".join(errors))


def details(ref):
    encoded = quote(
        base64.b64encode(ref.encode()).decode(),
        safe="",
    )
    result = api("/pc/v4/jobdetails/" + encoded)

    if result is None:
        return None

    expected = {
        "stellenangebotsTitel",
        "titel",
        "stellenangebotsBeschreibung",
        "stellenbeschreibung",
        "arbeitszeitmodelle",
        "referenznummer",
        "refnr",
    }

    if not isinstance(result, dict):
        raise ValueError("Detalji nisu JSON objekat")

    if not expected.intersection(result):
        raise ValueError(
            "Neprepoznat format detalja. Polja: "
            + ", ".join(str(key) for key in list(result)[:20])
        )

    return result


def source_link(ref):
    return (
        "https://www.arbeitsagentur.de/jobsuche/jobdetail/"
        + quote(ref, safe="")
    )


def safe_url(url):
    try:
        parsed = urlparse(url)

        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            return False

        addresses = socket.getaddrinfo(
            parsed.hostname,
            443,
            type=socket.SOCK_STREAM,
        )

        return bool(addresses) and all(
            ipaddress.ip_address(item[4][0]).is_global
            for item in addresses
        )

    except (ValueError, OSError, TypeError):
        return False


def check_link(url):
    # API key se nikada ne salje spoljnom poslodavcu.
    for _ in range(4):
        if not safe_url(url):
            return "Nebezbedan ili nedostupan URL"

        try:
            with requests.get(
                url,
                timeout=15,
                allow_redirects=False,
                stream=True,
                headers={
                    "User-Agent": "PersonalMinijobFinder/1.2"
                },
            ) as response:
                status = response.status_code

                if status in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if not location:
                        return "Preusmeravanje bez odredista"
                    url = urljoin(url, location)
                    continue

                if status in (404, 410):
                    return "Link vise nije dostupan"

                if 200 <= status < 300:
                    return (
                        "HTTP dostupan; oglas i poslodavac "
                        "nisu nezavisno potvrdjeni"
                    )

                return f"Nepotvrdjen HTTP {status}"

        except requests.RequestException:
            return "Provera linka nije uspela"

    return "Previse preusmeravanja"


def schedule_evidence(text):
    normalized = fold(text)

    patterns = [
        (
            r"(?:nur|ausschliesslich|arbeit\w*|einsatz\w*|"
            r"arbeitszeit\w*|taetigkeit\w*|schicht\w*)"
            r"[^.!?\n]{0,60}"
            r"(?:am wochenende|samstags|sonntags|samstag|sonntag)"
        ),
        (
            r"(?:am wochenende|samstags|sonntags)\s+"
            r"(?:arbeiten|taetig|ausliefern|fahren)"
        ),
        (
            r"(?:ab|von)\s*(?:17|18|19|20|21|22|23)"
            r"(?:[:.]\d{2})?\s*(?:uhr|h)"
        ),
    ]

    evidence = []

    for pattern in patterns:
        evidence.extend(
            match.group(0)
            for match in re.finditer(pattern, normalized)
        )

    return evidence[:5]


def analyse(summary, detail, config, scope):
    ref = reference(summary) or reference(detail)

    title = plain(
        detail.get("stellenangebotsTitel")
        or detail.get("titel")
        or summary.get("titel")
        or summary.get("beruf")
        or ""
    )

    description = plain(
        detail.get("stellenangebotsBeschreibung")
        or detail.get("stellenbeschreibung")
        or ""
    )

    models = detail.get("arbeitszeitmodelle") or []

    text = " ".join([
        title,
        description,
        json.dumps(models, ensure_ascii=False),
    ])

    if not hits(
        text,
        [
            "minijob",
            "mini-job",
            "geringfuegig",
            "geringfuegige",
            "geringfuegigen",
            "geringfuegiger",
            "geringfuegiges",
        ],
    ):
        return None

    locations = detail.get("arbeitsorte") or []

    if not isinstance(locations, list):
        locations = []

    locations = [
        item for item in locations
        if isinstance(item, dict)
    ]

    if not locations and isinstance(
        summary.get("arbeitsort"), dict
    ):
        locations = [summary["arbeitsort"]]

    distances = []

    for location in locations:
        coordinates = location.get("koordinaten") or {}

        if not isinstance(coordinates, dict):
            continue

        try:
            lat = coordinates.get("lat")
            lon = coordinates.get("lon")

            if lat is not None and lon is not None:
                distances.append(
                    distance(
                        config["centre"],
                        [float(lat), float(lon)],
                    )
                )
        except (TypeError, ValueError):
            continue

    km = min(distances) if distances else None

    remote_evidence = []

    remote_pattern = (
        r"(?:100\s*%\s*(?:remote|home\s*office)|"
        r"(?:vollstaendig|komplett|fully)\s+remote|"
        r"remote\s*(?:deutschlandweit|innerhalb deutschlands)|"
        r"deutschlandweit\s*(?:im\s*)?"
        r"(?:remote|home\s*office))"
    )

    for sentence in re.split(
        r"[\n.!?]", description + " " + title
    ):
        normalized = fold(sentence)

        if re.search(remote_pattern, normalized):
            negated = re.search(
                r"(?:nicht|kein|not)\s+"
                r"(?:100\s*%|fully|remote|home)",
                normalized,
            )
            if not negated:
                remote_evidence.append(sentence.strip())

    local = (
        km is not None
        and km <= config["radius_km"]
    )

    national_remote = (
        config["mode"] == "cv"
        and scope == "national"
        and bool(remote_evidence)
    )

    if not local and not national_remote:
        return None

    matched = []

    if config["mode"] == "cv":
        matched = hits(text, config.get("skills", []))
        if not matched:
            return None
    else:
        if not hits(
            title,
            config.get("delivery_terms", []),
        ):
            return None

    warnings = []
    evidence = schedule_evidence(description)

    if national_remote and not local:
        country_confirmed = any(
            fold(location.get("land", ""))
            in ("deutschland", "germany", "de")
            for location in locations
        ) or any(
            "deutschland" in fold(item)
            for item in remote_evidence
        )

        if not country_confirmed:
            warnings.append(
                "Potpuni remote se pominje, ali rad "
                "iz Nemacke nije eksplicitno potvrdjen"
            )

    if config["mode"] == "delivery":
        if not evidence:
            warnings.append(
                "Termin nije potvrdjen: proveriti "
                "vikend ili pocetak posle 17h"
            )
        elif not re.search(
            r"(?:nur|ausschliesslich)[^.!?\n]{0,45}"
            r"(?:wochenende|samstag|sonntag)|"
            r"(?:ab|von)\s*(?:17|18|19|20|21|22|23)"
            r"(?:[:.]\d{2})?\s*(?:uhr|h)",
            fold(description),
        ):
            warnings.append(
                "Vikend se pominje, ali rad samo "
                "vikendom nije potvrdjen"
            )

    if re.search(
        r"(?:deutsch|german)[^.!?\n]{0,70}"
        r"(?:b2|c1|c2|fliessend|fluent|verhandlungssicher)",
        fold(description),
    ):
        warnings.append(
            "Napredni nemacki: proveriti zahtev "
            "u odnosu na pocetni nivo iz CV-ja"
        )

    if not description:
        warnings.append("Nedostaje opis")

    company = plain(
        detail.get("arbeitgeber")
        or summary.get("arbeitgeber")
        or ""
    )

    if not company:
        company = "Nije navedeno"
        warnings.append("Nedostaje naziv kompanije")

    risk_terms = hits(
        description,
        [
            "vorkasse",
            "vorauszahlung",
            "kryptowaehrung",
            "pakete weiterleiten",
            "konto zur verfuegung",
        ],
    )

    if risk_terms:
        warnings.append(
            "Rizicni izrazi za rucnu proveru: "
            + ", ".join(risk_terms)
        )

    language = [
        sentence.strip()[:400]
        for sentence in re.split(r"[\n.!?]", description)
        if re.search(
            r"deutsch|german|englisch|english|"
            r"fuehrerschein|führerschein",
            sentence,
            re.I,
        )
    ][:8]

    required = detail.get("fertigkeiten")

    required_text = (
        plain(json.dumps(required, ensure_ascii=False))
        if required
        else "Nije strukturirano navedeno; otvori opis oglasa"
    )

    external = (
        detail.get("externeUrl")
        or summary.get("externeUrl")
        or ""
    )

    if not isinstance(external, str):
        external = ""

    if external and not safe_url(external):
        warnings.append(
            "Spoljni link nije prihvacen: "
            "potreban je javni HTTPS URL"
        )
        external = ""

    if remote_evidence:
        work_mode = "Potpuni remote: proveriti uslove"
    elif hits(
        text,
        ["homeoffice", "home office", "hybrid", "remote"],
    ):
        work_mode = "Home office / hibridno: proveriti"
    else:
        work_mode = "Na lokaciji / nije navedeno"

    return {
        "id": ref,
        "title": title,
        "company": company,
        "location": ", ".join(
            sorted({
                plain(item.get("ort", ""))
                for item in locations
                if item.get("ort")
            })
        ) or "Nije navedeno",
        "distance_km": km,
        "work_mode": work_mode,
        "job_type": "Minijob: tekst/model izvora",
        "required_skills": required_text,
        "matched_skills": matched,
        "schedule_evidence": evidence,
        "remote_evidence": remote_evidence,
        "language_and_licence": language,
        "pay": plain(
            detail.get("verguetung") or "Nije navedeno"
        ),
        "published": (
            detail.get("ersteVeroeffentlichungsdatum")
            or summary.get("aktuelleVeroeffentlichungsdatum")
            or ""
        ),
        "source_url": source_link(ref),
        "apply_url": external or source_link(ref),
        "apply_type": (
            "Spoljni oglas / prijava: proveriti"
            if external
            else "BA oglas: uputstvo za prijavu"
        ),
        "warnings": warnings,
        "review": bool(warnings),
        "status": "Извор доступан",
        "description_excerpt": description[:1800],
    }


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def build_site(config, report, database):
    template_path = Path("web/template.html")

    if not template_path.exists():
        raise FileNotFoundError(
            "Nedostaje web/template.html. "
            "Proveri putanju foldera."
        )

    template = template_path.read_text(encoding="utf-8")

    if "__PAYLOAD__" not in template:
        raise ValueError(
            "web/template.html nema __PAYLOAD__ marker. "
            "Koristi originalni template iz paketa."
        )

    payload = {
        "config": {
            "title": config["title"],
            "mode": config["mode"],
            "radius_km": config["radius_km"],
            "centre_label": config["centre_label"],
        },
        "report": report,
        "jobs": list(database.values()),
    }

    embedded = (
        json.dumps(payload, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )

    Path("site").mkdir(exist_ok=True)
    write_json("site/jobs.json", payload)

    Path("site/index.html").write_text(
        template.replace("__PAYLOAD__", embedded),
        encoding="utf-8",
    )
    Path("site/.nojekyll").touch()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()

    config = json.loads(
        Path("config.json").read_text(encoding="utf-8")
    )

    database_path = Path("data/jobs.json")
    database = (
        json.loads(
            database_path.read_text(encoding="utf-8")
        )
        if database_path.exists()
        else {}
    )

    if not isinstance(database, dict):
        raise ValueError(
            "data/jobs.json mora biti JSON objekat. "
            "Prazna baza treba da bude {}."
        )

    now = datetime.now(timezone.utc).isoformat()

    report = {
        "attempted_at": now,
        "errors": [],
        "warnings": [],
        "queries": [],
        "source": "BA Jobsuche: community-documented API",
        "live_tested": False,
    }

    if args.offline:
        report["warnings"].append(
            "Offline build: nije izvrsena live pretraga "
            "niti provera linkova."
        )
        build_site(config, report, database)
        print("Offline HTML je generisan.", flush=True)
        return

    scopes = [("local", "")]

    if config["mode"] == "cv":
        scopes.extend([
            ("national", "remote"),
            ("national", "homeoffice"),
            ("national", "home office"),
        ])

    found = {}
    successful = 0
    preferred_endpoint = None
    max_pages = int(config.get("max_pages", 5))

    for scope, term in scopes:
        for page in range(1, max_pages + 1):
            params = {
                "angebotsart": 1,
                "arbeitszeit": "mj",
                "size": 100,
                "page": page,
            }

            if term:
                params["was"] = term

            if scope == "local":
                params.update({
                    "wo": config["search_location"],
                    "umkreis": config.get(
                        "search_radius_km", 25
                    ),
                })

            print(
                f"Pretraga: scope={scope}; "
                f"term={term!r}; page={page}",
                flush=True,
            )

            try:
                rows, endpoint = search_jobs(
                    params,
                    preferred_endpoint,
                )

                preferred_endpoint = endpoint
                successful += 1

                report["queries"].append({
                    "scope": scope,
                    "term": term,
                    "page": page,
                    "endpoint": endpoint,
                    "returned": len(rows),
                })

                for row in rows:
                    ref = reference(row)
                    if not ref:
                        continue

                    if (
                        ref not in found
                        or scope == "national"
                    ):
                        found[ref] = (row, scope)

                if len(rows) < 100:
                    break

                if page == max_pages:
                    report["warnings"].append(
                        "Dostignut limit stranica: "
                        f"{scope} {term}. "
                        "Rezultati mogu biti nepotpuni."
                    )

            except Exception as exc:
                message = (
                    f"Search {scope} {term!r}: {exc}"
                )
                report["errors"].append(message)
                print(message, flush=True)
                break

    if successful == 0:
        raise RuntimeError(
            "Sve pretrage su neuspesne. "
            "Postojeca baza nije promenjena. "
            + " | ".join(report["errors"])
        )

    report["live_tested"] = True

    if config["mode"] == "delivery":
        found = {
            ref: value
            for ref, value in found.items()
            if (
                ref in database
                or hits(
                    str(
                        value[0].get("titel")
                        or value[0].get("beruf")
                        or ""
                    ),
                    config.get("delivery_terms", []),
                )
            )
        }

    # Najduze neprovereni stari oglasi idu prvi.
    old_refs = sorted(
        database,
        key=lambda ref: database[ref].get(
            "last_checked", ""
        ),
    )
    new_refs = [
        ref for ref in found if ref not in database
    ]

    # Naizmenicno proveravaj stare i nove oglase.
    refs = []
    for index in range(max(len(old_refs), len(new_refs))):
        if index < len(new_refs):
            refs.append(new_refs[index])
        if index < len(old_refs):
            refs.append(old_refs[index])

    max_details = int(config.get("max_details", 300))
    selected = refs[:max_details]

    if len(refs) > max_details:
        report["warnings"].append(
            f"Dostignut limit od {max_details} "
            "detaljnih provera. Nepregledani oglasi "
            "nisu potvrdjeni u ovom pokretanju."
        )

    checked = set()
    detail_successes = 0

    for index, ref in enumerate(selected, start=1):
        print(
            f"Detalji {index}/{len(selected)}: {ref}",
            flush=True,
        )
        checked.add(ref)

        try:
            detail = details(ref)
            detail_successes += 1

            if detail is None:
                if ref in database:
                    database[ref].update({
                        "status": (
                            "Izvor 404/410: "
                            "verovatno zatvoren"
                        ),
                        "last_checked": now,
                    })
                continue

            summary, scope = found.get(
                ref,
                (
                    {"refnr": ref},
                    database.get(ref, {}).get(
                        "scope", "local"
                    ),
                ),
            )

            job = analyse(
                summary,
                detail,
                config,
                scope,
            )

            if job is None:
                if ref in database:
                    database[ref].update({
                        "status": "Vise ne ispunjava filter",
                        "last_checked": now,
                    })
                continue

            job.update({
                "first_seen": database.get(ref, {}).get(
                    "first_seen", now
                ),
                "last_seen": now,
                "last_checked": now,
                "scope": scope,
            })

            job["link_check"] = check_link(
                job["apply_url"]
            )

            if not job["link_check"].startswith(
                "HTTP dostupan"
            ):
                job["warnings"].append(
                    job["link_check"]
                )
                job["review"] = True

            database[ref] = job

        except Exception as exc:
            message = (
                f"Detail {ref}: "
                f"{type(exc).__name__}: {exc}"
            )
            report["errors"].append(message)
            print(message, flush=True)

            if ref in database:
                database[ref].update({
                    "status": "Provera nije uspela",
                    "last_checked": now,
                })

    if selected and detail_successes == 0:
        raise RuntimeError(
            "Pretraga je odgovorila, ali nijedna "
            "provera detalja nije uspela. "
            "Postojeca baza na disku nije promenjena. "
            + " | ".join(report["errors"][-5:])
        )

    for ref in set(database) - checked:
        database[ref]["status"] = (
            "Nije proveren u ovom pokretanju"
        )

    report["completed_at"] = (
        datetime.now(timezone.utc).isoformat()
    )

    build_site(config, report, database)
    write_json(database_path, database)

    print(
        json.dumps(
            {
                "stored": len(database),
                "successful_search_pages": successful,
                "successful_detail_checks": detail_successes,
                "errors": report["errors"],
                "warnings": report["warnings"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
