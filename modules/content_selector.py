"""
content_selector.py
Scores and selects the best projects, work-exp titles, and bullet variants
from resume_data.json based on JD keywords and role category.
"""
from __future__ import annotations
import json
import re
from pathlib import Path


DATA_PATH = Path(__file__).parent.parent / "resume_data.json"


def _load_data() -> dict:
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


_ITEM_SPLIT = re.compile(r",\s*(?![^()]*\))")   # split on commas outside parentheses
_ALIASES = {"huggingface transformers": "transformers (huggingface)"}


def split_skill_items(value: str) -> list[str]:
    return [i.strip() for i in _ITEM_SPLIT.split(value) if i.strip()]


def _skill_is_grounded(item: str, blob: str) -> bool:
    """True if a skill is supported by resume_data.json (any text, or skills_pool.additional)."""
    low = item.lower().strip()
    low = _ALIASES.get(low, low)
    base = low.split("(")[0].strip()
    return low in blob or (len(base) > 1 and base in blob)


def ground_skills(skills: dict, data: dict) -> dict:
    """Drop any skill not backed by resume_data.json so tailoring never invents skills."""
    blob = json.dumps(data, ensure_ascii=False).lower()
    out = {}
    for cat, value in skills.items():
        kept = [i for i in split_skill_items(value) if _skill_is_grounded(i, blob)]
        if kept:
            out[cat] = ", ".join(kept)
    return out


def _keyword_score(text: str, keywords: list[str]) -> float:
    """Score text by how many JD keywords it contains."""
    text_lower = text.lower()
    hits = sum(1 for kw in keywords if kw.lower() in text_lower)
    return hits / max(len(keywords), 1)


def select_projects(keywords: list[str], role_category: str, n: int = 3) -> list[dict]:
    """
    Pick top N projects from the pool that best match the JD keywords.
    Always returns exactly n projects.
    """
    data = _load_data()
    pool = data["projects_pool"]

    scored = []
    for project in pool:
        # Score by tag overlap + full-text keyword match on bullets
        tag_hits = sum(1 for kw in keywords if any(kw.lower() in tag.lower() for tag in project["tags"]))
        text_blob = " ".join(project["star_bullets"]) + " " + " ".join(project["tags"])
        text_score = _keyword_score(text_blob, keywords)
        total_score = tag_hits * 2 + text_score * 10
        scored.append((total_score, project))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:n]]


def select_work_exp_bullets(
    company_index: int,
    keywords: list[str],
    role_category: str,
    n_bullets: int = 3
) -> tuple[str, list[str]]:
    """
    For a given work experience entry, select:
    - Best job title variant
    - Best N bullet points

    Returns (title, [bullet, ...])
    """
    data = _load_data()
    exp = data["work_experience"][company_index]

    # Pick title
    title_pool = exp["title_pool"]
    title = title_pool.get(role_category, title_pool.get("default", list(title_pool.values())[0]))

    # Pick bullets
    bullets_pool = exp["bullets_pool"]
    candidates = bullets_pool.get(role_category, bullets_pool.get("default", []))

    if not candidates:
        candidates = bullets_pool.get("default", [])

    # Score bullets by keyword overlap
    scored = [(  _keyword_score(b, keywords), b) for b in candidates]
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [b for _, b in scored[:n_bullets]]

    # Pad with default bullets if needed
    if len(selected) < n_bullets:
        defaults = bullets_pool.get("default", [])
        for d in defaults:
            if d not in selected:
                selected.append(d)
            if len(selected) >= n_bullets:
                break

    return title, selected[:n_bullets]


def select_education_courses(role_category: str) -> list[dict]:
    """Select appropriate coursework per education entry based on role."""
    data = _load_data()
    result = []
    for edu in data["education"]:
        courses = edu["coursework_pool"].get(role_category, edu["coursework_pool"]["default"])
        result.append({
            **{k: v for k, v in edu.items() if k != "coursework_pool"},
            "coursework": courses
        })
    return result


def build_skills_section(keywords: list[str], role_category: str) -> dict:
    """
    Build a comprehensive, ATS-optimized skills section — always 6 categories.
    Each category has 8-12 items, clearly separated by domain.
    """
    data = _load_data()
    pool = data["skills_pool"]
    kw_lower = " ".join(keywords).lower()

    # ── Languages ────────────────────────────────────────────────────────────
    lang_map = {
        "ml_ai":          ["Python", "SQL", "R", "Go", "JavaScript", "TypeScript", "Java", "C", "C++", "Bash"],
        "data_science":   ["Python", "SQL", "R", "MATLAB", "JavaScript", "TypeScript", "Java", "Scala", "Bash"],
        "data_engineer":  ["Python", "SQL", "Scala", "Java", "R", "Bash", "JavaScript", "TypeScript"],
        "swe":            ["Python", "JavaScript", "TypeScript", "Java", "C", "C++", "SQL", "Bash", "Go", "Node.js"],
        "analyst":        ["Python", "SQL", "R", "MATLAB", "JavaScript", "TypeScript", "Java", "Bash"],
        "mlops":          ["Python", "SQL", "Bash", "Go", "JavaScript", "TypeScript", "Java", "C"],
        "cv":             ["Python", "SQL", "C++", "MATLAB", "R", "JavaScript", "Bash", "Go"],
        "nlp":            ["Python", "SQL", "R", "JavaScript", "TypeScript", "Java", "Bash"],
    }
    languages = lang_map.get(role_category, lang_map["ml_ai"])
    # Boost with any JD-mentioned languages from core pool
    core_langs = pool["languages"]["core"]
    jd_langs = [l for l in core_langs if l.lower() in kw_lower and l not in languages]
    languages = list(dict.fromkeys(languages + jd_langs))[:11]

    # ── ML Frameworks (only actual libraries, no concepts) ───────────────────
    base_frameworks = ["PyTorch", "TensorFlow", "Scikit-learn", "Keras", "XGBoost",
                       "LightGBM", "HuggingFace Transformers", "spaCy", "LangChain", "OpenCV"]
    # Boost JD-matching frameworks first
    jd_frameworks = [f for f in base_frameworks if f.lower() in kw_lower]
    rest_frameworks = [f for f in base_frameworks if f not in jd_frameworks]
    ml_frameworks = list(dict.fromkeys(jd_frameworks + rest_frameworks))[:10]

    # ── ML Concepts & Methods ────────────────────────────────────────────────
    concept_map = {
        "ml_ai": [
            "Deep Learning", "Recommender Systems", "Representation Learning",
            "Reinforcement Learning", "Computer Vision", "NLP", "Transformers",
            "Generative AI", "A/B Testing", "Feature Engineering", "Embeddings",
        ],
        "data_science": [
            "Deep Learning", "Statistical Modeling", "Hypothesis Testing",
            "Feature Engineering", "A/B Testing", "Regression", "Classification",
            "Time-Series Forecasting", "EDA", "Model Evaluation",
        ],
        "cv": [
            "Object Detection", "Image Classification", "Semantic Segmentation",
            "Transfer Learning", "Face Recognition", "YOLO", "Feature Extraction",
            "Image Preprocessing", "Deep Learning", "Convolutional Networks",
        ],
        "nlp": [
            "Transformers", "Named Entity Recognition", "Sentiment Analysis",
            "Text Classification", "RAG", "Semantic Search", "Tokenization",
            "Language Modeling", "Intent Detection", "Summarization",
        ],
        "mlops": [
            "ML Lifecycle Management", "Model Deployment", "Experiment Tracking",
            "Model Monitoring", "CI/CD for ML", "A/B Testing", "Feature Stores",
            "Model Versioning", "Drift Detection", "Online Serving",
        ],
    }
    ml_concepts = concept_map.get(role_category, concept_map["ml_ai"])
    # Boost JD-matching concepts first
    jd_concepts = [c for c in ml_concepts if c.lower() in kw_lower]
    rest_concepts = [c for c in ml_concepts if c not in jd_concepts]
    ml_concepts = list(dict.fromkeys(jd_concepts + rest_concepts))[:11]

    # ── Cloud & DevOps ───────────────────────────────────────────────────────
    cloud_map = {
        "ml_ai":        ["AWS (EC2, S3, SageMaker, Lambda)", "GCP", "Azure", "Docker",
                         "Kubernetes", "CI/CD", "MLflow", "Git", "Linux", "REST APIs"],
        "data_science": ["AWS (EC2, S3, SageMaker, Glue)", "GCP", "Azure", "Docker",
                         "Kubernetes", "CI/CD", "MLflow", "Git", "Linux"],
        "data_engineer":["AWS (S3, Glue, Redshift, Lambda)", "GCP (BigQuery)", "Azure",
                         "Docker", "Kubernetes", "Airflow", "CI/CD", "Git", "Linux"],
        "swe":          ["AWS (EC2, S3, Lambda)", "GCP", "Azure", "Docker", "Kubernetes",
                         "CI/CD", "GitHub Actions", "Linux", "Git", "REST APIs"],
        "analyst":      ["AWS (S3, EC2, Redshift)", "GCP", "Azure", "Docker", "Git",
                         "Linux", "Tableau Server", "REST APIs"],
        "mlops":        ["AWS (EC2, S3, SageMaker, Lambda)", "GCP", "Azure", "Docker",
                         "Kubernetes", "GitHub Actions", "MLflow", "Git", "Linux", "CI/CD"],
    }
    cloud_skills = cloud_map.get(role_category, cloud_map["ml_ai"])

    # ── Libraries & Data Tools ───────────────────────────────────────────────
    lib_map = {
        "ml_ai":        ["Pandas", "NumPy", "Plotly", "Streamlit", "Matplotlib",
                         "Seaborn", "Flask", "FastAPI", "SciPy", "Statsmodels"],
        "data_science": ["Pandas", "NumPy", "Plotly", "Matplotlib", "Seaborn",
                         "Streamlit", "Power BI", "Flask", "SciPy", "Statsmodels"],
        "data_engineer":["Pandas", "NumPy", "Apache Spark", "Airflow", "Kafka",
                         "dbt", "Plotly", "Streamlit", "Snowflake", "FastAPI"],
        "swe":          ["React", "Node.js", "Flask", "FastAPI", "Express.js",
                         "NumPy", "Pandas", "Swagger / OpenAPI", "Jest", "Axios"],
        "analyst":      ["Pandas", "NumPy", "Plotly", "Power BI", "Tableau",
                         "Seaborn", "Matplotlib", "Streamlit", "Statsmodels", "SciPy"],
        "mlops":        ["MLflow", "Prometheus", "Grafana", "FastAPI", "Pandas",
                         "NumPy", "Plotly", "Streamlit", "DataDog", "Prefect"],
    }
    lib_skills = lib_map.get(role_category, lib_map["ml_ai"])

    # ── Databases ────────────────────────────────────────────────────────────
    db_map = {
        "ml_ai":        ["PostgreSQL", "MySQL", "MongoDB", "SQLite", "Redis", "BigQuery", "Elasticsearch"],
        "data_science": ["PostgreSQL", "MySQL", "MongoDB", "SQLite", "BigQuery", "Snowflake", "Redis"],
        "data_engineer":["PostgreSQL", "MySQL", "MongoDB", "Snowflake", "BigQuery",
                         "Redshift", "Cassandra", "Redis", "Elasticsearch"],
        "swe":          ["PostgreSQL", "MySQL", "MongoDB", "SQLite", "Redis", "DynamoDB", "Elasticsearch"],
        "analyst":      ["PostgreSQL", "MySQL", "SQLite", "MongoDB", "Snowflake", "BigQuery", "Redshift"],
        "mlops":        ["PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch", "Cassandra"],
    }
    db_skills = db_map.get(role_category, db_map["ml_ai"])

    # ── Assemble 6-category skills dict ─────────────────────────────────────
    skills = {}

    if role_category in ("ml_ai", "cv", "nlp", "mlops", "data_science"):
        skills["Languages"] = ", ".join(languages)
        skills["ML & AI Frameworks"] = ", ".join(ml_frameworks)
        skills["ML Concepts & Methods"] = ", ".join(ml_concepts)
        skills["Cloud & DevOps"] = ", ".join(cloud_skills)
        skills["Libraries & Tools"] = ", ".join(lib_skills)
        skills["Databases"] = ", ".join(db_skills)

    elif role_category == "data_engineer":
        skills["Languages"] = ", ".join(languages)
        skills["Data Engineering"] = ", ".join([
            "Apache Spark", "Airflow", "Kafka", "dbt", "Hadoop",
            "ETL Pipelines", "Data Modeling", "Snowflake", "BigQuery"
        ])
        skills["ML & Frameworks"] = ", ".join(ml_frameworks[:7])
        skills["Cloud & DevOps"] = ", ".join(cloud_skills)
        skills["Libraries & Tools"] = ", ".join(lib_skills)
        skills["Databases"] = ", ".join(db_skills)

    elif role_category == "swe":
        skills["Languages & APIs"] = ", ".join(languages[:8] + ["REST APIs", "GraphQL"])
        skills["Frameworks & Libraries"] = ", ".join(lib_skills)
        skills["Cloud & Infrastructure"] = ", ".join(cloud_skills)
        skills["Databases"] = ", ".join(db_skills)
        skills["AI & ML"] = ", ".join(ml_frameworks[:6] + ["LangChain", "Generative AI"])
        skills["Concepts & Methods"] = "Agile/Scrum, CI/CD, API Design, Testing & QA, Microservices, System Design"

    elif role_category == "analyst":
        skills["Languages"] = ", ".join(languages)
        skills["Analytics & BI"] = "SQL, Power BI, Tableau, Plotly, Pandas, Matplotlib, Seaborn, Streamlit"
        skills["ML & Statistical Methods"] = ", ".join(ml_frameworks[:5] + [
            "Regression", "Classification", "A/B Testing", "Hypothesis Testing"
        ])
        skills["Cloud & Data Stack"] = ", ".join(cloud_skills)
        skills["Libraries & Tools"] = ", ".join(lib_skills)
        skills["Databases"] = ", ".join(db_skills)

    else:
        # Default — comprehensive
        skills["Languages"] = ", ".join(languages)
        skills["ML & AI Frameworks"] = ", ".join(ml_frameworks)
        skills["ML Concepts & Methods"] = ", ".join(ml_concepts)
        skills["Cloud & DevOps"] = ", ".join(cloud_skills)
        skills["Libraries & Tools"] = ", ".join(lib_skills)
        skills["Databases"] = ", ".join(db_skills)

    return ground_skills(skills, data)



def select_all(jd_parsed: dict) -> dict:
    """
    Master selector: given parsed JD, select all resume content.
    Returns a complete content dict ready for the PDF renderer.
    """
    data = _load_data()
    keywords = jd_parsed["keywords"]
    role_cat = jd_parsed["role_category"]

    # Projects
    projects = select_projects(keywords, role_cat, n=3)

    # Work experience
    work_exp = []
    for i, exp in enumerate(data["work_experience"]):
        title, bullets = select_work_exp_bullets(i, keywords, role_cat)
        work_exp.append({
            "company": exp["company"],
            "location": exp["location"],
            "dates": exp["dates"],
            "title": title,
            "bullets": bullets
        })

    # Education
    education = select_education_courses(role_cat)

    # Skills
    skills = build_skills_section(keywords, role_cat)

    return {
        "personal": data["personal"],
        "education": education,
        "work_experience": work_exp,
        "projects": projects,
        "skills": skills,
        "certifications": data["certifications"],
        "jd_info": jd_parsed
    }


def build_fallback_summary(content: dict, keywords: list[str]) -> str:
    """Deterministic summary built only from resume_data.json facts (no LLM)."""
    edu = content.get("education") or [{}]
    degree = edu[0].get("degree", "").strip()
    roles = [f"{w['title']} at {w['company']}" for w in content.get("work_experience", [])[:2]]
    items = [i for v in content.get("skills", {}).values() for i in split_skill_items(v)]
    wanted = {k.lower() for k in keywords if len(k) > 2}
    skills = [i for i in items if i.lower().split(" (")[0] in wanted][:5]
    parts = []
    if degree:
        parts.append(f"{degree} candidate")
    else:
        parts.append("Candidate")
    if roles:
        parts[0] += " with experience as " + " and ".join(roles) + "."
    else:
        parts[0] += "."
    if skills:
        parts.append("Skilled in " + ", ".join(skills) + ".")
    return " ".join(parts)
