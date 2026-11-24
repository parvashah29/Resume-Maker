#!/usr/bin/env python3
"""
generate.py — Resume Tailoring Pipeline (Fully Local, No API Keys)
====================================================================
Usage:
    python3 generate.py --jd jd.txt
    python3 generate.py --jd "Software Engineer Intern at Google..."
    python3 generate.py                        # interactive mode
    python3 generate.py --jd jd.txt --no-ai   # rule-based only (faster, no LLM)

Output:
    output/<Name>_<Company>_<Role>.pdf
"""
import argparse
import os
import re
import sys
import time
from pathlib import Path

# Ensure modules are importable
sys.path.insert(0, str(Path(__file__).parent))

from modules.jd_parser import parse_jd, sanitize_filename
from modules.content_selector import select_all, build_fallback_summary
from modules.pdf_renderer import render_pdf


OUTPUT_DIR = Path(__file__).parent / "output"


MIN_JD_CHARS = 40       # shorter than this is almost certainly not a job description


def read_jd(jd_arg: str) -> str:
    """Accept JD as a file path or raw text string."""
    try:
        is_file = os.path.isfile(jd_arg)
    except (OSError, ValueError):      # very long raw text can't be a path
        is_file = False
    if is_file:
        with open(jd_arg, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    return jd_arg


def interactive_jd() -> str:
    """Prompt user to paste JD interactively."""
    print("\n📋 Paste your Job Description below.")
    print("   Press ENTER twice when done.\n")
    lines = []
    blank_count = 0
    while blank_count < 2:
        try:
            line = input()
        except EOFError:
            break
        if line == "":
            blank_count += 1
        else:
            blank_count = 0
        lines.append(line)
    return "\n".join(lines).strip()


def _name_prefix() -> str:
    """Filename prefix from resume_data.json (e.g. 'Parva_Shah_')."""
    try:
        from modules.content_selector import _load_data
        return re.sub(r"[^\w]+", "_", _load_data()["personal"]["name"].title()).strip("_") + "_"
    except Exception:
        return "Resume_"


def build_output_path(company: str, job_title: str) -> str:
    """Build the output file path: output/Parva_Shah_Company_Role.pdf"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    company_clean = sanitize_filename(company)
    role_clean = sanitize_filename(job_title)
    filename = f"{_name_prefix()}{company_clean}_{role_clean}.pdf"
    return str(OUTPUT_DIR / filename)


def print_banner():
    print("\n" + "="*60)
    print("  🎯 Resume Tailoring Pipeline — Parva Shah")
    print("  Local · No API Keys · Powered by a local Ollama model")
    print("="*60)


def _print_ats_report(jd_parsed: dict, pdf_path: str):
    """Extract text from generated PDF and report ATS keyword coverage."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        text = " ".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return

    text_lower = text.lower()
    keywords = jd_parsed.get("keywords", [])
    if not keywords:
        return

    found   = [kw for kw in keywords if kw.lower() in text_lower]
    missing = [kw for kw in keywords if kw.lower() not in text_lower]
    pct     = len(found) / len(keywords) * 100
    words   = len(text.split())

    print(f"\n📊 ATS Coverage : {len(found)}/{len(keywords)} keywords = {pct:.0f}%")
    print(f"📝 Word Count   : {words}  (target: 750–850)")
    if missing:
        print(f"⚠️  Missing      : {', '.join(missing[:12])}")
    else:
        print("✅  All JD keywords covered!")
    if pct < 85:
        print("   🔁 Tip: Re-run or use --role override to target missing keywords.")


def main():
    parser = argparse.ArgumentParser(description="Generate a tailored resume PDF from a job description.")
    parser.add_argument("--jd", type=str, default=None,
                        help="Path to JD text file OR JD text string")
    parser.add_argument("--no-ai", action="store_true",
                        help="Skip Ollama tailoring — use rule-based content selection only (faster)")
    parser.add_argument("--model", type=str, default=None,
                        help="Ollama model name (default: $RESUME_MAKER_MODEL or mistral:latest)")
    parser.add_argument("--company", type=str, default=None,
                        help="Override company name (if auto-detection fails)")
    parser.add_argument("--role", type=str, default=None,
                        help="Override job role title (if auto-detection fails)")
    parser.add_argument("--output", type=str, default=None,
                        help="Override output file path")
    args = parser.parse_args()

    print_banner()
    t0 = time.time()

    # ── 1. Get JD ────────────────────────────────────────────────────────────
    if args.jd:
        jd_text = read_jd(args.jd)
    else:
        # Auto-look for jd.txt in the same directory as generate.py
        default_jd = Path(__file__).parent / "jd.txt"
        if default_jd.exists():
            jd_text = read_jd(str(default_jd))
            print(f"\n📄 Reading JD from: jd.txt")
        else:
            jd_text = interactive_jd()

    if len(jd_text.strip()) < MIN_JD_CHARS:
        print("❌ No usable job description (empty or too short). "
              "Paste the full posting into jd.txt or pass --jd.")
        sys.exit(1)

    # ── 2. Parse JD ──────────────────────────────────────────────────────────
    print("\n🔍 Parsing job description...")
    jd_parsed = parse_jd(jd_text)

    # Allow manual overrides
    if args.company:
        jd_parsed["company"] = args.company
    if args.role:
        jd_parsed["job_title"] = args.role

    print(f"   Company     : {jd_parsed['company']}")
    print(f"   Role        : {jd_parsed['job_title']}")
    print(f"   Category    : {jd_parsed['role_category']}")
    print(f"   Keywords    : {', '.join(jd_parsed['keywords'][:12])}...")

    # ── 3. Select content ────────────────────────────────────────────────────
    print("\n📂 Selecting best-matching resume content...")
    selected = select_all(jd_parsed)

    # ── 4. Tailor with Ollama (unless --no-ai) ───────────────────────────────
    final_content = selected
    if args.no_ai:
        print("\n⚡ Skipping AI tailoring (--no-ai flag set)")
        selected["summary"] = build_fallback_summary(selected, jd_parsed["keywords"])
    else:
        try:
            from modules import ollama_tailor
            if args.model:
                ollama_tailor.set_model(args.model)
            print(f"\n🤖 Tailoring with Ollama ({ollama_tailor.MODEL})...")
            final_content = ollama_tailor.tailor_content(selected, jd_parsed)
        except ollama_tailor.OllamaError as e:
            print(f"\n⚠️  {e}\n   Falling back to rule-based selection (same as --no-ai).")
            selected["summary"] = build_fallback_summary(selected, jd_parsed["keywords"])
        except Exception as e:
            print(f"\n⚠️  Tailoring failed unexpectedly ({e!r}). Falling back to rule-based selection.")
            selected["summary"] = build_fallback_summary(selected, jd_parsed["keywords"])
            final_content = selected

    # ── 5. Render PDF ────────────────────────────────────────────────────────
    print("\n📄 Rendering PDF...")
    out_path = args.output or build_output_path(jd_parsed["company"], jd_parsed["job_title"])
    render_pdf(final_content, out_path)

    # ── 6. ATS Coverage Report ───────────────────────────────────────────────
    _print_ats_report(jd_parsed, out_path)

    elapsed = time.time() - t0
    print("\n" + "="*60)
    print(f"  ✅ Resume generated in {elapsed:.1f}s")
    print(f"  📁 Saved to: {out_path}")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
