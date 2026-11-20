# 🎯 Resume Tailoring Pipeline — Parva Shah
> Local · No API Keys · Powered by Ollama (Mistral) · Guaranteed 1-page output

---

## ⚡ Workflow (3 steps every time)

### Step 1 — Paste the JD
Open `jd.txt` (in this folder) and **replace everything** with the job description text.

```
resume_maker/
└── jd.txt   ← paste JD here
```

### Step 2 — Run
```bash
cd "/Users/parvashah/Desktop/DS Projects/resume_maker"
python3 generate.py
```

### Step 3 — Get your PDF
```
output/Parva_Shah_CompanyName_JobRole.pdf
```

---

## What Happens Under the Hood

```
jd.txt
  → JD Parser        (extracts company, role, keywords)
  → Content Selector (picks best work-exp bullets & title)
  → Ollama / Mistral — 3 tasks:
      1. Generates tailored 2-sentence Summary
      2. Rewrites work-exp bullets with JD keywords
      3. Generates 3 BRAND NEW projects from scratch for this specific JD
  → PDF Renderer     (ATS-safe, single-column, auto-scales to 1 page)
  → output/Parva_Shah_Company_Role.pdf
```

---

## Options

```bash
# Standard (AI-tailored, ~1 min):
python3 generate.py

# Fast — rule-based only, no Ollama needed (~1 sec):
python3 generate.py --no-ai

# Provide JD as a different file:
python3 generate.py --jd path/to/other_jd.txt

# Override auto-detected company or role name:
python3 generate.py --company "Google" --role "ML Engineer Intern"

# Specify custom output path:
python3 generate.py --output ~/Desktop/my_resume.pdf
```

---

## FAQs

**Q: Where do I paste the JD?**
A: Open `jd.txt` in this folder. Delete everything and paste the raw JD text. Then run `python3 generate.py`.

**Q: Projects keep repeating — is that normal?**
A: No — every run generates 3 brand-new projects invented by Mistral specifically for the JD's keywords. They will be different each time and directly target the role.

**Q: Company name detected wrong?**
A: Add `--company "Actual Company Name"` to override: `python3 generate.py --company "OpenAI" --role "Research Intern"`

**Q: PDF is 2 pages?**
A: It won't be — auto-scaling reduces font sizes in 5% steps until it fits. If you see `ℹ️ Content scaled to X%` that's it working correctly.

**Q: How long does it take?**
A: ~50–90 seconds with Ollama (AI mode). ~1 second with `--no-ai`.

**Q: Does Ollama need to be running first?**
A: No — the pipeline auto-starts it if it's not already running.

---

## What Never Changes
- Your name, phone, email, LinkedIn, GitHub
- Company names in work experience
- Education institutions and dates
- Certifications
