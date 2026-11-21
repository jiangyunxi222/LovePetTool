"""Convert the existing Garupa/OurNotes desktop role libraries without modifying them."""

import argparse
from collections import defaultdict
from pathlib import Path
import sys

from role_builder import (ACTION_REGIONS, HIT_REGIONS, NUMBERING, clean_reference, collect_files,
                          json_bytes, normalize_model, pack, read_json, text, verify)

WORKSPACE = Path(__file__).resolve().parents[1]
REGION_NAMES = {"body": "上身触发", "left": "左臂触发", "right": "右臂触发"}


def distinct(rows, base_name, source_detail):
    by_name = defaultdict(list)
    for row in rows:
        row["name"] = base_name(row)
        by_name[row["name"]].append(row)
    used = set(by_name)
    for name, matches in by_name.items():
        if len(matches) == 1:
            continue
        for row in matches:
            pieces = source_detail(row)
            for index in range(1, len(pieces) + 1):
                candidate = " · ".join([name, *pieces[:index]])
                if candidate not in used:
                    used.add(candidate)
                    row["name"] = candidate
                    break


def tracks(items, kind, hashes, original_name):
    routes = {}
    for original in items:
        item = dict(original)
        file = clean_reference(original["file"]) if original.get("file") else ""
        if "file" in original:
            item["file"] = file
        label = NUMBERING.sub("", original["name"]).strip()
        asset = hashes.get(file, file) if file else "reset"
        if kind == "actions":
            route = (label, asset, item.get("fadeIn", 1000), item.get("fadeOut", 1000), item.get("duration"))
            category = item.get("category")
            categories = [category] if category in ACTION_REGIONS else []
        elif kind == "voices":
            route = (label, asset, item.get("caption"), tuple(item.get("costumeIds") or ()))
            categories = []
        else:
            route = (label, asset)
            categories = []
        existing = routes.get(route)
        if existing is not None:
            if original["flag"] != existing["flag"]:
                existing.setdefault("aliasFlags", []).append(original["flag"])
            if kind == "actions":
                existing["categories"] = list(dict.fromkeys(existing["categories"] + categories))
            continue
        result = {key: item[key] for key in ("id", "name", "flag", "file", "duration", "fadeIn", "fadeOut", "costumeIds", "caption") if key in item}
        if kind == "actions":
            result.update(categories=categories)
        elif kind == "voices":
            result["caption"] = text(item.get("caption")) or text(item["name"])
        result["_original"] = original
        routes[route] = result
    rows = list(routes.values())
    duplicate_names = defaultdict(list)
    for row in rows:
        duplicate_names[NUMBERING.sub("", row["name"]).strip()].append(row)

    def context(row):
        original = row["_original"]
        similar = duplicate_names[NUMBERING.sub("", original["name"]).strip()]
        categories = row.get("categories", [])
        pieces = []
        if categories and any(other.get("categories", []) != categories for other in similar):
            pieces.append("、".join(REGION_NAMES[name] for name in categories))
        source = original_name(original)
        if source and NUMBERING.sub("", source).strip() != NUMBERING.sub("", original["name"]).strip():
            pieces.append("素材 " + source)
        if row.get("duration") and any(other.get("duration") != row["duration"] for other in similar):
            pieces.append(f"{row['duration']:.3f}".rstrip("0").rstrip(".") + " 秒")
        file = row.get("file", "")
        if file:
            pieces.append("资源 " + Path(file).name.split(".", 1)[0][:12])
        pieces.append("原编号 " + str(row["id"]))
        return pieces

    distinct(rows, lambda row: NUMBERING.sub("", row["name"]).strip(), context)
    for row in rows:
        del row["_original"]
    return rows


def convert(folder, helper):
    panel = folder / "ControlPanel"
    if not (panel / "library.json").is_file():
        panel = folder / "Preview"
    role = read_json(panel / "library.json")[0]
    source = read_json(panel / "data" / (role["id"] + ".json"))
    lock_path = folder / "source-lock.json"
    lock = read_json(lock_path) if lock_path.is_file() else {"costumes": [], "assets": {}}
    hashes = read_json(folder / "manifest.json")["files_sha256"]
    provenance = {row["file"]: row for row in lock["costumes"]}
    catalog = {key: source[key] for key in ("id", "game", "name", "group")}
    catalog["motionFadePolicy"] = source.get("motionFadePolicy", "zero")
    catalog["costumes"] = []
    models = {}
    for item in source["costumes"]:
        file = item["file"]
        outfit = {key: item[key] for key in ("id", "name", "file", "flag", "cubism3")}
        outfit["hitRegions"] = {key: value for key, value in item.get("hitRegions", {}).items() if key in HIT_REGIONS and value is not None}
        raw = read_json(folder / file)
        models[file] = normalize_model(raw, outfit["cubism3"])
        for kind in ("actions", "expressions"):
            outfit[kind] = tracks(item[kind], kind, hashes,
                                 lambda item: helper(item, provenance.get(file, {}), lock, kind[:-1]))
        catalog["costumes"].append(outfit)
    distinct(catalog["costumes"], lambda row: NUMBERING.sub("", row["name"]).strip(), lambda row: [
        "来源 " + (provenance.get(row["file"], {}).get("folder") or provenance.get(row["file"], {}).get("model") or row["file"]),
        "原编号 " + str(row["id"])])
    catalog["voices"] = tracks(source.get("voices", []), "voices", hashes,
                                lambda voice: Path(voice["file"]).stem.removeprefix("curated_"))
    runtime = folder / "ControlPanel/web/vendor"
    if not runtime.is_dir():
        runtime = panel / "web/vendor"
    return catalog, collect_files(folder, catalog, models, runtime)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library", choices=["Garupa", "OurNotes"])
    parser.add_argument("--role", help="只整理一个现有角色，用于检查")
    parser.add_argument("--check", action="store_true", help="验证输入和编目，不生成 ZIP")
    args = parser.parse_args()
    sys.path.insert(0, str(WORKSPACE / "tools"))
    from update_display_text import source_name
    library = args.library + "Live2D"
    source = WORKSPACE / "main" / library
    destination = WORKSPACE / (library + "-Mobile")
    index = []
    candidates = sorted(path.parents[1] for path in source.glob("*/*/ControlPanel/library.json"))
    for folder in candidates:
        if args.role and folder.name != args.role:
            continue
        try:
            catalog, files = convert(folder, source_name)
            path = f"packages/{folder.parent.name}/{folder.name}.zip"
            if not args.check:
                pack(files, destination / path)
                verify(destination / path)
            row = {key: catalog[key] for key in ("id", "game", "group", "name")}
            row.update(file=path, costumes=len(catalog["costumes"]), voices=len(catalog["voices"]))
            index.append(row)
            print(f"{library} {len(index)}/{len(candidates)} {catalog['name']}", flush=True)
        except Exception as error:
            raise ValueError(f"{folder}: {error}") from error
    if not index:
        parser.error("没有找到要整理的角色")
    if not args.role and not args.check:
        (destination / "index.json").write_bytes(json_bytes({"game": args.library, "roles": index}))


if __name__ == "__main__":
    main()
