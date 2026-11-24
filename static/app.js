// Comment Radar page: runs one analysis over Server-Sent Events (/analyze) and draws the report.
// Every string from the server can contain comment text written by strangers: always go through esc().

const EXAMPLES = [
    // {label: "Crypto scam replies", url: "https://www.youtube.com/watch?v=..."},
];
const PATTERNS = {
    promotion_reply_chain: "Promotion reply chain", copy_paste_campaign: "Copy-paste campaign",
    coordinated_burst: "Coordinated burst", new_account_cluster: "New-account cluster", unclear: "Unclear pattern",
    reply_chain: "Reply chain", copy_paste: "Near-copy comments", mixed: "Mixed signals",
};
const STATUS = {
    kept: "Held up", downgraded: "Downgraded", dismissed: "Dismissed by Defense", unreviewed: "Not reviewed by Defense",
    not_investigated: "Not investigated (weak signals)", review_failed: "Review failed",
};
const SENTIMENTS = ["negative", "neutral", "positive"];
const PAGE = 100;

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const pct = (x) => (x == null ? "–" : `${Math.round(x * 100)}%`);
const groupColor = (id) => `var(--g${((parseInt(String(id).slice(1), 10) || 1) - 1) % 6 + 1})`;
const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "");

let source = null;
let timer = null;
let report = null;
let filter = "all";
let shown = PAGE;

// --- Theme ---
(function theme() {
    const root = document.documentElement;
    try { const t = localStorage.getItem("radar-theme"); if (t) root.dataset.theme = t; } catch (e) {}
    $("btn-theme").addEventListener("click", () => {
        const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
        root.dataset.theme = dark ? "light" : "dark";
        try { localStorage.setItem("radar-theme", root.dataset.theme); } catch (e) {}
    });
})();

// --- Examples ---
if (EXAMPLES.length) {
    $("examples-wrap").classList.remove("hidden");
    $("examples").innerHTML = EXAMPLES.map((e, i) => `<button type="button" data-i="${i}">${esc(e.label)}</button>`).join("");
    $("examples").addEventListener("click", (ev) => {
        const b = ev.target.closest("button");
        if (b) { $("url").value = EXAMPLES[b.dataset.i].url; start(); }
    });
}

// --- Running ---
$("ask").addEventListener("submit", (ev) => { ev.preventDefault(); start(); });

function start() {
    const url = $("url").value.trim();
    if (!url) return;
    if (source) source.close();
    clearInterval(timer);
    report = null;
    ["error", "results"].forEach((id) => $(id).classList.add("hidden"));
    $("status").classList.remove("hidden");
    $("status-title").textContent = "Analyzing…";
    $("log").innerHTML = "";
    document.querySelectorAll("#steps li").forEach((li) => (li.className = ""));
    $("run").disabled = true;
    const began = Date.now();
    timer = setInterval(() => ($("elapsed").textContent = `${Math.round((Date.now() - began) / 1000)}s`), 500);

    const params = new URLSearchParams({ url, fresh: $("fresh").checked });
    source = new EventSource(`/analyze?${params}`);
    source.onmessage = (m) => handle(JSON.parse(m.data));
    source.onerror = () => {
        if (!report) fail("The connection dropped. Try again; a finished analysis is kept, so a retry is quick.");
    };
}

function finish() {
    if (source) source.close();
    source = null;
    clearInterval(timer);
    $("run").disabled = false;
}

function fail(message) {
    finish();
    $("status").classList.add("hidden");
    $("error").textContent = message;
    $("error").classList.remove("hidden");
}

function log(text) {
    const li = document.createElement("li");
    li.textContent = text;
    $("log").appendChild(li);
    $("log").scrollTop = $("log").scrollHeight;
}

function handle(e) {
    if (e.type === "step") {
        const li = document.querySelector(`#steps li[data-step="${e.step}"]`);
        if (li) li.className = e.status === "start" ? "active" : "done";
        if (e.step === "fetch" && e.status === "done") {
            const t = e.thread;
            log(`${t.cached ? "Loaded saved copy of" : "Fetched"} ${t.comments_fetched} comments from ${t.accounts} accounts: “${t.title}”`);
        }
        if (e.step === "sentiment" && e.status === "done") {
            const d = e.sentiment.distribution;
            log(`Sentiment: ${pct(d.negative)} negative, ${pct(d.neutral)} neutral, ${pct(d.positive)} positive (${e.sentiment.model})`);
        }
        if (e.step === "signals" && e.status === "done") {
            log(e.groups.length ? `Found ${e.groups.length} candidate group(s): ${e.groups.map((g) => `${g.id} (${g.accounts} accounts, score ${g.score})`).join(", ")}`
                : "No candidate groups: no accounts are linked by near-copy text or young accounts replying together.");
        }
        if (e.step === "investigate" && e.status === "start" && e.groups.length) log(`Investigating ${e.groups.join(", ")} in parallel…`);
    } else if (e.type === "finding") {
        log(`${e.group_id} Investigator: ${e.finding.headline} (confidence ${e.finding.confidence})`);
    } else if (e.type === "defense") {
        log(`${e.group_id} Defense: ${e.defense.verdict}. ${e.defense.reason}`);
    } else if (e.type === "done") {
        report = e;
        finish();
        $("status-title").textContent = e.cached ? "Saved result" : `Done in ${e.stats.seconds}s`;
        document.querySelectorAll("#steps li").forEach((li) => (li.className = "done"));
        render(e);
    } else if (e.type === "error") {
        fail(e.message);
    }
}

// --- Report ---
function render(r) {
    filter = "all";
    shown = PAGE;
    $("results").classList.remove("hidden");
    renderVerdict(r);
    renderTiles(r);
    renderSentiment(r);
    renderTimeline(r);
    renderGroups(r);
    renderComments();
    $("results").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderVerdict(r) {
    const v = r.video, tok = r.stats.tokens || {};
    $("verdict").className = `card verdict ${r.verdict.level}`;
    $("verdict").innerHTML = `
        <div class="level">${esc(r.verdict.text)}</div>
        <h2>${esc(r.summary.headline)}</h2>
        <p>${esc(r.summary.summary)}</p>
        <div class="meta"><a href="${esc(v.url)}" target="_blank" rel="noopener">${esc(v.title)}</a> · ${esc(v.channel_title)}
            ${v.was_live_or_premiere ? " · was a livestream or premiere" : ""} · fetched ${esc(fmtTime(r.thread.fetched_at))}
            · ${esc(r.stats.seconds)}s · ${((tok.input || 0) + (tok.output || 0)).toLocaleString()} tokens</div>`;
}

function renderTiles(r) {
    const held = r.groups.filter((g) => g.status === "kept" || g.status === "downgraded").length;
    const tiles = [
        [r.comments.length.toLocaleString(), `comments analyzed (of ${r.video.comment_count.toLocaleString()})`],
        [r.baseline.accounts.toLocaleString(), "accounts"],
        [`${held} / ${r.groups.length}`, "groups held up / candidates"],
        [pct(r.baseline.grouped_comment_share), "of comments come from a candidate group"],
    ];
    $("tiles").innerHTML = tiles.map(([v, l]) => `<div class="tile"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join("");
}

function sentimentBar(label, dist) {
    const parts = SENTIMENTS.map((s) => {
        const w = Math.round((dist[s] || 0) * 100);
        return w ? `<div style="width:${w}%;background:var(--${s})">${w >= 9 ? w + "%" : ""}</div>` : "";
    }).join("");
    return `<div class="bar-row"><div class="bar-head"><b>${esc(label)}</b><span class="muted">${dist.n} comments</span></div><div class="bar">${parts}</div></div>`;
}

function renderSentiment(r) {
    const s = r.sentiment;
    let html = sentimentBar("Comments from candidate groups", s.grouped) + sentimentBar("Everyone else", s.organic);
    html += `<div class="legend">${SENTIMENTS.map((x) => `<span><i style="background:var(--${x})"></i>${x}</span>`).join("")}</div>`;
    if (s.grouped.n) {
        const diff = SENTIMENTS.map((x) => [x, (s.grouped[x] || 0) - (s.organic[x] || 0)]).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0];
        if (Math.abs(diff[1]) >= 0.15) html += `<div class="note">Groups are ${pct(Math.abs(diff[1]))} ${diff[1] > 0 ? "more" : "less"} ${diff[0]} than everyone else.</div>`;
    } else {
        html += `<div class="note">No comments came from a candidate group.</div>`;
    }
    html += `<div class="legend">Model: ${esc(r.sentiment_model)}</div>`;
    $("sentiment").innerHTML = html;
}

function renderTimeline(r) {
    const bins = r.timeline.bins || [];
    const size = r.timeline.bin_minutes;
    $("tl-note").textContent = size ? `per ${size >= 1440 ? size / 1440 + " day" : size >= 60 ? size / 60 + " h" : size + " min"}` : "";
    if (!bins.length) { $("timeline").innerHTML = `<div class="empty">No timestamps.</div>`; return; }
    const W = 600, H = 140, max = Math.max(...bins.map((b) => b.total), 1), bw = W / bins.length;
    let svg = "";
    bins.forEach((b, i) => {
        const x = i * bw + 0.5, w = Math.max(bw - 1, 1);
        const th = (b.total / max) * (H - 10);
        const tip = `${fmtTime(b.start)}: ${b.total} comments${Object.keys(b.groups).length ? " · " + Object.entries(b.groups).map(([g, n]) => `${g}: ${n}`).join(", ") : ""}`;
        svg += `<g><title>${esc(tip)}</title><rect x="${x}" y="${H - th}" width="${w}" height="${th}" fill="var(--neutral)" opacity=".55"/>`;
        let y = H;
        for (const [g, n] of Object.entries(b.groups)) {
            const h = (n / max) * (H - 10);
            y -= h;
            svg += `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${groupColor(g)}"/>`;
        }
        svg += "</g>";
    });
    const labels = [0, Math.floor(bins.length / 2), bins.length - 1].map((i) =>
        `<text x="${Math.min(i * bw, W - 70)}" y="${H + 14}" font-size="11" fill="var(--muted)">${esc(fmtTime(bins[i].start))}</text>`).join("");
    const groups = r.groups.map((g) => `<span><i style="background:${groupColor(g.id)}"></i>${esc(g.id)}</span>`).join("");
    $("timeline").innerHTML = `<svg viewBox="0 0 ${W} ${H + 18}" preserveAspectRatio="none" role="img" aria-label="Comments over time">${svg}${labels}</svg>
        <div class="legend"><span><i style="background:var(--neutral);opacity:.55"></i>all comments</span>${groups}</div>`;
}

function renderGroups(r) {
    if (!r.groups.length) {
        $("groups").innerHTML = `<div class="empty">No candidate groups. Near-copy comments and young accounts replying together are the two signals that link accounts; neither appeared here.</div>`;
        return;
    }
    $("groups").innerHTML = r.groups.map((g) => {
        const f = g.finding, d = g.defense;
        const conf = g.confidence == null ? "" : ` · confidence ${pct(g.confidence)}`;
        const signals = g.signals.slice(0, 3).map((s) => `<span class="chip">${esc(s.text)}</span>`).join("");
        const finding = f ? `<p><b>${esc(f.headline)}</b></p><ul>${f.evidence.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
            <div class="muted" style="font-size:13px">Likely purpose: ${esc(f.likely_purpose)} · Investigator's confidence ${pct(f.confidence)}</div>` : "";
        const defense = d ? `<div class="defense"><b>Defense (${esc(d.verdict)}):</b>${esc(d.innocent_explanation)}<br><span class="muted">${esc(d.reason)}</span></div>` : "";
        const accounts = (g.account_profiles || []).map((a) => `<tr><td class="mono">${esc(a.account)}</td><td>${a.age_days_at_first_comment ?? "?"}</td>
            <td>${a.video_count ?? "?"}</td><td>${a.subscriber_count ?? "hidden"}</td><td>${a.comments_here}</td></tr>`).join("");
        return `<div class="group ${["dismissed", "not_investigated"].includes(g.status) ? "dim" : ""}" style="--gc:${groupColor(g.id)}">
            <div class="group-top"><h3>${esc(g.id)} · ${esc(PATTERNS[f?.pattern] || PATTERNS[g.pattern] || g.pattern)}</h3>
                <span class="badge ${esc(g.status)}">${esc(STATUS[g.status] || g.status)}${esc(conf)}</span></div>
            <div class="chips"><span class="chip">${g.n_accounts} accounts</span><span class="chip">${g.n_comments} comments</span>
                <span class="chip">signal score ${pct(g.score)}</span>${signals}</div>
            ${finding}${defense}
            <details><summary>Accounts and all signals</summary>
                <table><tr><th>Account</th><th>Age at comment (days)</th><th>Videos</th><th>Subscribers</th><th>Comments here</th></tr>${accounts}</table>
                <table><tr><th>Signal</th><th>Value</th><th>Adds to score</th></tr>${g.signals.map((s) => `<tr><td>${esc(s.name)}</td><td>${s.value}</td><td>${s.contribution}</td></tr>`).join("")}</table>
            </details>
            <button class="link-btn" type="button" data-group="${esc(g.id)}">Show this group's comments ↓</button>
        </div>`;
    }).join("");
}

$("groups").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-group]");
    if (!b) return;
    filter = b.dataset.group;
    shown = PAGE;
    renderComments();
    $("comments").scrollIntoView({ behavior: "smooth", block: "start" });
});

function matches(c, f) {
    if (f === "all") return true;
    if (f === "grouped") return !!c.group;
    if (SENTIMENTS.includes(f)) return c.sentiment === f;
    return c.group === f;
}

function renderComments() {
    if (!report) return;
    const cs = report.comments;
    const options = [["all", "All"], ["grouped", "In a group"], ...report.groups.map((g) => [g.id, g.id]), ...SENTIMENTS.map((s) => [s, s])];
    $("filters").innerHTML = options.map(([k, label]) =>
        `<button type="button" data-f="${esc(k)}" class="${k === filter ? "on" : ""}">${esc(label)}<span class="n">${cs.filter((c) => matches(c, k)).length}</span></button>`).join("");
    const list = cs.filter((c) => matches(c, filter));
    $("comments-note").textContent = `${list.length} shown · oldest first`;
    $("comments").innerHTML = list.length ? list.slice(0, shown).map((c) => `
        <div class="comment">
            <div class="c-meta"><span class="mono">${esc(c.account || "unknown")}</span><span>${esc(fmtTime(c.published_at))}</span>
                ${c.is_reply ? "<span>reply</span>" : ""}
                ${c.sentiment ? `<span class="tag ${esc(c.sentiment)}">${esc(c.sentiment)}</span>` : ""}
                ${c.group ? `<span class="tag group" style="--gc:${groupColor(c.group)}">${esc(c.group)}</span>` : ""}
                <a href="${esc(report.video.url)}&lc=${encodeURIComponent(c.id)}" target="_blank" rel="noopener">view</a></div>
            <p class="c-text">${esc(c.text)}</p>
        </div>`).join("") : `<div class="empty">No comments match.</div>`;
    $("more").classList.toggle("hidden", list.length <= shown);
}

$("filters").addEventListener("click", (ev) => {
    const b = ev.target.closest("button");
    if (!b) return;
    filter = b.dataset.f;
    shown = PAGE;
    renderComments();
});
$("more").addEventListener("click", () => { shown += PAGE; renderComments(); });
