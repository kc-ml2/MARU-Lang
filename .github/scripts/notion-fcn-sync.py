import os
import re
import json
import requests
from datetime import datetime, timezone

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
FCN_DB_ID = os.environ["NOTION_FCN_DATABASE_ID"]
COMMIT_DB_ID = os.environ["NOTION_COMMIT_DATABASE_ID"]
EVENT_PATH = os.environ["GITHUB_EVENT_PATH"]
REPO = os.environ.get("GITHUB_REPOSITORY", "")  # owner/repo

NOTION_VERSION = "2022-06-28"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}

# ===== Notion property names (수정 필요하면 여기만 바꾸면 됨) =====
FCN_KEY_PROP = "ID"           # FCN DB의 Title 속성 이름
FCN_STATUS_PROP = "Status Update"  # FCN DB의 Status 속성 이름
FCN_COMMITS_REL_PROP = "Commits"  # FCN DB에서 Commit DB로 향하는 Relation 속성 이름

COMMIT_TITLE_PROP = "Commit"   # Commit DB의 Title 속성 이름
COMMIT_MSG_PROP = "Message"
COMMIT_URL_PROP = "URL"
COMMIT_DATE_PROP = "Date"
COMMIT_FCN_REL_PROP = "FCN"    # Commit DB에서 FCN DB로 향하는 Relation 속성 이름

# ===== Commit tag format: [S01F08] =====
TAG_RE = re.compile(r"\[(S\d{2}F\d{2})\]")
DONE_MARKERS = ["[DONE]", "DONE", "완료", "complete", "completed", "finish", "finished", "✅"]

def debug_db_properties(db_id: str):
    url = f"https://api.notion.com/v1/databases/{db_id}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    print("DB schema status:", r.status_code)
    print(r.text)  # 여기 안에 properties 이름/타입 다 나옴
    r.raise_for_status()

def is_done_message(msg: str) -> bool:
    lower = msg.lower()
    return any(m.lower() in lower for m in DONE_MARKERS)

def notion_db_query_by_title(db_id: str, title_prop: str, equals: str):
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    payload = {
        "filter": {
            "property": title_prop,
            "title": {"equals": equals}
        }
    }
    r = requests.post(url, headers=HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    results = r.json().get("results", [])
    return results[0] if results else None

def notion_create_page(db_id: str, properties: dict):
    url = "https://api.notion.com/v1/pages"
    payload = {"parent": {"database_id": db_id}, "properties": properties}
    r = requests.post(url, headers=HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()

def notion_patch_page(page_id: str, properties: dict):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    r = requests.patch(url, headers=HEADERS, json={"properties": properties}, timeout=30)
    r.raise_for_status()
    return r.json()

def notion_retrieve_page(page_id: str):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()

def get_status_name(page_json: dict, status_prop: str):
    props = page_json.get("properties", {})
    st = (props.get(status_prop) or {}).get("status") or {}
    return st.get("name")

def main():
    with open(EVENT_PATH, "r", encoding="utf-8") as f:
        event = json.load(f)

    commits = event.get("commits", [])
    if not commits:
        print("No commits found in event payload. Exiting.")
        return

    # Map fcn_key -> list of commit dicts
    fcn_updates = {}  # key -> {"done": bool, "commits": [commit_info,...]}
    for c in commits:
        msg = c.get("message", "")
        keys = TAG_RE.findall(msg)
        if not keys:
            continue

        sha = c.get("id") or ""
        sha7 = sha[:7]
        url = c.get("url") or ""
        author = ((c.get("author") or {}).get("name")) or ""
        done = is_done_message(msg)
        first_line = msg.splitlines()[0]
        now_iso = datetime.now(timezone.utc).isoformat()

        commit_title = f"{sha7}@{REPO}" if REPO else sha7

        info = {
            "sha7": sha7,
            "sha": sha,
            "title": commit_title,
            "message": first_line,
            "url": url,
            "author": author,
            "date_iso": now_iso,
        }

        for key in set(keys):
            bucket = fcn_updates.setdefault(key, {"done": False, "commits": []})
            bucket["done"] = bucket["done"] or done
            bucket["commits"].append(info)

    if not fcn_updates:
        print("No [SxxFyy] tags found. Exiting.")
        return

    # Process each FCN key
    for fcn_key, pack in fcn_updates.items():
        # 1) Find or create FCN page
        fcn_page = notion_db_query_by_title(FCN_DB_ID, FCN_KEY_PROP, fcn_key)
        if not fcn_page:
            # Create FCN row
            props = {
                FCN_KEY_PROP: {"title": [{"type": "text", "text": {"content": fcn_key}}]},
            }
            # optional: set initial status
            props[FCN_STATUS_PROP] = {"status": {"name": "Not started"}}
            created = notion_create_page(FCN_DB_ID, props)
            fcn_page_id = created["id"]
            print(f"Created FCN: {fcn_key}")
        else:
            fcn_page_id = fcn_page["id"]

        # Retrieve current FCN status (avoid downgrading Done)
        fcn_full = notion_retrieve_page(fcn_page_id)
        current_status = get_status_name(fcn_full, FCN_STATUS_PROP)

        new_status = current_status
        if current_status != "Done":
            new_status = "Done" if pack["done"] else "In progress"

        # 2) For each commit: create Commit DB row if not exists, relate to FCN
        commit_page_ids = []
        for ci in pack["commits"]:
            # Dedup by Commit title (sha7@repo)
            existing_commit = notion_db_query_by_title(COMMIT_DB_ID, COMMIT_TITLE_PROP, ci["title"])
            if existing_commit:
                commit_page_id = existing_commit["id"]
            else:
                commit_props = {
                    COMMIT_TITLE_PROP: {"title": [{"type": "text", "text": {"content": ci["title"]}}]},
                    COMMIT_MSG_PROP: {"rich_text": [{"type": "text", "text": {"content": ci["message"]}}]},
                    COMMIT_URL_PROP: {"url": ci["url"] or None},
                    COMMIT_DATE_PROP: {"date": {"start": ci["date_iso"]}},
                    COMMIT_FCN_REL_PROP: {"relation": [{"id": fcn_page_id}]},
                }
                created_commit = notion_create_page(COMMIT_DB_ID, commit_props)
                commit_page_id = created_commit["id"]
                print(f"Created Commit: {ci['title']} -> {fcn_key}")

            commit_page_ids.append(commit_page_id)

        # 3) Link commits to FCN (append relation entries)
        # Note: patching relation with a list REPLACES the relation set.
        # We'll merge existing relations to avoid overwriting.
        props = fcn_full.get("properties", {})
        existing_rel = (props.get(FCN_COMMITS_REL_PROP) or {}).get("relation") or []
        existing_ids = {x["id"] for x in existing_rel}

        merged_ids = list(existing_ids.union(commit_page_ids))
        patch_props = {
            FCN_COMMITS_REL_PROP: {"relation": [{"id": pid} for pid in merged_ids]},
        }
        if new_status and FCN_STATUS_PROP in props:
            patch_props[FCN_STATUS_PROP] = {"status": {"name": new_status}}

        notion_patch_page(fcn_page_id, patch_props)
        print(f"Updated FCN {fcn_key}: status={new_status}, commits+={len(commit_page_ids)}")


def debug_db_schema(db_id):
    url = f"https://api.notion.com/v1/databases/{db_id}"
    r = requests.get(url, headers=HEADERS)
    print(r.json())


if __name__ == "__main__":
    debug_db_properties(FCN_DB_ID)
    main()