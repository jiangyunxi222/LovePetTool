"""Normalize legacy role catalogs for conversion by LovePetTool."""

from collections import defaultdict
from pathlib import Path

from role_builder import (ACTION_REGIONS, HIT_REGIONS, NUMBERING, clean_reference, collect_files,
                          json_bytes, normalize_model, read_json, text)

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


def merge_outfits(costumes, models, voices):
    """Merge only outfits whose rendered model and playback lists are identical."""
    retained = {}
    aliases = {}
    excluded = {"id", "flag", "aliasFlags"}
    for outfit in costumes:
        number = outfit["id"]
        track_data = {kind: [{key: value for key, value in item.items() if key not in excluded} for item in outfit[kind]]
                      for kind in ("actions", "expressions")}
        scoped = [voice["id"] for voice in voices if number in (voice.get("costumeIds") or [])]
        key = json_bytes([outfit["name"], models[outfit["file"]], outfit["hitRegions"], track_data, scoped])
        existing = retained.get(key)
        if existing is None:
            retained[key] = outfit
            continue
        aliases[number] = existing["id"]
        existing.setdefault("aliasIds", []).append(number)
        merge_flags(existing, outfit)
        for kind in ("actions", "expressions"):
            for item, old in zip(existing[kind], outfit[kind]):
                merge_flags(item, old)
        del models[outfit["file"]]
    for voice in voices:
        if voice.get("costumeIds"):
            voice["costumeIds"] = list(dict.fromkeys(aliases.get(number, number) for number in voice["costumeIds"]))
    return list(retained.values())


def merge_flags(item, old):
    flags = dict.fromkeys([*item.get("aliasFlags", []), old["flag"], *old.get("aliasFlags", [])])
    flags.pop(item["flag"], None)
    if flags:
        item["aliasFlags"] = list(flags)


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
    catalog["voices"] = tracks(source.get("voices", []), "voices", hashes,
                                lambda voice: Path(voice["file"]).stem.removeprefix("curated_"))
    catalog["costumes"] = merge_outfits(catalog["costumes"], models, catalog["voices"])
    distinct(catalog["costumes"], lambda row: NUMBERING.sub("", row["name"]).strip(), lambda row: [
        "来源 " + (provenance.get(row["file"], {}).get("folder") or provenance.get(row["file"], {}).get("model") or row["file"]),
        "原编号 " + str(row["id"])])
    runtime = folder / "ControlPanel/web/vendor"
    if not runtime.is_dir():
        runtime = panel / "web/vendor"
    return catalog, collect_files(folder, catalog, models, runtime)
