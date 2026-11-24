import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import content_selector as cs
from modules import jd_parser as jp
from modules import ollama_tailor as ot
from modules import pdf_renderer as pr

SAMPLE_JD = """Data Integrity & Automation Intern
Southlake, Texas

About Us: FiberFirst, a leading fiber internet service provider.

Requirements: Python, SQL, Docker and AWS. Experience with Power BI dashboards.
"""

GOOGLE_JD = ("Google LLC is hiring a Machine Learning Engineer Intern. You will build deep "
             "learning models using PyTorch and TensorFlow. Requirements: Python, SQL, Docker, AWS.")


# ---------------- JD parsing ----------------
def test_parse_structured_jd():
    r = jp.parse_jd(SAMPLE_JD)
    assert r["company"] == "FiberFirst"
    assert r["job_title"] == "Data Integrity & Automation Intern"


def test_parse_keywords_word_boundaries():
    kws = jp.parse_jd(SAMPLE_JD)["keywords"]
    assert {"python", "sql", "docker", "aws"} <= set(kws)
    assert "go" not in kws and "r" not in kws      # no substring false-positives


def test_role_category():
    assert jp.parse_jd(GOOGLE_JD)["role_category"] == "ml_ai"


def test_header_template_stripped_and_oversized_truncated():
    jd = "PASTE YOUR JOB DESCRIPTION BELOW THIS LINE\n====\n" + SAMPLE_JD + ("x " * 50000)
    r = jp.parse_jd(jd)
    assert "PASTE YOUR JOB" not in r["raw_text"]
    assert len(r["raw_text"]) <= jp.MAX_JD_CHARS
    assert r["job_title"] == "Data Integrity & Automation Intern"


def test_empty_jd_does_not_crash():
    r = jp.parse_jd("")
    assert r["company"] and r["job_title"] and r["keywords"] == []


def test_sanitize_filename():
    assert "/" not in jp.sanitize_filename("A/B Co.")
    assert " " not in jp.sanitize_filename("Machine Learning Engineer")


# ---------------- Content selection ----------------
def test_select_all_shape_and_grounding():
    jd = jp.parse_jd(GOOGLE_JD)
    sel = cs.select_all(jd)
    data = cs._load_data()
    assert len(sel["projects"]) == 3
    assert {w["company"] for w in sel["work_experience"]} == {w["company"] for w in data["work_experience"]}
    pool_names = {p["name"] for p in data["projects_pool"]}
    assert {p["name"] for p in sel["projects"]} <= pool_names


@pytest.mark.parametrize("cat", ["ml_ai", "swe", "data_science", "data_engineer", "analyst",
                                 "mlops", "cv", "nlp", "default"])
def test_skills_never_invented(cat):
    data = cs._load_data()
    blob = json.dumps(data).lower()
    skills = cs.build_skills_section(["python"], cat)
    assert skills
    for value in skills.values():
        for item in cs.split_skill_items(value):
            base = item.lower().split("(")[0].strip()
            assert base in blob or item.lower() in blob or item == "HuggingFace Transformers", item


def test_project_selection_prefers_matching_tags():
    top = cs.select_projects(["nlp", "spacy", "chatbot"], "nlp", n=1)[0]
    assert "chatbot" in json.dumps(top).lower() or "nlp" in json.dumps(top).lower()


def test_split_skill_items_keeps_parentheses():
    assert cs.split_skill_items("AWS (EC2, S3), GCP, Docker") == ["AWS (EC2, S3)", "GCP", "Docker"]


def test_fallback_summary_uses_only_resume_facts():
    sel = cs.select_all(jp.parse_jd(GOOGLE_JD))
    s = cs.build_fallback_summary(sel, ["python"])
    assert "Adiance" in s and s.endswith(".")


# ---------------- LLM output validation ----------------
def test_parse_bullets_and_numbers():
    out = ot.parse_bullets("Here are the bullets:\n• Built a model cutting latency by 25% on 50K images\n- tiny\n2) Wrote a long enough second bullet line")
    assert len(out) == 2 and out[0].startswith("Built")


def test_merge_bullets_rejects_invented_numbers():
    orig = ["Cut latency by 25% using batching and caching", "Processed 50K images nightly with Spark"]
    new = ["Reduced latency by 90% using batching and caching tricks", "Processed 50K images nightly using Spark pipelines"]
    merged = ot.merge_bullets(orig, new)
    assert merged[0] == orig[0]          # 90 not in original -> reverted
    assert merged[1] == new[1]


def test_merge_bullets_pads_missing():
    orig = ["a" * 30, "b" * 30, "c" * 30]
    assert ot.merge_bullets(orig, ["rewritten bullet number one"])[1:] == orig[1:]


def test_clean_summary_rules():
    good = "Engineering data science student with experience building machine learning pipelines and dashboards for analytics teams."
    assert ot.clean_summary(good)
    assert ot.clean_summary("too short") is None
    assert ot.clean_summary("I built " + good) is None
    assert ot.clean_summary(good + " Improved revenue by 400%.", allowed_numbers={"25"}) is None


def test_call_validated_retries_then_gives_up(monkeypatch):
    calls = []
    monkeypatch.setattr(ot, "_call_ollama", lambda p, max_tokens=0: calls.append(1) or "garbage")
    assert ot._call_validated("p", lambda t: None, 10) is None
    assert len(calls) == ot.LLM_RETRIES


def test_tailor_falls_back_to_original_on_malformed_llm(monkeypatch):
    monkeypatch.setattr(ot, "ensure_ollama", lambda: None)
    monkeypatch.setattr(ot, "_call_ollama", lambda p, max_tokens=0: "nonsense")
    jd = jp.parse_jd(GOOGLE_JD)
    sel = cs.select_all(jd)
    out = ot.tailor_content(sel, jd)
    assert [w["bullets"] for w in out["work_experience"]] == [w["bullets"] for w in sel["work_experience"]]
    assert out["summary"]


def test_missing_model_gives_clear_error(monkeypatch):
    monkeypatch.setattr(ot, "_is_ollama_running", lambda: True)
    monkeypatch.setattr(ot, "_installed_models", lambda: ["mistral:latest"])
    monkeypatch.setattr(ot, "MODEL", "nope-model")
    with pytest.raises(ot.OllamaError, match="ollama pull nope-model"):
        ot.ensure_ollama()


# ---------------- PDF page fit ----------------
def _pages(path):
    from pypdf import PdfReader
    return len(PdfReader(str(path)).pages)


def test_render_is_one_page(tmp_path):
    sel = cs.select_all(jp.parse_jd(GOOGLE_JD))
    sel["summary"] = cs.build_fallback_summary(sel, ["python"])
    out = tmp_path / "nested" / "deeper" / "r.pdf"      # folders created automatically
    pr.render_pdf(sel, str(out))
    assert out.exists() and _pages(out) == 1


def test_render_oversized_content_trimmed_to_one_page(tmp_path):
    sel = cs.select_all(jp.parse_jd(GOOGLE_JD))
    sel["summary"] = "word " * 80
    for w in sel["work_experience"]:
        w["bullets"] = [("Very long bullet text about work. " * 12)] * 3
    for p in sel["projects"]:
        p["star_bullets"] = [("Very long project bullet. " * 12)] * 3
    out = tmp_path / "big.pdf"
    pr.render_pdf(sel, str(out))
    assert _pages(out) == 1


def test_trim_cuts_cleanly():
    t = pr._trim("First clause, second clause " * 30, 100)
    assert len(t) <= 101 and t.endswith(".") and not t.endswith(",.")
    assert pr._trim("short") == "short"


def test_merge_bullets_rejects_claimed_jd_skills():
    jd = jp.parse_jd("Requirements: Kubernetes, PyTorch, object detection and image segmentation.")
    terms = ot.jd_terms(jd)
    orig = ["Built a face recognition pipeline with PyTorch for 50K images"]
    bad = ["Implemented Kubernetes-orchestrated face recognition pipeline with PyTorch for 50K images"]
    ok = ["Engineered a face recognition pipeline with PyTorch handling 50K images"]
    assert ot.merge_bullets(orig, bad, terms) == orig
    assert ot.merge_bullets(orig, ok, terms) == ok


def test_summary_rejects_unsupported_jd_claims():
    jd = jp.parse_jd("We need image segmentation and Kubernetes experience.")
    terms = ot.jd_terms(jd)
    text = "Engineering data science student proficient in image segmentation and building machine learning pipelines for analytics teams."
    assert ot.clean_summary(text, terms=terms, source="pytorch pipelines") is None
    assert ot.clean_summary(text, terms=terms, source="image segmentation pytorch")
