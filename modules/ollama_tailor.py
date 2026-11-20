"""
ollama_tailor.py
Uses local Ollama (Mistral) to intelligently rewrite and tailor resume content.
No API keys. Runs fully offline after Ollama is installed.
"""
from __future__ import annotations
import json
import re
import subprocess
import time
import urllib.request
import urllib.error


OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "mistral:latest"


# ---------------------------------------------------------------------------
# Ollama lifecycle helpers
# ---------------------------------------------------------------------------

def _is_ollama_running() -> bool:
    try:
        urllib.request.urlopen("http://localhost:11434", timeout=2)
        return True
    except Exception:
        return False


def _start_ollama():
    """Start Ollama server in background if not already running."""
    print("⏳ Starting Ollama server...")
    subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    for _ in range(15):
        time.sleep(1)
        if _is_ollama_running():
            print("✅ Ollama is running.")
            return
    raise RuntimeError("Could not start Ollama. Please run 'ollama serve' manually.")


def ensure_ollama():
    if not _is_ollama_running():
        _start_ollama()


# ---------------------------------------------------------------------------
# Core LLM call
# ---------------------------------------------------------------------------

def _call_ollama(prompt: str, max_tokens: int = 1200) -> str:
    """Send a prompt to Ollama and return the response text."""
    ensure_ollama()
    payload = json.dumps({
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.4,
            "num_predict": max_tokens,
            "top_p": 0.9
        }
    }).encode()

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
        return data.get("response", "").strip()


# ---------------------------------------------------------------------------
# Tailoring tasks
# ---------------------------------------------------------------------------

def generate_summary(
    jd_text: str,
    role_category: str,
    selected_content: dict,
    keywords: list[str],
    job_title: str = "",
    critical_keywords: list[str] = None
) -> str:
    """Generate a tailored professional summary — always includes job title for ATS."""
    top_kws = ", ".join(keywords[:15])
    crit = ", ".join((critical_keywords or [])[:6])
    work = selected_content["work_experience"]
    w1 = f"{work[0]['title']} at {work[0]['company']}"
    w2 = f"{work[1]['title']} at {work[1]['company']}"

    title_instruction = ""
    if job_title:
        title_instruction = f"- MUST include the exact job title '{job_title}' in the summary (ATS requirement)"

    crit_instruction = ""
    if crit:
        crit_instruction = f"- MUST naturally include these high-priority ATS keywords: {crit}"

    prompt = f"""You are a professional resume writer. Write a 3-sentence professional summary (max 80 words total).

RULES — STRICTLY FOLLOW:
- Do NOT use first-person pronouns (I, my, me, we)
- Do NOT invent companies, schools, or experiences not provided
{title_instruction}
{crit_instruction}
- Mention: M.S. Engineering Data Science student, experience at {work[0]['company']} and {work[1]['company']}
- MUST include the phrase "applied machine learning" at least once
- MUST use the phrase "recommender systems" (plural, not singular) at least once
- Weave in these JD keywords naturally: {top_kws}
- Be specific and results-oriented
- Exactly 3 sentences, MAX 80 words total
- Output ONLY the summary text, no labels or quotes

JOB DESCRIPTION (first 700 chars):
{jd_text[:700]}

OUTPUT (3 sentences, max 75 words):"""

    result = _call_ollama(prompt, max_tokens=250)
    # Strip LLM preamble
    result = re.sub(r"^(Summary:|Here is|Here's|Sure[,:]?)\s*", "", result, flags=re.IGNORECASE).strip().strip('"')

    # ── Post-process: guarantee job title appears ───────────────────────────
    if job_title and job_title.lower() not in result.lower():
        # Inject naturally: "[Title] and M.S. candidate..." or prepend
        if result.lower().startswith("m.s."):
            result = f"{job_title} and {result[0].lower()}{result[1:]}"
        else:
            result = f"Aspiring {job_title} — {result}"
        print(f"   ✅ Job title '{job_title}' injected into summary.")

    return result


def rewrite_bullets(
    bullets: list[str],
    jd_text: str,
    keywords: list[str],
    company: str,
    title: str,
    critical_keywords: list[str] = None
) -> list[str]:
    """
    Rewrite work experience bullets with JD keywords.
    critical_keywords are ATS-gap terms that MUST appear.
    """
    top_kws = ", ".join(keywords[:20])
    bullets_text = "\n".join(f"- {b}" for b in bullets)
    crit = ", ".join((critical_keywords or [])[:8])
    crit_instruction = f"- MUST naturally use these high-priority ATS gap keywords across the 3 bullets: {crit}" if crit else ""

    prompt = f"""You are a professional resume writer. Rewrite exactly 3 bullet points for a work experience entry.

RULES — STRICTLY FOLLOW:
- Output EXACTLY 3 bullets — no more, no less
- Keep company name exactly: "{company}"
- Keep ALL numbers/percentages/rankings unchanged — they are facts
- Incorporate these JD keywords naturally: {top_kws}
{crit_instruction}
- IMPORTANT PHRASING: always use "recommender systems" (plural), "applied machine learning", "representation learning"
- Each bullet: strong action verb → specific technical work → measurable result with a number
- Each bullet should be 1–2 lines, impactful and detailed (160–220 characters)
- Use collaborative, research-oriented language where appropriate
- Do NOT add fake numbers or experiences
- Output ONLY 3 bullet lines starting with "•", nothing else

ROLE: {title} at {company}

ORIGINAL BULLETS (use as basis, rewrite with JD focus):
{bullets_text}

JD KEYWORDS: {top_kws}

REWRITTEN BULLETS (exactly 3, each starting with •):"""

    result = _call_ollama(prompt, max_tokens=500)

    # Parse output
    lines = [l.strip() for l in result.split("\n") if l.strip()]
    rewritten = []
    for line in lines:
        # Strip bullet markers
        line = re.sub(r"^[•\-\*]\s*", "", line).strip()
        if len(line) > 20:
            rewritten.append(line)

    # Fallback: if rewrite failed or produced too few, use originals
    if len(rewritten) < 3:
        rewritten = rewritten + bullets[:3][len(rewritten):]

    return rewritten[:3]


def rewrite_project_bullets(
    project: dict,
    jd_text: str,
    keywords: list[str]
) -> list[str]:
    """
    Rewrite project bullets to embed JD keywords while preserving STAR structure.
    """
    top_kws = ", ".join(keywords[:15])
    bullets_text = "\n".join(f"- {b}" for b in project["star_bullets"])

    prompt = f"""You are a professional resume writer. Rewrite exactly 3 bullet points for a technical project on a resume.

RULES — STRICTLY FOLLOW:
- Output EXACTLY 3 bullets — no more, no less
- Keep ALL numbers/percentages/rankings unchanged — they are facts
- Incorporate these JD keywords naturally: {top_kws}
- Bullet 1: situation/problem + technical action
- Bullet 2: implementation details with specific technologies
- Bullet 3: measurable result (%, time saved, accuracy, users, etc.)
- Each bullet MUST be under 180 characters — concise and punchy
- Do NOT invent new numbers or technologies
- Output ONLY 3 bullet lines starting with "•", nothing else

PROJECT: {project['name']}
TECH: {project['tech']}

ORIGINAL BULLETS (pick best 3):
{bullets_text}

RESUME KEYWORDS: {top_kws}

REWRITTEN BULLETS (exactly 3, each starting with •, each under 180 chars):"""

    result = _call_ollama(prompt, max_tokens=400)

    lines = [l.strip() for l in result.split("\n") if l.strip()]
    rewritten = []
    for line in lines:
        line = re.sub(r"^[•\-\*]\s*", "", line).strip()
        if len(line) > 20:
            rewritten.append(line)

    if len(rewritten) < 3:
        rewritten = rewritten + project["star_bullets"][:3][len(rewritten):]

    return rewritten


def generate_projects(
    jd_text: str,
    keywords: list[str],
    role_category: str,
    candidate_skills: dict,
    critical_keywords: list[str] = None
) -> list[dict]:
    """
    Generate 3 BRAND NEW projects from scratch using Mistral, tailored to this JD.
    Not selected from a fixed pool — invented fresh every time.
    """
    top_kws = ", ".join(keywords[:20])

    langs  = candidate_skills.get("Languages", "Python, SQL, JavaScript, TypeScript, R")
    ml     = candidate_skills.get(
        "ML & AI Frameworks",
        candidate_skills.get("ML & Statistical Methods",
        candidate_skills.get("ML & Frameworks", "PyTorch, TensorFlow, Scikit-learn")))
    cloud  = candidate_skills.get(
        "Cloud & DevOps",
        candidate_skills.get("Cloud & Tools", "AWS, GCP, Docker, Git, Linux"))

    crit = ", ".join((critical_keywords or [])[:6])
    research_kw = "recommender systems, representation learning, research, applied machine learning"
    must_use = f"Include these keywords naturally across the 3 projects: {research_kw}" + (f", {crit}" if crit else "") + "."

    # ── Simplified prompt — complex nested rules confuse Mistral 7B ──────────
    prompt = f"""Write exactly 3 technical resume project entries in this EXACT format.

Tech stack to use (ONLY these):
Languages: {langs}
ML/AI: {ml}
Tools: {cloud}, Flask, FastAPI, Streamlit, PostgreSQL, MongoDB, Pandas, NumPy, Plotly, LangChain, spaCy

{must_use}
Target these JD keywords: {top_kws}

Rules:
- Each project is a solo personal/academic project (no company names)
- Bullet 1: describe the real-world problem and what you designed (include scale e.g. N users/records)
- Bullet 2: your technical implementation — specific tools, model type, technique
- Bullet 3: quantified result with % improvement AND comparison baseline (vs. X method/baseline)
- Realistic numbers only (20-45% improvement, 75-93% accuracy) — no 99%+ claims
- Bullets under 220 characters each

OUTPUT FORMAT — follow exactly, blank line between projects:
PROJECT: <title>
TECH: <4-7 tools>
• <bullet 1 — situation/task>
• <bullet 2 — action/implementation>
• <bullet 3 — result with number and baseline>

JD keywords context:
{jd_text[:550]}

Write the 3 projects:"""

    result = _call_ollama(prompt, max_tokens=1100)

    # ── Hardened parser: handles Mistral's common output variants ─────────────
    projects = []

    # Split on blank lines OR on PROJECT: markers
    proj_sections = re.split(
        r"\n(?=PROJECT\s*:|Project\s+\d+\s*:)",
        result.strip(), flags=re.IGNORECASE
    )
    if len(proj_sections) <= 1:
        proj_sections = re.split(r"\n{2,}", result.strip())

    for block in proj_sections:
        block = block.strip()
        if not block:
            continue

        lines = [l.strip() for l in block.splitlines() if l.strip()]
        name, tech, bullets = "", "", []

        for line in lines:
            if re.match(r"^(PROJECT|Project\s*\d*)\s*:", line, re.IGNORECASE):
                name = re.sub(r"^(PROJECT|Project\s*\d*)\s*:\s*", "", line, flags=re.IGNORECASE).strip()
            elif re.match(r"^(TECH|Technologies?|Tech\s*Stack)\s*:", line, re.IGNORECASE):
                tech = re.sub(r"^(TECH|Technologies?|Tech\s*Stack)\s*:\s*", "", line, flags=re.IGNORECASE).strip()
            elif re.match(r"^[•\-\*]\s*|\d[\.\)]\s+", line):
                # Strip bullet marker then strip STAR labels if present
                bullet = re.sub(r"^[•\-\*]\s*|\d[\.\)]\s+", "", line).strip()
                bullet = re.sub(r"^(Situation|Task|Action|Result)\s*:\s*", "", bullet, flags=re.IGNORECASE).strip()
                if len(bullet) > 20:
                    bullets.append(bullet)

        # Fallback: if name not found via PROJECT:, use first substantial line
        if not name:
            for line in lines:
                if len(line) > 10 and not re.match(r"^(TECH|•|\-|\*|\d|Write|PROJECT)", line, re.IGNORECASE):
                    name = line.strip()
                    break
        if not tech and len(lines) > 1:
            for line in lines[:4]:
                if re.search(r"Python|PyTorch|SQL|TensorFlow|Flask|Scikit", line, re.IGNORECASE):
                    tech = line.strip()
                    break

        if name and bullets:
            if not tech:
                tech = "Python, PyTorch, SQL, Pandas, NumPy"
            while len(bullets) < 3:
                bullets.append(
                    f"Achieved significant performance improvement over baseline "
                    f"using {tech.split(',')[0].strip()} and data-driven methods."
                )
            projects.append({"name": name, "tech": tech, "star_bullets": bullets[:3]})

        if len(projects) >= 3:
            break

    if len(projects) < 3:
        print(f"   ⚠️  Project generation returned {len(projects)}/3 — pool fallback for remaining.")

    return projects


def _rewrite_pool_project(project: dict, jd_text: str, keywords: list[str]) -> dict:
    """Fallback: rewrite a pool project's bullets with JD keywords."""
    top_kws = ", ".join(keywords[:15])
    bullets_text = "\n".join(f"- {b}" for b in project["star_bullets"])

    prompt = f"""Rewrite exactly 3 resume bullet points for this project. Output ONLY 3 lines starting with •.
Keep all numbers unchanged. Each bullet under 180 chars. Weave in: {top_kws}

PROJECT: {project['name']} | TECH: {project['tech']}
ORIGINAL:
{bullets_text}

REWRITTEN (exactly 3 bullets starting with •):"""

    result = _call_ollama(prompt, max_tokens=400)
    lines = [l.strip() for l in result.split("\n") if l.strip()]
    rewritten = []
    for line in lines:
        line = re.sub(r"^[•\-\*]\s*", "", line).strip()
        if len(line) > 20:
            rewritten.append(line)
    if len(rewritten) < 3:
        rewritten = rewritten + project["star_bullets"][:3][len(rewritten):]
    return {**project, "star_bullets": rewritten[:3]}


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


def _ensure_critical_keywords(content: dict, critical_keywords: list, job_title: str = "") -> dict:
    """
    Post-processing safety net — after all LLM calls, scan the FULL generated
    text. For any critical keyword appearing 0 times, inject it into the summary.
    This guarantees minimum keyword presence regardless of LLM compliance.
    """
    # Build full text snapshot
    full_text = content.get("summary", "").lower()
    for exp in content.get("work_experience", []):
        for b in exp.get("bullets", []):
            full_text += " " + b.lower()
    for proj in content.get("projects", []):
        full_text += " " + proj.get("name", "").lower()
        for b in proj.get("star_bullets", []):
            full_text += " " + b.lower()
    for cat, val in content.get("skills", {}).items():
        full_text += " " + val.lower()

    # Find completely missing critical keywords
    missing = [kw for kw in (critical_keywords or []) if kw.lower() not in full_text]

    if missing:
        missing_str = ", ".join(missing[:6])
        print(f"   💉 Injecting {len(missing)} missing ATS keywords: {missing_str}")
        # Append as a natural addendum sentence to the summary
        summary = content.get("summary", "").rstrip(".")
        content["summary"] = (
            summary
            + f". Hands-on experience with {missing_str} applied"
              f" to real-world research and production ML systems."
        )
    else:
        print("   ✅ All critical ATS keywords present in resume text.")

    return content


def _tailor_skills(skills: dict, keywords: list, critical_keywords: list) -> dict:
    """
    Deterministically re-order and enrich the skills section — no LLM needed.
    1. Within each category, surfaces items matching JD keywords first.
    2. Injects missing critical domain terms into the 'ML Concepts' category.
    """
    all_kw = {kw.lower() for kw in (keywords or []) + (critical_keywords or [])}

    tailored = {}
    for category, value in skills.items():
        if not value:
            continue
        items = [item.strip() for item in value.split(",") if item.strip()]
        # Priority items = those matching any JD keyword
        priority = [it for it in items if any(kw in it.lower() for kw in all_kw)]
        rest     = [it for it in items if it not in priority]
        tailored[category] = ", ".join(priority + rest)

    # Inject missing critical ML concepts into the ML Concepts & Methods category
    concepts_key = next(
        (k for k in tailored if "concept" in k.lower() or "method" in k.lower()), None
    )
    if concepts_key:
        existing_lower = tailored[concepts_key].lower()
        to_inject = []
        for kw in (critical_keywords or []):
            # Only inject if: domain concept (len>4), not already present
            if len(kw) > 4 and kw.lower() not in existing_lower:
                # Title-case for readability in the skills row
                to_inject.append(kw.title())
        if to_inject:
            tailored[concepts_key] = tailored[concepts_key] + ", " + ", ".join(to_inject[:4])

    return tailored


def tailor_content(selected_content: dict, jd_parsed: dict) -> dict:
    """
    Main entry point: takes selected content + parsed JD,
    returns fully tailored content dict ready for PDF rendering.
    """
    jd_text   = jd_parsed["raw_text"]
    keywords  = jd_parsed["keywords"]
    role_cat  = jd_parsed["role_category"]
    job_title = jd_parsed.get("job_title", "")

    # Identify ATS gap keywords that need higher frequency
    critical_keywords = _extract_critical_keywords(jd_text, keywords)
    if critical_keywords:
        print(f"   🎯 Critical ATS keywords: {', '.join(critical_keywords[:6])}")

    print("🤖 Generating tailored summary...")
    summary = generate_summary(
        jd_text, role_cat, selected_content, keywords,
        job_title=job_title,
        critical_keywords=critical_keywords
    )

    print("📝 Rewriting work experience bullets...")
    tailored_work = []
    for exp in selected_content["work_experience"]:
        rewritten = rewrite_bullets(
            exp["bullets"], jd_text, keywords,
            exp["company"], exp["title"],
            critical_keywords=critical_keywords
        )
        tailored_work.append({**exp, "bullets": rewritten})

    print("🚀 Generating fresh projects for this JD...")
    fresh_projects = generate_projects(
        jd_text, keywords, role_cat, selected_content["skills"],
        critical_keywords=critical_keywords
    )

    # If generation produced fewer than 3, top up from selected pool
    if len(fresh_projects) < 3:
        pool_projects = selected_content["projects"]
        for proj in pool_projects:
            if len(fresh_projects) >= 3:
                break
            fresh_projects.append(_rewrite_pool_project(proj, jd_text, keywords))

    # ── Tailor skills section (deterministic — no LLM needed) ─────────────
    tailored_skills = _tailor_skills(selected_content["skills"], keywords, critical_keywords)

    result = {
        **selected_content,
        "summary": summary,
        "work_experience": tailored_work,
        "projects": fresh_projects[:3],
        "skills": tailored_skills,
    }

    # ── Safety net: guarantee all critical keywords appear ─────────────────
    print("🔍 Verifying ATS keyword coverage...")
    result = _ensure_critical_keywords(result, critical_keywords, job_title)

    return result
