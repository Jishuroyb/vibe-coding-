"""Tech Stack Compatibility ("Vibe Check").

Compares technologies mentioned in a job description with what the user's cached
repositories show (primary languages, topics, names, descriptions).

Scoring (transparent on purpose, easy to explain in a viva):
  1. Extract tech terms from the JD using a vocabulary of languages + frameworks/tools.
     Each term's weight grows with how often the JD repeats it (capped), so
     "Python ... Python ... Python" matters more than a one-off "Go".
  2. For each term, compute how well the profile covers it:
       language  -> 0.6 base if the user has >=1 original repo in it, up to 1.0 with 3+ repos
       framework -> 1.0 if repo topics/name/description mention it,
                    0.5 if the user at least works in the framework's language
  3. percentage = sum(weight * coverage) / sum(weight) * 100
"""
import math
import re
from collections import Counter
from typing import Optional

# canonical language -> regex aliases (matched case-insensitively unless noted)
LANGUAGES: dict[str, list[str]] = {
    "Python": [r"python3?"],
    "JavaScript": [r"javascript", r"ecmascript", r"\bjs\b"],
    "TypeScript": [r"typescript", r"\bts\b"],
    "Java": [r"java(?!\s*script)"],
    "C++": [r"c\+\+", r"cpp"],
    "C#": [r"c#", r"csharp", r"\.net"],
    "C": [r"\bC\s+(?:programming|language)\b", r"\bC/C\+\+"],
    "Go": [r"golang"],
    "Rust": [r"\brust\b"],
    "Ruby": [r"\bruby\b"],
    "PHP": [r"\bphp\b"],
    "Swift": [r"\bswift\b"],
    "Kotlin": [r"\bkotlin\b"],
    "Dart": [r"\bdart\b"],
    "Scala": [r"\bscala\b"],
    "R": [r"\bR\s+(?:programming|language|studio)\b", r"\brstudio\b"],
    "SQL": [r"\bsql\b", r"postgres(?:ql)?", r"mysql", r"sqlite", r"t-sql", r"pl/sql"],
    "HTML": [r"\bhtml5?\b"],
    "CSS": [r"\bcss3?\b", r"\bscss\b", r"\bsass\b", r"tailwind"],
    "Shell": [r"\bbash\b", r"shell script", r"\bshell\b"],
}
CASE_SENSITIVE = {"Go": [r"\bGo\b(?!\s+to\b)"]}

# framework/tool -> (regex aliases, implied language)
FRAMEWORKS: dict[str, tuple[list[str], str]] = {
    "FastAPI": ([r"fastapi"], "Python"),
    "Django": ([r"django"], "Python"),
    "Flask": ([r"flask"], "Python"),
    "Pandas": ([r"pandas"], "Python"),
    "PyTorch": ([r"pytorch"], "Python"),
    "TensorFlow": ([r"tensorflow"], "Python"),
    "Airflow": ([r"airflow"], "Python"),
    "React": ([r"\breact(?:\.?js)?\b"], "JavaScript"),
    "Node.js": ([r"node\.?js", r"\bnode\b"], "JavaScript"),
    "Express": ([r"express\.?js", r"\bexpress\b"], "JavaScript"),
    "Vue": ([r"\bvue(?:\.?js)?\b"], "JavaScript"),
    "Angular": ([r"angular"], "TypeScript"),
    "Next.js": ([r"next\.?js"], "TypeScript"),
    "Spring": ([r"spring\s*boot", r"\bspring\b"], "Java"),
    "Rails": ([r"ruby on rails", r"\brails\b"], "Ruby"),
    "Laravel": ([r"laravel"], "PHP"),
    "Flutter": ([r"flutter"], "Dart"),
    "Docker": ([r"docker"], "Shell"),
    "Kubernetes": ([r"kubernetes", r"\bk8s\b"], "Go"),
    "GraphQL": ([r"graphql"], "TypeScript"),
}

LABELS = [(80, "Excellent match"), (60, "Strong match"), (40, "Partial match"), (0, "Low match")]


def _find(patterns: list[str], text: str, flags: int) -> int:
    return sum(len(re.findall(p, text, flags)) for p in patterns)


def extract_terms(job_description: str) -> dict[str, dict]:
    """Return {term: {'kind': 'language'|'framework', 'mentions': n, 'language': implied}}."""
    found: dict[str, dict] = {}
    for lang, pats in LANGUAGES.items():
        n = _find(pats, job_description, re.IGNORECASE)
        if lang in CASE_SENSITIVE:
            n += _find(CASE_SENSITIVE[lang], job_description, 0)
        if n:
            found[lang] = {"kind": "language", "mentions": n, "language": lang}
    for name, (pats, lang) in FRAMEWORKS.items():
        n = _find(pats, job_description, re.IGNORECASE)
        if n:
            found[name] = {"kind": "framework", "mentions": n, "language": lang}
    return found


def _profile_signals(repos: list[dict]) -> tuple[Counter, str]:
    own = [r for r in repos if not r.get("is_fork")] or repos
    lang_counts = Counter(r["language"] for r in own if r.get("language"))
    haystack = " ".join(
        " ".join([r.get("name", ""), r.get("description") or "", " ".join(r.get("topics", []))]) for r in own
    ).lower()
    return lang_counts, haystack


def compute_match(job_description: str, repos: list[dict]) -> dict:
    terms = extract_terms(job_description)
    lang_counts, haystack = _profile_signals(repos)

    total_w = earned_w = 0.0
    matched, partial, missing = [], [], []
    for term, info in terms.items():
        weight = 1 + min(math.log2(info["mentions"]), 2)  # 1 mention=1.0, 2=2.0, 4+=3.0
        if info["kind"] == "language":
            repos_in_lang = lang_counts.get(term, 0)
            coverage = 0.0 if repos_in_lang == 0 else min(1.0, 0.6 + 0.2 * (repos_in_lang - 1))
            evidence = f"{repos_in_lang} repo{'s' if repos_in_lang != 1 else ''}" if repos_in_lang else ""
        else:
            aliases = FRAMEWORKS[term][0]
            direct = any(re.search(p, haystack, re.IGNORECASE) for p in aliases)
            has_lang = lang_counts.get(info["language"], 0) > 0
            coverage = 1.0 if direct else (0.5 if has_lang else 0.0)
            evidence = "found in your repos" if direct else (f"you code in {info['language']}" if has_lang else "")
        total_w += weight
        earned_w += weight * coverage
        entry = {"term": term, "kind": info["kind"], "mentions": info["mentions"], "evidence": evidence}
        (matched if coverage >= 1.0 or (info["kind"] == "language" and coverage >= 0.6)
         else partial if coverage > 0 else missing).append(entry)

    percentage = round(earned_w / total_w * 100, 1) if total_w else 0.0
    label = next(text for threshold, text in LABELS if percentage >= threshold)
    return {
        "percentage": percentage,
        "label": label,
        "detected_terms": len(terms),
        "matched": matched,
        "partial": partial,
        "missing": missing,
        "note": None if terms else "No known technologies were found in that job description.",
    }
