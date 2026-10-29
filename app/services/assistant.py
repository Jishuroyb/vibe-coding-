"""Extra features built on chatbot capabilities.

1. DevBot      - ask natural-language questions about the developer's profile.
2. Profile Coach - generates a recruiter-friendly bio and concrete improvement tips.

Both work offline with a deterministic rule engine grounded in the cached data, and
automatically upgrade to Claude when ANTHROPIC_API_KEY is set. The LLM is only given the
computed facts (never raw HTML), and told to answer strictly from them.
"""
import json
import re
from typing import Optional

import httpx

from ..config import settings

SYSTEM_PROMPT = (
    "You are DevBot, an assistant embedded in a developer's GitHub portfolio. "
    "Answer ONLY from the JSON facts provided. If the facts don't contain the answer, say so. "
    "Be concise (max 4 sentences), friendly, and specific; cite repo names and numbers."
)


def llm_available() -> bool:
    return bool(settings.anthropic_api_key)


def _call_llm(system: str, messages: list[dict], max_tokens: int = 400) -> Optional[str]:
    if not llm_available():
        return None
    try:
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": settings.llm_model, "max_tokens": max_tokens, "system": system, "messages": messages},
            timeout=25,
        )
        resp.raise_for_status()
        return "".join(b.get("text", "") for b in resp.json()["content"] if b.get("type") == "text").strip() or None
    except (httpx.HTTPError, KeyError, ValueError):
        return None  # silently fall back to the rule engine


# --------------------------------------------------------------------- facts
def build_facts(payload: dict) -> dict:
    repos = [r for r in payload["repos"] if not r["is_fork"]]
    top = sorted(repos, key=lambda r: r["stars"], reverse=True)[:5]
    recent = sorted(repos, key=lambda r: r.get("pushed_at") or "", reverse=True)[:5]
    return {
        "name": payload["profile"]["name"], "login": payload["profile"]["login"], "bio": payload["profile"]["bio"],
        "location": payload["profile"]["location"], "stats": payload["stats"],
        "top_languages": [{"name": l["name"], "percent": l["percent"]} for l in payload["languages"]],
        "streaks": payload["streaks"],
        "top_repos": [{"name": r["name"], "stars": r["stars"], "forks": r["forks"], "language": r["language"],
                       "description": r["description"]} for r in top],
        "recently_pushed": [{"name": r["name"], "pushed_at": r["pushed_at"], "language": r["language"]} for r in recent],
        "tech_match": ({"percentage": payload["match"]["percentage"], "label": payload["match"]["label"],
                        "missing": [m["term"] for m in payload["match"]["missing"]]} if payload.get("match") else None),
        "contribution_source": payload["contribution_source"],
    }


# --------------------------------------------------------------------- DevBot
def _join(items: list[str]) -> str:
    return ", ".join(items[:-1]) + f" and {items[-1]}" if len(items) > 1 else (items[0] if items else "")


def _rule_answer(question: str, f: dict) -> str:
    q = question.lower()
    s, st = f["stats"], f["streaks"]
    name = f["name"].split()[0] if f["name"] else f["login"]

    if re.search(r"language|stack|tech|skill|written in|code in|work with|work in|use\b|uses\b|good at", q):
        if not f["top_languages"]:
            return f"{name} has no repositories with a detected primary language yet."
        langs = [f"{l['name']} ({l['percent']:.0f}%)" for l in f["top_languages"][:4]]
        return f"{name}'s most-used languages across original repos are {_join(langs)}."
    if re.search(r"star|popular|best|top repo|famous|highlight|showcase|project|proud|flagship", q):
        if not f["top_repos"] or f["top_repos"][0]["stars"] == 0:
            return f"None of {name}'s repositories have stars yet, so there is no standout project by popularity."
        top = f["top_repos"][0]
        return (f"The most starred project is {top['name']} with {top['stars']:,} stars and {top['forks']:,} forks"
                + (f", written in {top['language']}." if top["language"] else ".")
                + f" In total {name} has earned {s['total_stars']:,} stars.")
    if re.search(r"streak|consisten|active|commit|contribut|how often", q):
        src = " (estimated from recent public events)" if f["contribution_source"] == "events" else ""
        return (f"Current streak: {st['current']} day(s); longest: {st['longest']} day(s). "
                f"{st['total']:,} contributions across {st['active_days']} active days{src}.")
    if re.search(r"follow|audience|network|reach", q):
        return f"{name} has {s['followers']:,} followers and follows {s['following']:,} accounts."
    if re.search(r"recent|latest|lately|working on|currently|now", q):
        if not f["recently_pushed"]:
            return "No recent pushes were found."
        names = [f"{r['name']}" for r in f["recently_pushed"][:3]]
        return f"Most recently pushed repositories: {_join(names)}."
    if re.search(r"match|fit|job|compat|hire", q):
        m = f["tech_match"]
        if not m:
            return "Paste a job description in the Tech Stack Compatibility box and I can talk through the match."
        gap = f" Gaps: {_join(m['missing'][:4])}." if m["missing"] else ""
        return f"Latest tech-stack match is {m['percentage']:.0f}% ({m['label']}).{gap}"
    if re.search(r"how many repo|repositor", q):
        return f"{name} has {s['original_repos']} original repositories ({s['public_repos']} public in total)."
    if re.search(r"who|about|summar|introduc|overview", q):
        return summarize(f)
    return (summarize(f) + " You can also ask about languages, top repos, streaks, followers, "
            "recent work, or how well the profile matches a job.")


def summarize(f: dict) -> str:
    s = f["stats"]
    parts = [f"{f['name']} has {s['original_repos']} original repositories, {s['total_stars']:,} total stars "
             f"and {s['followers']:,} followers."]
    if f["top_languages"]:
        parts.append("Works mainly in " + _join([l["name"] for l in f["top_languages"][:3]]) + ".")
    if f["top_repos"] and f["top_repos"][0]["stars"]:
        parts.append(f"Best-known project: {f['top_repos'][0]['name']}.")
    return " ".join(parts)


def chat(question: str, payload: dict, history: list[dict]) -> dict:
    facts = build_facts(payload)
    answer = None
    if llm_available():
        msgs = [m for m in history if m["role"] in ("user", "assistant")][-4:]
        msgs.append({"role": "user", "content": f"FACTS:\n{json.dumps(facts)}\n\nQUESTION: {question}"})
        answer = _call_llm(SYSTEM_PROMPT, msgs)
    mode = "llm" if answer else "rules"
    return {"answer": answer or _rule_answer(question, facts), "mode": mode}


# --------------------------------------------------------------------- Profile Coach
def coach(payload: dict) -> dict:
    f = build_facts(payload)
    repos = [r for r in payload["repos"] if not r["is_fork"]]
    tips = []

    no_desc = [r["name"] for r in repos if not r["description"]]
    if no_desc:
        tips.append({"title": "Add descriptions to your repos",
                     "detail": f"{len(no_desc)} repo(s) have no description (e.g. {_join(no_desc[:3])}). "
                               "Recruiters skim descriptions first."})
    no_topics = [r["name"] for r in repos if not r["topics"]]
    if len(no_topics) > len(repos) / 2 and repos:
        tips.append({"title": "Tag repositories with topics",
                     "detail": "Most repos have no topics. Topics make your stack searchable and strengthen the tech-match score."})
    if not payload["profile"]["bio"]:
        tips.append({"title": "Write a profile bio", "detail": "Your GitHub bio is empty. One line on what you build goes a long way."})
    if not payload["profile"]["blog"]:
        tips.append({"title": "Link a portfolio or LinkedIn", "detail": "Add a website/LinkedIn URL to your profile so visitors can reach you."})
    if f["streaks"]["current"] == 0 and f["streaks"]["total"] > 0:
        tips.append({"title": "Restart your streak", "detail": "No activity yesterday or today. Small daily commits keep the graph warm."})
    if f["top_repos"] and f["top_repos"][0]["stars"] < 5:
        tips.append({"title": "Pin one flagship project",
                     "detail": "Pick your best repo, add a README with a screenshot, and pin it to the top of your profile."})
    stale = [r["name"] for r in repos if (r.get("pushed_at") or "") < "2024-01-01"]
    if len(stale) > 3 and repos:
        tips.append({"title": "Archive or refresh old repos",
                     "detail": f"{len(stale)} repos haven't been pushed since 2023. Archive the abandoned ones so your best work stands out."})
    if f["tech_match"] and f["tech_match"]["missing"]:
        tips.append({"title": "Close the gaps for your target role",
                     "detail": "Build a small project using " + _join(f["tech_match"]["missing"][:3]) + " to lift your match score."})
    if not tips:
        tips.append({"title": "Looking strong", "detail": "No obvious gaps. Keep shipping and keep READMEs polished."})

    bio = None
    if llm_available():
        bio = _call_llm(
            "Write a 2-sentence, first-person-free professional bio for a developer portfolio. "
            "Use only the facts given. No hype words, no emojis.",
            [{"role": "user", "content": json.dumps(f)}], max_tokens=160)
    if not bio:
        langs = _join([l["name"] for l in f["top_languages"][:3]])
        bio = (f"{f['name']} is a developer working mainly in {langs or 'a range of languages'}, with "
               f"{f['stats']['original_repos']} original projects and {f['stats']['total_stars']:,} stars on GitHub.")
        if f["top_repos"] and f["top_repos"][0]["stars"]:
            bio += f" Notable work includes {f['top_repos'][0]['name']}."
    return {"bio": bio, "tips": tips[:6], "mode": "llm" if llm_available() and bio else "rules"}
