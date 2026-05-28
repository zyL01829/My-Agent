const state = {
  dashboard: null,
};

const titles = {
  dashboard: ["今日工作台", "学习提醒、前沿日报和 Agent 任务统一展示。"],
  learning: ["学习规划", "创建计划、记录进度，并让 Agent 后续调整。"],
  knowledge: ["RAG 知识库", "上传本地资料，供所有 Agent 检索引用。"],
  ppt: ["PPT 制作", "基于主题和知识库素材生成 PPT 文件。"],
  frontier: ["前沿资讯", "AI 与金融量化日报归档。"],
};

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: options.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function item(title, body, meta = "") {
  return `<article class="item"><h3>${escapeHtml(title)}</h3><p>${escapeHtml(body)}</p>${meta ? `<small>${meta}</small>` : ""}</article>`;
}

function setView(view) {
  document.querySelectorAll(".nav-item").forEach((btn) => btn.classList.toggle("active", btn.dataset.view === view));
  document.querySelectorAll(".view").forEach((el) => el.classList.toggle("active", el.id === view));
  document.getElementById("pageTitle").textContent = titles[view][0];
  document.getElementById("pageSubtitle").textContent = titles[view][1];
}

async function refreshDashboard() {
  state.dashboard = await api("/api/dashboard");
  renderAgents(state.dashboard.agents);
  renderDashboard(state.dashboard);
  await Promise.all([refreshKnowledge(), refreshLearning(), refreshPPT(), refreshFrontier()]);
}

function renderAgents(agents) {
  const enabled = agents.filter((agent) => agent.enabled).length;
  document.getElementById("agentSummary").textContent = `${enabled}/${agents.length} 启用`;
  document.getElementById("agentList").innerHTML = agents
    .map(
      (agent) => `
      <div class="agent-pill ${agent.enabled ? "" : "disabled"}">
        <div class="agent-row">
          <strong>${escapeHtml(agent.name)}</strong>
          <span class="status-dot ${agent.enabled ? "on" : ""}"></span>
        </div>
        <p>${escapeHtml(agent.description)}</p>
        <small>${escapeHtml(agent.enabled ? "已启用" : "预留")} · ${escapeHtml(agent.tools.join(", "))}</small>
      </div>
    `,
    )
    .join("");
}

function renderDashboard(data) {
  const unread = data.notifications.filter((n) => !n.is_read);
  document.getElementById("unreadCount").textContent = unread.length;
  document.getElementById("planCount").textContent = data.plans.length;
  document.getElementById("fileCount").textContent = data.knowledge_files.length;
  document.getElementById("reportCount").textContent = data.frontier_reports.length;
  document.getElementById("notificationList").innerHTML =
    data.notifications.map((n) => item(n.title, n.body, `${n.source_agent} · ${n.created_at}`)).join("") ||
    `<div class="empty">暂无通知。</div>`;

  const plan = data.plans[0];
  if (!plan) {
    document.getElementById("todayLearning").innerHTML = "暂无学习计划，先创建一个。";
    return;
  }
  const days = plan.plan.days || [];
  const today = days[0] || {};
  document.getElementById("todayLearning").innerHTML = `
    <article class="item">
      <h3>${escapeHtml(plan.topic)}</h3>
      <p>${escapeHtml(today.goal || "按计划完成今日学习。")}</p>
      <small>${escapeHtml(plan.duration_days)} 天 · 每日 ${escapeHtml(plan.daily_minutes)} 分钟</small>
    </article>
  `;
}

async function refreshKnowledge() {
  const files = await api("/api/knowledge/files");
  document.getElementById("knowledgeFiles").innerHTML =
    files
      .map((f) =>
        `<article class="item">
          <h3>${escapeHtml(f.filename)}</h3>
          <p>${escapeHtml(`${f.chunk_count} 个切片 · ${f.file_type}`)}</p>
          <small>${escapeHtml(f.uploaded_at)} ${f.tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</small><br />
          <button class="small-button" data-delete-file="${f.id}">删除</button>
        </article>`,
      )
      .join("") || `<div class="empty">暂无文件。</div>`;
  document.querySelectorAll("[data-delete-file]").forEach((button) => {
    button.addEventListener("click", async () => {
      await api(`/api/knowledge/files/${button.dataset.deleteFile}`, { method: "DELETE" });
      await refreshDashboard();
    });
  });
}

async function refreshLearning() {
  const plans = await api("/api/learning/plans");
  document.getElementById("learningPlans").innerHTML =
    plans
      .map((p) => {
        const day = (p.plan.days || [])[0] || {};
        return item(p.topic, day.goal || "已生成学习计划。", `${p.duration_days} 天 · ${p.daily_minutes} 分钟/天 · ${p.created_at}`);
      })
      .join("") || `<div class="empty">暂无学习计划。</div>`;
}

async function refreshPPT() {
  const jobs = await api("/api/ppt/jobs");
  document.getElementById("pptJobs").innerHTML =
    jobs
      .map((job) => {
        const output = job.output || {};
        const link = output.file ? `<br /><a href="${output.file}" target="_blank">下载 PPT</a>` : "";
        return item(job.title, `${job.status}${link}`, job.created_at);
      })
      .join("") || `<div class="empty">暂无 PPT 任务。</div>`;
}

async function refreshFrontier() {
  const reports = await api("/api/frontier/reports");
  document.getElementById("frontierReports").innerHTML =
    reports
      .map((r) => {
        const sections = (r.content.sections || []).map((s) => `${s.name}：${s.items.join("；")}`).join("\n");
        return item(r.title, sections, r.created_at);
      })
      .join("") || `<div class="empty">暂无日报。</div>`;
}

document.querySelectorAll(".nav-item").forEach((btn) => btn.addEventListener("click", () => setView(btn.dataset.view)));
document.getElementById("refreshBtn").addEventListener("click", refreshDashboard);

document.getElementById("uploadForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  await api("/api/knowledge/upload", { method: "POST", body: form });
  event.currentTarget.reset();
  await refreshDashboard();
});

document.getElementById("queryForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const result = await api("/api/knowledge/query", {
    method: "POST",
    body: JSON.stringify({ query: form.get("query"), limit: 5 }),
  });
  const sources = result.sources.map((s) => `\n\n来源：${s.filename} #${s.chunk_index}\n${s.content}`).join("");
  document.getElementById("queryResult").textContent = `${result.answer}${sources}`;
});

document.getElementById("learningForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  await api("/api/learning/plans", {
    method: "POST",
    body: JSON.stringify({
      topic: form.get("topic"),
      duration_days: Number(form.get("duration_days")),
      daily_minutes: Number(form.get("daily_minutes")),
      target_level: form.get("target_level"),
      use_knowledge: form.get("use_knowledge") === "on",
    }),
  });
  await refreshDashboard();
});

document.getElementById("pptForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  await api("/api/ppt/generate", {
    method: "POST",
    body: JSON.stringify({
      topic: form.get("topic"),
      audience: form.get("audience"),
      style: form.get("style"),
      slides: Number(form.get("slides")),
      use_knowledge: form.get("use_knowledge") === "on",
    }),
  });
  await refreshDashboard();
});

document.getElementById("runFrontier").addEventListener("click", async () => {
  await api("/api/frontier/run", { method: "POST", body: "{}" });
  await refreshDashboard();
});

refreshDashboard().catch((error) => {
  document.body.insertAdjacentHTML("beforeend", `<div class="empty">${escapeHtml(error.message)}</div>`);
});
