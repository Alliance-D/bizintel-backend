from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from textwrap import wrap
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

BRAND = (16 / 255, 35 / 255, 31 / 255)
TEAL = (15 / 255, 118 / 255, 110 / 255)
MINT = (236 / 255, 253 / 255, 245 / 255)
SLATE = (71 / 255, 85 / 255, 105 / 255)
LINE = (226 / 255, 217 / 255, 205 / 255)
AMBER = (245 / 255, 158 / 255, 11 / 255)
ROSE = (225 / 255, 29 / 255, 72 / 255)
BG = (251 / 255, 250 / 255, 247 / 255)


def _safe_number(value, fallback=0):
    """Coerce a value to a number, falling back when it is not numeric."""
    try:
        numeric = float(value)
        if numeric != numeric:
            return fallback
        return numeric
    except Exception:
        return fallback


def _label_score(value: float) -> str:
    """Map a 0-100 score to a short qualitative label."""
    if value >= 78:
        return "Strong"
    if value >= 60:
        return "Promising"
    return "Needs checks"


def _wrap_text(pdf: canvas.Canvas, text: str, x: float, y: float, max_chars: int, leading: float = 12, font: str = "Helvetica", size: int = 9, color=SLATE, max_lines: int | None = None) -> float:
    """Draw text wrapped to a character width and return the new y position."""
    pdf.setFont(font, size)
    pdf.setFillColorRGB(*color)
    lines = wrap(str(text or ""), width=max_chars) or [""]
    if max_lines:
        lines = lines[:max_lines]
    for line in lines:
        pdf.drawString(x, y, line)
        y -= leading
    return y


def _section_title(pdf: canvas.Canvas, title: str, x: float, y: float) -> float:
    """Draw a section title and return the y position below it."""
    pdf.setFillColorRGB(*BRAND)
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(x, y, title)
    return y - 18


def _card(pdf: canvas.Canvas, x: float, y: float, w: float, h: float, title: str, value: str, subtitle: str, accent=TEAL):
    """Draw a titled stat card and return its bottom y position."""
    pdf.setFillColorRGB(1, 1, 1)
    pdf.setStrokeColorRGB(*LINE)
    pdf.roundRect(x, y - h, w, h, 12, fill=1, stroke=1)
    pdf.setFillColorRGB(*SLATE)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(x + 12, y - 18, title.upper())
    pdf.setFillColorRGB(*BRAND)
    pdf.setFont("Helvetica-Bold", 24)
    pdf.drawString(x + 12, y - 45, value)
    pdf.setFillColorRGB(*accent)
    pdf.roundRect(x + 12, y - h + 14, max(18, min(w - 24, float(value) / 100 * (w - 24))) if value.replace('.', '', 1).isdigit() else 48, 5, 2, fill=1, stroke=0)
    pdf.setFillColorRGB(*SLATE)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(x + 12, y - h + 28, subtitle[:42])


def _bar(pdf: canvas.Canvas, x: float, y: float, label: str, value: float, color=TEAL) -> float:
    """Draw a labelled horizontal bar for a 0-100 value."""
    safe = max(0, min(100, _safe_number(value)))
    pdf.setFont("Helvetica-Bold", 9)
    pdf.setFillColorRGB(*BRAND)
    pdf.drawString(x, y, label)
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawRightString(x + 250, y, str(round(safe)))
    pdf.setFillColorRGB(240 / 255, 245 / 255, 245 / 255)
    pdf.roundRect(x, y - 12, 250, 6, 3, fill=1, stroke=0)
    pdf.setFillColorRGB(*color)
    pdf.roundRect(x, y - 12, safe / 100 * 250, 6, 3, fill=1, stroke=0)
    return y - 28


def _bullet_list(pdf: canvas.Canvas, items: list[str], x: float, y: float, max_chars: int, max_items: int = 6) -> float:
    """Draw a capped bulleted list and return the y position below it."""
    pdf.setFont("Helvetica", 9)
    pdf.setFillColorRGB(*SLATE)
    for item in (items or [])[:max_items]:
        lines = wrap(str(item), width=max_chars)
        pdf.setFillColorRGB(*TEAL)
        pdf.circle(x + 3, y + 3, 2, fill=1, stroke=0)
        pdf.setFillColorRGB(*SLATE)
        for idx, line in enumerate(lines):
            pdf.drawString(x + 12, y - idx * 11, line)
        y -= max(16, len(lines) * 11 + 6)
    return y


def _draw_header(pdf: canvas.Canvas, title: str, width: float, height: float):
    """Draw the report's page header."""
    pdf.setFillColorRGB(*BRAND)
    pdf.roundRect(1.4 * cm, height - 2.15 * cm, 34, 34, 9, fill=1, stroke=0)
    pdf.setFillColorRGB(1, 1, 1)
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawCentredString(1.4 * cm + 17, height - 1.78 * cm, "B")
    pdf.setFillColorRGB(*BRAND)
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(2.5 * cm, height - 1.55 * cm, "BizIntel")
    pdf.setFillColorRGB(*SLATE)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(2.5 * cm, height - 1.86 * cm, "Location intelligence report")
    pdf.setStrokeColorRGB(*LINE)
    pdf.line(1.4 * cm, height - 2.45 * cm, width - 1.4 * cm, height - 2.45 * cm)


def _draw_footer(pdf: canvas.Canvas, page: int, width: float):
    """Draw the report's page footer with the page number."""
    pdf.setStrokeColorRGB(*LINE)
    pdf.line(1.4 * cm, 1.45 * cm, width - 1.4 * cm, 1.45 * cm)
    pdf.setFillColorRGB(*SLATE)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(1.4 * cm, 1.05 * cm, "BizIntel location intelligence - for shortlist, comparison and field validation")
    pdf.drawRightString(width - 1.4 * cm, 1.05 * cm, f"Page {page}")


def build_pdf_report(report: dict) -> bytes:
    """Render a location-report dict to PDF bytes."""
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 1.4 * cm

    title = str(report.get("title") or "Location decision report")
    category = str(report.get("business_category") or "business")
    latitude = report.get("latitude", "n/a")
    longitude = report.get("longitude", "n/a")
    score = _safe_number(report.get("overall_score") or report.get("opportunity_score"), 76)
    confidence_raw = report.get("confidence", report.get("confidence_score", 81))
    confidence = 81 if isinstance(confidence_raw, str) else _safe_number(confidence_raw, 81)
    opportunity_type = str(report.get("opportunity_type") or _label_score(score))
    factors = report.get("factors") or []
    strengths = report.get("strengths") or ["Demand and access signals support further review", "Commercial activity suggests possible customer flow"]
    risks = report.get("risks") or ["Competition pressure should be confirmed on the street", "Rent and space availability are not guaranteed by public data"]
    checklist = report.get("field_visit_checklist") or []
    next_steps = report.get("recommended_next_steps") or ["Compare at least two alternative locations", "Visit the area during peak and quiet hours", "Confirm rent, frontage, visibility and informal competitors"]
    competitive = report.get("competitive_analysis") or {}

    _draw_header(pdf, title, width, height)
    y = height - 3.15 * cm
    pdf.setFillColorRGB(*BRAND)
    pdf.setFont("Helvetica-Bold", 24)
    pdf.drawString(margin, y, title[:54])
    y -= 18
    pdf.setFillColorRGB(*SLATE)
    pdf.setFont("Helvetica", 10)
    pdf.drawString(margin, y, f"{category.title()} - {latitude}, {longitude}")
    pdf.drawRightString(width - margin, y, "Generated report")
    y -= 26

    pdf.setFillColorRGB(*MINT)
    pdf.roundRect(margin, y - 58, width - 2 * margin, 58, 12, fill=1, stroke=0)
    pdf.setFillColorRGB(*BRAND)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(margin + 12, y - 18, "Executive summary")
    y2 = _wrap_text(pdf, report.get("executive_summary") or f"This location is classified as {opportunity_type}. Use the score as a decision signal before committing to rent or lease terms", margin + 12, y - 34, 92, leading=11, size=8.7, max_lines=2)
    y -= 78

    card_w = (width - 2 * margin - 18) / 3
    _card(pdf, margin, y, card_w, 78, "Opportunity", f"{round(score)}", "Overall fit signal", TEAL)
    _card(pdf, margin + card_w + 9, y, card_w, 78, "Confidence", f"{round(confidence)}", "Data reliability", TEAL)
    _card(pdf, margin + (card_w + 9) * 2, y, card_w, 78, "Class", f"{round(score)}", opportunity_type[:32], AMBER if score < 78 else TEAL)
    y -= 104

    y = _section_title(pdf, "Score profile", margin, y)
    factor_map = {str(f.get("label") or f.get("key", "")).lower(): _safe_number(f.get("score"), 0) for f in factors if isinstance(f, dict)}
    demand = factor_map.get("demand", factor_map.get("demand score", _safe_number(report.get("demand_score"), max(0, score + 8))))
    access = factor_map.get("access", factor_map.get("accessibility", _safe_number(report.get("access_score"), max(0, score + 5))))
    competition = factor_map.get("competition", factor_map.get("competition pressure", _safe_number(report.get("competition_pressure"), 63)))
    activity = factor_map.get("commercial activity", factor_map.get("activity", _safe_number(report.get("commercial_activity_score"), max(0, score + 2))))
    y = _bar(pdf, margin, y, "Demand", demand, TEAL)
    y = _bar(pdf, margin, y, "Access", access, TEAL)
    y = _bar(pdf, margin, y, "Commercial activity", activity, TEAL)
    y = _bar(pdf, margin, y, "Competition pressure", competition, AMBER if competition < 75 else ROSE)

    x2 = width / 2 + 0.4 * cm
    y_right = y + 112
    y_right = _section_title(pdf, "Competitive context", x2, y_right)
    context = competitive.get("summary") or "Competition pressure must be read together with demand, access and differentiation. High demand can still be useful when the business has a distinct offer"
    y_right = _wrap_text(pdf, context, x2, y_right, 47, leading=11, size=9, max_lines=5)
    y_right -= 6
    pdf.setFillColorRGB(*MINT)
    pdf.roundRect(x2, y_right - 46, width - margin - x2, 46, 10, fill=1, stroke=0)
    pdf.setFillColorRGB(*BRAND)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(x2 + 10, y_right - 18, "Recommended strategy")
    _wrap_text(pdf, "Compare this site with at least two nearby alternatives, then validate rent, frontage, foot traffic and informal competitors", x2 + 10, y_right - 32, 44, leading=10, size=8.4, max_lines=2)

    y = min(y, y_right - 62)
    y -= 4
    y = _section_title(pdf, "Strengths", margin, y)
    y = _bullet_list(pdf, strengths, margin, y, 76, 4)
    y -= 8
    y = _section_title(pdf, "Risks to verify", margin, y)
    y = _bullet_list(pdf, risks, margin, y, 76, 4)

    _draw_footer(pdf, 1, width)
    pdf.showPage()

    _draw_header(pdf, title, width, height)
    y = height - 3.1 * cm
    y = _section_title(pdf, "Field validation checklist", margin, y)
    y = _bullet_list(pdf, checklist, margin, y, 95, 8)
    y -= 10
    y = _section_title(pdf, "Recommended next steps", margin, y)
    y = _bullet_list(pdf, next_steps, margin, y, 95, 6)
    y -= 12

    pdf.setFillColorRGB(1, 1, 1)
    pdf.setStrokeColorRGB(*LINE)
    pdf.roundRect(margin, y - 90, width - 2 * margin, 90, 14, fill=1, stroke=1)
    pdf.setFillColorRGB(*BRAND)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(margin + 14, y - 22, "Important use note")
    _wrap_text(pdf, "This report supports decision making. It is not a guarantee of revenue, profit, rent availability, regulatory approval or business success. Use it to shortlist, compare and prepare field checks before committing", margin + 14, y - 42, 95, leading=12, size=9, max_lines=4)

    _draw_footer(pdf, 2, width)
    pdf.save()
    return buffer.getvalue()


# --- Unified report (the /start -> /report/[token] flow) -------------------

def _gap_verdict(expected: float, observed: float) -> str:
    """Verdict from absolute expected-vs-observed counts - the same bands the
    web report uses, so the PDF and the page never disagree."""
    room = expected - observed
    if expected < 0.75 and abs(room) < 1:
        return "Thin demand"
    if room <= -0.75:
        return "Saturated"
    if room >= 1.5:
        return "Underserved"
    if room >= 0.5:
        return "Room to grow"
    return "Balanced"


def _plural(word: str) -> str:
    """English plural of a category word (pharmacy -> pharmacies)."""
    w = word.strip()
    if w.endswith("y") and len(w) > 1 and w[-2].lower() not in "aeiou":
        return w[:-1] + "ies"
    return w if w.endswith("s") else w + "s"


def build_unified_pdf(report: dict) -> bytes:
    """Render a unified report to a branded PDF, dispatching by report mode so
    single-point, area (ranked shortlist) and compare (head-to-head) reports all
    render real content rather than an empty single-location template."""
    if report.get("comparison"):
        return _build_compare_pdf(report)
    entries = report.get("entries") or []
    point = next((e for e in entries if e.get("mode") == "point"), None)
    if point is not None:
        return _build_point_pdf(report, point)
    area = next((e for e in entries if e.get("mode") == "area"), None)
    if area is not None:
        return _build_area_pdf(report, area)
    return _build_point_pdf(report, {})


def _build_point_pdf(report: dict, entry: dict) -> bytes:
    """Branded single-location page: verdict, capacity, signals, narrative, checklist."""
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 1.4 * cm

    category = str(report.get("business_category") or "business").replace("_", " ")
    cats = _plural(category)
    assessment = entry.get("assessment") or {}
    overall = assessment.get("overall") or {}
    signals = assessment.get("signals") or {}
    label = entry.get("label") or assessment.get("landmark") or assessment.get("location_label") or "Kigali"

    expected = _safe_number(overall.get("expected_count"))
    observed = _safe_number(overall.get("observed_count"))
    room = expected - observed
    verdict = _gap_verdict(expected, observed)
    confidence = _safe_number(overall.get("confidence_score"))
    narrative = ((entry.get("narrative") or {}).get("advice")) or ""

    _draw_header(pdf, "BizIntel", width, height)
    y = height - 3.15 * cm
    pdf.setFillColorRGB(*BRAND)
    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawString(margin, y, f"{category.title()} location report"[:52])
    y -= 18
    pdf.setFillColorRGB(*SLATE)
    pdf.setFont("Helvetica", 10)
    pdf.drawString(margin, y, str(label)[:70])
    pdf.drawRightString(width - margin, y, datetime.now(timezone.utc).strftime("%d %b %Y"))
    y -= 26

    # Verdict banner + plain-language summary
    pdf.setFillColorRGB(*MINT)
    pdf.roundRect(margin, y - 58, width - 2 * margin, 58, 12, fill=1, stroke=0)
    pdf.setFillColorRGB(*BRAND)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(margin + 12, y - 20, verdict.upper())
    summary = f"The area looks able to support about {expected:.0f} {cats}; {observed:.0f} are open within a kilometre."
    _wrap_text(pdf, summary, margin + 12, y - 38, 92, leading=11, size=9)
    y -= 78

    # Capacity cards: open now / room-or-over / can support
    card_w = (width - 2 * margin - 18) / 3
    over = observed > expected
    _card(pdf, margin, y, card_w, 78, "Open now", f"{observed:.0f}", f"{cats} within 1 km", TEAL)
    if over:
        _card(pdf, margin + card_w + 9, y, card_w, 78, "Over capacity", f"+{observed - expected:.0f}", "more than expected", ROSE)
    else:
        _card(pdf, margin + card_w + 9, y, card_w, 78, "Room", f"+{max(0.0, room):.0f}", "could be supported", TEAL)
    _card(pdf, margin + (card_w + 9) * 2, y, card_w, 78, "Can support", f"{max(expected, 0):.0f}", "from area fundamentals", AMBER if over else TEAL)
    y -= 104

    # Signals
    y = _section_title(pdf, "The signals behind it", margin, y)
    rows = [
        ("People nearby (within 1 km)", f"{_safe_number(signals.get('people_within_1km')):,.0f}"),
        ("Commercial activity", str(signals.get("commercial_activity_level") or "-")),
        (f"{cats.title()} already open", f"{observed:.0f}"),
        ("Foot-traffic anchors (within 1 km)", f"{_safe_number(signals.get('anchor_count_1000m')):,.0f}"),
        ("Model estimate", f"~ {expected:.1f} {cats}"),
    ]
    pdf.setFont("Helvetica", 9)
    for name, value in rows:
        pdf.setFillColorRGB(*SLATE)
        pdf.setFont("Helvetica", 9)
        pdf.drawString(margin, y, name)
        pdf.setFillColorRGB(*BRAND)
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawRightString(margin + 250, y, value)
        pdf.setStrokeColorRGB(*LINE)
        pdf.line(margin, y - 6, margin + 250, y - 6)
        y -= 18

    # Why this location (AI narrative), on the right column
    x2 = width / 2 + 0.4 * cm
    y_right = y + 5 * 18 + 18
    y_right = _section_title(pdf, "Why this location", x2, y_right)
    narrative_text = narrative or "A written explanation was not available when this report was generated."
    narr_bottom = _wrap_text(pdf, narrative_text, x2, y_right, 46, leading=11, size=9, max_lines=14)

    # Start the full-width section below whichever column ran lower.
    y = min(y, narr_bottom) - 14
    y = _section_title(pdf, "Before you decide", margin, y)
    y = _bullet_list(pdf, [
        "Visit at morning, midday and evening to see how the foot traffic changes.",
        f"Walk the street and count the {cats} you can see, including small informal stalls.",
        "Check how easily customers reach the spot on foot from the nearest road and bus stop.",
        "Ask nearby shopkeepers and residents what they still travel elsewhere to buy.",
    ], margin, y, 92, 4)

    y -= 6
    pdf.setFillColorRGB(*SLATE)
    pdf.setFont("Helvetica", 8.5)
    pdf.drawString(margin, y, f"Confidence: {confidence:.0f}%   ·   Based on mapped {cats} within 1 km   ·   Informal shops uncounted")
    y -= 22

    pdf.setFillColorRGB(1, 1, 1)
    pdf.setStrokeColorRGB(*LINE)
    pdf.roundRect(margin, y - 66, width - 2 * margin, 66, 12, fill=1, stroke=1)
    pdf.setFillColorRGB(*BRAND)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(margin + 12, y - 20, "How to use this report")
    _wrap_text(pdf, "This measures the gap between the demand an area's fundamentals predict and the businesses observed there. It is a decision signal for shortlisting and field validation, not a prediction of revenue, profit or business success.", margin + 12, y - 38, 95, leading=11, size=8.6, max_lines=3)

    _draw_footer(pdf, 1, width)
    pdf.save()
    return buffer.getvalue()


def _candidate_counts(c: dict) -> tuple[float, float]:
    """Expected/observed counts for an area candidate cell."""
    gd = (c.get("explanation") or {}).get("gap_details") or {}
    return _safe_number(gd.get("expected_count")), _safe_number(gd.get("observed_count"))


def _use_note(pdf, margin, width, y):
    """Draw the shared 'how to use this report' disclaimer box."""
    pdf.setFillColorRGB(1, 1, 1)
    pdf.setStrokeColorRGB(*LINE)
    pdf.roundRect(margin, y - 66, width - 2 * margin, 66, 12, fill=1, stroke=1)
    pdf.setFillColorRGB(*BRAND)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(margin + 12, y - 20, "How to use this report")
    _wrap_text(pdf, "This measures the gap between the demand an area's fundamentals predict and the businesses observed there. It is a decision signal for shortlisting and field validation, not a prediction of revenue, profit or business success.", margin + 12, y - 38, 95, leading=11, size=8.6, max_lines=3)


def _build_area_pdf(report: dict, entry: dict) -> bytes:
    """Branded page for an area report: the ranked shortlist of strongest spots."""
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 1.4 * cm
    category = str(report.get("business_category") or "business").replace("_", " ")
    cats = _plural(category)
    area_label = entry.get("label") or "your area"
    candidates = entry.get("top_candidates") or []

    _draw_header(pdf, "BizIntel", width, height)
    y = height - 3.15 * cm
    pdf.setFillColorRGB(*BRAND)
    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawString(margin, y, f"{category.title()} location report"[:52])
    y -= 18
    pdf.setFillColorRGB(*SLATE)
    pdf.setFont("Helvetica", 10)
    pdf.drawString(margin, y, f"The strongest spots in {area_label}")
    pdf.drawRightString(width - margin, y, datetime.now(timezone.utc).strftime("%d %b %Y"))
    y -= 24
    y = _wrap_text(pdf, f"Ranked by how much room each spot has for a {category}. Open the online report to explore any of them in full.", margin, y, 95, leading=12, size=9)
    y -= 8

    if not candidates:
        _wrap_text(pdf, "No candidate spots were found for this area.", margin, y, 90, size=10)
    for i, c in enumerate(candidates[:3], start=1):
        expected, observed = _candidate_counts(c)
        verdict = _gap_verdict(expected, observed)
        name = c.get("landmark") or c.get("location_label") or c.get("name") or "Unnamed spot"
        pdf.setFillColorRGB(1, 1, 1)
        pdf.setStrokeColorRGB(*LINE)
        pdf.roundRect(margin, y - 62, width - 2 * margin, 62, 12, fill=1, stroke=1)
        pdf.setFillColorRGB(*BRAND)
        pdf.setFont("Helvetica-Bold", 13)
        pdf.drawString(margin + 14, y - 22, f"#{i}  {str(name)[:52]}")
        pdf.setFillColorRGB(*(ROSE if verdict == "Saturated" else TEAL))
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawRightString(width - margin - 14, y - 22, verdict.upper())
        pdf.setFillColorRGB(*SLATE)
        pdf.setFont("Helvetica", 9)
        sub = c.get("location_label")
        if sub and sub != name:
            pdf.drawString(margin + 14, y - 38, str(sub)[:60])
        pdf.drawString(margin + 14, y - 52, f"Area can support about {expected:.0f} {cats}  ·  {observed:.0f} open within 1 km")
        y -= 74

    y -= 4
    _use_note(pdf, margin, width, y)
    _draw_footer(pdf, 1, width)
    pdf.save()
    return buffer.getvalue()


def _build_compare_pdf(report: dict) -> bytes:
    """Branded page for a compare report: head-to-head across the chosen spots."""
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 1.4 * cm
    category = str(report.get("business_category") or "business").replace("_", " ")
    cats = _plural(category)
    comparison = report.get("comparison") or {}
    locations = comparison.get("locations") or []
    winner = comparison.get("best_location") or {}
    winner_label = winner.get("label")

    _draw_header(pdf, "BizIntel", width, height)
    y = height - 3.15 * cm
    pdf.setFillColorRGB(*BRAND)
    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawString(margin, y, f"{category.title()} comparison"[:52])
    y -= 18
    pdf.setFillColorRGB(*SLATE)
    pdf.setFont("Helvetica", 10)
    pdf.drawString(margin, y, "Head to head")
    pdf.drawRightString(width - margin, y, datetime.now(timezone.utc).strftime("%d %b %Y"))
    y -= 26

    if comparison.get("summary"):
        pdf.setFillColorRGB(*MINT)
        pdf.roundRect(margin, y - 52, width - 2 * margin, 52, 12, fill=1, stroke=0)
        pdf.setFillColorRGB(*BRAND)
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(margin + 12, y - 18, "Stronger opening")
        _wrap_text(pdf, str(comparison["summary"]), margin + 12, y - 34, 92, leading=11, size=9, max_lines=2)
        y -= 70

    # Table header
    pdf.setFillColorRGB(*SLATE)
    pdf.setFont("Helvetica-Bold", 8)
    cols_x = [margin, margin + 230, margin + 310, margin + 390]
    pdf.drawString(cols_x[0], y, "LOCATION")
    pdf.drawString(cols_x[1], y, "CAN SUPPORT")
    pdf.drawString(cols_x[2], y, "OPEN NOW")
    pdf.drawString(cols_x[3], y, "VERDICT")
    y -= 6
    pdf.setStrokeColorRGB(*LINE)
    pdf.line(margin, y, width - margin, y)
    y -= 16

    for row in locations:
        expected = _safe_number(row.get("expected_count"))
        observed = _safe_number(row.get("observed_count"))
        verdict = _gap_verdict(expected, observed)
        name = row.get("landmark") or row.get("label") or "Unnamed"
        is_winner = row.get("label") == winner_label
        pdf.setFillColorRGB(*(BRAND if is_winner else SLATE))
        pdf.setFont("Helvetica-Bold" if is_winner else "Helvetica", 9.5)
        marker = "* " if is_winner else "  "
        pdf.drawString(cols_x[0], y, f"{marker}{str(name)[:34]}")
        pdf.setFont("Helvetica", 9.5)
        pdf.setFillColorRGB(*SLATE)
        pdf.drawString(cols_x[1], y, f"{expected:.0f} {cats}")
        pdf.drawString(cols_x[2], y, f"{observed:.0f}")
        pdf.setFillColorRGB(*(ROSE if verdict == "Saturated" else TEAL))
        pdf.setFont("Helvetica-Bold", 8.5)
        pdf.drawString(cols_x[3], y, verdict.upper())
        y -= 18

    y -= 4
    pdf.setFillColorRGB(*SLATE)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(margin, y, "* strongest opening. Each spot is the best cell inside the area you chose.")
    y -= 22
    _use_note(pdf, margin, width, y)
    _draw_footer(pdf, 1, width)
    pdf.save()
    return buffer.getvalue()
