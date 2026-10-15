"""Public web discovery addon. Does not scrape protected job-board pages."""
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import collector

SOURCES = {
    "LinkedIn": "linkedin.com",
    "Indeed": "indeed.com",
    "Jooble": "jooble.org",
    "StepStone": "stepstone.de",
    "Kleinanzeigen": "kleinanzeigen.de",
    "meinestadt": "meinestadt.de",
    "Minijob-Zentrale": "minijob-zentrale.de",
}


def canonical_url(value, domain):
    try:
        p = urlparse(value)
        host = (p.hostname or "").lower()
        if p.scheme != "https" or p.username or p.password:
            return None
        if host != domain and not host.endswith("." + domain):
            return None
        if p.port not in (None, 443):
            return None
        query = [(k, v) for k, v in parse_qsl(p.query)
                 if not k.lower().startswith("utm_")]
        return urlunparse(("https", host, p.path, "", urlencode(query), ""))
    except (ValueError, TypeError):
        return None


def queries(config):
    if config["mode"] == "delivery":
        return [
            ('local', 'Minijob Muenchen Fahrer Wochenende'),
            ('local', 'Minijob Muenchen Kurier Samstag'),
            ('local', 'Minijob Muenchen Lieferfahrer "ab 17"'),
        ]
    return [
        ('local', 'Minijob Muenchen Projektassistenz PMO'),
        ('local', 'Minijob Muenchen IT Support'),
        ('local', 'Minijob Muenchen Kundenservice'),
        ('national', 'Minijob Deutschland "100% remote" Support'),
        ('national', 'Minijob Deutschland Homeoffice Projektassistenz'),
    ]


def candidate(row, platform, domain, scope, config, now):
    url = canonical_url(row.get("href") or row.get("url") or "", domain)
    if not url:
        return None
    title = collector.plain(row.get("title", "")).strip()
    snippet = collector.plain(row.get("body", ""))
    text = title + " " + snippet
    if not title or not re.search(r"mini[ -]?job|geringf", collector.fold(text)):
        return None
    matched = collector.hits(text, config.get("skills", []))
    if config["mode"] == "cv" and not matched:
        return None
    if config["mode"] == "delivery" and not collector.hits(
        text, config.get("delivery_terms", [])
    ):
        return None
    if scope == "local" and not re.search(
        r"muenchen|munich", collector.fold(text)
    ):
        return None
    evidence = collector.schedule_evidence(text)
    if scope == "national" and not re.search(
        r"remote|home[ -]?office", collector.fold(text)
    ):
        return None
    identifier = "web:" + hashlib.sha256(url.encode()).hexdigest()[:24]
    warnings = [
        "Rezultat web pretrage, ne provereni aktivni oglas",
        "Kompanija, tip ugovora i uslovi nisu nezavisno potvrdjeni",
    ]
    if scope == "local":
        warnings.append("Muenchen se pominje; radijus 15 km NIJE potvrdjen")
    else:
        warnings.append("Potpuni remote i pravo rada iz Nemacke proveriti")
    if config["mode"] == "delivery":
        warnings.append("Rad samo vikendom / posle 17h proveriti kod poslodavca")
    return {
        "id": identifier,
        "title": title,
        "company": "Nije potvrdjeno; izvor: " + platform,
        "location": "Muenchen: tekstualni signal" if scope == "local" else "Nemacka / remote: proveriti",
        "distance_km": None,
        "work_mode": "Remote kandidat: proveriti" if scope == "national" else "Nije potvrdjeno",
        "job_type": "Minijob pomenut u indeksu: proveriti",
        "required_skills": "Nisu preuzeti puni uslovi; otvori original",
        "matched_skills": matched,
        "schedule_evidence": evidence,
        "remote_evidence": [],
        "language_and_licence": [],
        "pay": "Nije potvrdjeno",
        "published": "",
        "source_url": url,
        "apply_url": url,
        "apply_type": "Rezultat sa " + platform + "; moze biti oglas ili lista rezultata",
        "warnings": warnings,
        "review": True,
        "status": "Web kandidat: rucna provera",
        "description_excerpt": "Nije preuzet pun opis. Otvori izvor i proveri uslove.",
        "first_seen": now,
        "last_seen": now,
        "last_checked": now,
        "scope": scope,
        "source": platform,
        "link_check": "Link iz indeksa; HTTP, aktivnost i spam nisu provereni",
    }


def main():
    from ddgs import DDGS
    config = json.loads(Path("config.json").read_text(encoding="utf-8"))
    database_path = Path("data/jobs.json")
    # Keep web candidates separate from BA reference numbers.
    extra_path = Path("data/web_candidates.json")
    report = {
        "attempted_at": datetime.now(timezone.utc).isoformat(),
        "errors": [], "warnings": [], "queries": [],
        "source": "BA + public web discovery", "live_tested": False,
    }
    ba_failed = False
    try:
        collector.main()
        payload = json.loads(Path("site/jobs.json").read_text(encoding="utf-8"))
        report = payload["report"]
    except Exception as exc:
        ba_failed = True
        report["errors"].append("BA collector failed: " + str(exc))
        print(report["errors"][-1], flush=True)
    database = json.loads(database_path.read_text(encoding="utf-8")) if database_path.exists() else {}
    extra = json.loads(extra_path.read_text(encoding="utf-8")) if extra_path.exists() else {}
    if not isinstance(database, dict) or not isinstance(extra, dict):
        raise ValueError("Database files must contain JSON objects")
    if ba_failed:
        for item in database.values():
            item["status"] = "BA provera nije uspela; istorijski zapis"
            item["review"] = True
    now = datetime.now(timezone.utc).isoformat()
    for item in extra.values():
        item["status"] = "Stari web kandidat: nije ponovo pronadjen"
        item["review"] = True
    searcher = DDGS(timeout=20)
    successes = 0
    for platform, domain in SOURCES.items():
        for scope, terms in queries(config):
            query = "site:" + domain + " " + terms
            print("WEB QUERY: " + query, flush=True)
            try:
                rows = list(searcher.text(query, max_results=8))
                successes += 1
                report["queries"].append({"platform": platform, "query": query, "returned": len(rows)})
                for row in rows:
                    job = candidate(row, platform, domain, scope, config, now)
                    if job:
                        job["first_seen"] = extra.get(job["id"], {}).get("first_seen", now)
                        extra[job["id"]] = job
            except Exception as exc:
                message = platform + ": " + type(exc).__name__ + ": " + str(exc)
                report["errors"].append(message)
                print(message, flush=True)
            time.sleep(3)
    report["warnings"].append(
        "Dodatni portali su pretrazeni kroz javni web indeks, ne direktnim scrapingom. "
        "Kandidati su samo u prikazu Za rucnu proveru / Svi. "
        "Nema garancije pokrivenosti, aktivnosti, tacnog radijusa, smena ili odsustva spama."
    )
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    report["web_successful_queries"] = successes
    if successes == 0:
        report["warnings"].append("Sve dodatne web pretrage su neuspesne; prikazana je istorija.")
    merged = dict(database)
    known_urls = {j.get("apply_url") for j in database.values()}
    for key, job in extra.items():
        if job.get("apply_url") not in known_urls:
            merged[key] = job
    collector.build_site(config, report, merged)
    collector.write_json(extra_path, extra)
    print(json.dumps({"BA_records": len(database), "web_candidates": len(extra),
                      "web_successful_queries": successes}, indent=2), flush=True)


if __name__ == "__main__":
    main()
