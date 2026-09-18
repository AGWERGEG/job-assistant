"""One local Chinese resume template. Optional, established export libraries."""
import io
import os
import re
from pathlib import Path
from xml.sax.saxutils import escape
from .store import Problem, text_field

SECTIONS={'个人简介','求职意向','教育经历','工作经历','实习经历','项目经历','校园经历','技能','技能与证书','专业技能','自我评价','职业摘要','个人优势'}


def lines(content):
    for raw in content.splitlines():
        value=raw.strip()
        if not value:continue
        title=value.lstrip('#').strip().strip('*').strip('【】').rstrip('：:')
        heading=value.startswith('#') or title in SECTIONS or (value.startswith('【') and value.endswith('】') and len(value)<25)
        bullet=bool(re.match(r'^[-*•]\s*',value))
        value=re.sub(r'^#{1,6}\s*','',value)
        value=re.sub(r'^[-*•]\s*','',value).replace('**','')
        if heading:value=title
        yield heading,bullet,value


def export_resume(store,version_id,format,content=None):
    version_id=text_field(version_id,'简历版本',100,True)
    with store.connect() as db:
        row=db.execute('SELECT * FROM resume_versions WHERE id=?',(version_id,)).fetchone()
    if not row:raise Problem('简历版本不存在',404)
    content=row['content'] if content is None else content
    out=io.BytesIO()
    if format=='docx':
        try:
            from docx import Document
            from docx.shared import Inches,Pt,RGBColor
            from docx.oxml.ns import qn
        except ImportError:raise Problem('请安装 requirements.txt 中的 python-docx 后导出Word',503)
        doc=Document()
        for node in list(doc.element.body):
            if node.tag!=qn('w:sectPr'):doc.element.body.remove(node)
        sec=doc.sections[0];sec.page_width=Inches(8.5);sec.page_height=Inches(11)
        for part in (sec.header,sec.footer):
            for p in part.paragraphs:p.clear()
        sec.top_margin=sec.bottom_margin=Inches(.72);sec.left_margin=sec.right_margin=Inches(.8)
        for key in ('Normal','Title','Heading 1'):
            st=doc.styles[key];st.font.name='Heiti SC' if os.name=='posix' and Path('/System/Library/Fonts/STHeiti Light.ttc').exists() else 'Microsoft YaHei';st.font.color.rgb=RGBColor(0,0,0)
            fonts=st._element.get_or_add_rPr().get_or_add_rFonts()
            for attr in ('ascii','hAnsi','eastAsia','cs'):fonts.set(qn('w:'+attr),st.font.name)
            for attr in ('asciiTheme','hAnsiTheme','eastAsiaTheme','cstheme'):
                fonts.attrib.pop(qn('w:'+attr),None)
            for border in st._element.xpath('.//w:pBdr'):border.getparent().remove(border)
        doc.styles['Normal'].font.size=Pt(11);doc.styles['Normal'].paragraph_format.space_after=Pt(5)
        doc.styles['Normal'].paragraph_format.line_spacing=1.25
        doc.styles['Title'].font.size=Pt(20);doc.styles['Heading 1'].font.size=Pt(13)
        doc.add_paragraph('个人简历','Title')
        for heading,bullet,value in lines(content):
            p=doc.add_paragraph(value,'Heading 1' if heading else 'Normal')
            if bullet:p.paragraph_format.left_indent=Inches(.12)
        doc.core_properties.author='';doc.core_properties.last_modified_by='';doc.save(out)
        return out.getvalue(),'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    if format=='pdf':
        try:
            from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer
            from reportlab.lib.styles import ParagraphStyle
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.lib.pagesizes import letter
        except ImportError:raise Problem('请安装 requirements.txt 中的 reportlab 后导出PDF',503)
        candidates=[os.environ.get('JOB_ASSISTANT_CJK_FONT',''),'/System/Library/Fonts/STHeiti Light.ttc','C:/Windows/Fonts/msyh.ttc','C:/Windows/Fonts/simsun.ttc','/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc']
        font=next((p for p in candidates if p and Path(p).is_file()),None)
        if not font:raise Problem('PDF需可嵌入的中文TTF字体；设置JOB_ASSISTANT_CJK_FONT后重试，或先导出Word',503)
        pdfmetrics.registerFont(TTFont('ResumeCJK',font,subfontIndex=0))
        body=ParagraphStyle('body',fontName='ResumeCJK',fontSize=11,leading=17,spaceAfter=6,wordWrap='CJK')
        title=ParagraphStyle('title',parent=body,fontSize=20,leading=28,spaceAfter=16)
        heading=ParagraphStyle('heading',parent=body,fontSize=13,leading=20,spaceBefore=10,spaceAfter=6,keepWithNext=True)
        story=[Paragraph('个人简历',title)]
        for isheading,bullet,value in lines(content):story.append(Paragraph(escape(value),heading if isheading else body))
        SimpleDocTemplate(out,pagesize=letter,rightMargin=58,leftMargin=58,topMargin=52,bottomMargin=52,title='个人简历',author='').build(story)
        return out.getvalue(),'application/pdf'
    if format=='txt':return content.encode(),'text/plain; charset=utf-8'
    raise Problem('支持PDF、DOCX、TXT导出')
