"""Bounded imports. Extracted content is a draft until the user saves the profile."""
import base64
import binascii
import io
import re
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .store import Problem, text_field

MAX_FILE = 5 * 1024 * 1024
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def _docx_paragraphs(root):
    """Yield only outer paragraphs; nested text-box paragraphs belong to them."""
    parents = {child: parent for parent in root.iter() for child in parent}
    for paragraph in root.iter(f"{{{WORD_NS}}}p"):
        parent = parents.get(paragraph)
        nested = False
        while parent is not None:
            if parent.tag == f"{{{WORD_NS}}}p":
                nested = True
                break
            parent = parents.get(parent)
        if not nested:
            yield paragraph


def _docx_paragraph_text(paragraph):
    pieces = []

    def visit(node):
        if node.tag in {f"{{{WORD_NS}}}del", f"{{{WORD_NS}}}moveFrom", f"{{{MC_NS}}}Fallback"}:
            return
        if node.tag == f"{{{WORD_NS}}}t":
            pieces.append(node.text or "")
            return
        if node.tag == f"{{{WORD_NS}}}tab":
            pieces.append("\t")
            return
        if node.tag in {f"{{{WORD_NS}}}br", f"{{{WORD_NS}}}cr"}:
            pieces.append("\n")
            return
        for child in node:
            visit(child)

    visit(paragraph)
    return "".join(pieces)


def _docx_text(archive, document_xml):
    roots = [ElementTree.fromstring(document_xml)]
    story_parts = sorted(
        name for name in archive.namelist()
        if re.fullmatch(r"word/(?:header|footer)\d+\.xml", name)
    )
    total_size = len(document_xml)
    for name in story_parts:
        info = archive.getinfo(name)
        total_size += info.file_size
        if total_size > MAX_FILE:
            raise Problem("DOCX 文本过大")
        xml = archive.read(info)
        if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
            raise Problem("不支持含自定义实体的 DOCX")
        roots.append(ElementTree.fromstring(xml))
    return "\n".join(
        text for root in roots for paragraph in _docx_paragraphs(root)
        if (text := _docx_paragraph_text(paragraph))
    )


def clean_text(value):
    # Word field codes often leak into XML extraction as: HYPERLINK "url" display-text.
    value = re.sub(r'\bHYPERLINK\s+"[^"]*"\s*', '', value, flags=re.I)
    value = value.replace("\u00a0", " ").replace("\x00", "")
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def import_document(store, payload):
    name = text_field(payload.get("name", ""), "name", 200, True)
    name = name.replace("\\", "/").split("/")[-1]
    suffix = Path(name).suffix.lower()
    if suffix not in {".txt", ".md", ".docx", ".pdf"}:
        raise Problem("支持 TXT、Markdown、DOCX、PDF；截图 OCR 尚未接入")
    try:
        raw = base64.b64decode(payload.get("base64", ""), validate=True)
    except (ValueError, TypeError, binascii.Error):
        raise Problem("文件编码无效")
    if not raw or len(raw) > MAX_FILE:
        raise Problem("文件不能为空，最大 5 MB")
    status = "extracted"
    try:
        if suffix in {".txt", ".md"}:
            try:
                extracted = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                extracted = raw.decode("gb18030")
        elif suffix == ".docx":
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > MAX_FILE:
                    raise Problem("DOCX 文本过大")
                xml = archive.read(info)
                if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
                    raise Problem("不支持含自定义实体的 DOCX")
                extracted = _docx_text(archive, xml)
        else:
            if not raw.startswith(b"%PDF-"):
                raise Problem("无效的 PDF 文件")
            try:
                from pypdf import PdfReader
            except ImportError:
                extracted, status = "", "parser_missing"
            else:
                reader = PdfReader(io.BytesIO(raw))
                if reader.is_encrypted:
                    try:
                        unlocked = reader.decrypt("")
                    except Exception:
                        unlocked = 0
                    if not unlocked:
                        extracted, status = "", "encrypted"
                    else:
                        if len(reader.pages) > 30:
                            raise Problem("简历 PDF 最大支持 30 页")
                        extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
                else:
                    if len(reader.pages) > 30:
                        raise Problem("简历 PDF 最大支持 30 页")
                    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
        extracted = clean_text(extracted)
        if len(extracted) > 80000:
            raise Problem("提取文本超过 80000 字，请缩短后导入")
        if not extracted.strip() and status == "extracted":
            status = "needs_ocr"
    except Problem:
        raise
    except Exception:
        raise Problem("文件无法解析；请另存为文本或未加密文件重试")
    doc_id = uuid.uuid4().hex
    folder = store.directory / "uploads"
    folder.mkdir(exist_ok=True, mode=0o700)
    storage_name = doc_id + suffix
    dest = folder / storage_name
    with dest.open("xb") as f:
        f.write(raw)
    dest.chmod(0o600)
    store.add_document(doc_id, name, storage_name, extracted, status)
    return {"id": doc_id, "name": name, "extracted": extracted, "extraction_status": status}
