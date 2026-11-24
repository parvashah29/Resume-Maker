# Resume Maker

A local, offline resume-tailoring CLI. Paste a job description into `jd.txt`; it parses the JD, picks the best-matching content from `resume_data.json`, optionally has a local [Ollama](https://ollama.com) model reword it, and renders an ATS-friendly **one-page PDF** with reportlab. No API keys.

`resume_data.json` holds the author's personal resume content (name, employers, projects, skills). That is intended: the tool is data-driven.

## Setup (Python 3.10+, tested on 3.12 / macOS arm64)

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt          # reportlab, pypdf
pip install -r requirements-dev.txt      # only for tests (pytest)
ollama pull mistral                      # only for AI mode
```

## Use

```bash
# 1. replace the contents of jd.txt with the job posting
python generate.py                       # AI-tailored (about 1-1.5 min with mistral)
python generate.py --no-ai               # rule-based only, about 1 second, no Ollama needed
python generate.py --jd other.txt        # other file, or pass raw JD text
python generate.py --model llama3.2      # choose model (or set RESUME_MAKER_MODEL)
python generate.py --company "Acme" --role "ML Intern" --output ~/Desktop/r.pdf
```

Output goes to `output/Parva_Shah_<Company>_<Role>.pdf` (folder is created automatically and git-ignored). If the company or role is misdetected, override with `--company` / `--role`.

## How it works

1. `modules/jd_parser.py` extracts company, title, role category and keywords (JD input is cleaned and capped at 20,000 characters).
2. `modules/content_selector.py` picks work-experience titles/bullets, the 3 best projects, coursework and skills from `resume_data.json`. Skills not supported by `resume_data.json` are dropped.
3. `modules/ollama_tailor.py` (skipped with `--no-ai`) asks the model to reword the summary and bullets. It cannot add content: a rewritten bullet is kept only if it adds no new number and no new JD skill/term absent from the original; otherwise the original bullet is used. Malformed output is retried, then falls back to rule-based text. Skills are only reordered.
4. `modules/pdf_renderer.py` shrinks fonts (down to 80%) and, if still too long, drops the lowest-ranked project content so the result is always exactly one page.

If Ollama is not running, the tool tries `ollama serve`. If Ollama or the model is missing, it prints how to fix it and falls back to `--no-ai` behaviour.

## Adapting it to someone else

Replace `resume_data.json` with your own content, keeping its structure: `personal`, `education` (with `coursework_pool`), `work_experience` (with `title_pool` and `bullets_pool` keyed by role category, plus `default`), `projects_pool`, `skills_pool`, `certifications`. To allow extra skills, list them under `skills_pool` (anything not found in the file is filtered out). The `Parva_Shah_` filename prefix lives in `generate.py` (`build_output_path`).

## Tests

```bash
python -m pytest
```

Covers JD parsing, content selection and skill grounding, LLM-output validation/fallback, and one-page PDF fitting. Real-Ollama runs are manual.
