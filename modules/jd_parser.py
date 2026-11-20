"""
jd_parser.py
Extracts company name, job role, role category, and ranked keywords from a JD.
"""
import re
import string
from collections import Counter


# -------------------------------------------------------------------
# Stop-words (minimal, inline — no external NLP deps required)
# -------------------------------------------------------------------
STOP_WORDS = set("""
a an the and or but in on at to for of with as by from is are was were be been
being have has had do does did will would could should may might shall can not
no nor so yet both either neither each few more most other some such than
then there these this that those through what which who why how all also just
well than very too much many any our your we us our their its it its we
you he she they them his her we our it be to do
""".split())

# Role → internal category mapping  
ROLE_KEYWORDS = {
    "ml_ai": [
        "machine learning", "ml", "artificial intelligence", "ai", "deep learning",
        "computer vision", "nlp", "natural language", "generative ai", "llm",
        "model", "training", "inference", "pytorch", "tensorflow", "neural",
        "ml engineer", "ai engineer", "research scientist", "applied scientist"
    ],
    "swe": [
        "software engineer", "software developer", "swe", "backend", "frontend",
        "full stack", "full-stack", "node.js", "react", "api", "rest",
        "microservices", "system design", "object oriented", "oop",
        "ci/cd", "devops", "platform engineer", "site reliability"
    ],
    "data_science": [
        "data scientist", "data science", "statistical", "statistics",
        "predictive", "analytics", "eda", "exploratory", "hypothesis",
        "regression", "classification", "clustering", "xgboost", "sklearn"
    ],
    "data_engineer": [
        "data engineer", "data engineering", "etl", "pipeline", "spark",
        "airflow", "kafka", "hadoop", "snowflake", "dbt", "bigquery",
        "redshift", "warehouse", "lakehouse", "ingestion", "streaming"
    ],
    "analyst": [
        "analyst", "business analyst", "data analyst", "product analyst",
        "power bi", "tableau", "dashboard", "reporting", "kpi", "metrics",
        "sql analyst", "insights", "business intelligence"
    ],
    "mlops": [
        "mlops", "ml infrastructure", "ml platform", "model deployment",
        "model serving", "mlflow", "kubeflow", "monitoring", "observability",
        "experiment tracking", "feature store", "model registry"
    ],
    "cv": [
        "computer vision", "cv", "image processing", "object detection",
        "yolo", "segmentation", "ocr", "video analytics", "cctv"
    ],
    "nlp": [
        "natural language processing", "nlp", "text mining", "sentiment",
        "ner", "chatbot", "language model", "bert", "gpt", "transformer"
    ]
}

# High-value tech keywords to always capture
TECH_KEYWORDS = {
    "python", "sql", "java", "javascript", "typescript", "r", "scala", "go",
    "c++", "bash", "matlab", "node.js", "html", "css",
    "pytorch", "tensorflow", "scikit-learn", "keras", "xgboost", "lightgbm",
    "spark", "airflow", "kafka", "hadoop", "dbt", "snowflake",
    "aws", "gcp", "azure", "docker", "kubernetes", "ci/cd", "git", "linux",
    "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "bigquery",
    "power bi", "tableau", "plotly", "streamlit",
    "langchain", "openai", "llm", "rag", "huggingface", "transformers",
    "opencv", "yolo", "retinaface", "fastapi", "flask", "django", "react",
    "mlflow", "mlops", "sagemaker", "databricks",
    "agile", "scrum", "rest api", "microservices"
}


def _clean_text(text: str) -> str:
    """Lowercase, remove punctuation."""
    text = text.lower()
    text = text.replace("/", " ").replace("-", " ").replace(".", " ")
    text = text.translate(str.maketrans("", "", string.punctuation))
    return text


def _extract_company(jd_text: str) -> str:
    """Extract company name — handles structured and modern unstructured JDs."""
    # Skip the separator line the pipeline prepends
    lines = [l.strip() for l in jd_text.strip().splitlines()
             if l.strip() and not l.startswith('===') and
             'PASTE YOUR JOB' not in l.upper()]

    # ── Priority 1: explicit label ──────────────────────────────────────────
    m = re.search(r"(?:Company|Employer|Organization)[:\s]+([A-Z][A-Za-z0-9\s&.,'-]{2,40}?)\s*[\n\r,]",
                  jd_text, re.IGNORECASE)
    if m:
        return m.group(1).strip().rstrip(".,")

    # ── Priority 2: "About CompanyName" section ─────────────────────────────
    m = re.search(r"About\s+([A-Z][A-Za-z0-9\s&.,'-]{2,35}?)[\n\r:,]", jd_text, re.IGNORECASE)
    if m:
        candidate = m.group(1).strip().rstrip(".,")
        low = candidate.lower()
        if len(candidate) > 1 and low not in ("the", "our", "this", "we", "a", "an",
                                               "the role", "the company", "us"):
            return candidate

    # ── Priority 3: "CompanyName is on/a/an/the/building…" at line start ────
    m = re.search(
        r"^([A-Z][A-Za-z0-9]{2,25})\s+is\s+(?:on\s+a|a\s+|an\s+|the\s+|building|now|hiring)",
        jd_text, re.MULTILINE)
    if m:
        return m.group(1).strip()

    # ── Priority 4: common patterns ──────────────────────────────────────────
    patterns = [
        r"(?:at|@|join|joining)\s+([A-Z][A-Za-z0-9\s&.,'-]{2,35}?)(?:\s*[,\n\r]|\s+is\s|\s+we\s|\s+our\s)",
        r"^([A-Z][A-Za-z0-9\s&.,'-]{1,25}?)\s+(?:engineers?|team|employees?)\s+",
        r"([A-Z][A-Za-z0-9\s&.,'-]{2,35}?)\s+(?:Inc|LLC|Corp|Ltd|Co)\b",
    ]
    for pat in patterns:
        m = re.search(pat, jd_text, re.MULTILINE)
        if m:
            cand = m.group(1).strip().rstrip(".,'")
            low = cand.lower()
            if len(cand) > 2 and low not in (
                "the", "our", "this", "we", "a", "an", "what",
                "rilla engineers", "role", "team"):
                return cand

    # ── Priority 5: first short title-case word among early lines ───────────
    SKIP = {"the", "our", "this", "we", "a", "an", "what", "why", "how",
            "about", "role", "team", "company", "position", "job",
            "technologies", "benefits", "requirements", "responsibilities"}
    for line in lines[:20]:
        words = line.split()
        # Single capitalized word, 3-25 chars — likely a company name
        if 1 <= len(words) <= 3:
            candidate = " ".join(words)
            low = candidate.lower()
            if (candidate[0].isupper() and low not in SKIP
                    and 3 <= len(candidate) <= 30
                    and not any(c.isdigit() for c in candidate)):
                return candidate

    return "Company"


def _extract_job_title(jd_text: str) -> str:
    """Extract job title — handles both structured and free-form JDs."""
    SECTION_HEADER_BLACKLIST = {
        "internship details", "about this role", "about the role", "what you'll work on",
        "what you will work on", "basic qualifications", "preferred qualifications",
        "why this role", "why this role is unique", "what we look for",
        "recruiter tips", "job level match", "responsibilities", "requirements",
        "your responsibilities", "the role", "role overview", "is unique",
        "why this", "why the", "how you", "what you", "what we", "who you",
        "about you", "you will", "you'll", "we are", "we're", "our team", "the team",
        "location", "salary", "compensation", "benefits", "about us",
        "don't work here", "do not work here", "what we value", "what we require",
        "technologies we use", "what you'll do", "what you will do",
    }

    # 1. Explicit label patterns
    for pat in [
        r"(?:Position|Role|Title|Job Title)[:\s]+([A-Za-z\s/&\-]{5,70}?)[\n\r,]",
        r"(?:hiring|seeking|looking for)\s+(?:a|an)\s+([A-Za-z\s/&\-]{5,60}?)(?:\s+to\s|\s+who\s|[.,\n])",
        r"(?:We are hiring|We're hiring|Now hiring)\s+(?:a|an)?\s*([A-Za-z\s/&\-]{5,60}?)(?:\s+to\s|[.,\n])",
    ]:
        m = re.search(pat, jd_text, re.IGNORECASE | re.MULTILINE)
        if m:
            title = m.group(1).strip().rstrip(".,")
            if 4 < len(title) < 70 and title.lower() not in SECTION_HEADER_BLACKLIST:
                return title

    # 2. "The Role" section → use the FIRST sentence that contains a role keyword
    role_section = re.search(
        r"(?:The Role|About the Role|About This Role)[\s\S]{0,20}?\n([^\n]{5,120})",
        jd_text, re.IGNORECASE)
    if role_section:
        first_sentence = role_section.group(1).strip()
        # If it's a clean short title, keep it
        if len(first_sentence) < 60 and first_sentence.lower() not in SECTION_HEADER_BLACKLIST:
            return first_sentence

    # 3. Line scan — whole-word match to avoid "engineering" matching "engineer"
    title_words = [
        "engineer", "analyst", "scientist", "developer", "intern",
        "manager", "specialist", "associate", "consultant", "architect",
        "researcher", "lead", "director", "coordinator", "designer",
        "full stack", "full-stack", "backend", "frontend",
    ]
    # Lines starting with these words are requirements, never job titles
    REQ_PREFIXES = (
        "strong", "demonstrated", "familiarity", "experience",
        "proficiency", "knowledge", "ability", "proven",
        "excellent", "good", "solid", "basic", "advanced",
        "must", "preferred", "required", "ideally", "currently",
        "please", "build", "constantly", "working", "attempting",
        "medical", "dental", "gym", "commuter", "relocation",
        "breakfast", "lunch", "dinner", "unlimited", "tech equipment",
    )
    for line in jd_text.strip().splitlines():
        line = line.strip()
        if 5 < len(line) < 80 and not line.startswith("http"):
            if line.lower() in SECTION_HEADER_BLACKLIST:
                continue
            if any(line.lower().startswith(p) for p in REQ_PREFIXES):
                continue
            # Whole-word match
            if any(re.search(r"\b" + re.escape(w) + r"\b", line, re.IGNORECASE)
                   for w in title_words):
                clean = re.sub(r"\s*[—\-–|@].*$", "", line).strip()
                if clean.lower() not in SECTION_HEADER_BLACKLIST and len(clean) < 80:
                    return clean

    # 4. Specialization inference
    m = re.search(
        r"looking for.*?(?:candidates?|students?).*?(?:specializ\w+ in|focus\w+ on|expertise in)"
        r"\s+([A-Za-z\s,/&\-]{5,60}?)(?:\.|,|\n)",
        jd_text, re.IGNORECASE | re.DOTALL)
    if m:
        spez = m.group(1).strip().split(",")[0].strip()
        return f"Research Scientist Intern ({spez.title()})"

    # 5. Last resort — infer from role category
    cat = _detect_role_category(jd_text)
    fallback_map = {
        "swe": "Software Engineer", "ml_ai": "Machine Learning Engineer",
        "data_science": "Data Scientist", "data_engineer": "Data Engineer",
        "analyst": "Data Analyst", "mlops": "MLOps Engineer",
        "cv": "Computer Vision Engineer", "nlp": "NLP Engineer",
    }
    return fallback_map.get(cat, "Intern")



def _extract_keywords(jd_text: str, top_n: int = 40) -> list[str]:
    """Extract ranked tech keywords from JD text."""
    cleaned = _clean_text(jd_text)
    words = cleaned.split()

    found_tech = []
    # Multi-word tech terms first
    for tech in sorted(TECH_KEYWORDS, key=len, reverse=True):
        if tech in cleaned:
            found_tech.append(tech)

    # Uni-gram frequency analysis (excluding stop words)
    word_freq = Counter(w for w in words if w not in STOP_WORDS and len(w) > 2)
    freq_keywords = [w for w, _ in word_freq.most_common(60) if w not in STOP_WORDS]

    # Combine: tech keywords first (they're precise), then frequency-based
    combined = list(dict.fromkeys(found_tech + freq_keywords))
    return combined[:top_n]


def _detect_role_category(jd_text: str) -> str:
    """Detect best role category from JD."""
    cleaned = jd_text.lower()
    scores = {}
    for category, markers in ROLE_KEYWORDS.items():
        score = sum(1 for m in markers if m in cleaned)
        scores[category] = score

    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "default"
    return best


def parse_jd(jd_text: str) -> dict:
    """
    Parse a job description and return structured info.

    Returns:
        {
            "company": str,
            "job_title": str,
            "role_category": str,  # ml_ai | swe | data_science | data_engineer | analyst | mlops | cv | nlp | default
            "keywords": [str, ...],
            "raw_text": str
        }
    """
    company = _extract_company(jd_text)
    job_title = _extract_job_title(jd_text)
    role_category = _detect_role_category(jd_text)
    keywords = _extract_keywords(jd_text)

    return {
        "company": company,
        "job_title": job_title,
        "role_category": role_category,
        "keywords": keywords,
        "raw_text": jd_text
    }


def sanitize_filename(text: str) -> str:
    """Convert text to safe filename component."""
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s/]+", "_", text.strip())
    return text.title().replace(" ", "")


if __name__ == "__main__":
    sample = """
    Google LLC is hiring a Machine Learning Engineer Intern.
    You will work on building and deploying deep learning models using PyTorch and TensorFlow.
    Requirements: Python, SQL, MLOps, Docker, Kubernetes, CI/CD, AWS.
    """
    result = parse_jd(sample)
    print(result)
