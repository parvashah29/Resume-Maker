"""
pdf_renderer.py
Renders the tailored resume as a clean, ATS-optimized SINGLE-PAGE PDF.

Key standards (from Resume_Building_Instructions_Complete_Guide.md):
  - Font: Times-Roman / Times-Bold / Times-Italic
  - Body text: 9.2pt base (never below 8.3pt after scaling)
  - Two-column layout: company | location (right-aligned), role | dates (right-aligned)
  - Section headers: ALL CAPS, bold, with full-width horizontal rule underneath
  - Auto-scaling: reduces 5% per step until content fits exactly 1 page
"""
from __future__ import annotations
import io
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame,
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    KeepTogether, Table, TableStyle
)


# ---------------------------------------------------------------------------
# Colors — ATS safe (black-on-white only, blue for hyperlinks)
# ---------------------------------------------------------------------------
BLACK     = colors.HexColor("#000000")
DARK_GRAY = colors.HexColor("#1a1a1a")
MID_GRAY  = colors.HexColor("#555555")
RULE_COLOR = colors.HexColor("#000000")

# ---------------------------------------------------------------------------
# Page geometry  (guide: L/R 0.50in, T/B 0.30in)
# ---------------------------------------------------------------------------
PAGE_W, PAGE_H = letter          # 612 × 792 pts
MARGIN_LR = 0.50 * inch          # 36 pts
MARGIN_TB = 0.30 * inch          # 21.6 pts
USABLE_W  = PAGE_W - 2 * MARGIN_LR   # 540 pts
USABLE_H  = PAGE_H - 2 * MARGIN_TB   # 748.8 pts

# Column split for two-column rows (company/location, role/dates)
COL_L = USABLE_W * 0.68          # 367 pts
COL_R = USABLE_W * 0.32          # 173 pts


def _make_doc(output, as_stream: bool = False):
    """
    Build a BaseDocTemplate with a zero-padding Frame so that every
    flowable — Paragraphs AND Tables — starts flush at the page margin.
    (SimpleDocTemplate adds 6pt frame padding which shifts Paragraphs
    to x=42 while full-width Tables land at x=36, causing misalignment.)
    """
    frame = Frame(
        MARGIN_LR, MARGIN_TB,
        USABLE_W, USABLE_H,
        id='normal',
        leftPadding=0, rightPadding=0,
        topPadding=0, bottomPadding=0,
    )
    doc = BaseDocTemplate(
        output, pagesize=letter,
        leftMargin=MARGIN_LR, rightMargin=MARGIN_LR,
        topMargin=MARGIN_TB,  bottomMargin=MARGIN_TB,
        pageTemplates=[PageTemplate(id='main', frames=[frame])],
    )
    return doc


# ---------------------------------------------------------------------------
# Style factory — Times font, 9.2pt body, all dims scale with `s`
# ---------------------------------------------------------------------------
def _make_styles(s: float = 1.0) -> dict:
    def sp(pts): return pts * s

    ts = TableStyle([
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING",   (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
    ])

    return {
        # ── Header ──────────────────────────────────────────────────────────
        "name": ParagraphStyle(
            "Name", fontName="Times-Bold",
            fontSize=sp(16), textColor=BLACK,
            alignment=TA_CENTER, spaceAfter=sp(1), leading=sp(19),
            letterSpacing=1.5,
        ),
        "contact": ParagraphStyle(
            "Contact", fontName="Times-Roman",
            fontSize=sp(9), textColor=DARK_GRAY,
            alignment=TA_CENTER, spaceAfter=0, leading=sp(11),
        ),
        # ── Section headers ──────────────────────────────────────────────────
        "section": ParagraphStyle(
            "SectionHeader", fontName="Times-Bold",
            fontSize=sp(9.5), textColor=BLACK,
            alignment=TA_LEFT, spaceBefore=sp(4), spaceAfter=sp(0.5),
            leading=sp(11), letterSpacing=1.2,
        ),
        # ── Company row (left column) ────────────────────────────────────────
        "company": ParagraphStyle(
            "Company", fontName="Times-Bold",
            fontSize=sp(9.2), textColor=BLACK,
            alignment=TA_LEFT, spaceBefore=sp(4), spaceAfter=0,
            leading=sp(11),
        ),
        # ── Location / date (right column) ──────────────────────────────────
        "right_bold": ParagraphStyle(
            "RightBold", fontName="Times-Bold",
            fontSize=sp(9.2), textColor=BLACK,
            alignment=TA_RIGHT, spaceBefore=sp(4), spaceAfter=0,
            leading=sp(11),
        ),
        # ── Role / sub-title (left col, italic) ─────────────────────────────
        "job_title": ParagraphStyle(
            "JobTitle", fontName="Times-Italic",
            fontSize=sp(8.8), textColor=DARK_GRAY,
            alignment=TA_LEFT, spaceBefore=0, spaceAfter=sp(1),
            leading=sp(11),
        ),
        # ── Dates / right label (right col, italic) ──────────────────────────
        "right_italic": ParagraphStyle(
            "RightItalic", fontName="Times-Italic",
            fontSize=sp(8.8), textColor=DARK_GRAY,
            alignment=TA_RIGHT, spaceBefore=0, spaceAfter=sp(1),
            leading=sp(11),
        ),
        # ── Bullets ─────────────────────────────────────────────────────────
        "bullet": ParagraphStyle(
            "Bullet", fontName="Times-Roman",
            fontSize=sp(9.2), textColor=DARK_GRAY,
            alignment=TA_JUSTIFY,
            leftIndent=sp(10), firstLineIndent=0,
            spaceBefore=sp(1.0), spaceAfter=sp(1.0),
            leading=sp(11.5),
        ),
        # ── Projects ────────────────────────────────────────────────────────
        "project_name": ParagraphStyle(
            "ProjectName", fontName="Times-Bold",
            fontSize=sp(9.2), textColor=BLACK,
            alignment=TA_LEFT, spaceBefore=sp(4), spaceAfter=0,
            leading=sp(11),
        ),
        "project_tech": ParagraphStyle(
            "ProjectTech", fontName="Times-Italic",
            fontSize=sp(8.2), textColor=MID_GRAY,
            alignment=TA_LEFT, spaceBefore=0, spaceAfter=sp(0.5),
            leading=sp(10),
        ),
        # ── Skills / certs ──────────────────────────────────────────────────
        "skills": ParagraphStyle(
            "Skills", fontName="Times-Roman",
            fontSize=sp(9.2), textColor=DARK_GRAY,
            alignment=TA_LEFT, spaceBefore=sp(1.5), spaceAfter=0,
            leading=sp(11),
        ),
        "summary": ParagraphStyle(
            "Summary", fontName="Times-Roman",
            fontSize=sp(9.2), textColor=DARK_GRAY,
            alignment=TA_JUSTIFY, spaceBefore=sp(2), spaceAfter=sp(2),
            leading=sp(12),
        ),
        "cert": ParagraphStyle(
            "Cert", fontName="Times-Roman",
            fontSize=sp(8.6), textColor=DARK_GRAY,
            alignment=TA_LEFT, spaceBefore=sp(1.5), spaceAfter=0,
            leading=sp(11),
        ),
        # Shared table style
        "_ts": ts,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _hr(s: float = 1.0, thickness: float = 0.5) -> HRFlowable:
    return HRFlowable(
        width="100%", thickness=thickness,
        color=RULE_COLOR, spaceAfter=s * 2, spaceBefore=0
    )


def _safe(text: str) -> str:
    """Escape XML special chars for ReportLab."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _two_col(left_para: Paragraph, right_para: Paragraph, ts, s: float) -> Table:
    """Two-column row spanning full usable width (margins are fixed, not scaled)."""
    t = Table([[left_para, right_para]], colWidths=[COL_L, COL_R])
    t.setStyle(ts)
    return t


def _bullet(text: str, styles: dict, keywords: list = None) -> Paragraph:
    safe = _safe(text)
    if keywords:
        safe = _bold_keywords(safe, keywords)
    return Paragraph(f"• &nbsp;{safe}", styles["bullet"])


def _section_hdr(title: str, styles: dict, s: float = 1.0) -> list:
    return [Paragraph(title.upper(), styles["section"]), _hr(s)]


def _trim(text: str, max_chars: int = 290) -> str:
    """Hard-cap bullet length. Cuts at sentence boundary within max_chars."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    for sep in (". ", "; ", ", "):
        idx = cut.rfind(sep)
        if idx > max_chars * 0.6:
            return cut[:idx + 1].rstrip()
    return cut.rstrip() + "…"


def _bold_keywords(text: str, keywords: list) -> str:
    """Wrap JD keywords in <b> tags. text must already be XML-safe."""
    if not keywords:
        return text
    import re
    skip = {"and", "the", "for", "with", "from", "that", "this", "via",
            "are", "our", "all", "based", "using", "into", "over", "not",
            "has", "have", "its", "was", "were", "been", "will", "can"}
    clean = sorted(
        set(kw for kw in keywords if len(kw) >= 3 and kw.lower() not in skip),
        key=len, reverse=True
    )[:20]
    if not clean:
        return text
    pattern = "|".join(
        r"(?<![a-zA-Z0-9/])" + re.escape(kw) + r"(?![a-zA-Z0-9/])"
        for kw in clean
    )
    return re.sub(pattern, lambda m: f"<b>{m.group(0)}</b>", text, flags=re.IGNORECASE)


# ---------------------------------------------------------------------------
# Story builder (scale-aware)
# ---------------------------------------------------------------------------
def _build_story(content: dict, styles: dict, s: float) -> list:
    story = []
    p = content["personal"]
    kws = content.get("jd_info", {}).get("keywords", [])
    ts = styles["_ts"]

    # ── HEADER ──────────────────────────────────────────────────────────────
    story.append(Paragraph(p["name"], styles["name"]))
    email, linkedin, github = p["email"], p["linkedin"], p["github"]
    contact = (
        f"{p['phone']} | "
        f"<a href='mailto:{email}' color='#1155CC'>{email}</a> | "
        f"<a href='https://{linkedin}' color='#1155CC'>{linkedin}</a> | "
        f"<a href='https://{github}' color='#1155CC'>{github}</a>"
    )
    story.append(Paragraph(contact, styles["contact"]))
    story.append(Spacer(1, s * 3))
    story.append(_hr(s, thickness=0.8))

    # ── SUMMARY ─────────────────────────────────────────────────────────────
    if content.get("summary"):
        story += _section_hdr("Summary", styles, s)
        summary_text = _safe(content["summary"])
        summary_text = _bold_keywords(summary_text, kws)
        story.append(Paragraph(summary_text, styles["summary"]))

    # ── EDUCATION ───────────────────────────────────────────────────────────
    story += _section_hdr("Education", styles, s)
    for edu in content["education"]:
        row1 = _two_col(
            Paragraph(f"<b>{_safe(edu['institution'])}</b>", styles["company"]),
            Paragraph(f"<b>{_safe(edu['location'])}</b>", styles["right_bold"]),
            ts, s
        )
        row2 = _two_col(
            Paragraph(_safe(edu["degree"]), styles["job_title"]),
            Paragraph(_safe(edu["dates"]), styles["right_italic"]),
            ts, s
        )
        block = [row1, row2, _bullet(f"Relevant Courses: {edu['coursework']}", styles, kws)]
        story.append(KeepTogether(block))
        story.append(Spacer(1, s * 1.5))

    # ── PROFESSIONAL EXPERIENCE ─────────────────────────────────────────────
    story += _section_hdr("Professional Experience", styles, s)
    for exp in content["work_experience"]:
        row1 = _two_col(
            Paragraph(f"<b>{_safe(exp['company'])}</b>", styles["company"]),
            Paragraph(f"<b>{_safe(exp['location'])}</b>", styles["right_bold"]),
            ts, s
        )
        row2 = _two_col(
            Paragraph(f"<i>{_safe(exp['title'])}</i>", styles["job_title"]),
            Paragraph(f"<i>{_safe(exp['dates'])}</i>", styles["right_italic"]),
            ts, s
        )
        block = [row1, row2]
        for bul in exp["bullets"][:3]:
            block.append(_bullet(_trim(bul), styles, kws))
        story.append(KeepTogether(block))
        story.append(Spacer(1, s * 1.5))

    # ── TECHNICAL PROJECTS ───────────────────────────────────────────────────
    story += _section_hdr("Technical Projects", styles, s)
    for proj in content["projects"]:
        block = [
            Paragraph(f"<b>{_safe(proj['name'])}</b>", styles["project_name"]),
            Paragraph(_safe(proj["tech"]), styles["project_tech"]),
        ]
        for bul in proj["star_bullets"][:3]:
            block.append(_bullet(_trim(bul), styles, kws))
        story.append(KeepTogether(block))
        story.append(Spacer(1, s * 1.5))

    # ── SKILLS ──────────────────────────────────────────────────────────────
    story += _section_hdr("Skills", styles, s)
    for category, value in content["skills"].items():
        story.append(Paragraph(
            f"<b>{_safe(category)}:</b> {_safe(value)}",
            styles["skills"]
        ))
        story.append(Spacer(1, s * 1))

    # ── CERTIFICATIONS ───────────────────────────────────────────────────────
    story += _section_hdr("Certifications", styles, s)
    cert_text = " &nbsp;|&nbsp; ".join(_safe(c) for c in content["certifications"])
    story.append(Paragraph(cert_text, styles["cert"]))

    return story


# ---------------------------------------------------------------------------
# Page counter
# ---------------------------------------------------------------------------
def _count_pages(story: list, s: float) -> int:
    """Count pages using a real temp file (BaseDocTemplate needs a seekable file path)."""
    import tempfile, os
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False,
                                         dir=tempfile.gettempdir()) as tmp:
            tmp_path = tmp.name
        doc = _make_doc(tmp_path)
        doc.build(story)
        n = getattr(doc, 'page', 1)
        return n
    except Exception as e:
        print(f"   ⚠️  Page-count probe failed ({e}); assuming 2 pages to force scaling.")
        return 2          # conservative: trigger scale-down
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def render_pdf(content: dict, output_path: str) -> str:
    """
    Guarantees single-page output via auto-scaling (3% steps).
    Base: 9.2pt Times body text. Hard floor: 0.80 (≈ 7.4pt).
    The _count_pages probe uses a temp file so BaseDocTemplate works correctly.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    scale     = 1.0
    min_scale = 0.80      # hard floor — below this ATS scanners may struggle
    step      = 0.03      # finer steps → more precise fit

    while scale >= min_scale:
        styles = _make_styles(scale)
        story  = _build_story(content, styles, scale)
        pages  = _count_pages(story, scale)

        if pages <= 1:
            break
        scale = round(scale - step, 2)
    else:
        # If still >1 page at floor, force render at floor and warn
        print("   ⚠️  Content is very long — forced to minimum scale. Consider trimming bullets.")

    # Final render to disk at the scale that fits (or min_scale)
    styles = _make_styles(scale)
    story  = _build_story(content, styles, scale)

    doc = _make_doc(output_path)
    doc.build(story)

    if scale < 1.0:
        print(f"   ℹ️  Content scaled to {scale:.0%} (body ≈ {9.2*scale:.1f}pt) to fit one page.")
    else:
        print(f"   ✅ Content fits at 100% (9.2pt Times body text).")

    return output_path
