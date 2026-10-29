/* Presentation + interaction only. Every number shown here is computed by the FastAPI backend. */
const $ = (id) => document.getElementById(id);
const fmt = new Intl.NumberFormat("en-US");
const state = { username: "", langColors: {} };

/* ---------- tiny helpers ---------- */
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k === "style") Object.assign(node.style, v);
    else if (k.startsWith("data-")) node.setAttribute(k, v);
    else if (k in node) node[k] = v;
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c != null) node.append(c.nodeType ? c : document.createTextNode(c));
  return node;
}

async function api(path, options) {
  const res = await fetch(path, options);
  let body = null;
  try { body = await res.json(); } catch (_) { /* non-JSON error */ }
  if (!res.ok) throw new Error(body?.detail || `Request failed (${res.status})`);
  return body;
}

function notice(message, kind = "warn") {
  const n = $("notice");
  n.textContent = message || "";
  n.hidden = !message;
  n.classList.toggle("error", kind === "error");
}

/* ---------- theme + settings ---------- */
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("theme", theme);
}
$("theme").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(next);
  api("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ theme: next }) }).catch(() => {});
});

/* ---------- rendering ---------- */
function renderHero(data) {
  const { profile: p, stats: s } = data;
  const initial = encodeURIComponent((p.name || p.login || "?").trim()[0].toUpperCase());
  const fallback = `data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='104' height='104'><rect width='104' height='104' fill='%230C7C8C'/><text x='52' y='68' font-size='48' text-anchor='middle' fill='white' font-family='sans-serif'>${initial}</text></svg>`;
  $("avatar").onerror = () => { $("avatar").onerror = null; $("avatar").src = fallback; };
  $("avatar").src = p.avatar_url || fallback;
  $("avatar").alt = `${p.name} avatar`;
  $("name").textContent = p.name;
  const handle = $("handle");
  handle.textContent = `@${p.login}`;
  handle.href = p.html_url || "#";
  $("where").textContent = [p.company, p.location].filter(Boolean).join(" / ");
  $("bio").textContent = p.bio || "";
  $("bio").hidden = !p.bio;
  $("s-followers").textContent = fmt.format(s.followers);
  $("s-stars").textContent = fmt.format(s.total_stars);
  $("s-repos").textContent = fmt.format(s.original_repos);
  $("s-forks").textContent = fmt.format(s.total_forks);
  document.title = `${p.name} · Developer Portfolio`;
}

function renderBadge(match) {
  const badge = $("badge");
  if (!match) {
    badge.dataset.tone = "none";
    $("badge-value").textContent = "–";
    $("badge-label").textContent = "Run the vibe check";
    $("ring").style.strokeDasharray = "0 100";
    return;
  }
  const pct = match.percentage;
  badge.dataset.tone = pct >= 80 ? "excellent" : pct >= 60 ? "strong" : pct >= 40 ? "partial" : "low";
  $("badge-value").textContent = `${Math.round(pct)}%`;
  $("badge-label").textContent = match.label;
  requestAnimationFrame(() => { $("ring").style.strokeDasharray = `${pct} 100`; });
}

function renderHeatmap(data) {
  const { heatmap, streaks, contribution_source: source } = data;
  const root = $("heatmap");
  root.replaceChildren();

  const months = el("div", { class: "hm-months" });
  const cs = getComputedStyle(root);
  const step = parseFloat(cs.getPropertyValue("--cell")) + parseFloat(cs.getPropertyValue("--gap"));
  heatmap.months.forEach((m) => months.append(el("span", { style: { left: `${m.week * step}px` } }, m.label)));
  const days = el("div", { class: "hm-days" }, ...["", "Mon", "", "Wed", "", "Fri", ""].map((d) => el("span", {}, d)));
  const grid = el("div", { class: "hm-grid" });
  heatmap.weeks.forEach((week) => week.forEach((cell) => {
    if (!cell) return grid.append(el("i", { class: "blank" }));
    const label = `${cell.count} contribution${cell.count === 1 ? "" : "s"} on ${cell.date}`;
    grid.append(el("i", { "data-l": cell.level, title: label }));
  }));
  root.append(months, days, grid);

  $("st-current").textContent = streaks.current;
  $("st-longest").textContent = streaks.longest;
  $("st-total").textContent = fmt.format(streaks.total);
  $("st-active").textContent = streaks.active_days;
  $("st-busiest").textContent = streaks.busiest_day ? streaks.busiest_day.count : "–";
  $("st-busiest-label").textContent = streaks.busiest_day ? `most in a day (${streaks.busiest_day.date})` : "busiest day";
  $("heat-sub").textContent = source === "graphql"
    ? "Last 12 months, from GitHub's contribution calendar"
    : "Estimated from public events (last ~90 days). Set GITHUB_TOKEN on the server for the full year.";
}

function polar(r, pct) {
  const a = 2 * Math.PI * pct - Math.PI / 2;
  return [r * Math.cos(a), r * Math.sin(a)];
}

function renderLanguages(languages) {
  const svg = $("pie"), list = $("lang-list");
  svg.replaceChildren(); list.replaceChildren();
  $("lang-empty").hidden = languages.length > 0;
  state.langColors = Object.fromEntries(languages.map((l) => [l.name, l.color]));
  let acc = 0;
  const NS = "http://www.w3.org/2000/svg";
  languages.forEach((l) => {
    const frac = l.percent / 100;
    if (frac >= 0.999) {
      const c = document.createElementNS(NS, "circle");
      c.setAttribute("r", 56); c.setAttribute("fill", l.color);
      svg.append(c);
    } else {
      const [x1, y1] = polar(56, acc), [x2, y2] = polar(56, acc + frac);
      const path = document.createElementNS(NS, "path");
      path.setAttribute("d", `M0 0 L${x1} ${y1} A56 56 0 ${frac > 0.5 ? 1 : 0} 1 ${x2} ${y2} Z`);
      path.setAttribute("fill", l.color);
      const t = document.createElementNS(NS, "title"); t.textContent = `${l.name}: ${l.percent}% (${l.repos} repos)`;
      path.append(t); svg.append(path);
    }
    acc += frac;
    list.append(el("li", {}, el("i", { style: { background: l.color } }), l.name, el("b", {}, `${l.percent.toFixed(0)}%`)));
  });
  const hole = document.createElementNS(NS, "circle");
  hole.setAttribute("r", 28); hole.setAttribute("fill", "var(--surface)");
  if (languages.length) svg.append(hole);
}

function renderRepos(data) {
  const grid = $("repo-grid");
  grid.replaceChildren();
  $("repo-count").textContent = `(${data.repos.length})`;
  $("repo-empty").hidden = data.repos.length > 0;
  data.repos.forEach((r) => {
    const meta = el("div", { class: "repo-meta" },
      el("span", { class: "stars", title: "Stars" }, `★ ${fmt.format(r.stars)}`),
      el("span", { title: "Forks" }, `⑂ ${fmt.format(r.forks)}`),
      r.language ? el("span", { class: "lang-tag" }, el("i", { style: { background: state.langColors[r.language] || "#8A9A9E" } }), r.language) : null,
      r.is_fork ? el("span", { class: "tag-note" }, "fork") : null,
      r.archived ? el("span", { class: "tag-note" }, "archived") : null,
    );
    grid.append(el("a", { class: "repo", href: r.url, target: "_blank", rel: "noopener" },
      el("h3", {}, r.name), el("p", {}, r.description || "No description yet."), meta));
  });
}

function fillLanguageFilter(langs) {
  const sel = $("f-lang"), current = sel.value;
  sel.replaceChildren(el("option", { value: "" }, "All languages"), ...langs.map((l) => el("option", { value: l }, l)));
  sel.value = langs.includes(current) ? current : "";
}

function renderMatch(result) {
  const box = $("match-result");
  box.hidden = false;
  $("match-headline").textContent = result.note
    ? result.note
    : `${Math.round(result.percentage)}% match, ${result.label.toLowerCase()}. ${result.detected_terms} technologies found in the job description.`;
  const chips = (id, items, cls) => $(id).replaceChildren(...items.map((i) => el("span", { class: `chip ${cls}` }, i.term, i.evidence ? el("small", {}, i.evidence) : null)));
  chips("chips-matched", result.matched, "ok");
  chips("chips-partial", result.partial, "part");
  chips("chips-missing", result.missing, "miss");
}

/* ---------- loading ---------- */
function repoQuery() {
  const p = new URLSearchParams({ sort: $("f-sort").value, include_forks: $("f-forks").checked });
  if ($("f-lang").value) p.set("language", $("f-lang").value);
  if ($("f-q").value.trim()) p.set("q", $("f-q").value.trim());
  return p;
}

async function load({ refresh = false, reposOnly = false } = {}) {
  const username = $("username").value.trim().replace(/^@/, "");
  if (!username) return;
  const params = repoQuery();
  if (refresh) params.set("refresh", "true");
  const buttons = document.querySelectorAll("#search-form button");
  buttons.forEach((b) => (b.disabled = true));
  try {
    const data = await api(`/api/portfolio/${encodeURIComponent(username)}?${params}`);
    const userChanged = username.toLowerCase() !== state.username.toLowerCase();
    state.username = data.profile.login;
    $("empty").hidden = true; $("dashboard").hidden = false;
    if (!reposOnly || userChanged) {
      renderHero(data); renderBadge(data.match); renderHeatmap(data); renderLanguages(data.languages);
      fillLanguageFilter(data.available_languages);
      if (userChanged) { $("bot-log").replaceChildren(); $("match-result").hidden = true; loadCoach(); }
      if (data.match) renderMatch({ ...data.match });
    }
    renderRepos(data);
    notice(data.meta.warning ? `GitHub is unavailable (${data.meta.warning}) Showing cached data.` : "");
    const pill = $("cache-pill");
    pill.hidden = false;
    pill.textContent = data.meta.cache === "hit" ? "From cache" : data.meta.cache === "stale" ? "Stale cache" : "Fresh from GitHub";
    $("foot").textContent = `Last synced ${new Date(data.meta.fetched_at).toLocaleString()}. Data is cached in SQLite to stay within GitHub rate limits.`;
    history.replaceState(null, "", `#u=${encodeURIComponent(data.profile.login)}`);
  } catch (err) {
    notice(err.message, "error");
  } finally {
    buttons.forEach((b) => (b.disabled = false));
  }
}

async function loadCoach() {
  $("coach-bio").textContent = "Reviewing your profile…"; $("coach-tips").replaceChildren();
  try {
    const c = await api(`/api/coach/${encodeURIComponent(state.username)}`);
    $("coach-bio").textContent = c.bio;
    $("coach-mode").textContent = c.mode === "llm" ? "Claude" : "Built-in rules";
    $("coach-tips").replaceChildren(...c.tips.map((t) => el("li", {}, el("strong", {}, t.title), el("span", {}, t.detail))));
  } catch (err) {
    $("coach-bio").textContent = `Could not load suggestions: ${err.message}`;
  }
}

/* ---------- events ---------- */
$("search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  api("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: $("username").value.trim() }) }).catch(() => {});
  load();
});
$("refresh").addEventListener("click", () => load({ refresh: true }));

let debounce;
["f-lang", "f-sort", "f-forks"].forEach((id) => $(id).addEventListener("change", () => load({ reposOnly: true })));
$("f-q").addEventListener("input", () => { clearTimeout(debounce); debounce = setTimeout(() => load({ reposOnly: true }), 250); });

$("run-match").addEventListener("click", async () => {
  const jd = $("jd").value.trim();
  const msg = $("match-msg");
  if (jd.length < 10) { msg.textContent = "Paste a longer job description first."; return; }
  msg.textContent = "Comparing…"; $("run-match").disabled = true;
  try {
    const result = await api("/api/match", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: state.username, job_description: jd }) });
    renderMatch(result); renderBadge(result); loadCoach();
    msg.textContent = "";
  } catch (err) { msg.textContent = err.message; }
  finally { $("run-match").disabled = false; }
});

function addMsg(role, text) {
  const m = el("div", { class: `msg ${role}` }, text);
  $("bot-log").append(m); $("bot-log").scrollTop = $("bot-log").scrollHeight;
  return m;
}
async function ask(question) {
  addMsg("user", question);
  const pending = addMsg("bot", "Thinking…");
  try {
    const r = await api("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: state.username, message: question }) });
    pending.textContent = r.answer;
    $("bot-mode").textContent = r.mode === "llm" ? "Claude" : "Built-in rules";
  } catch (err) { pending.textContent = err.message; }
}
$("bot-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("bot-input").value.trim();
  if (!q) return;
  $("bot-input").value = "";
  ask(q);
});
$("bot-suggest").addEventListener("click", (e) => { if (e.target.tagName === "BUTTON") ask(e.target.textContent); });

/* ---------- boot ---------- */
(async function boot() {
  applyTheme(localStorage.getItem("theme") || "light");
  let saved = { username: "", theme: "", job_description: "" };
  try { saved = await api("/api/settings"); } catch (_) {}
  if (saved.theme && !localStorage.getItem("theme")) applyTheme(saved.theme);
  const fromHash = new URLSearchParams(location.hash.slice(1)).get("u");
  $("username").value = fromHash || saved.username || "";
  $("jd").value = saved.job_description || "";
  if ($("username").value) load();
})();
