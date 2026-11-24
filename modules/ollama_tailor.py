"""
ollama_tailor.py
Uses a local Ollama model to lightly rewrite resume content for a job description.

Design rules (so the resume stays truthful):
  * The LLM only REWORDS content that already exists in resume_data.json.
    It never invents projects, employers, degrees, skills or numbers.
  * Every LLM output is validated; anything malformed, empty or containing
    numbers that were not in the source bullet is discarded and the original
    (rule-selected) text is used instead.
  * If Ollama is unavailable, OllamaError is raised and generate.py falls back
    to the rule-based content.
"""
from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request

from modules.content_selector import build_fallback_summary

OLLAMA_BASE = os.environ.get("RESUME_MAKER_OLLAMA_URL", "http://localhost:11434").rstrip("/")
DEFAULT_MODEL = "mistral:latest"
MODEL = os.environ.get("RESUME_MAKER_MODEL", DEFAULT_MODEL)
REQUEST_TIMEOUT = 180
LLM_RETRIES = 2          # attempts per LLM task before falling back to source text


class OllamaError(RuntimeError):
    """Ollama is not reachable, or the requested model is not installed."""


def set_model(name: str) -> None:
    global MODEL
    MODEL = name


# ---------------------------------------------------------------------------
# Ollama lifecycle helpers
# ---------------------------------------------------------------------------

def _is_ollama_running() -> bool:
    try:
        urllib.request.urlopen(OLLAMA_BASE, timeout=2)
        return True
    except Exception:
        return False


def _start_ollama() -> None:
    """Try to start `ollama serve` in the background (only if the binary exists)."""
    if not re.match(r"^https?://(localhost|127\.0\.0\.1)(:11434)?$", OLLAMA_BASE):
        raise OllamaError(f"Ollama is not reachable at {OLLAMA_BASE}. Check RESUME_MAKER_OLLAMA_URL.")
    if not shutil.which("ollama"):
        raise OllamaError(
            "Ollama is not installed. Install it from https://ollama.com, then run "
            f"'ollama pull {MODEL}'. Or use --no-ai for rule-based tailoring without an LLM."
        )
    print("⏳ Starting Ollama server...")
    subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(15):
        time.sleep(1)
        if _is_ollama_running():
            print("✅ Ollama is running.")
            return
    raise OllamaError("Could not start Ollama. Please run 'ollama serve' in another terminal and retry.")


def _installed_models() -> list[str]:
    with urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=5) as resp:
        return [m.get("name", "") for m in json.loads(resp.read()).get("models", [])]


def ensure_ollama() -> None:
    """Make sure the server is up and the configured model is pulled; raise OllamaError otherwise."""
    if not _is_ollama_running():
        _start_ollama()
    try:
        names = _installed_models()
    except Exception as e:
        raise OllamaError(f"Ollama is running but its model list could not be read ({e}).")
    wanted = MODEL if ":" in MODEL else MODEL + ":latest"
    if wanted not in names and MODEL not in names:
        have = ", ".join(names) or "none"
        raise OllamaError(
            f"Model '{MODEL}' is not installed (installed: {have}). Run 'ollama pull {MODEL}', "
            "or pick another with --model / RESUME_MAKER_MODEL."
        )


# ---------------------------------------------------------------------------
# Core LLM call
# ---------------------------------------------------------------------------

def _call_ollama(prompt: str, max_tokens: int = 1200) -> str:
    """Send a prompt to Ollama and return the response text."""
    payload = json.dumps({
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": max_tokens, "top_p": 0.9},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/generate", data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read()).get("response", "").strip()
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError) as e:
        raise OllamaError(f"Ollama request failed: {e}")


def _call_validated(prompt: str, validate, max_tokens: int):
    """Call the LLM up to LLM_RETRIES times; return validate(text) or None if it never validates."""
    for attempt in range(1, LLM_RETRIES + 1):
        text = _call_ollama(prompt, max_tokens=max_tokens)
        result = validate(text)
        if result:
            return result
        print(f"   ⚠️  Malformed LLM output (attempt {attempt}/{LLM_RETRIES}).")
    return None


# ---------------------------------------------------------------------------
# Validation helpers (pure, unit-tested)
# ---------------------------------------------------------------------------

_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def numbers_in(text: str) -> set[str]:
    return set(_NUM.findall(text))


def parse_bullets(text: str) -> list[str]:
    """Extract bullet lines from LLM output, dropping markers, labels and tiny fragments."""
    out = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[•\-\*]|\d+[.)])\s*", "", line.strip()).strip()
        if len(line) > 20 and not line.lower().startswith(("here are", "here is", "sure")):
            out.append(line)
    return out


def _norm(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9+#]+", " ", text.lower()).strip() + " "


def jd_terms(jd_parsed: dict) -> set[str]:
    """
    Terms from the JD that the LLM might wrongly claim as the candidate's own:
    parsed keywords, known tech names, and adjacent-word phrases (e.g. 'object detection').
    """
    from modules.jd_parser import STOP_WORDS, TECH_KEYWORDS
    terms = {k.lower() for k in jd_parsed.get("keywords", []) if len(k) > 2}
    terms |= {t for t in TECH_KEYWORDS if len(t) > 2}
    run: list[str] = []
    for tok in re.findall(r"[A-Za-z0-9+#]+|[.,;:!?()\n-]", jd_parsed.get("raw_text", "").lower()):
        if re.match(r"[a-z0-9+#]{3,}$", tok) and tok not in STOP_WORDS:
            run.append(tok)
            if len(run) >= 2:
                terms.add(f"{run[-2]} {run[-1]}")
        else:
            run = []
    return terms


def introduced_terms(text: str, source: str, terms: set[str]) -> list[str]:
    """JD terms that appear in `text` but nowhere in the trusted `source` text."""
    t, src = _norm(text), _norm(source)
    return [x for x in terms if f" {_norm(x).strip()} " in t and f" {_norm(x).strip()} " not in src]


def merge_bullets(originals: list[str], rewritten: list[str],
                  terms: set[str] | None = None, context: str = "") -> list[str]:
    """
    Keep the rewrite at position i only if it introduces no new number and no new JD
    term (skill/technology claim) beyond the original bullets; otherwise keep the original.
    """
    allowed = set()
    for o in originals:
        allowed |= numbers_in(o)
    source = " ".join(originals) + " " + context
    merged = []
    for i, orig in enumerate(originals):
        cand = rewritten[i] if i < len(rewritten) else None
        if cand and terms and introduced_terms(cand, source, terms):
            cand = None
        if cand and numbers_in(cand) <= allowed and len(cand) <= 320:
            merged.append(cand)
        else:
            merged.append(orig)
    return merged


def clean_summary(text: str, max_words: int = 90, allowed_numbers: set | None = None,
                  terms: set[str] | None = None, source: str = "") -> str | None:
    text = re.sub(r"^(Summary:|Here is|Here's|Sure[,:]?)[^\n]*?[:\n]\s*", "", text.strip(), flags=re.IGNORECASE)
    text = text.strip().strip('"').strip()
    text = re.sub(r"\s+", " ", text)
    if len(text.split()) < 12 or len(text.split()) > max_words:
        return None
    if re.search(r"\b(I|my|me|we)\b", text):
        return None
    if allowed_numbers is not None and not numbers_in(text) <= allowed_numbers:
        return None            # invented figure
    if terms and introduced_terms(text, source, terms):
        return None            # claims a JD skill/term that is nowhere in resume_data.json
    return text


# ---------------------------------------------------------------------------
# Tailoring tasks
# ---------------------------------------------------------------------------

def generate_summary(jd_text: str, selected_content: dict, keywords: list[str],
                     job_title: str = "", terms: set[str] | None = None, source: str = "") -> str:
    """LLM summary grounded in the real resume facts; deterministic fallback if it fails."""
    work = selected_content["work_experience"]
    facts = "\n".join(f"- {w['title']} at {w['company']}: " + " ".join(w["bullets"][:2]) for w in work)
    degree = selected_content["education"][0]["degree"] if selected_content.get("education") else ""
    top_kws = ", ".join(keywords[:12])
    title_rule = f'- Mention the target role "{job_title}" once.\n' if job_title else ""

    prompt = f"""You are a professional resume writer. Write a 2-3 sentence professional summary (max 70 words).

RULES:
- No first-person pronouns (I, my, me, we).
- Use ONLY the facts below. The candidate is a current student, not a graduate; use the degree wording exactly. Do NOT invent employers, schools, degrees, skills, projects or numbers.
{title_rule}- The job description describes the EMPLOYER's needs, not the candidate. Mention a JD keyword only if the facts below support it; never claim a skill, tool or experience that is not in the facts.
- JD keywords (use only if supported): {top_kws}
- Output ONLY the summary text.

CANDIDATE FACTS:
- Degree: {degree}
{facts}

JOB DESCRIPTION (excerpt):
{jd_text[:700]}

SUMMARY:"""
    allowed = numbers_in(" ".join(b for w in work for b in w["bullets"]) + " " + degree + " " + job_title)
    summary = _call_validated(prompt, lambda t: clean_summary(t, allowed_numbers=allowed, terms=terms, source=source), max_tokens=250)
    if not summary:
        print("   ⚠️  Using rule-based summary.")
        return build_fallback_summary(selected_content, keywords)

    if job_title and job_title.lower() not in summary.lower():
        summary = f"Aspiring {job_title} — {summary[0].lower()}{summary[1:]}" \
            if not summary.startswith(("M.S.", "MS")) else f"Aspiring {job_title} — {summary}"
    return summary


def _rewrite(bullets: list[str], header: str, keywords: list[str], terms: set[str] | None = None,
             extra_rules: str = "") -> list[str]:
    """Rewrite bullets with JD keywords; numbers and facts are validated afterwards."""
    top_kws = ", ".join(keywords[:15])
    bullets_text = "\n".join(f"- {b}" for b in bullets)
    n = len(bullets)
    prompt = f"""You are a professional resume writer. Rewrite exactly {n} resume bullet points.

RULES:
- Output EXACTLY {n} bullets, each on one line starting with "•", same order as the originals.
- Keep every number, percentage and ranking unchanged. Do NOT add new numbers, tools, employers or claims.
- Reword with these JD keywords only where they honestly fit the original: {top_kws}
- Strong action verb first; each bullet under 280 characters.
{extra_rules}
{header}

ORIGINAL BULLETS:
{bullets_text}

REWRITTEN BULLETS:"""
    parsed = _call_validated(prompt, lambda t: parse_bullets(t) if len(parse_bullets(t)) >= n else None,
                             max_tokens=700)
    return merge_bullets(bullets, parsed, terms, context=header) if parsed else bullets


def rewrite_bullets(bullets: list[str], keywords: list[str], company: str, title: str,
                    terms: set[str] | None = None) -> list[str]:
    return _rewrite(bullets, f"ROLE: {title} at {company} (do not change the company name)", keywords, terms)


def rewrite_project_bullets(project: dict, keywords: list[str], terms: set[str] | None = None) -> list[str]:
    return _rewrite(project["star_bullets"], f"PROJECT: {project['name']}\nTECH: {project['tech']}",
                    keywords, terms)


def _extract_critical_keywords(jd_text: str, keywords: list[str]) -> list[str]:
    """
    Identify the highest-priority ATS keywords — multi-word domain phrases
    that appear frequently in the JD and are most likely to be scanned.
    Prioritises phrases over single words.
    """
    jd_lower = jd_text.lower()
    # Domain phrases to check (ordered by ATS value)
    candidate_phrases = [
        "recommender systems", "recommendation system", "personalization",
        "representation learning", "collaborative filtering", "ranking systems",
        "research", "research projects", "applied machine learning",
        "sequential models", "contextual bandits", "reinforcement learning",
        "a/b experiments", "a/b testing", "large-scale retrieval",
        "machine learning research", "graph-based methods", "embedding", "embeddings",
        "ndcg", "recall@k", "exploration exploitation", "multi-sided marketplace",
        "data scientist", "data science", "online experimentation",
        "collaborative", "collaboration", "production ml", "ml lifecycle",
        "deep learning", "neural network", "data pipeline", "feature engineering",
        "model evaluation", "offline evaluation", "model deployment",
    ]
    found = []
    for phrase in candidate_phrases:
        if phrase in jd_lower:
            count = jd_lower.count(phrase)
            found.append((count, phrase))
    # Sort by frequency in JD
    found.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in found[:12]]


def _tailor_skills(skills: dict, keywords: list, critical_keywords: list) -> dict:
    """
    Deterministically re-order skills so JD-matching items come first.
    Never adds skills: the set of items is unchanged.
    """
    from modules.content_selector import split_skill_items
    all_kw = {kw.lower() for kw in (keywords or []) + (critical_keywords or [])}
    tailored = {}
    for category, value in skills.items():
        items = split_skill_items(value)
        if not items:
            continue
        priority = [it for it in items if any(kw in it.lower() for kw in all_kw)]
        rest = [it for it in items if it not in priority]
        tailored[category] = ", ".join(priority + rest)
    return tailored


def tailor_content(selected_content: dict, jd_parsed: dict) -> dict:
    """
    Main entry point: takes selected content + parsed JD and returns tailored content.
    Raises OllamaError if Ollama/model is unavailable; individual task failures
    fall back to the rule-selected text.
    """
    ensure_ollama()
    jd_text = jd_parsed["raw_text"]
    keywords = jd_parsed["keywords"]
    job_title = jd_parsed.get("job_title", "")
    critical = _extract_critical_keywords(jd_text, keywords)
    terms = jd_terms(jd_parsed)
    from modules.content_selector import _load_data
    resume_blob = json.dumps(_load_data(), ensure_ascii=False)
    summary_source = f"{resume_blob} {job_title} {jd_parsed.get('company', '')}"

    def safe(task, fallback, *a, **kw):
        try:
            return task(*a, **kw)
        except OllamaError as e:
            print(f"   ⚠️  {e} — keeping original text for this section.")
            return fallback

    print("🤖 Generating tailored summary...")
    summary = safe(generate_summary, build_fallback_summary(selected_content, keywords),
                   jd_text, selected_content, keywords, job_title=job_title,
                   terms=terms, source=summary_source)

    print("📝 Rewriting work experience bullets...")
    work = []
    for exp in selected_content["work_experience"]:
        new = safe(rewrite_bullets, exp["bullets"], exp["bullets"], keywords, exp["company"], exp["title"], terms)
        work.append({**exp, "bullets": new})

    print("🚀 Rewriting project bullets...")
    projects = []
    for proj in selected_content["projects"]:
        new = safe(rewrite_project_bullets, proj["star_bullets"], proj, keywords, terms)
        projects.append({**proj, "star_bullets": new})

    return {
        **selected_content,
        "summary": summary,
        "work_experience": work,
        "projects": projects,
        "skills": _tailor_skills(selected_content["skills"], keywords, critical),
    }
