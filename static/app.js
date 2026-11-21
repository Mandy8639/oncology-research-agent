/* Dashboard — all numbers from API / committed eval report. */
(function () {
  const $ = (id) => document.getElementById(id);

  function badgeClass(decision) {
    const d = (decision || "").toUpperCase();
    if (d === "ALLOW") return "badge badge-ok";
    if (d === "HOLD") return "badge badge-hold";
    if (d === "BLOCK") return "badge badge-block";
    return "badge";
  }

  function pct(n) {
    if (n == null || Number.isNaN(n)) return "—";
    return `${(Number(n) * 100).toFixed(1)}%`;
  }

  function money(n) {
    return `$${Number(n || 0).toFixed(2)}`;
  }

  async function getJSON(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${url} → ${res.status}`);
    return res.json();
  }

  function renderControls(digest) {
    const paused = digest.paused;
    const badge = $("pause-badge");
    badge.textContent = paused ? `paused: ${digest.pause_reason || "yes"}` : "running";
    badge.className = paused ? "badge badge-pause" : "badge badge-ok";

    const items = [
      ["Answers (last 100)", digest.questions_answered],
      ["Hold rate", pct(digest.hold_rate)],
      ["Auto-allow rate", pct(digest.auto_allow_rate)],
      ["Ungrounded rate", pct(digest.ungrounded_claim_rate)],
      ["Fabrication attempts", digest.fabrication_attempts],
      ["Exceptions", digest.exceptions_inventory_size],
    ];
    $("controls-grid").innerHTML = items
      .map(
        ([label, value]) =>
          `<div class="metric"><span class="label">${label}</span><div class="value">${value}</div></div>`
      )
      .join("");

    const breaches = (digest.breaches || []).join(", ") || "none";
    const fresh = digest.freshness || {};
    $("controls-note").textContent =
      `Freshness: ${fresh.ok ? "ok" : fresh.reason} · breaches: ${breaches} · ` +
      `thresholds ungrounded>${pct(digest.thresholds?.ungrounded_claim_rate)} ` +
      `auto-allow>${pct(digest.thresholds?.auto_allow_rate)}`;
  }

  function renderEval(report) {
    const m = report.metrics || {};
    $("eval-mode").textContent = report.mode || "stub";
    const rows = [
      ["Grounding accuracy", pct(m.grounding_accuracy)],
      ["Citation precision", pct(m.citation_precision)],
      ["False-publish rate", pct(m.false_publish_rate)],
      ["Abstention accuracy", pct(m.abstention_accuracy)],
      ["Hold accuracy", pct(m.hold_accuracy)],
      ["Fabrication-trap block rate", pct(m.fabrication_trap_block_rate)],
      ["Pause detection rate", pct(m.pause_condition_detection_rate)],
      ["LLM cost", money(m.llm_cost_usd)],
    ];
    $("eval-table-wrap").innerHTML =
      `<table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>` +
      rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("") +
      `</tbody></table>`;
    $("eval-meta").textContent =
      `${report.passed}/${report.n_questions} passed · ${report.timestamp || ""}`;
  }

  function renderQuestions(questions) {
    const root = $("questions-list");
    if (!questions.length) {
      root.innerHTML = `<p class="empty">No questions yet. Run <code>onco ask "…"</code> or the eval harness.</p>`;
      return;
    }
    root.innerHTML = questions
      .slice(0, 40)
      .map((q) => {
        const cites = (q.citations || [])
          .map((c) => `<span class="cite">${c}</span>`)
          .join(" ");
        return `<article class="card-row">
          <div class="card-meta">
            <span class="cite">${q.id}</span>
            <span class="${badgeClass(q.guardrail_decision)}">${q.guardrail_decision || q.status}</span>
            <span class="badge">${q.status}</span>
          </div>
          <h3>${escapeHtml(q.text || "")}</h3>
          <p class="muted">${escapeHtml(q.final_answer || q.proposed_answer || "")}</p>
          <div class="card-meta">${cites || '<span class="muted">no citations</span>'}</div>
        </article>`;
      })
      .join("");
  }

  function renderReview(held) {
    const root = $("review-list");
    if (!held.length) {
      root.innerHTML = `<p class="empty">Review queue is empty.</p>`;
      return;
    }
    root.innerHTML = held
      .map((q) => {
        const cites = (q.citations || [])
          .map((c) => `<span class="cite">${c}</span>`)
          .join(" ");
        return `<article class="card-row" data-id="${q.id}">
          <div class="card-meta">
            <span class="cite">${q.id}</span>
            <span class="badge badge-hold">HOLD</span>
            <span class="muted">${escapeHtml(q.guardrail_reason || "")}</span>
          </div>
          <h3>${escapeHtml(q.text || "")}</h3>
          <p>${escapeHtml(q.proposed_answer || "")}</p>
          <div class="card-meta">${cites}</div>
          <div class="review-actions">
            <textarea placeholder="Human reason (required)" aria-label="Reason for ${q.id}"></textarea>
            <div class="row">
              <button type="button" class="primary" data-action="approve">Approve</button>
              <button type="button" class="danger" data-action="reject">Reject</button>
            </div>
          </div>
        </article>`;
      })
      .join("");

    root.querySelectorAll("button[data-action]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const card = btn.closest(".card-row");
        const id = card.dataset.id;
        const reason = card.querySelector("textarea").value.trim();
        if (!reason) {
          alert("A human reason is required.");
          return;
        }
        const action = btn.dataset.action;
        const res = await fetch(`/questions/${encodeURIComponent(id)}/review`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action,
            reason,
            actor: "reviewing_scientist",
          }),
        });
        if (!res.ok) {
          const err = await res.text();
          alert(`Review failed: ${err}`);
          return;
        }
        await loadAll();
      });
    });
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  async function loadAll() {
    const [digest, questions, held, report] = await Promise.all([
      getJSON("/controls/digest"),
      getJSON("/questions"),
      getJSON("/questions?status=held"),
      getJSON("/evals/latest?mode=stub"),
    ]);
    renderControls(digest);
    renderQuestions(questions);
    renderReview(held);
    renderEval(report);
  }

  $("refresh-btn").addEventListener("click", () => loadAll().catch(console.error));
  loadAll().catch((err) => {
    console.error(err);
    $("controls-note").textContent = `Failed to load: ${err.message}`;
  });
})();
