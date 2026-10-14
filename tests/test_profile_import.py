import json
import tempfile
import unittest

from app.bridge import Bridge
from app.journey import Journey
from app.profile_import import ProfileImport
from app.store import Problem, Store


def fixture():
    empty = {"status": "empty", "items": []}
    return {
        "schema": "job-assistant.boss-resume.v1",
        "source_url": "https://www.zhipin.com/web/geek/resume?tracking=discarded",
        "name": "测试同学",
        "sections": {
            "advantage": {"status": "present", "items": ["擅长客户沟通与项目复盘"]},
            "expectations": {"status": "present", "items": ["产品运营 · 杭州"]},
            "work": {"status": "present", "items": ["虚构科技 · 运营助理 · 支持用户访谈"]},
            "projects": empty.copy(),
            "education": {"status": "unavailable", "items": []},
            "certificates": empty.copy(),
            "custom": empty.copy(),
        },
    }


class ProfileImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.store.save_profile({"name": "原姓名", "preferences": "原偏好", "facts": "原经历"})

    def test_explicit_draft_is_idempotent_and_does_not_overwrite_profile(self):
        importer = ProfileImport(self.store)
        first = importer.save({"resume": fixture()})
        second = importer.save({"resume": fixture()})
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["source_url"], "https://www.zhipin.com/web/geek/resume")
        self.assertEqual(self.store.state()["profile"]["facts"], "原经历")
        editor = importer.editor_values(first)
        self.assertIn("工作经历", editor["facts"])
        self.assertEqual(editor["preferences"], "产品运营 · 杭州")

    def test_strict_source_status_and_masked_name_validation(self):
        importer = ProfileImport(self.store)
        bad = fixture();bad["source_url"] = "https://example.com/web/geek/resume"
        with self.assertRaises(Problem): importer.save({"resume": bad})
        bad = fixture();bad["sections"]["projects"] = {"status": "present", "items": []}
        with self.assertRaises(Problem): importer.save({"resume": bad})
        masked = fixture();masked["name"] = "138******00"
        self.assertEqual(importer.save({"resume": masked})["content"]["name"], "")

    def test_bridge_export_and_erase_cover_import_draft(self):
        client = "chrome-extension://" + "a" * 32
        result = Bridge(self.store).resume_import(client, {"resume": fixture()})
        exported = json.loads(Journey(self.store).export_data())
        self.assertEqual(exported["profile_import_drafts"][0]["id"], result["id"])
        Journey(self.store).erase({"confirmation": "删除本机全部求职资料"})
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM profile_import_drafts").fetchone()[0], 0)

    def test_editor_values_keep_structured_sections_for_deduplication(self):
        editor = ProfileImport(self.store).editor_values(ProfileImport(self.store).save({'resume': fixture()}))
        self.assertEqual(editor['facts'].count('虚构科技 · 运营助理 · 支持用户访谈'), 1)


if __name__ == "__main__":
    unittest.main()
