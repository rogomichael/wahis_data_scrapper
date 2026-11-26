import time
from collections import Counter
import requests
import pandas as pd

BASE = "https://wahis.woah.org"
LIST_URL = f"{BASE}/api/v1/pi/event/filtered-list?language=en"
OUTBREAK_URL = f"{BASE}/api/v1/pi/map-data/outbreaks-from-event-ids?language=en"
INFO_URL = f"{BASE}/api/v1/pi/outbreak/additional-information"

# None = discover avian influenza disease IDs automatically.
# If discovery fails, put the IDs here by hand, e.g. [668, 1234].
DISEASE_IDS = [668, 671]

EUROPE = [5, 6, 16, 27, 19, 26, 23, 105, 58, 62, 70, 76, 72, 148, 75, 59, 89, 95,
          107, 114, 111, 116, 138, 133, 136, 137, 150, 142, 141, 152, 170, 171,
          184, 187, 193, 194, 207, 210, 214, 215, 69, 203, 216, 41, 236, 79, 241, 57]
#DATE_FROM, DATE_TO = "2023-01-01", "2025-12-31"
DATE_FROM, DATE_TO = "2006-01-01", "2024-12-31"
PAGE_SIZE = 100
BATCH = 50
PAUSE = 1.0

HEADERS = {
    "accept": "application/json", "accept-language": "en",
    "clientid": "OIEwebsite", "env": "PRD", "type": "REQUEST",
    "security-token": "token", "token": "#PIPRD202006#",
    "content-type": "application/json",
    "origin": BASE, "referer": BASE + "/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36",
}


# ---------- disease ID discovery ----------
def walk(obj, found):
    if isinstance(obj, dict):
        name, did = None, None
        for k, v in obj.items():
            if isinstance(v, str) and "avian influenza" in v.lower():
                name = v
            if isinstance(v, int) and not isinstance(v, bool) and \
               k.lower() in ("id", "diseaseid", "value", "code", "key"):
                did = v
        if name and did is not None:
            found[did] = name
        for v in obj.values():
            walk(v, found)
    elif isinstance(obj, list):
        for x in obj:
            walk(x, found)


def discover_disease_ids():
    paths = ["/api/v1/pi/event/first-level-filters",
             "/api/v1/pi/first-level-filters",
             "/api/v1/pi/filter/first-level-filters",
             "/api/v1/pi/event/second-level-filters",
             "/api/v1/pi/second-level-filters"]
    found = {}
    print("Looking up avian influenza diseases:")
    for p in paths:
        for method in ("GET", "POST"):
            try:
                r = requests.request(method, f"{BASE}{p}?language=en", headers=HEADERS,
                                     json={} if method == "POST" else None, timeout=60)
            except requests.RequestException as e:
                print(f"  {method} {p}: {type(e).__name__}")
                continue
            if r.status_code == 200:
                try:
                    walk(r.json(), found)
                except ValueError:
                    pass
                print(f"  {method} {p}: 200, {len(found)} candidates so far")
                break
            print(f"  {method} {p}: HTTP {r.status_code}")
    if found:
        print("\nAvian influenza diseases found (id: name):")
        for did, name in sorted(found.items()):
            print(f"  {did}: {name}")
    return found


# ---------- downloads ----------
def list_payload(page, disease_ids):
    return {
        "animalTypes": [], "countries": EUROPE, "eventIds": [], "eventStartDate": None,
        "eventStatuses": [], "firstDiseases": disease_ids, "pageNumber": page,
        "pageSize": PAGE_SIZE, "reasons": [], "reportIds": [], "reportStatuses": [],
        "reportTypes": [], "secondDiseases": [], "sortColumn": "submissionDate",
        "sortOrder": "desc", "submissionDate": None, "typeStatuses": [],
    }


def find_rows(obj):
    best = []
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        best = obj
    elif isinstance(obj, dict):
        for v in obj.values():
            r = find_rows(v)
            if len(r) > len(best):
                best = r
    return best


def get_event_id(row):
    for k, v in row.items():
        if k.lower() == "eventid" and isinstance(v, int):
            return v
    return None


def download_events(disease_ids):
    events, page = {}, 0
    while True:
        r = requests.post(LIST_URL, headers=HEADERS,
                          json=list_payload(page, disease_ids), timeout=120)
        if r.status_code != 200:
            print(f"list page {page}: HTTP {r.status_code} {r.text[:200]!r}")
            break
        rows = find_rows(r.json())
        if not rows:
            break
        for row in rows:
            eid = get_event_id(row)
            if eid is not None and eid not in events:
                events[eid] = row
        print(f"list page {page}: +{len(rows)} rows, {len(events)} distinct events")
        if len(rows) < PAGE_SIZE:
            break
        page += 1
        time.sleep(PAUSE)
    return events


def fetch_outbreaks(event_ids, style):
    if style == "post_list":
        r = requests.post(OUTBREAK_URL, headers=HEADERS, json=event_ids, timeout=120)
    elif style == "post_eventIds":
        r = requests.post(OUTBREAK_URL, headers=HEADERS, json={"eventIds": event_ids}, timeout=120)
    else:
        r = requests.get(OUTBREAK_URL + "&eventIds=" + ",".join(map(str, event_ids)),
                         headers=HEADERS, timeout=120)
    if r.status_code != 200:
        return r.status_code, r.text[:150]
    try:
        return 200, r.json()
    except ValueError:
        return r.status_code, r.text[:150]


def find_outbreak_style():
    for style in ("post_list", "post_eventIds", "get_query"):
        status, data = fetch_outbreaks([6954], style)
        if status == 200 and isinstance(data, list) and data and "outbreakId" in data[0]:
            return style
    return None


def fetch_info(ids):
    r = requests.post(INFO_URL, headers=HEADERS, json={"outbreakInfoIds": ids}, timeout=120)
    if r.status_code != 200:
        return r.status_code, r.text[:150]
    try:
        return 200, r.json()
    except ValueError:
        return r.status_code, r.text[:150]


def main():
    # 1. which diseases
    if DISEASE_IDS:
        disease_ids = DISEASE_IDS
    else:
        found = discover_disease_ids()
        disease_ids = [i for i, n in found.items() if "high pathogenicity" in n.lower()]
        if 668 not in found:
            print("\nWARNING: known ID 668 was not among the candidates, so discovery "
                  "may have misread the response.")
        if not disease_ids:
            print("No diseases discovered. Set DISEASE_IDS by hand at the top of the "
                  "script, or send me the output above.")
            return
    print(f"\nUsing disease IDs: {disease_ids}")

    ostyle = find_outbreak_style()
    if not ostyle:
        print("Outbreaks request shape failed.")
        return

    # 2. events -> outbreaks (with coordinates)
    events = download_events(disease_ids)
    if not events:
        print("No events found.")
        return
    ids = list(events.keys())

    all_outbreaks = []
    for i in range(0, len(ids), BATCH):
        status, data = fetch_outbreaks(ids[i:i + BATCH], ostyle)
        if status != 200 or not isinstance(data, list):
            print(f"batch {i}: HTTP {status} {str(data)[:150]!r}")
            continue
        all_outbreaks.extend(data)
        print(f"outbreaks: batch {i // BATCH + 1}/{-(-len(ids) // BATCH)}, total {len(all_outbreaks)}")
        time.sleep(PAUSE)
    if not all_outbreaks:
        print("No outbreaks retrieved.")
        return

    out = pd.json_normalize(all_outbreaks)
    ev = pd.json_normalize(list(events.values()))
    ev.columns = ["event_" + c for c in ev.columns]
    ev_id_col = next((c for c in ev.columns if c.lower() == "event_eventid"), None)
    if ev_id_col:
        out = out.merge(ev, left_on="eventId", right_on=ev_id_col, how="left")

    out["startDate"] = pd.to_datetime(out["startDate"], errors="coerce")
    sel = out[(out["startDate"] >= DATE_FROM) & (out["startDate"] <= DATE_TO)].copy()
    print(f"\n{len(out)} outbreaks in total, {len(sel)} start in {DATE_FROM} to {DATE_TO}")

    # 3. species per outbreak (counted, not deduplicated)
    oids = sel["outbreakId"].dropna().astype(int).tolist()
    info_rows, long_rows = [], []
    for i in range(0, len(oids), BATCH):
        status, data = fetch_info(oids[i:i + BATCH])
        if status != 200 or not isinstance(data, list):
            print(f"info batch {i}: HTTP {status} {str(data)[:150]!r}")
            continue
        for d in data:
            oid = d.get("outbreakInfoId")
            names = [s.get("spicieName").strip()
                     for s in (d.get("speciesDetails") or []) if s.get("spicieName")]
            counts = Counter(names)
            info_rows.append({
                "outbreakId": oid,
                "info_diseaseName": d.get("diseaseName"),
                "info_totalCases": d.get("totalCases"),
                "species": "; ".join(sorted(counts)),
                "_counts": dict(counts),
            })
            for sp, n in counts.items():
                long_rows.append({"outbreakId": oid, "species": sp, "count": n})
        print(f"info: batch {i // BATCH + 1}/{-(-len(oids) // BATCH)}, records {len(info_rows)}")
        time.sleep(PAUSE)

    info = pd.DataFrame(info_rows).drop_duplicates("outbreakId")
    final = sel.merge(info, on="outbreakId", how="left")

    counts_col = final["_counts"].apply(lambda x: x if isinstance(x, dict) else {})
    all_species = sorted({sp for c in counts_col for sp in c})
    indicators = pd.DataFrame(
        {f"sp_{sp}": counts_col.apply(lambda c, sp=sp: c.get(sp, 0)) for sp in all_species},
        index=final.index,
    )
    final = pd.concat([final.drop(columns=["_counts"]), indicators], axis=1)

    final.to_csv("wahis_hpai_europe_2006_2024.csv", index=False)
    pd.DataFrame(long_rows).to_csv("wahis_hpai_europe_outbreak_species_long_2006_2024.csv", index=False)
    print(f"\nSaved {len(final)} outbreaks with {len(all_species)} species columns "
          f"to wahis_hpai_europe_2006_2024.csv")
    print("Top species:", pd.DataFrame(long_rows).groupby("species")["count"].sum()
          .sort_values(ascending=False).head(10).to_dict())


if __name__ == "__main__":
    main()