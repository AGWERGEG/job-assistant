import base64
import io
import json
import tempfile
import unittest
import zipfile

from app.companion import Companion
from app.documents import import_document
from app.journey import Journey
from app.privacy import redact
from app.resume_restore import preview_resume
from app.store import Store


class ReviewMaterialsTests(unittest.TestCase):
    def test_redaction_handles_common_contact_forms_without_hiding_job_sources(self):
        hidden = (
            "手机：１３８００１３８０００", "138.0013.8000", "微信 liming_1999",
            "WeChat: liming_1999", "QQ 123456789", "liming＠163.com",
            "现居：上海市浦东新区张江路88弄6号1202室",
            "身份证号码 110101 19900307 1234",
        )
        for value in hidden:
            with self.subTest(value=value):
                self.assertNotIn("liming_1999", redact(value))
                self.assertNotEqual(redact(value), value)
        unredacted = "自信：积极乐观，诚信：踏实可靠"
        self.assertEqual(redact(unredacted), unredacted)
        job_address = "工作地址：杭州市西湖区文三路（JD 原文）"
        self.assertEqual(redact(job_address), job_address)

    @staticmethod
    def _minimal_docx():
        document = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
 xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
 xmlns:v="urn:schemas-microsoft-com:vml">
 <w:body>
  <w:p><w:r><w:t>姓名：[本地隐去]</w:t><w:tab/><w:t>手机：[手机号]</w:t><w:br/><w:t>邮箱：[邮箱]</w:t></w:r></w:p>
  <w:p><w:r><w:t>现有经历</w:t><w:drawing><wp:anchor><a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
   <mc:AlternateContent><mc:Choice Requires="wps"><wps:wsp><wps:txbx><w:txbxContent><w:p><w:r><w:t>文本框经历</w:t></w:r></w:p></w:txbxContent></wps:txbx></wps:wsp></mc:Choice>
   <mc:Fallback><w:pict><v:shape><v:textbox><w:txbxContent><w:p><w:r><w:t>文本框经历</w:t></w:r></w:p></w:txbxContent></v:textbox></v:shape></w:pict></mc:Fallback></mc:AlternateContent>
  </a:graphic></wp:anchor></w:drawing><w:del><w:r><w:delText>旧手机号 13900000000</w:delText></w:r></w:del></w:r></w:p>
  <w:sectPr/>
 </w:body>
</w:document>'''
        header = '''<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
 <w:p><w:r><w:t>张三</w:t><w:tab/><w:t>手机：13812345678</w:t><w:tab/><w:t>邮箱：zhangsan@example.com</w:t></w:r></w:p>
</w:hdr>'''
        footer = '''<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
 <w:p><w:r><w:t>页脚保留</w:t></w:r></w:p>
</w:ftr>'''
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", document)
            archive.writestr("word/header1.xml", header)
            archive.writestr("word/footer1.xml", footer)
        return stream.getvalue()

    @staticmethod
    def _import(store, name, raw):
        return import_document(store, {"name": name, "base64": base64.b64encode(raw).decode("ascii")})

    @staticmethod
    def _approved_store_profile(store, facts, name="张三"):
        companion = Companion(store)
        store.save_profile({"name": name, "facts": facts})
        companion.approve({"token": companion.preview_profile()["token"], "confirmed": True})
        return companion

    def test_docx_import_preserves_structure_and_restoration_uses_clean_contacts(self):
        with tempfile.TemporaryDirectory(prefix="ja_review_docx_") as folder:
            store = Store(folder)
            imported = self._import(store, "虚构简历.docx", self._minimal_docx())
            text = imported["extracted"]
            self.assertIn("张三\t手机：13812345678", text)
            self.assertIn("邮箱：[邮箱]", text)
            self.assertIn("现有经历文本框经历", text)
            self.assertIn("页脚保留", text)
            self.assertEqual(text.count("文本框经历"), 1)
            self.assertNotIn("13900000000", text)

            self._approved_store_profile(store, text)
            job = store.save_job({"title": "虚构岗位", "company": "虚构公司", "jd": "虚构 JD"})
            task = store.create_task({"kind": "tailor_resume", "job_id": job["id"],
                                      "instruction": "虚构简历修订"})
            with store.connect() as db:
                db.execute("INSERT INTO resume_versions VALUES(?,?,?,?,?)",
                           ("version-test", job["id"], task["id"],
                            "姓名：[本地隐去]\n邮箱：[邮箱]\n手机号：[手机号]\n经历", 1))
            restored = preview_resume(store, "version-test")["content"]
            self.assertIn("姓名：张三", restored)
            self.assertIn("邮箱：zhangsan@example.com", restored)
            self.assertIn("手机号：13812345678", restored)
            self.assertNotIn("年龄：25", restored)

    def test_resume_restore_stops_name_before_other_fields_and_uses_ascii_email(self):
        with tempfile.TemporaryDirectory(prefix="ja_review_restore_") as folder:
            store = Store(folder)
            self._approved_store_profile(store,
                                         "姓名：张三    性别：男    年龄：25\t手机：13812345678\t邮箱：zhangsan@example.com")
            job = store.save_job({"title": "虚构岗位", "company": "虚构公司", "jd": "虚构 JD"})
            task = store.create_task({"kind": "tailor_resume", "job_id": job["id"], "instruction": "修订"})
            with store.connect() as db:
                db.execute("INSERT INTO resume_versions VALUES(?,?,?,?,?)",
                           ("version-test", job["id"], task["id"],
                            "姓名：[本地隐去]\n邮箱：[邮箱]\n手机号：[手机号]", 1))
            restored = preview_resume(store, "version-test")["content"]
            self.assertIn("姓名：张三", restored)
            self.assertIn("邮箱：zhangsan@example.com", restored)
            self.assertIn("手机号：13812345678", restored)
            self.assertNotIn("性别：男", restored)
            self.assertNotIn("年龄：25", restored)

    def test_gb18030_txt_import_falls_back_after_utf8(self):
        with tempfile.TemporaryDirectory(prefix="ja_review_txt_") as folder:
            store = Store(folder)
            imported = self._import(store, "虚构简历.txt", "虚构姓名：张三，经历：销售实习".encode("gb18030"))
            self.assertEqual(imported["extraction_status"], "extracted")
            self.assertIn("虚构姓名：张三", imported["extracted"])

    def test_empty_password_pdf_is_opened_when_pypdf_is_available(self):
        try:
            from pypdf import PdfWriter
        except ImportError:
            self.skipTest("pypdf is optional and is not installed")
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=300)
        writer.encrypt(user_password="", owner_password="synthetic-owner-password")
        stream = io.BytesIO()
        writer.write(stream)
        with tempfile.TemporaryDirectory(prefix="ja_review_pdf_") as folder:
            imported = self._import(Store(folder), "虚构空密码.pdf", stream.getvalue())
        self.assertEqual(imported["extraction_status"], "needs_ocr")

    def test_local_export_includes_user_words_without_credentials_or_lease_tokens(self):
        with tempfile.TemporaryDirectory(prefix="ja_review_export_") as folder:
            store = Store(folder)
            companion = Companion(store)
            store.save_profile({"name": "虚构姓名", "facts": "虚构经历"})
            companion.approve({"token": companion.preview_profile()["token"], "confirmed": True})
            job = store.save_job({"title": "虚构销售", "company": "虚构公司", "jd": "虚构 JD"})
            first_task = None
            for index, (kind, text) in enumerate((
                    ("interview_review", "ZZRECALL面试官问我为什么离职，我回答得不太好"),
                    ("companion_chat", "ZZCHAT我想补充一段2022年的校园销售经历")), 1):
                task = store.create_task({"kind": kind, "job_id": job["id"], "instruction": text,
                                          "companion": True, "request_id": "review-" + str(index)})
                if first_task is None:
                    first_task = task
            claimed = store.claim(first_task["id"])
            companion.save_settings({"provider": "api", "api_key": "synthetic-api-key-not-exported"})
            exported = Journey(store).export_data().decode("utf-8")
            self.assertIn("ZZRECALL", exported)
            self.assertIn("ZZCHAT", exported)
            self.assertNotIn("synthetic-api-key-not-exported", exported)
            self.assertNotIn("claim_token", exported)
            self.assertNotIn(claimed["claim_token"], exported)


if __name__ == "__main__":
    unittest.main()
