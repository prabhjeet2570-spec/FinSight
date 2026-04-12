"""End-to-end integration test for Phase 2.

Generates a synthetic SEC 10-Q PDF (with realistic structure: cover page,
financial statement table, MD&A narrative) and runs the full extraction
pipeline against it.

Run from backend dir: python -m scripts.test_integration
"""
import os
import sys
import tempfile

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib import colors

from app.services.chunking import chunk_pages
from app.services.extraction import extract_pdf
from app.services.metadata_detection import detect_metadata
from app.services.metric_flattening import flatten_tables


PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"

results = []


def check(name: str, condition: bool, detail: str = ""):
    results.append(condition)
    marker = PASS if condition else FAIL
    suffix = f" ({detail})" if detail else ""
    print(f"  {marker} {name}{suffix}")


# ---------- Generate a synthetic SEC 10-Q PDF ----------

def make_test_pdf(path: str) -> None:
    doc = SimpleDocTemplate(path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    # Cover page
    story.append(Paragraph("UNITED STATES SECURITIES AND EXCHANGE COMMISSION", styles["Title"]))
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph("Washington, D.C. 20549", styles["Normal"]))
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph("FORM 10-Q", styles["Heading1"]))
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph(
        "For the quarterly period ended September 28, 2025", styles["Normal"]
    ))
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph("Apple Inc. (AAPL)", styles["Heading2"]))
    story.append(Paragraph("NASDAQ: AAPL", styles["Normal"]))
    story.append(PageBreak())

    # Financial statements page
    story.append(Paragraph("Item 1. Financial Statements", styles["Heading1"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(
        "CONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS (Unaudited)",
        styles["Heading3"],
    ))
    story.append(Spacer(1, 0.2 * inch))

    # Income statement table — use short, single-line headers so pdfplumber
    # doesn't have to deal with wrapping (which mangles cells in narrow PDFs)
    table_data = [
        ["", "Q3 2025", "Q3 2024"],
        ["Net sales", "$94,000", "$85,800"],
        ["Cost of sales", "50,000", "47,000"],
        ["Gross profit", "44,000", "38,800"],
        ["Operating expenses", "14,000", "13,800"],
        ["Operating income", "30,000", "25,000"],
        ["Net income", "$23,400", "$21,400"],
        ["Diluted earnings per share", "$1.40", "$1.25"],
    ]
    t = Table(table_data, colWidths=[3 * inch, 1.5 * inch, 1.5 * inch])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ]))
    story.append(t)
    story.append(PageBreak())

    # MD&A page
    story.append(Paragraph(
        "Item 2. Management's Discussion and Analysis of Financial Condition and Results of Operations",
        styles["Heading1"],
    ))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(
        "Net sales increased 9.6% during the third quarter of 2025 compared to "
        "the third quarter of 2024, driven primarily by higher iPhone sales and "
        "continued strength in our Services segment. Gross margin expanded by "
        "30 basis points year-over-year, reflecting favorable mix and operating "
        "leverage. We continue to invest in research and development, particularly "
        "in artificial intelligence and machine learning capabilities across our "
        "product line.",
        styles["Normal"],
    ))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(
        "Operating income grew 20% year-over-year, demonstrating strong "
        "operational execution. Free cash flow remained robust, supporting our "
        "capital return program. Looking ahead, we remain focused on long-term "
        "growth opportunities and expect continued momentum in our key product "
        "categories during the upcoming holiday quarter.",
        styles["Normal"],
    ))
    story.append(PageBreak())

    # Risk factors page
    story.append(Paragraph(
        "Part II — Item 1A. Risk Factors", styles["Heading1"],
    ))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(
        "Our business is subject to a variety of risks and uncertainties. "
        "Macroeconomic conditions, including inflation, interest rates, and "
        "currency fluctuations, could materially impact our results. Supply "
        "chain disruptions remain a key area of focus. We face intense "
        "competition across all of our product categories.",
        styles["Normal"],
    ))

    doc.build(story)


# ---------- Run pipeline ----------

def run_test():
    print("\nGenerating synthetic Apple 10-Q PDF...")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.close()
    pdf_path = tmp.name
    try:
        make_test_pdf(pdf_path)
        size = os.path.getsize(pdf_path)
        print(f"  PDF written to {pdf_path} ({size} bytes)")

        # 1. Extract
        print("\n[1] PDF extraction")
        result = extract_pdf(pdf_path)
        check("page count == 4", result.page_count == 4, f"got {result.page_count}")
        check("found at least 1 table", len(result.all_tables) >= 1, f"got {len(result.all_tables)}")
        check("total text non-empty", len(result.total_text) > 100)

        # 2. Section detection (across pages)
        print("\n[2] Section detection")
        sections_found = {p.section for p in result.pages if p.section}
        check("Financial Statements detected", "Financial Statements" in sections_found,
              f"sections: {sections_found}")
        check("MD&A detected", "MD&A" in sections_found, f"sections: {sections_found}")
        check("Risk Factors detected", "Risk Factors" in sections_found,
              f"sections: {sections_found}")

        # 3. Metadata detection
        print("\n[3] Metadata detection")
        first_page = result.pages[0].text
        md = detect_metadata("apple-10q-q3-2025.pdf", first_page)
        check("company is Apple", "Apple" in md.company, f"got {md.company!r}")
        check("ticker is AAPL", md.ticker == "AAPL", f"got {md.ticker!r}")
        check("filing type 10-Q", md.filing_type == "10-Q", f"got {md.filing_type!r}")
        # Period detection from "Three months ended September 28, 2025" -> Q3 2025
        check("period detected", md.period is not None, f"got {md.period!r}")

        # 4. Chunking
        print("\n[4] Chunking")
        chunks = chunk_pages(result.pages)
        check("at least 3 chunks", len(chunks) >= 3, f"got {len(chunks)}")
        sectioned_chunks = [c for c in chunks if c.section]
        check("chunks tagged with sections", len(sectioned_chunks) > 0,
              f"{len(sectioned_chunks)}/{len(chunks)} have section")

        # 5. Metric flattening
        print("\n[5] Metric flattening")
        metrics = flatten_tables(result.all_tables)
        metric_names = {m.metric_name for m in metrics}
        check("revenue extracted", "revenue" in metric_names, f"found: {metric_names}")
        check("net_income extracted", "net_income" in metric_names)
        check("gross_profit extracted", "gross_profit" in metric_names)

        # Verify the actual numbers match the PDF
        rev = next((m for m in metrics if m.metric_name == "revenue"), None)
        if rev:
            check("revenue value == 94000", rev.value == 94000.0, f"got {rev.value}")
            check("revenue prior == 85800", rev.prior_value == 85800.0, f"got {rev.prior_value}")
            check("revenue change_pct ~9.56",
                  rev.change_pct is not None and round(rev.change_pct, 1) == 9.6,
                  f"got {rev.change_pct}")

        ni = next((m for m in metrics if m.metric_name == "net_income"), None)
        if ni:
            check("net_income value == 23400", ni.value == 23400.0, f"got {ni.value}")

        # 6. Print a summary of what we extracted
        print("\n[6] Extraction summary")
        print(f"  Document: {md.company} ({md.ticker}) {md.filing_type} {md.period}")
        print(f"  Pages: {result.page_count}")
        print(f"  Tables: {len(result.all_tables)}")
        print(f"  Chunks: {len(chunks)}")
        print(f"  Metrics: {len(metrics)}")
        for m in sorted(metrics, key=lambda x: x.metric_name):
            chg = f"{m.change_pct:+.1f}%" if m.change_pct is not None else "n/a"
            print(f"    - {m.metric_name}: {m.value} (prior {m.prior_value}, {chg})")

    finally:
        if os.path.exists(pdf_path):
            os.unlink(pdf_path)

    print()
    total = len(results)
    passed = sum(results)
    print(f"{passed}/{total} integration checks passed")
    return passed == total


if __name__ == "__main__":
    sys.exit(0 if run_test() else 1)
