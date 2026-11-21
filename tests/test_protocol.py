import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import role_builder as roles
from migrate_libraries import merge_outfits
from viewer_formats import convert_package, inspect_source


class PackageProtocolTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "authoring"
        self.write("role.json", roles.json_bytes({"id": "test", "name": "测试", "game": "游戏", "group": "分组"}))
        self.write("001__常服.model3.json", roles.json_bytes({"Version": 3, "FileReferences": {
            "Moc": "old.moc3", "Textures": ["assets/model.png"],
        }}))
        self.write("renames.json", roles.json_bytes({"old.moc3": "assets/model.moc3"}))
        self.write("assets/model.moc3", b"MOC3 test fixture")
        self.write("assets/model.png", b"test texture")
        self.write("assets/motions/001/001__挥手__body-left.motion3.json", roles.json_bytes({"Meta": {"Duration": 2}}))
        self.write("assets/expressions/001/001__开心.exp3.json", roles.json_bytes({"Parameters": []}))
        self.write("assets/voices/001__问候.wav", b"test audio")
        self.write("assets/voices/001__问候.txt", "你好。".encode())
        runtime = b"test runtime"
        core = "runtime/live2dcubismcore.min.js"
        self.write(core, runtime)
        patcher = patch.dict(roles.RUNTIME, {core: hashlib.sha256(runtime).hexdigest()})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, path, data):
        target = self.source / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def test_all_containers_and_roundtrip(self):
        expected = None
        for extension in ("zip", "lpk", "wpk"):
            bundle, catalog = roles.build(self.source, self.root / f"role.{extension}")
            expected = expected or catalog
            self.assertEqual(roles.verify(bundle), expected)
            self.assertEqual(inspect_source(bundle)["format"], roles.FORMAT)
        output = self.root / "again.zip"
        convert_package(self.root / "role.wpk", output)
        self.assertEqual(roles.verify(output), expected)
        self.assertEqual(expected["costumes"][0]["actions"][0]["categories"], ["body", "left"])
        self.assertEqual(expected["voices"][0]["caption"], "你好。")

    def test_authoring_zip_with_one_wrapper(self):
        asset_zip = self.root / "source.zip"
        with zipfile.ZipFile(asset_zip, "w") as archive:
            for path in self.source.rglob("*"):
                if path.is_file():
                    archive.write(path, f"role/{path.relative_to(self.source).as_posix()}")
        self.assertEqual(inspect_source(asset_zip)["format"], "按协议整理的素材 ZIP")
        converted = self.root / "publish.lpk"
        convert_package(asset_zip, converted)
        self.assertEqual(roles.verify(converted)["id"], "test")

    def test_missing_reference_rejected(self):
        (self.source / "assets/model.moc3").unlink()
        with self.assertRaisesRegex(ValueError, "找不到资源"):
            roles.from_folder(self.source)

    def test_merge_identical_outfits_preserves_legacy_ids(self):
        first = {"id": 1, "name": "常服", "flag": "outfit_one", "file": "one.model3.json", "hitRegions": {},
                 "actions": [{"id": 0, "name": "挥手", "flag": "first_hand", "file": "assets/hand.motion3.json"}],
                 "expressions": []}
        second = {**first, "id": 2, "flag": "outfit_two", "file": "two.model3.json",
                  "actions": [{**first["actions"][0], "flag": "second_hand"}]}
        models = {first["file"]: {}, second["file"]: {}}
        merged, = merge_outfits([first, second], models, [])
        self.assertEqual(merged["id"], 1)
        self.assertEqual(merged["aliasIds"], [2])
        self.assertEqual(merged["aliasFlags"], ["outfit_two"])
        self.assertEqual(merged["actions"][0]["aliasFlags"], ["second_hand"])
        self.assertEqual(list(models), [first["file"]])

    def test_display_numbering_rejected(self):
        motion = self.source / "assets/motions/001/001__挥手__body-left.motion3.json"
        motion.rename(motion.with_name("001__挥手（2）__body-left.motion3.json"))
        with self.assertRaisesRegex(ValueError, "自动重名编号"):
            roles.from_folder(self.source)

    def test_tampered_asset_rejected(self):
        original, _ = roles.build(self.source, self.root / "valid.zip")
        broken = self.root / "broken.zip"
        with zipfile.ZipFile(original) as good, zipfile.ZipFile(broken, "w") as bad:
            for file in good.namelist():
                payload = good.read(file)
                bad.writestr(file, payload + b"changed" if file == "assets/model.png" else payload)
        with self.assertRaisesRegex(ValueError, "文件校验失败"):
            roles.verify(broken)


if __name__ == "__main__":
    unittest.main()
