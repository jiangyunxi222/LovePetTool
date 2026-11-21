"""Build and verify BandoriLovePet mobile role packages offline."""

import argparse
import hashlib
import json
import math
import re
import tempfile
import zipfile
from pathlib import Path


FORMAT = "bandorilovepet-role"
VERSION = 1
MAX_BYTES = 2 * 1024**3
JSON_LIMIT = 12 * 1024**2
RUNTIME = {
    "runtime/live2dcubismcore.min.js": "913e10e881aa7abec8e65bbb8c2540db3fe9acf987c7537befa521f8a7f51009",
    "runtime/live2d.min.js": "e4ea1f18bdd44b65394ffd5a1bab16982e88757d45134d1bd0737c8a6b3ddd08",
}
IMAGE = {"png", "jpg", "jpeg", "webp"}
AUDIO = {"wav", "mp3", "ogg", "m4a", "flac"}
ASSETS = IMAGE | AUDIO | {"moc", "moc3", "json", "mtn"}
ACTION_REGIONS = ("body", "left", "right")
HIT_REGIONS = set(ACTION_REGIONS) | {"expression", "voice", "wardrobe", "menu"}
ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
FLAG = re.compile(r"[A-Za-z0-9_-]{1,128}")
MODEL = re.compile(r"[^/]+\.model3?\.json", re.IGNORECASE)
NUMBERING = re.compile(r"\s*[（(][0-9]+[）)]$")
WINDOWS_DEVICE = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?", re.IGNORECASE)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def extension(name):
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def safe(name):
    if not isinstance(name, str) or any(not part or part.endswith((".", " ")) or WINDOWS_DEVICE.fullmatch(part)
                                         or re.search(r'[\\<>:"|?*\x00-\x1f]', part)
                                         for part in name.split("/")):
        raise ValueError(f"无效文件路径 {name!r}")
    return name


def clean_reference(name):
    name = name.replace("\\", "/")
    while name.startswith("./"):
        name = name[2:]
    return safe(name)


def text(value):
    return value.strip() if isinstance(value, str) else ""


def check_name(value, context, unique=None):
    name = text(value)
    if not name or (unique is not None and (name in unique or NUMBERING.search(name))):
        raise ValueError(f"{context}缺少名称、名称重复或使用了自动重名编号 {value!r}")
    if unique is not None:
        unique.add(name)
    return name


def normalize_model(raw, modern, renames=None):
    """Retain the fields LovePet's Cubism loaders actually read."""
    original = raw["FileReferences"] if modern else raw
    moc, textures, motion, file_key, idle, start, command = (
        ("Moc", "Textures", "Motions", "File", "Idle", "Start", "PostCommand") if modern else
        ("model", "textures", "motions", "file", "idle", "start", "post_command")
    )
    groups = original.get(motion, {})
    texture_paths = list(original[textures])
    startup = next(iter(groups.get(start, [])), {})
    for index, path in re.findall(r"replace_tex (\d+) ([^;\s]+)", startup.get(command, "")):
        if int(index) < len(texture_paths):
            texture_paths[int(index)] = path
    renames = renames or {}

    def reference(path):
        path = clean_reference(path)
        return renames.get(path, path)

    refs = {moc: reference(original[moc]), textures: [reference(path) for path in texture_paths]}
    for optional in ("Physics", "Pose") if modern else ("physics", "pose"):
        if original.get(optional):
            refs[optional] = reference(original[optional])
    idle_entry = next(iter(groups.get(idle, [])), {})
    if idle_entry.get(file_key):
        refs[motion] = {idle: [{file_key: reference(idle_entry[file_key])}]}
    result = {"Version": 3, "FileReferences": refs} if modern else refs
    controllers, lip = ("Controllers", "LipSync") if modern else ("controllers", "lip_sync")
    if raw.get(controllers, {}).get(lip):
        result[controllers] = {lip: raw[controllers][lip]}
    return result


def model_assets(model, modern):
    refs = model["FileReferences"] if modern else model
    yield refs["Moc" if modern else "model"], {"moc3" if modern else "moc"}
    textures = refs["Textures" if modern else "textures"]
    if not isinstance(textures, list) or not textures:
        raise ValueError("模型需要至少一张贴图")
    for file in textures:
        yield file, IMAGE
    for field in ("Physics", "Pose") if modern else ("physics", "pose"):
        if field in refs:
            yield refs[field], {"json"}
    for record in refs.get("Motions" if modern else "motions", {}).get("Idle" if modern else "idle", []):
        yield record["File" if modern else "file"], {"mtn", "json"}


def entries(items, kind):
    if not isinstance(items, list):
        raise ValueError(f"{kind}列表必须是 JSON 数组")
    ids, names, flags = set(), set(), set()
    for item in items:
        name = check_name(item.get("name"), kind, names)
        number = item.get("id")
        if type(number) is not int or not 0 <= number <= 2147483647 or number in ids:
            raise ValueError(f"{kind}编号无效或重复 {name}")
        ids.add(number)
        for flag in (item["flag"], *item.get("aliasFlags", [])):
            if not FLAG.fullmatch(flag) or flag in flags:
                raise ValueError(f"{kind}收藏标识无效或重复 {flag}")
            flags.add(flag)
        yield item


def referenced_assets(catalog, models):
    if not ID.fullmatch(catalog["id"]):
        raise ValueError("role.json 的 id 应为 1 到 80 位英文、数字、下划线或短横线")
    for property_name in ("name", "game", "group"):
        check_name(catalog.get(property_name), f"角色 {property_name}")
    if not catalog["costumes"]:
        raise ValueError("至少需要一件衣装")
    seen_models = set()
    for costume in entries(catalog["costumes"], "衣装"):
        file = costume["file"]
        modern = costume["cubism3"]
        if (file in seen_models or not MODEL.fullmatch(file) or type(modern) is not bool
                or modern != file.lower().endswith(".model3.json")):
            raise ValueError(f"衣装的模型文件无效 {file}")
        seen_models.add(file)
        yield from model_assets(models[file], modern)
        for kind, endings in (("actions", {"mtn", "json"}), ("expressions", {"json"})):
            for item in entries(costume[kind], kind):
                if kind == "actions" or item.get("file"):
                    yield item["file"], endings
                if kind == "actions":
                    regions = item["categories"]
                    if not isinstance(regions, list) or set(regions).difference(ACTION_REGIONS) or len(set(regions)) != len(regions):
                        raise ValueError(f"动作触发区无效 {item['name']}")
        for name, box in costume.get("hitRegions", {}).items():
            if (name not in HIT_REGIONS or not isinstance(box, list) or len(box) != 4
                    or any(type(value) not in (int, float) or not math.isfinite(value) for value in box)
                    or box[0] > box[2] or box[1] > box[3]):
                raise ValueError(f"衣装的触发区域坐标无效 {costume['name']} / {name}")
    for voice in entries(catalog["voices"], "语音"):
        yield voice["file"], AUDIO
        check_name(voice.get("caption"), "语音字幕")


def collect_files(root, catalog, models, runtime_folder=None):
    root = Path(root).resolve()
    files = {"catalog.json": json_bytes(catalog)}
    for name, model in models.items():
        files[safe(name)] = json_bytes(model)
    for name, endings in referenced_assets(catalog, models):
        safe(name)
        if not name.startswith("assets/") or extension(name) not in endings:
            raise ValueError(f"资源必须放在 assets 下，并使用正确扩展名 {name}")
        if name in files:
            continue
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"找不到资源 {name}")
        files[name] = path
    names = list(RUNTIME) if any(not item["cubism3"] for item in catalog["costumes"]) else [next(iter(RUNTIME))]
    runtime_folder = Path(runtime_folder).resolve() if runtime_folder else root / "runtime"
    for name in names:
        path = (runtime_folder / Path(name).name).resolve()
        if not path.is_relative_to(runtime_folder) or not path.is_file() or path.stat().st_size > 512_000 or digest(path) != RUNTIME[name]:
            raise ValueError(f"缺少已支持的 Live2D 运行库，或其版本不符 {name}")
        files[name] = path
    return files


def digest(value):
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    with value.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pack(files, output):
    output = Path(output)
    suffix = output.suffix.lower()
    if suffix not in {".zip", ".lpk", ".wpk"}:
        raise ValueError("输出格式请选择 ZIP、LPK 或 WPK")
    if suffix == ".wpk":
        catalog = json.loads(files["catalog.json"])
        filename = catalog["id"] + ".lpk"
        with tempfile.TemporaryDirectory() as folder:
            embedded = Path(folder) / filename
            pack(files, embedded)
            write_archive(output, {"config.json": json_bytes({"title": catalog["name"], "lpkFile": filename}), filename: embedded})
        return
    if suffix == ".lpk":
        catalog = json.loads(files["catalog.json"])
        costumes = [{"name": outfit["name"], "path": outfit["file"]} for outfit in catalog["costumes"]]
        metadata = {"type": "STD2_0", "encrypt": False, "id": catalog["id"], "name": catalog["name"],
                    "list": [{"name": catalog["name"], "costume": costumes}]}
        files = dict(files, **{"config.mlve": json_bytes(metadata)})
    if len(files) >= 20_000 or len({key.lower() for key in files}) != len(files):
        raise ValueError("角色包的文件过多或存在大小写重名")
    size = sum(len(data) if isinstance(data, bytes) else data.stat().st_size for data in files.values())
    if size > MAX_BYTES:
        raise ValueError("角色包解压后超过 2 GB")
    hashes = {name: digest(files[name]) for name in sorted(files)}
    manifest = json_bytes({"format": FORMAT, "version": VERSION, "files_sha256": hashes})
    if len(manifest) > JSON_LIMIT or any(len(value) > JSON_LIMIT for value in files.values() if isinstance(value, bytes)):
        raise ValueError("角色包索引或模型 JSON 过大")
    write_archive(output, {"manifest.json": manifest, **{name: files[name] for name in hashes}})


def write_archive(output, files):
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".partial", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
            for name, data in files.items():
                if isinstance(data, bytes):
                    archive.writestr(name, data)
                else:
                    compression = zipfile.ZIP_STORED if extension(name) in IMAGE | {"mp3", "m4a", "ogg", "flac", "lpk"} else zipfile.ZIP_DEFLATED
                    archive.write(data, name, compress_type=compression, compresslevel=3)
        if temporary.stat().st_size > MAX_BYTES:
            raise ValueError("ZIP 文件超过 2 GB")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def verify(path):
    from viewer_formats import open_role_archive
    with open_role_archive(Path(path)) as (archive, suffix):
        return verify_archive(archive, suffix)


def verify_archive(archive, suffix):
    members = [item for item in archive.infolist() if not item.is_dir()]
    names = [safe(item.filename) for item in members]
    if len(names) > 20_000 or len({name.lower() for name in names}) != len(names) or sum(item.file_size for item in members) > MAX_BYTES:
        raise ValueError("ZIP 文件过多、存在重名或解压后超过 2 GB")
    def load(name):
        if archive.getinfo(name).file_size > JSON_LIMIT:
            raise ValueError(f"模型 JSON 过大 {name}")
        return json.loads(archive.read(name).decode("utf-8-sig"))
    manifest = load("manifest.json")
    if manifest.get("format") != FORMAT or type(manifest.get("version")) is not int or manifest["version"] != VERSION:
        raise ValueError("不是支持的手机版角色包")
    hashes = manifest["files_sha256"]
    if set(names) != set(hashes) | {"manifest.json"} or "manifest.json" in hashes:
        raise ValueError("ZIP 内容与 SHA-256 清单不一致")
    catalog = load("catalog.json")
    container = set()
    if suffix == ".lpk":
        config = load("config.mlve")
        if config.get("type") != "STD2_0" or config.get("encrypt") is not False:
            raise ValueError("手机版 LPK 的容器配置无效")
        container.add("config.mlve")
    models = {item["file"]: load(item["file"]) for item in catalog["costumes"]}
    for file, endings in referenced_assets(catalog, models):
        if file not in hashes or not file.startswith("assets/") or extension(file) not in endings:
            raise ValueError(f"缺少引用资源或格式错误 {file}")
    if not catalog["costumes"] or "runtime/live2dcubismcore.min.js" not in hashes:
        raise ValueError("缺少 Live2D 运行库或衣装")
    if any(not item["cubism3"] for item in catalog["costumes"]) and "runtime/live2d.min.js" not in hashes:
        raise ValueError("缺少 Cubism 2 运行库")
    for name, expected in hashes.items():
        if name not in {"catalog.json", *models, *RUNTIME, *container} and not (name.startswith("assets/") and extension(name) in ASSETS):
            raise ValueError(f"角色包内不允许此文件 {name}")
        if name in RUNTIME and (RUNTIME[name] != expected or archive.getinfo(name).file_size > 512_000):
            raise ValueError(f"不支持的 Live2D 运行库 {name}")
        with archive.open(name) as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError(f"文件校验失败 {name}")
    return catalog


def named_file(path, suffix, kind):
    stem = path.name[:-len(suffix)]
    fields = stem.split("__")
    if len(fields) not in (2, 3) or not re.fullmatch(r"[0-9]{3}", fields[0]) or not text(fields[1]) or len(fields) == 3 and kind != "action":
        raise ValueError(f"文件名应为三位编号__显示名称{suffix} {path.name}")
    return fields[0], fields[1], fields[2] if len(fields) == 3 else ""


def motion_duration(path):
    if path.name.lower().endswith(".motion3.json"):
        result = float(read_json(path)["Meta"]["Duration"])
    else:
        source = path.read_text(encoding="utf-8-sig")
        rate = re.search(r"(?im)^\s*@?fps\s*=\s*([\d.]+)", source)
        rows = [row.partition("=")[2] for row in source.splitlines() if not row.startswith(("@", "#")) and "=" in row]
        frames = max((len(v.strip(", ").split(",")) for v in rows), default=0)
        result = frames / (float(rate[1]) if rate else 30)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"不能从动作读取有效时长 {path.name}")
    return result


def folder_items(root, directory, suffixes, kind, prefix):
    base = root / directory
    if not base.exists():
        return []
    result = []
    for path in sorted(base.iterdir()):
        suffix = next((ending for ending in suffixes if path.name.lower().endswith(ending)), None)
        if not path.is_file() or not suffix:
            if kind == "voice" and path.is_file() and path.suffix.lower() == ".txt":
                continue
            raise ValueError(f"{kind}目录有不支持的文件 {path.relative_to(root)}")
        number, name, region_field = named_file(path, suffix, kind)
        record = {"id": int(number), "name": name, "file": path.relative_to(root).as_posix(), "flag": prefix + number}
        if kind == "action":
            record["categories"] = region_field.split("-") if region_field else []
            record.update(duration=motion_duration(path), fadeIn=1000, fadeOut=1000)
        elif kind == "voice":
            caption = path.with_suffix(".txt")
            if not caption.is_file():
                raise ValueError(f"语音缺少同名 UTF-8 字幕 {caption.name}")
            record["caption"] = caption.read_text(encoding="utf-8-sig").strip()
        result.append(record)
    return result


def from_folder(root, runtime=None):
    root = Path(root).resolve()
    role = read_json(root / "role.json")
    catalog = {key: role[key] for key in ("id", "game", "group", "name")}
    catalog.update(motionFadePolicy="source", costumes=[], voices=[])
    mapping = root / "renames.json"
    renames = {clean_reference(old): clean_reference(new) for old, new in read_json(mapping).items()} if mapping.is_file() else {}
    models = {}
    for path in sorted(root.iterdir()):
        if not path.is_file() or not MODEL.fullmatch(path.name):
            continue
        modern = path.name.lower().endswith(".model3.json")
        suffix = ".model3.json" if modern else ".model.json"
        number, name, _ = named_file(path, suffix, "costume")
        models[path.name] = normalize_model(read_json(path), modern, renames)
        catalog["costumes"].append({"id": int(number), "name": name, "file": path.name,
            "flag": "costume_" + number, "cubism3": modern, "hitRegions": role.get("hitRegions", {}).get(number, {}),
            "actions": folder_items(root, f"assets/motions/{number}", (".motion3.json",) if modern else (".mtn",), "action", f"action_{number}_"),
            "expressions": folder_items(root, f"assets/expressions/{number}", (".exp3.json",) if modern else (".exp.json",), "expression", f"expression_{number}_")})
    outfit_ids = {f"{item['id']:03d}" for item in catalog["costumes"]}
    for folder in (root / "assets/motions", root / "assets/expressions"):
        if folder.is_dir():
            for directory in folder.iterdir():
                if not directory.is_dir() or directory.name not in outfit_ids:
                    raise ValueError(f"素材目录未对应任何衣装 {directory.relative_to(root)}")
    catalog["voices"] = folder_items(root, "assets/voices", tuple("." + name for name in sorted(AUDIO)), "voice", "voice_")
    return catalog, collect_files(root, catalog, models, runtime)


def build(source, output=None, runtime=None):
    source = Path(source).resolve()
    output = Path(output).resolve() if output else source.parent / (source.name + ".zip")
    catalog, files = from_folder(source, runtime)
    pack(files, output)
    return output, catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    create = sub.add_parser("pack", help="按文件夹规则生成单角色 ZIP、LPK 或 WPK")
    create.add_argument("source", type=Path)
    create.add_argument("output", type=Path, nargs="?")
    create.add_argument("--runtime", type=Path, help="集中存放 Live2D 运行库的目录")
    check = sub.add_parser("verify", help="验证手机版角色包")
    check.add_argument("source", type=Path)
    inspect = sub.add_parser("inspect", help="识别 ZIP、LPK 或 WPK 的格式和内容")
    inspect.add_argument("source", type=Path)
    convert = sub.add_parser("convert", help="转换 ZIP、LPK 或 WPK")
    convert.add_argument("source", type=Path)
    convert.add_argument("output", type=Path)
    convert.add_argument("--runtime", type=Path, help="第三方 LPK/WPK 转手机版时使用的运行库目录")
    args = parser.parse_args()
    if not args.command:
        from windows_app import launch
        launch()
        return
    try:
        if args.command == "inspect":
            from viewer_formats import inspect_source
            print(json.dumps(inspect_source(args.source), ensure_ascii=False, indent=2))
            return
        if args.command == "convert":
            from viewer_formats import convert_package
            catalog = convert_package(args.source, args.output, args.runtime)
            print(f"已转换 {args.output.resolve()}")
        elif args.command == "pack":
            path, catalog = build(args.source, args.output, args.runtime)
            print(f"已成包 {path}")
        else:
            catalog = verify(args.source)
        print(f"{catalog['name']} · {len(catalog['costumes'])} 件衣装 · {len(catalog['voices'])} 条语音")
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
