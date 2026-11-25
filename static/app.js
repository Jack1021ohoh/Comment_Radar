// Comment Radar page. Runs one analysis over Server-Sent Events (/analyze), draws the report as numbered steps
// (each: a question, a one-sentence takeaway, then the picture, with details on demand), and asks follow-ups (/api/ask).
// Everything from the server can carry comment text written by strangers: it always goes through esc().

const EXAMPLES = [
    // {label: "BBC: a promotion ring", url: "https://www.youtube.com/watch?v=..."},
];
const PATTERNS = {
    opinion_steering: "Opinion steering", steering: "New accounts pushing one side",
    promotion_reply_chain: "Promotion reply chain", copy_paste_campaign: "Copy-paste campaign",
    coordinated_burst: "Coordinated burst", new_account_cluster: "New-account cluster", unclear: "Unclear pattern",
    reply_chain: "Reply chain", copy_paste: "Near-copy comments", mixed: "Mixed signals",
};
const PURPOSES = {
    steer_opinion: "Steer opinion", promote_or_scam: "Promotion or scam", harass: "Harassment",
    boost_engagement: "Boost engagement", unclear: "Purpose unclear",
};
const RULINGS = {
    kept: "Held up", downgraded: "Weakened by the Defense", dismissed: "Dismissed by the Defense", unreviewed: "Not yet reviewed",
    not_investigated: "Too weak to investigate", review_failed: "Review failed",
};
const STAMPS = { coordinated: "Coordinated<br>activity", possible: "Possible<br>coordination", none: "No clear<br>coordination" };
const SIGNAL_NAMES = {
    text_similarity: "Comments look alike", burst: "Posted within one hour", young_share: "Young accounts",
    created_cluster: "Accounts created together", same_thread_share: "In one reply thread", sentiment_uniformity: "Same tone",
    stance_push: "Push a side new accounts favour",
};
const OTHER_STANCES = { off_topic: "Off topic", promotion: "Promotion", neutral: "No side" };
const UNTESTED = {
    promotion: "Ads for a person, coin or service. Not tested as a side: promotion rings are checked in section 3, Groups.",
    neutral: "Questions, jokes, plain facts. Not a side, so not tested.",
};
const SENTIMENTS = ["negative", "neutral", "positive"];
const HELD = ["kept", "downgraded"];
const PAGE = 60;
const SVGNS = "http://www.w3.org/2000/svg";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const pct = (x) => (x == null ? "–" : `${Math.round(x * 100)}%`);
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const gnum = (id) => ((parseInt(String(id).slice(1), 10) || 1) - 1) % 6 + 1;
const gcolor = (id) => `var(--g${gnum(id)})`;
const when = (iso, opts = { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" }) => (iso ? new Date(iso).toLocaleString("en-US", opts) : "");
const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const ageText = (d) => (d == null ? "unknown" : d < 1 ? "under a day" : d < 60 ? plural(d, "day") : d < 730 ? plural(Math.round(d / 30), "month") : `${(d / 365).toFixed(1)} years`);
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
const stanceName = (r, key) => (r.brief?.sides || []).find((s) => s.id === key)?.label || OTHER_STANCES[key] || key;
const duration = (min) => (min == null ? "" : min < 10 ? `${Math.max(0.1, min).toFixed(1)} minutes` : min < 90 ? `${Math.round(min)} minutes` : `${Math.round(min / 60)} hours`);

let source = null, timer = null, began = 0;
let report = null, filter = "all", shown = PAGE, chat = [];

// ------------------------------------------------------------------ theme
(function theme() {
    const root = document.documentElement;
    try { const t = localStorage.getItem("radar-theme"); if (t) root.dataset.theme = t; } catch (e) {}
    $("btn-theme").addEventListener("click", () => {
        const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
        root.dataset.theme = dark ? "light" : "dark";
        try { localStorage.setItem("radar-theme", root.dataset.theme); } catch (e) {}
    });
})();

// ------------------------------------------------------------------ landing radar
const scope = (function () {
    const ticks = $("ticks"), blips = $("blips");
    for (let a = 0; a < 360; a += 10) {
        const r1 = a % 30 === 0 ? 92 : 96, t = (a * Math.PI) / 180;
        const l = document.createElementNS(SVGNS, "line");
        l.setAttribute("x1", r1 * Math.sin(t)); l.setAttribute("y1", -r1 * Math.cos(t));
        l.setAttribute("x2", 100 * Math.sin(t)); l.setAttribute("y2", -100 * Math.cos(t));
        ticks.appendChild(l);
    }
    let hot = 0.08;
    function blip() {
        const t = Math.random() * Math.PI * 2, r = 8 + Math.random() * 88;
        const c = document.createElementNS(SVGNS, "circle");
        c.setAttribute("cx", r * Math.sin(t)); c.setAttribute("cy", -r * Math.cos(t)); c.setAttribute("r", 2.5);
        c.setAttribute("class", Math.random() < hot ? "blip hot" : "blip");
        blips.appendChild(c);
        setTimeout(() => c.remove(), 3300);
    }
    let id = setInterval(blip, 650);
    return {
        mode(m, caption) {
            $("scope").classList.toggle("fast", m === "scan");
            hot = m === "scan" ? 0.2 : 0.08;
            clearInterval(id); id = setInterval(blip, m === "scan" ? 220 : 650);
            $("scope-caption").textContent = caption;
        },
    };
})();

if (EXAMPLES.length) {
    $("examples").classList.remove("hidden");
    $("examples").innerHTML = "Try: " + EXAMPLES.map((e, i) => `<button type="button" data-i="${i}">${esc(e.label)}</button>`).join("");
    $("examples").addEventListener("click", (ev) => {
        const b = ev.target.closest("button");
        if (b) { $("url").value = EXAMPLES[b.dataset.i].url; start(); }
    });
}

// ------------------------------------------------------------------ running
$("ask").addEventListener("submit", (ev) => { ev.preventDefault(); start(); });

function start() {
    const url = $("url").value.trim();
    if (!url) return;
    if (source) source.close();
    clearInterval(timer);
    report = null; chat = [];
    $("error").classList.add("hidden");
    $("results").classList.add("hidden");
    $("stepnav").classList.add("hidden");
    $("status").classList.remove("hidden");
    $("status-title").textContent = "Reading the comments…";
    $("log").innerHTML = "";
    document.querySelectorAll("#steps li").forEach((li) => (li.className = ""));
    $("run").disabled = true;
    scope.mode("scan", "Scanning");
    began = Date.now();
    timer = setInterval(() => ($("elapsed").textContent = clock((Date.now() - began) / 1000)), 500);
    $("status").scrollIntoView({ behavior: "smooth", block: "center" });

    history.replaceState(null, "", `?${new URLSearchParams({ url })}`);  // the address bar is now a link to this report
    source = new EventSource(`/analyze?${new URLSearchParams({ url, fresh: $("fresh").checked })}`);
    source.onmessage = (m) => handle(JSON.parse(m.data));
    source.onerror = () => { if (!report) fail("The connection dropped. Try again: a finished analysis is kept, so a retry is quick."); };
}

function finish() {
    if (source) source.close();
    source = null;
    clearInterval(timer);
    $("run").disabled = false;
}

function fail(message) {
    finish();
    scope.mode("idle", "Standing by");
    $("status").classList.add("hidden");
    $("error").textContent = message;
    $("error").classList.remove("hidden");
}

function wire(text) {
    const li = document.createElement("li");
    li.innerHTML = `<span>${clock((Date.now() - began) / 1000)}</span><div>${esc(text)}</div>`;
    $("log").appendChild(li);
    $("log").scrollTop = $("log").scrollHeight;
}

function handle(e) {
    if (e.type === "step") {
        const li = document.querySelector(`#steps li[data-step="${e.step}"]`);
        if (li) li.className = e.status === "start" ? "active" : e.status === "failed" ? "failed" : "done";
        if (e.step === "watch" && e.status === "start") wire(`Watching the first ${mmss(e.seconds)} of the video…`);
        if (e.step === "watch" && e.status === "done") wire(`The video: ${e.brief.summary} Sides: ${e.brief.sides.map((s) => `“${s.label}”`).join(", ")}.`);
        if (e.step === "watch" && e.status === "failed") wire("Couldn't read the video, so the sides check is skipped.");
        if (e.step === "stance" && e.status === "start") wire(`Reading which side ${e.comments} comments take: all ${e.new} by new accounts, and a random ${e.sampled} of the rest…`);
        if (e.step === "fetch" && e.status === "start") wire("Fetching comments and commenter profiles from YouTube…");
        if (e.step === "fetch" && e.status === "done") {
            const t = e.thread;
            $("status-title").textContent = t.title;
            wire(`${t.cached ? "Using the saved copy:" : "Fetched"} ${t.comments_fetched} comments from ${t.accounts} accounts.`);
        }
        if (e.step === "sentiment" && e.status === "start") wire("Reading the tone of every comment…");
        if (e.step === "sentiment" && e.status === "done") {
            const d = e.sentiment.distribution;
            wire(`Tone: ${pct(d.negative)} negative, ${pct(d.neutral)} neutral, ${pct(d.positive)} positive.`);
        }
        if (e.step === "signals" && e.status === "done") {
            const pushed = (e.stance?.rows || []).filter((x) => x.pushed);
            if (e.stance) wire(pushed.length ? `New accounts push: ${pushed.map((x) => `“${x.label}” (${x.lift ? x.lift + "×" : "only them"})`).join(", ")}.`
                : "New accounts take the same sides as established commenters.");
            wire(e.groups.length ? `Found ${plural(e.groups.length, "candidate group")}: ${e.groups.map((g) => `${g.id} (${g.accounts} accounts)`).join(", ")}.`
                : "No accounts are linked together.");
        }
        if (e.step === "investigate" && e.status === "start" && e.groups.length) wire(`Investigating ${e.groups.join(", ")}…`);
        if (e.step === "report" && e.status === "start") wire("Writing the verdict…");
    } else if (e.type === "finding") {
        wire(`${e.group_id}, Investigator: ${e.finding.headline}`);
    } else if (e.type === "defense") {
        wire(`${e.group_id}, Defense: “${e.defense.innocent_explanation.trim()}” ${e.defense.holds_up ? "holds up" : "doesn't hold up"}.`);
    } else if (e.type === "done") {
        report = e;
        finish();
        const held = e.groups.filter((g) => HELD.includes(g.status)).length;
        scope.mode("idle", held ? `${plural(held, "group")} found` : "All clear");
        $("status").classList.add("hidden");
        render(e);
    } else if (e.type === "error") {
        fail(e.message);
    }
}

// ------------------------------------------------------------------ report
function render(r) {
    filter = "all"; shown = PAGE;
    document.body.classList.add("has-report");
    $("results").classList.remove("hidden");
    $("stepnav").classList.remove("hidden");
    $("s-comments").open = false;
    renderVideo(r);
    renderVerdict(r);
    renderSides(r);
    renderGroups(r);
    renderPlot(r);
    renderTone(r);
    renderTiming(r);
    renderAsk(r);
    renderComments();
    $("results").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderVideo(r) {
    const v = r.video, tok = r.stats.tokens || {};
    $("video").innerHTML = `<img src="https://i.ytimg.com/vi/${encodeURIComponent(v.id)}/mqdefault.jpg" alt="" loading="lazy" />
        <div><b><a href="${esc(v.url)}" target="_blank" rel="noopener">${esc(v.title)}</a></b>
        <span>${esc(v.channel_title)} · analyzed in ${esc(r.stats.seconds)}s · ${((tok.input || 0) + (tok.output || 0)).toLocaleString()} tokens${r.cached ? " · saved result" : ""}</span>
        <span class="coverage">${esc(coverageText(r))}</span></div>`;
}

// How much of the comment section the report covers. Reply threads are read whole, newest first.
function coverageText(r) {
    const c = r.coverage, n = (x) => Number(x || 0).toLocaleString();
    const read = r.comments.length, onYT = r.video.comment_count;
    if (!c || c.all_threads == null) return `Read ${n(read)} of ${n(onYT)} comments on YouTube.`;
    const replies = c.replies >= c.replies_expected ? "every reply" : `${n(c.replies)} of ${n(c.replies_expected)} replies`;
    if (c.all_threads) return `Read the whole section: ${n(read)} comments in ${n(c.threads)} threads, ${replies}.`;
    return `Read the newest ${n(c.threads)} threads in full (${n(read)} of ${n(onYT)} comments, ${replies}). Older threads were not read.`;
}

// 1. Verdict
function renderVerdict(r) {
    const level = r.verdict.level;
    const held = r.groups.filter((g) => HELD.includes(g.status));
    const heldAccounts = held.reduce((n, g) => n + g.n_accounts, 0);
    const heldComments = held.reduce((n, g) => n + g.n_comments, 0);
    $("verdict").innerHTML = `
        <div class="verdict-card ${esc(level)}">
            <div class="stamp ${esc(level)}">${STAMPS[level] || esc(r.verdict.text)}${r.verdict.top_confidence ? `<small>${pct(r.verdict.top_confidence)} confidence</small>` : ""}</div>
            <div><h3>${esc(r.summary.headline)}</h3><p>${esc(r.summary.summary)}</p></div>
        </div>
        <div class="numbers">
            <div class="number"><b>${r.comments.length.toLocaleString()}</b><span>comments read, from ${r.baseline.accounts.toLocaleString()} accounts</span></div>
            <div class="number ${held.length ? "alarm" : ""}"><b>${held.length}</b><span>${held.length === 1 ? "group" : "groups"} acting together</span></div>
            <div class="number ${held.length ? "alarm" : ""}"><b>${heldAccounts}</b><span>accounts in them, writing ${pct(heldComments / Math.max(1, r.comments.length))} of comments</span></div>
        </div>`;
}

// 2. The video and its sides
function sidePair(cls, label, x) {
    const [lo, hi] = x.ci || [x.share, x.share];
    return `<div class="pair ${cls}"><span>${esc(label)}</span>
        <span class="track"><span class="fill" style="width:${(x.share * 100).toFixed(1)}%"></span>
        <span class="ci" style="left:${(lo * 100).toFixed(1)}%;width:${((hi - lo) * 100).toFixed(1)}%" title="95% interval ${pct(lo)}–${pct(hi)}"></span></span>
        <b>${pct(x.share)}</b></div>`;
}

function renderSides(r) {
    const b = r.brief, st = r.stance;
    if (!b) {
        $("sides-takeaway").textContent = "This report has no reading of the video, so the sides check didn't run.";
        $("sides").innerHTML = `<div class="empty-card">Scan again with “Fetch the comments again” ticked to watch the video and compare sides.</div>`;
        return;
    }
    const src = b.source === "video"
        ? `Gemini watched ${b.duration_seconds && b.watched_seconds < b.duration_seconds ? `the first ${mmss(b.watched_seconds)} of ${mmss(b.duration_seconds)}` : "the whole video"}.`
        : "The video couldn't be watched; this comes from its title and description.";
    let html = `<div class="brief"><p>${esc(b.summary)}</p>${b.claims?.length ? `<ul>${b.claims.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}<p class="src">${esc(src)}</p></div>`;
    if (!st || !st.rows) {
        $("sides-takeaway").textContent = "The stances couldn't be read, so the sides check didn't run.";
        $("sides").innerHTML = html;
        return;
    }
    const pushed = st.rows.filter((x) => x.pushed);
    const top = st.rows.filter((x) => (b.sides || []).some((s) => s.id === x.stance)).sort((a, z) => z.established.share - a.established.share)[0];
    const gap = top ? Math.round((top.established.share - top.new.share) * 100) : 0;
    const topText = !top ? "" : Math.abs(gap) < 6
        ? ` The biggest side, “${esc(top.label)}”, is as common among both (${pct(top.new.share)} vs ${pct(top.established.share)}).`
        : ` The biggest side, “${esc(top.label)}”, comes ${gap > 0 ? "more from established commenters" : "more from new accounts"} (${pct(top.established.share)} vs ${pct(top.new.share)} of new accounts).`;
    $("sides-takeaway").innerHTML = pushed.length
        ? pushed.map((x) => `New accounts take “${esc(x.label)}” <mark>${x.lift ? `${x.lift}× as often` : "where established commenters don't"}</mark> as established commenters (${pct(x.new.share)} vs ${pct(x.established.share)}).`).join(" ")
        : st.new_accounts < 10 ? `Only ${plural(st.new_accounts, "new account")} commented: too few to compare sides.`
        : `New accounts don't push any side.${topText}`;
    const rows = st.rows.filter((x) => x.new.accounts || x.established.accounts);
    html += `<div class="sides">${rows.map((x) => `<div class="side ${x.tested ? "" : "quiet"}">
            <div class="side-head"><div><b>${esc(stanceName(r, x.stance))}</b><small>${esc((b.sides || []).find((s) => s.id === x.stance)?.description || UNTESTED[x.stance] || "Comments that push a subject the video isn't about.")}</small></div>
                ${x.pushed ? `<span class="pushed">Pushed by new accounts${x.lift ? ` · ${x.lift}×` : ""}</span>` : ""}</div>
            ${sidePair("new", `New: ${x.new.accounts} of ${x.new.of}`, x.new)}${sidePair("old", `Established: ${x.established.accounts} of ${x.established.of}`, x.established)}
        </div>`).join("")}</div>
        <div class="key"><span><i style="background:var(--red)"></i>New accounts: under ${st.young_days} days old, all ${st.new_accounts} labelled</span>
            <span><i style="background:var(--ink);opacity:.45"></i>Established accounts: a random ${st.established_accounts}</span><span>┝┥ 95% interval</span></div>
        <p class="subtle">Each account counts once, with the side most of its comments take. A side is “pushed” when new accounts take it at least ${st.min_lift}× as often and Fisher's exact test gives p &lt; ${st.p_threshold} after correcting for the ${st.rows.filter((x) => x.tested).length} sides tested. Sides come from Gemini; it can misread sarcasm.</p>`;
    $("sides").innerHTML = html;
}

// 3. Groups
function renderGroups(r) {
    const held = r.groups.filter((g) => HELD.includes(g.status) || g.status === "unreviewed");
    const others = r.groups.filter((g) => !held.includes(g));
    if (!r.groups.length) {
        $("groups-takeaway").textContent = "No accounts acted together here.";
        $("groups").innerHTML = `<div class="empty-card">No accounts posted near-copies of each other, no new accounts crowded one reply thread, and no side was pushed by new accounts. These are the patterns that make a group.</div>`;
        return;
    }
    $("groups-takeaway").innerHTML = held.length
        ? `${plural(held.length, "group")} held up: ${held.map((g) => `<b>${esc(g.id)}</b>, ${g.n_accounts} accounts that wrote ${g.n_comments} comments`).join("; ")}.`
        : `${plural(r.groups.length, "possible group")} looked suspicious at first, but none held up.`;
    let html = held.map((g) => groupCard(g, r)).join("");
    if (others.length) {
        html += `<h4 class="subtle" style="margin:8px 0 6px">${held.length ? "Also checked" : "Checked and set aside"}</h4><ul class="also">${others.map((g) =>
            `<li><b style="color:${gcolor(g.id)}">${esc(g.id)}</b>: ${g.n_accounts} accounts, ${esc(RULINGS[g.status] || g.status).toLowerCase()}${g.defense ? `. ${esc(g.defense.reason)}` : ""}</li>`).join("")}</ul>`;
    }
    $("groups").innerHTML = html;
}

function groupCard(g, r) {
    const f = g.finding, d = g.defense;
    const why = (f ? f.evidence : g.signals.map((s) => s.text)).slice(0, 3);
    const quotes = r.comments.filter((c) => c.group === g.id).slice(0, 2)
        .map((c) => `<blockquote>${esc(c.text.length > 200 ? c.text.slice(0, 200) + "…" : c.text)}<cite>${esc(c.account)} · ${esc(when(c.published_at))}${c.is_reply ? " · reply" : ""}</cite></blockquote>`).join("");
    const meters = g.signals.map((s) => `<div class="meter"><div><span>${esc(SIGNAL_NAMES[s.name] || s.name)}</span><span>${pct(s.value)}</span></div>
        <span class="track"><span class="fill" style="width:${Math.round(s.value * 100)}%"></span></span></div>`).join("");
    const accounts = (g.account_profiles || []).map((a) => `<tr><td class="mono">${esc(a.account)}</td><td>${esc(ageText(a.age_days_at_first_comment))}</td>
        <td>${a.video_count ?? "?"}</td><td>${a.comments_here}</td></tr>`).join("");
    const defense = d ? `<div class="defense"><b>The Defense asked: could it be innocent? “${esc(d.innocent_explanation.trim())}”</b>
            <p>${d.holds_up ? "That explanation holds up." : "That explanation doesn't hold up."} ${esc(d.reason)}</p></div>` : "";
    return `<article class="group" style="--gc:${gcolor(g.id)}">
        <div class="group-top"><span class="group-name">${esc(g.id)} · ${esc(PATTERNS[f?.pattern] || PATTERNS[g.pattern] || g.pattern)}</span>
            <span class="badge ${esc(g.status)}">${esc(RULINGS[g.status] || g.status)}${g.confidence != null ? ` · ${pct(g.confidence)} confidence` : ""}</span></div>
        <h3>${esc(f ? f.headline : "Accounts linked by the statistics")}</h3>
        <div class="facts">${g.n_accounts} accounts · ${g.n_comments} comments · ${esc(when(g.first_at))}${g.features.span_minutes != null ? `, all within ${duration(g.features.span_minutes)}` : ""}${f ? ` · ${esc(PURPOSES[f.purpose] || "Purpose")}: ${esc(f.likely_purpose)}` : ""}${g.features.steering_stance ? ` · side: “${esc(stanceName(r, g.features.steering_stance))}”` : ""}</div>
        <h4>Why we flagged it</h4><ul class="why">${why.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
        <h4>What they wrote</h4><div class="quotes">${quotes}</div>
        ${defense}
        <details><summary>See all the evidence</summary>
            <div class="more-grid">
                <div><h4>Signals (score ${pct(g.score)})</h4>${meters}</div>
                <div><h4>The ${g.n_accounts} accounts</h4><table><tr><th>Account</th><th>Age when commenting</th><th>Videos</th><th>Comments</th></tr>${accounts}</table></div>
            </div>
            <p><button class="link" type="button" data-group="${esc(g.id)}">Show all ${g.n_comments} of their comments</button></p>
        </details>
    </article>`;
}

$("groups").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-group]");
    if (b) showComments(b.dataset.group);
});

// 3. Accounts plot: radius = account age when it commented (log scale), angle = when it commented.
const MAX_AGE = 365 * 15, R = 200;
const radiusOf = (age) => (age == null ? R + 14 : Math.max(6, (R * Math.log10(1 + Math.max(0, age))) / Math.log10(1 + MAX_AGE)));
function jitter(s) { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) | 0; return ((h % 1000) / 1000) * 0.018; }

function renderPlot(r) {
    const accs = (r.accounts || []).filter((a) => a.first_comment_at);
    if (!accs.length) { $("scope-takeaway").textContent = "No accounts to plot."; $("plot").innerHTML = ""; return; }
    const heldIds = r.groups.filter((g) => HELD.includes(g.status)).map((g) => g.id);
    const young = accs.filter((a) => a.age_days != null && a.age_days <= 30);
    const youngHeld = young.filter((a) => heldIds.includes(a.group)).length;
    $("scope-takeaway").innerHTML = `Only <b>${young.length} of ${accs.length}</b> accounts were under a month old when they commented` +
        (youngHeld ? `, and <b>${youngHeld}</b> of them are in ${heldIds.join(", ")}. That is why the group sits near the centre.` : ".");

    // Clockwise = the order accounts first commented (clock time would pile most dots into the first hours).
    const sorted = accs.slice().sort((a, b) => (a.first_comment_at < b.first_comment_at ? -1 : 1));
    const turn = (i) => (i / sorted.length) * Math.PI * 2 * 0.96;
    const pts = sorted.map((a, i) => {
        const th = turn(i) + jitter(a.account), rr = Math.min(radiusOf(a.age_days), R + 14);
        return { a, th, x: rr * Math.sin(th), y: -rr * Math.cos(th), r: a.group ? 5.5 : 3 };
    });
    for (let it = 0; it < 6; it++) {  // push overlapping dots apart, so five same-day accounts read as five dots
        for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++) {
            const p = pts[i], q = pts[j], dx = q.x - p.x, dy = q.y - p.y, d = Math.hypot(dx, dy) || 0.01, min = p.r + q.r + 1;
            if (d < min) { const k = (min - d) / 2 / d; p.x -= dx * k; p.y -= dy * k; q.x += dx * k; q.y += dy * k; }
        }
    }
    let svg = `<svg viewBox="-290 -255 580 510" role="img" aria-label="Accounts by age and order of comment">`;
    svg += `<circle r="${radiusOf(1)}" class="ring"/>`;
    [[30, "1 month old"], [365, "1 year"], [1825, "5 years"]].forEach(([d, label]) => {
        const rr = radiusOf(d);
        svg += `<circle r="${rr}" class="ring"/><text class="ring-label" x="4" y="${-rr - 4}">${label}</text>`;
    });
    svg += `<circle r="${R}" class="ring outer"/>`;
    [0, 0.25, 0.5, 0.75].forEach((q, i) => {
        const a = sorted[Math.floor(q * sorted.length)], th = turn(Math.floor(q * sorted.length));
        const x = (R + 22) * Math.sin(th), y = -(R + 22) * Math.cos(th);
        svg += `<text class="time-label" x="${x}" y="${y}" text-anchor="${["middle", "start", "middle", "end"][i]}" dominant-baseline="middle">${esc(when(a.first_comment_at))}</text>`;
    });
    pts.filter((p) => !p.a.group).forEach((p) => { svg += `<circle class="dot" data-a="${esc(p.a.account)}" cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="3"/>`; });
    for (const g of r.groups) {
        const members = pts.filter((p) => p.a.group === g.id);
        if (!members.length) continue;
        const cx = members.reduce((s, m) => s + m.x, 0) / members.length, cy = members.reduce((s, m) => s + m.y, 0) / members.length;
        const ring = members.slice().sort((m, n) => Math.atan2(m.y - cy, m.x - cx) - Math.atan2(n.y - cy, n.x - cx));
        const reach = Math.max(14, Math.max(...members.map((m) => Math.hypot(m.x - cx, m.y - cy))) + 10);
        const th = members.reduce((s, m) => s + m.th, 0) / members.length;  // label outside the dial, at the group's time
        const lx = (R + 48) * Math.sin(th), ly = -(R + 48) * Math.cos(th);
        const ex = cx + reach * Math.sin(th), ey = cy - reach * Math.cos(th);
        const dim = HELD.includes(g.status) ? "" : ' opacity=".4"';
        svg += `<g style="--gc:${gcolor(g.id)}"${dim}>`;
        if (members.length > 2) svg += `<polygon class="web" points="${ring.map((m) => `${m.x.toFixed(1)},${m.y.toFixed(1)}`).join(" ")}"/>`;
        svg += `<circle class="halo" cx="${cx}" cy="${cy}" r="${reach}"/><line class="leader" x1="${ex}" y1="${ey}" x2="${lx}" y2="${ly}"/>
            <text class="glabel" x="${lx}" y="${ly}" text-anchor="${Math.sin(th) >= 0 ? "start" : "end"}" dominant-baseline="middle">${esc(g.id)} · ${g.n_accounts} accounts</text>`;
        members.forEach((m) => { svg += `<circle class="dot member" data-a="${esc(m.a.account)}" cx="${m.x.toFixed(1)}" cy="${m.y.toFixed(1)}" r="5.5" fill="${gcolor(g.id)}"/>`; });
        svg += `</g>`;
    }
    $("plot").innerHTML = svg + `</svg>`;

    $("plot-legend").innerHTML = r.groups.map((g) => `<div><i style="background:${gcolor(g.id)}"></i>${esc(g.id)}: ${g.n_accounts} accounts</div>`).join("") +
        `<div><i style="background:var(--ink);opacity:.28"></i>Everyone else (${accs.filter((a) => !a.group).length})</div>`;

    const byAccount = Object.fromEntries(accs.map((a) => [a.account, a]));
    const firstText = {};
    for (const c of r.comments) if (c.account && !(c.account in firstText)) firstText[c.account] = c.text;
    const info = (acct) => {
        const a = byAccount[acct];
        if (!a) return;
        const text = firstText[acct] || "";
        $("plot-info").innerHTML = `<b class="mono">${esc(a.account)}</b>${a.group ? ` <b style="color:${gcolor(a.group)}">· ${esc(a.group)}</b>` : ""}<br>
            Account age: <b>${esc(ageText(a.age_days))}</b><br>First comment: ${esc(when(a.first_comment_at))}<br>Comments here: ${a.comments}<br>
            <p style="margin:8px 0">“${esc(text.slice(0, 140))}${text.length > 140 ? "…" : ""}”</p><button class="link" type="button" data-acct="${esc(acct)}">Show this account's comments</button>`;
    };
    $("plot").onmouseover = (ev) => { const d = ev.target.closest(".dot"); if (d) info(d.dataset.a); };
    $("plot").onclick = (ev) => { const d = ev.target.closest(".dot"); if (d) info(d.dataset.a); };
    const first = accs.find((a) => heldIds.includes(a.group));
    if (first) info(first.account); else $("plot-info").textContent = "Hover over a dot to see the account.";
}

$("plot-info").addEventListener("click", (ev) => { const b = ev.target.closest("[data-acct]"); if (b) showComments(`acct:${b.dataset.acct}`); });

// 4. Tone
function toneBar(label, dist) {
    const parts = SENTIMENTS.map((s) => {
        const w = Math.round((dist[s] || 0) * 100);
        return w ? `<div style="width:${w}%;background:var(--${s})" title="${s} ${w}%">${w >= 9 ? w + "%" : ""}</div>` : "";
    }).join("");
    return `<div class="bar-row"><div class="bar-head"><b>${esc(label)}</b><span>${plural(dist.n, "comment")}</span></div><div class="bar">${parts}</div></div>`;
}

function renderTone(r) {
    const s = r.sentiment;
    if (s.grouped.n) {
        const [name, diff] = SENTIMENTS.map((x) => [x, (s.grouped[x] || 0) - (s.organic[x] || 0)]).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0];
        const pts = Math.round(Math.abs(diff) * 100);
        $("tone-takeaway").innerHTML = pts >= 10
            ? `Group comments are <mark>${pts} percentage points ${diff > 0 ? "more" : "less"} ${name}</mark> than everyone else's (${pct(s.grouped[name])} vs ${pct(s.organic[name])}).`
            : "The groups sound about the same as everyone else.";
    } else {
        $("tone-takeaway").textContent = `Most comments read as ${SENTIMENTS.slice().sort((a, b) => (s.all[b] || 0) - (s.all[a] || 0))[0]}: ${pct(s.all.negative)} negative, ${pct(s.all.neutral)} neutral, ${pct(s.all.positive)} positive.`;
    }
    $("sentiment").innerHTML = (s.grouped.n ? toneBar("Comments from the groups", s.grouped) + toneBar("Everyone else", s.organic) : toneBar("All comments", s.all)) +
        `<div class="key">${SENTIMENTS.map((x) => `<span><i style="background:var(--${x})"></i>${x}</span>`).join("")}</div>
        <p class="subtle">Model: ${esc(r.sentiment_model)}. It can misread sarcasm and non-English comments.</p>`;
}

// 5. Timing
function renderTiming(r) {
    const bins = r.timeline.bins || [], size = r.timeline.bin_minutes;
    if (!bins.length) { $("timing-takeaway").textContent = "No timestamps."; $("timeline").innerHTML = ""; return; }
    const peak = bins.reduce((a, b) => (b.total > a.total ? b : a));
    const unit = size >= 1440 ? "day" : size >= 60 ? (size === 60 ? "hour" : `${size / 60} hours`) : `${size} minutes`;
    const g = r.groups.find((x) => HELD.includes(x.status));
    $("timing-takeaway").innerHTML = `Comments peaked at <b>${peak.total} per ${unit}</b> around ${esc(when(peak.start))}.` +
        (g ? ` ${esc(g.id)} posted all ${g.n_comments} of its comments within <b>${duration(g.features.span_minutes)}</b>, starting ${esc(when(g.first_at))}.` : "");
    const W = 700, H = 170, max = Math.max(peak.total, 1), bw = W / bins.length;
    let svg = `<line x1="0" x2="${W}" y1="${H}" y2="${H}" stroke="var(--ink)" stroke-width="1.2"/>`;
    bins.forEach((b, i) => {
        const x = i * bw + 0.5, w = Math.max(bw - 2, 1.5), th = (b.total / max) * (H - 14);
        const groups = Object.entries(b.groups);
        svg += `<g><title>${esc(`${when(b.start)}: ${b.total} comments${groups.length ? " · " + groups.map(([k, n]) => `${k}: ${n}`).join(", ") : ""}`)}</title>
            <rect x="${x}" y="${H - th}" width="${w}" height="${th}" rx="1.5" fill="var(--ink)" opacity=".2"/>`;
        let y = H;
        for (const [k, n] of groups) {
            const h = Math.max((n / max) * (H - 14), 4);
            y -= h;
            svg += `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${gcolor(k)}"/>`;
        }
        const marked = groups.filter(([k]) => r.groups.some((x) => x.id === k && HELD.includes(x.status)));
        if (marked.length) {
            const top = Math.min(H - th, y) - 8;
            svg += `<text x="${x + w / 2}" y="${top}" text-anchor="middle" font-family="var(--sans)" font-size="13" font-weight="800" fill="${gcolor(marked[0][0])}">▼ ${esc(marked.map(([k]) => k).join(", "))}</text>`;
        }
        svg += `</g>`;
    });
    const label = (x, anchor, text) => `<text x="${x}" y="${H + 18}" text-anchor="${anchor}" font-family="var(--sans)" font-size="12" fill="var(--ink-3)">${esc(text)}</text>`;
    svg += label(0, "start", when(bins[0].start)) + label(W, "end", when(bins[bins.length - 1].start));
    $("timeline").innerHTML = `<svg viewBox="0 0 ${W} ${H + 26}" preserveAspectRatio="none" role="img" aria-label="Comments over time">${svg}</svg>
        <div class="key"><span><i style="background:var(--ink);opacity:.2"></i>All comments per ${unit}</span>${r.groups.filter((x) => HELD.includes(x.status)).map((x) => `<span><i style="background:${gcolor(x.id)}"></i>${esc(x.id)}</span>`).join("")}</div>`;
}

// 6. Ask a follow-up
function suggestions(r) {
    const g = r.groups.find((x) => HELD.includes(x.status));
    if (g) return [`What does ${g.id} want readers to believe?`, `When were ${g.id}'s accounts created?`, "What do established commenters mostly say?"];
    return ["Why was nothing flagged?", "Which side do most commenters take, and why?", "What do the new accounts say?"];
}

function renderAsk(r) {
    $("chat").innerHTML = "";
    $("suggest").innerHTML = suggestions(r).map((q) => `<button type="button">${esc(q)}</button>`).join("");
}

$("suggest").addEventListener("click", (ev) => {
    const b = ev.target.closest("button");
    if (b) { $("question").value = b.textContent; askQuestion(); }
});
$("ask-form").addEventListener("submit", (ev) => { ev.preventDefault(); askQuestion(); });
$("question").addEventListener("keydown", (ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); askQuestion(); } });

function prose(text) {
    // A small, safe Markdown: escape first, then line by line: "- " / "1." lists, paragraphs, **bold**, `code`.
    const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
    const ITEM = /^\s*([-*•]|\d+[.)])\s+/;
    let html = "", list = null, para = [];
    const flushPara = () => { if (para.length) html += `<p>${para.join("<br>")}</p>`; para = []; };
    const flushList = () => { if (list) html += `<${list.tag}>${list.items.map((i) => `<li>${i}</li>`).join("")}</${list.tag}>`; list = null; };
    for (const line of esc(text).split("\n")) {
        const m = line.match(ITEM);
        if (m) {
            flushPara();
            const tag = /\d/.test(m[1]) ? "ol" : "ul";
            if (!list || list.tag !== tag) { flushList(); list = { tag, items: [] }; }
            list.items.push(inline(line.replace(ITEM, "")));
        } else if (!line.trim()) {
            flushPara(); flushList();
        } else {
            flushList();
            para.push(inline(line));
        }
    }
    flushPara(); flushList();
    return html;
}

async function askQuestion() {
    const question = $("question").value.trim();
    if (!question || !report) return;
    $("question").value = "";
    $("ask-btn").disabled = true;
    const turn = document.createElement("div");
    turn.className = "turn";
    turn.innerHTML = `<div class="q">${esc(question)}</div><div class="a wait">Searching the comments</div>`;
    $("chat").appendChild(turn);
    turn.scrollIntoView({ behavior: "smooth", block: "nearest" });
    const answer = turn.querySelector(".a");
    try {
        const res = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url: report.url, question, history: chat }) });
        const body = await res.json();
        if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
        chat.push({ question, answer: body.answer });
        const tok = body.tokens || {};
        answer.className = "a";
        answer.innerHTML = `${prose(body.answer)}<div class="cost">${body.seconds}s · ${((tok.input || 0) + (tok.output || 0)).toLocaleString()} tokens</div>`;
    } catch (e) {
        answer.className = "a err";
        answer.textContent = `Couldn't answer: ${e.message}`;
    } finally {
        $("ask-btn").disabled = false;
    }
}

// ------------------------------------------------------------------ all comments
function matches(c, f) {
    if (f === "all") return true;
    if (f === "grouped") return !!c.group;
    if (f.startsWith("acct:")) return c.account === f.slice(5);
    if (SENTIMENTS.includes(f)) return c.sentiment === f;
    if (f.startsWith("stance:")) return c.stance === f.slice(7);
    return c.group === f;
}

function showComments(f) {
    filter = f; shown = PAGE;
    $("s-comments").open = true;
    renderComments();
    $("s-comments").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderComments() {
    if (!report) return;
    const cs = report.comments;
    const sides = (report.brief?.sides || []).map((s) => [`stance:${s.id}`, s.label]);
    const options = [["all", "All"], ["grouped", "In a group"], ...report.groups.map((g) => [g.id, g.id]), ...sides, ...SENTIMENTS.map((s) => [s, s[0].toUpperCase() + s.slice(1)])];
    if (filter.startsWith("acct:")) options.push([filter, filter.slice(5)]);
    $("filters").innerHTML = options.map(([k, label]) =>
        `<button type="button" data-f="${esc(k)}" class="${k === filter ? "on" : ""}">${esc(label)}<span class="n">${cs.filter((c) => matches(c, k)).length}</span></button>`).join("");
    const list = cs.filter((c) => matches(c, filter));
    $("comments-note").textContent = `${cs.length.toLocaleString()} comments with their tone and group. Filter to check the evidence yourself.`;
    $("comments").innerHTML = list.length ? list.slice(0, shown).map((c) => `
        <div class="comment ${c.group ? "in-group" : ""}" ${c.group ? `style="--gc:${gcolor(c.group)}"` : ""}>
            <div class="c-meta"><span class="who">${esc(c.account || "unknown")}</span><span>${esc(when(c.published_at))}</span>
                <a href="${esc(report.video.url)}&lc=${encodeURIComponent(c.id)}" target="_blank" rel="noopener">Open on YouTube</a></div>
            <div><p class="c-text">${esc(c.text)}</p>
                <div class="tags">${c.group ? `<span class="tag group">${esc(c.group)}</span>` : ""}${c.sentiment ? `<span class="tag ${esc(c.sentiment)}">${esc(c.sentiment)}</span>` : ""}${c.stance ? `<span class="tag">${esc(stanceName(report, c.stance))}</span>` : ""}${c.is_reply ? `<span class="tag">reply</span>` : ""}</div></div>
        </div>`).join("") : `<p class="subtle">No comments match.</p>`;
    $("more").classList.toggle("hidden", list.length <= shown);
}

$("filters").addEventListener("click", (ev) => {
    const b = ev.target.closest("button");
    if (b) { filter = b.dataset.f; shown = PAGE; renderComments(); }
});
$("more").addEventListener("click", () => { shown += PAGE; renderComments(); });

// ------------------------------------------------------------------ step navigation: highlight the section in view
(function stepnav() {
    if (!("IntersectionObserver" in window)) return;
    const links = Object.fromEntries([...document.querySelectorAll("#stepnav a")].map((a) => [a.getAttribute("href").slice(1), a]));
    const seen = new IntersectionObserver((entries) => {
        for (const e of entries) {
            if (e.isIntersecting) {
                Object.values(links).forEach((a) => a.classList.remove("on"));
                links[e.target.id]?.classList.add("on");
            }
        }
    }, { rootMargin: "-40% 0px -55% 0px" });
    Object.keys(links).forEach((id) => seen.observe($(id)));
})();

// ------------------------------------------------------------------ a link like /?url=<video> opens that video's report
(function autostart() {
    const url = new URLSearchParams(location.search).get("url");
    if (url) { $("url").value = url; start(); }
})();
