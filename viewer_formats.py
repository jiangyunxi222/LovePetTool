"""Read ViewerEX containers and convert their declared data to the mobile protocol."""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import zipfile

from role_builder import (FORMAT, JSON_LIMIT, MAX_BYTES, clean_reference, collect_files, extension, from_folder,
                          motion_duration, normalize_model, pack, read_json, safe, text, verify_archive)


MEMBER_LIMIT = 20_000
CHUNK = 1024 * 1024
META = hashlib.md5(b"config.mlve").hexdigest()


def members(archive):
    result, seen, size = {}, set(), 0
    for member in archive.infolist():
        name = safe(member.filename.removesuffix("/"))
        if member.is_dir():
            continue
        if len(seen) >= MEMBER_LIMIT or name.lower() in seen:
            raise ValueError("模型包包含重复或过多的文件")
        seen.add(name.lower())
        size += member.file_size
        if size > MAX_BYTES:
            raise ValueError("模型包解压后超过 2 GB")
        result[name] = member
    return result


def archive_json(archive, name):
    if archive.getinfo(name).file_size > JSON_LIMIT:
        raise ValueError(f"模型配置过大 {name}")
    return json.loads(archive.read(name).decode("utf-8-sig"))


@contextmanager
def open_role_archive(path, workshop=None):
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in {".zip", ".lpk", ".wpk"} or path.stat().st_size > MAX_BYTES:
        raise ValueError("请选择不超过 2 GB 的 ZIP、LPK 或 WPK")
    with zipfile.ZipFile(path) as archive:
        if suffix != ".wpk":
            yield archive, suffix
            return
        files = members(archive)
        indexes = [name for name in files if PurePosixPath(name).name == "config.json"]
        if "config.json" in files:
            indexes = ["config.json"]
        if len(indexes) != 1:
            raise ValueError("WPK 缺少唯一的 config.json")
        config = archive_json(archive, indexes[0])
        lpk_name = clean_reference(config["lpkFile"])
        nested = (PurePosixPath(indexes[0]).parent / lpk_name).as_posix()
        if extension(lpk_name) != "lpk" or (nested not in files and lpk_name not in files):
            raise ValueError("WPK 没有可用的 LPK 成员")
        if workshop is not None:
            workshop.update(config)
        with tempfile.TemporaryFile() as packed:
            with archive.open(nested if nested in files else lpk_name) as incoming:
                shutil.copyfileobj(incoming, packed, CHUNK)
            packed.seek(0)
            with zipfile.ZipFile(packed) as inner:
                yield inner, ".lpk"


def role_manifest(archive):
    if "manifest.json" in archive.namelist():
        return archive_json(archive, "manifest.json")
    return {}


def legacy_folder(files):
    candidates = {str(PurePosixPath(name).parent.parent) for name in files
                  if name.endswith(("ControlPanel/library.json", "Preview/library.json"))}
    if len(candidates) != 1:
        raise ValueError("ZIP 缺少唯一的 BandoriLove 旧版角色索引")
    root = candidates.pop()
    return "" if root == "." else root + "/"


def authoring_root(files):
    indexes = [path for path in files if re.fullmatch(r"(?:[^/]+/)?role\.json", path)]
    if len(indexes) > 1:
        raise ValueError("一个素材 ZIP 只能包含一个 role.json")
    return indexes[0].removesuffix("role.json") if indexes else None


def read_viewer_meta(archive, files):
    name = META if META in files else "config.mlve"
    meta = archive_json(archive, name)
    if meta.get("type") not in {"STD2_0", "STM_1_0"}:
        raise ValueError(f"暂不支持此 LPK 类型 {meta.get('type', '未知')}")
    return meta


def wardrobe_paths(meta, files):
    result = {}
    for role in meta.get("list", []):
        for costume in role.get("costume", []):
            if costume.get("path"):
                result[clean_reference(costume["path"])] = text(costume.get("name"))
    if not result:
        result = {name: "" for name in files if name.lower().endswith((".model3.json", ".model.json"))}
    if not result:
        raise ValueError("LPK 没有模型入口")
    return result


def member_mask(seed):
    # ViewerEX STD2_0 / STM_1_0 member encoding, also used by DesktopPet's importer.
    key = 0
    for character in seed:
        key = (key * 31 + ord(character)) & 0xFFFFFFFF
    stream = bytearray()
    for _ in range(1024):
        key = ((2531011 + 214013 * key) >> 16) & 0xFFFF
        stream.append(key & 255)
    return bytes(stream)


def decode_chunk(data, mask):
    if not mask:
        return data
    repeated = (mask * ((len(data) + 1023) // 1024))[:len(data)]
    return (int.from_bytes(data, "little") ^ int.from_bytes(repeated, "little")).to_bytes(len(data), "little")


def make_mask(path, archive, meta, workshop, first):
    if str(meta.get("encrypt", True)).lower() == "false":
        if meta["type"] == "STM_1_0":
            with archive.open(first) as stream:
                if not stream.read(128).lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"{"):
                    return lambda _: member_mask("")
        return lambda _: b""
    identity = str(meta.get("id", ""))
    if not identity or len(identity) > 128:
        raise ValueError("LPK 缺少有效的模型编号")
    if meta["type"] == "STD2_0":
        return lambda name: member_mask(identity + name)
    if not workshop:
        sidecar = path.parent / "config.json"
        if not sidecar.is_file() or sidecar.stat().st_size > JSON_LIMIT:
            raise ValueError("创意工坊 LPK 需要同目录 config.json，或直接使用完整 WPK")
        workshop = read_json(sidecar)
    file_id = str(workshop.get("fileId") or PurePosixPath(workshop.get("lpkFile", "")).stem)
    tag = workshop.get("metaData", "")
    if not re.fullmatch(r"[0-9]{1,24}", file_id) or not isinstance(tag, str) or not 0 < len(tag) <= 256:
        raise ValueError("创意工坊模型配置缺少有效的物品编号或元数据")
    return lambda name: member_mask(identity + file_id + name + tag)


def asset_ending(prefix, kind):
    if kind == "texture":
        if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
            return ".png"
        if prefix.startswith(b"\xff\xd8\xff"):
            return ".jpg"
        if prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP":
            return ".webp"
    elif kind == "sound":
        if prefix[:4] == b"RIFF" and prefix[8:12] == b"WAVE":
            return ".wav"
        if prefix.startswith(b"OggS"):
            return ".ogg"
        if prefix.startswith(b"fLaC"):
            return ".flac"
        if prefix[4:8] == b"ftyp":
            return ".m4a"
        if prefix.startswith(b"ID3") or len(prefix) > 1 and prefix[0] == 255 and prefix[1] & 224 == 224:
            return ".mp3"
    elif kind in {".moc", ".moc3"}:
        if prefix.startswith(b"MOC3" if kind == ".moc3" else b"moc"):
            return kind
    elif kind == ".mtn":
        if prefix.strip() and b"\0" not in prefix:
            return kind
    elif prefix.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"{"):
        return kind
    raise ValueError(f"无法识别模型素材类型 {kind}")


def viewer_to_files(path, archive, files, workshop, root, runtime):
    from migrate_libraries import distinct, tracks
    meta = read_viewer_meta(archive, files)
    paths = wardrobe_paths(meta, files)
    mask_for = make_mask(path, archive, meta, workshop, next(iter(paths)))
    cached, voices, models = {}, [], {}

    def asset(reference, kind):
        name = clean_reference(reference)
        if name not in files:
            raise ValueError(f"LPK 缺少引用文件 {name}")
        key = (name, kind)
        if key in cached:
            return cached[key]
        with archive.open(name) as read:
            mask = mask_for(name)
            block = decode_chunk(read.read(CHUNK), mask)
            suffix = asset_ending(block[:4096], kind)
            target = "assets/viewer/" + hashlib.sha256((name + "|" + kind).encode("utf-8")).hexdigest()[:24] + suffix
            file = root / target
            file.parent.mkdir(parents=True, exist_ok=True)
            with file.open("wb") as stream:
                stream.write(block)
                while block := read.read(CHUNK):
                    stream.write(decode_chunk(block, mask))
        cached[key] = target
        return target

    title = text(workshop.get("title")) or text(meta.get("name")) or path.stem
    identity = "viewer_" + hashlib.sha256((str(meta.get("id")) + "|" + title).encode("utf-8")).hexdigest()[:24]
    catalog = {"id": identity, "name": title, "game": "Live2D", "group": "ViewerEX", "costumes": [], "voices": [],
               "motionFadePolicy": "source"}
    for name, label in paths.items():
        member = files.get(name)
        if member is None or member.file_size > JSON_LIMIT:
            raise ValueError(f"LPK 模型配置缺失或过大 {name}")
        raw = json.loads(decode_chunk(archive.read(member), mask_for(name)).decode("utf-8-sig"))
        modern = "FileReferences" in raw
        original = raw["FileReferences"] if modern else raw
        moc, textures, motion, file_key, idle = (("Moc", "Textures", "Motions", "File", "Idle") if modern else
                                                  ("model", "textures", "motions", "file", "idle"))
        file_suffix = ".motion3.json" if modern else ".mtn"
        if not original.get(moc) or not original.get(textures):
            continue
        outfit_id = len(models) + 1
        model = normalize_model(raw, modern)
        refs = model["FileReferences"] if modern else model
        refs[moc] = asset(refs[moc], ".moc3" if modern else ".moc")
        refs[textures] = [asset(value, "texture") for value in refs[textures]]
        for field in ("Physics", "Pose") if modern else ("physics", "pose"):
            if field in refs:
                refs[field] = asset(refs[field], ".json")
        for row in refs.get(motion, {}).get(idle, []):
            row[file_key] = asset(row[file_key], file_suffix)
        model_file = f"{outfit_id:03d}_costume.model{'3' if modern else ''}.json"
        models[model_file] = model
        outfit = {"id": outfit_id, "name": label or PurePosixPath(name).stem.removesuffix(".model3").removesuffix(".model"),
                  "file": model_file, "flag": f"costume_{outfit_id}", "cubism3": modern, "hitRegions": {}}
        actions = []
        for group, rows in original.get(motion, {}).items():
            for row in rows:
                source = row.get(file_key)
                if source:
                    target = asset(source, file_suffix)
                    number = len(actions)
                    action_name = text(row.get("Name" if modern else "name")) or f"{group} · {PurePosixPath(source).stem}"
                    actions.append({"id": number, "name": action_name, "file": target, "flag": f"action_{outfit_id}_{number}",
                                    "duration": motion_duration(root / target), "fadeIn": 1000, "fadeOut": 1000})
                sound = row.get("Sound" if modern else "sound")
                if sound:
                    target = asset(sound, "sound")
                    caption = text(row.get("Text" if modern else "text"))
                    number = len(voices)
                    voices.append({"id": number, "file": target, "name": caption or PurePosixPath(sound).stem,
                                   "caption": caption or "原包未提供字幕", "flag": f"voice_{number}", "costumeIds": [outfit_id]})
        expressions = []
        for row in original.get("Expressions" if modern else "expressions", []):
            source = row.get(file_key)
            if source:
                number = len(expressions)
                expressions.append({"id": number, "flag": f"expression_{outfit_id}_{number}",
                                    "name": text(row.get("Name" if modern else "name")) or PurePosixPath(source).stem,
                                    "file": asset(source, ".exp3.json" if modern else ".exp.json")})
        outfit["actions"] = tracks(actions, "actions", {}, lambda item: "")
        outfit["expressions"] = tracks(expressions, "expressions", {}, lambda item: "")
        catalog["costumes"].append(outfit)
    distinct(catalog["costumes"], lambda row: row["name"], lambda row: ["模型 " + row["file"]])
    catalog["voices"] = tracks(voices, "voices", {}, lambda voice: "")
    return catalog, collect_files(root, catalog, models, runtime or path.parent / "runtime")


def extract_member(archive, name, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(name) as incoming, output.open("wb") as target:
        shutil.copyfileobj(incoming, target, CHUNK)


def inspect_source(path):
    path = Path(path).resolve()
    workshop = {}
    with open_role_archive(path, workshop) as (archive, suffix):
        files = members(archive)
        manifest = role_manifest(archive)
        if manifest.get("format") == FORMAT:
            catalog = verify_archive(archive, suffix)
            return {"format": FORMAT, "version": manifest["version"], "name": catalog["name"],
                    "costumes": len(catalog["costumes"]), "voices": len(catalog["voices"])}
        if suffix == ".zip":
            authored = authoring_root(files)
            if authored is not None:
                role = archive_json(archive, authored + "role.json")
                return {"format": "按协议整理的素材 ZIP", "name": role["name"], "id": role["id"]}
            prefix = legacy_folder(files)
            index = prefix + "ControlPanel/library.json"
            if index not in files:
                index = prefix + "Preview/library.json"
            roles = archive_json(archive, index)
            return {"format": "BandoriLove 旧版 ZIP", "roles": [row["name"] for row in roles]}
        meta = read_viewer_meta(archive, files)
        return {"format": meta["type"], "name": text(workshop.get("title")) or meta.get("name", path.stem),
                "costumes": list(wardrobe_paths(meta, files))}


def convert_package(source, output, runtime=None):
    from migrate_libraries import convert
    source = Path(source).resolve()
    output = Path(output).resolve()
    workshop = {}
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        with open_role_archive(source, workshop) as (archive, suffix):
            files = members(archive)
            manifest = role_manifest(archive)
            if manifest.get("format") == FORMAT:
                catalog = verify_archive(archive, suffix)
                for name in manifest["files_sha256"]:
                    if name != "config.mlve":
                        extract_member(archive, name, root / name)
                models = {item["file"]: read_json(root / item["file"]) for item in catalog["costumes"]}
                payload = collect_files(root, catalog, models)
            elif suffix == ".zip":
                prefix = authoring_root(files)
                if prefix is not None:
                    for name in files:
                        relative = name[len(prefix):]
                        if name.startswith(prefix) and (relative.startswith(("assets/", "runtime/")) or relative.endswith(
                                ("role.json", "renames.json", ".model.json", ".model3.json"))):
                            extract_member(archive, name, root / relative)
                    catalog, payload = from_folder(root, runtime)
                else:
                    prefix = legacy_folder(files)
                    for name in files:
                        relative = name[len(prefix):]
                        if name.startswith(prefix) and (relative.startswith(("assets/", "ControlPanel/data/", "Preview/data/")) or relative.endswith((
                                "library.json", ".model.json", ".model3.json", "manifest.json", "source-lock.json",
                                "vendor/live2d.min.js", "vendor/live2dcubismcore.min.js"))):
                            extract_member(archive, name, root / relative)
                    catalog, payload = convert(root, lambda item, _, __, ___: "")
            else:
                catalog, payload = viewer_to_files(source, archive, files, workshop, root, runtime)
        pack(payload, output)
    return catalog
