const state = {
  dashboard: null,
  activePlan: null,
  selectedDay: 1,
};

const titles = {
  dashboard: ["今日工作台", "学习提醒、前沿日报和 Agent 任务统一展示。"],
  learning: ["学习规划", "创建计划、记录进度，并让 Agent 后续调整。"],
  learningDetail: ["学习计划详情", "查看进度、日历安排，并和学习 Agent 互动。"],
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
        return `
          <article class="item clickable" data-plan-id="${p.id}" tabindex="0" role="button">
            <div class="plan-card-head">
              <h3>${escapeHtml(p.topic)}</h3>
              <button class="text-button danger" data-delete-plan="${p.id}" type="button">删除</button>
            </div>
            <p>${escapeHtml(day.goal || "已生成学习计划。")}</p>
            <small>${escapeHtml(`${p.duration_days} 天 · ${p.daily_minutes} 分钟/天 · ${p.created_at}`)}</small>
          </article>
        `;
      })
      .join("") || `<div class="empty">暂无学习计划。</div>`;
  document.querySelectorAll("[data-plan-id]").forEach((card) => {
    const open = () => openLearningDetail(Number(card.dataset.planId));
    card.addEventListener("click", open);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        open();
      }
    });
  });
  document.querySelectorAll("[data-delete-plan]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      if (!window.confirm("确定删除这个学习计划吗？")) return;
      await api(`/api/learning/plans/${button.dataset.deletePlan}`, { method: "DELETE" });
      await refreshDashboard();
    });
  });
}

async function openLearningDetail(planId) {
  const detail = await api(`/api/learning/plans/${planId}`);
  if (!detail.found) return;
  state.activePlan = detail;
  state.selectedDay = detail.progress.current_day || 1;
  renderLearningDetail();
  setView("learningDetail");
}

function renderLearningDetail() {
  const detail = state.activePlan;
  const plan = detail.plan || {};
  const days = plan.days || [];
  const progress = detail.progress || {};
  const latest = progress.latest_by_day || {};
  const percent = Number(progress.percent || 0);

  document.getElementById("detailTopic").textContent = detail.topic;
  document.getElementById("detailMeta").textContent = `${detail.duration_days} 天 · 每日 ${detail.daily_minutes} 分钟 · ${detail.target_level}`;
  document.getElementById("detailProgressText").textContent = `${percent}%`;
  document.getElementById("detailProgressFill").style.width = `${Math.max(0, Math.min(100, percent))}%`;
  document.getElementById("calendarMeta").textContent = `${progress.completed_days || 0}/${detail.duration_days} 天完成`;
  const settingsForm = document.getElementById("planSettingsForm");
  settingsForm.elements.plan_id.value = detail.id;
  settingsForm.elements.duration_days.value = detail.duration_days;
  settingsForm.elements.daily_minutes.value = detail.daily_minutes;

  document.getElementById("learningCalendar").innerHTML = days
    .map((day) => {
      const record = latest[day.day] || {};
      const complete = Number(record.completion || 0) >= 100;
      const selected = day.day === state.selectedDay;
      return `
        <button class="calendar-day ${selected ? "selected" : ""} ${complete ? "done" : ""}" data-day="${day.day}">
          <span>Day ${day.day}</span>
          <strong>${complete ? "完成" : "待学"}</strong>
        </button>
      `;
    })
    .join("");
  document.querySelectorAll("[data-day]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedDay = Number(button.dataset.day);
      renderLearningDetail();
    });
  });

  const selected = days[state.selectedDay - 1] || {};
  const selectedRecord = latest[state.selectedDay] || {};
  const isDone = Number(selectedRecord.completion || 0) >= 100;
  document.getElementById("selectedDayTitle").textContent = `Day ${state.selectedDay} 当日安排`;
  document.getElementById("selectedDayStatus").textContent = isDone ? "已完成" : "未完成";
  document.getElementById("selectedDayPlan").innerHTML = `
    <h3>${escapeHtml(selected.title || detail.topic)}</h3>
    <p>${escapeHtml(selected.goal || "按计划完成今日学习。")}</p>
    <ul>${(selected.tasks || []).map((task) => `<li>${escapeHtml(task)}</li>`).join("")}</ul>
    <small>${escapeHtml(selected.check || "")}</small>
    <form class="inline-progress" data-progress-form>
      <input type="hidden" name="plan_id" value="${detail.id}" />
      <input type="hidden" name="day_index" value="${state.selectedDay}" />
      <label>完成度<input name="completion" type="number" min="0" max="100" value="${selectedRecord.completion || 100}" /></label>
      <label>掌握度<input name="mastery" type="number" min="0" max="100" value="${selectedRecord.mastery || 80}" /></label>
      <button type="submit">保存进度</button>
    </form>
  `;
  document.querySelector("[data-progress-form]").addEventListener("submit", saveSelectedProgress);

  const pending = days.filter((day) => Number((latest[day.day] || {}).completion || 0) < 100);
  const done = days.filter((day) => Number((latest[day.day] || {}).completion || 0) >= 100);
  document.getElementById("pendingCount").textContent = `${pending.length} 项`;
  document.getElementById("doneCount").textContent = `${done.length} 项`;
  document.getElementById("pendingTasks").innerHTML =
    pending.map((day) => compactTaskItem(day, latest[day.day])).join("") || `<div class="empty">暂无未完成计划。</div>`;
  document.getElementById("doneTasks").innerHTML =
    done.map((day) => compactTaskItem(day, latest[day.day])).join("") || `<div class="empty">暂无已完成计划。</div>`;
  document.querySelectorAll("[data-jump-day]").forEach((row) => {
    row.addEventListener("click", () => {
      state.selectedDay = Number(row.dataset.jumpDay);
      renderLearningDetail();
      document.getElementById("selectedDayPlan").scrollIntoView({ behavior: "smooth", block: "center" });
    });
  });
}

function compactTaskItem(day, record = {}) {
  const completion = Number(record.completion || 0);
  return `
    <article class="item task-row" data-jump-day="${day.day}">
      <div>
        <h3>Day ${day.day}</h3>
        <p>${escapeHtml(day.goal)}</p>
      </div>
      <span>${completion}%</span>
    </article>
  `;
}

async function saveSelectedProgress(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  await api("/api/learning/progress", {
    method: "POST",
    body: JSON.stringify({
      plan_id: Number(form.get("plan_id")),
      day_index: Number(form.get("day_index")),
      completion: Number(form.get("completion")),
      mastery: Number(form.get("mastery")),
      notes: "",
    }),
  });
  await openLearningDetail(Number(form.get("plan_id")));
  await refreshDashboard();
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
document.getElementById("backToLearning").addEventListener("click", () => setView("learning"));

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
  const message = document.getElementById("learningMessage");
  message.className = "form-message";
  message.textContent = "";
  const result = await api("/api/learning/plans", {
    method: "POST",
    body: JSON.stringify({
      topic: form.get("topic"),
      duration_days: Number(form.get("duration_days")),
      daily_minutes: Number(form.get("daily_minutes")),
      target_level: form.get("target_level"),
      use_knowledge: form.get("use_knowledge") === "on",
    }),
  });
  message.textContent = result.message || "学习计划已生成。";
  message.classList.add("show");
  message.classList.toggle("warning", Boolean(result.duplicate));
  if (result.duplicate) {
    window.alert("该计划已添加");
  }
  await refreshDashboard();
});

document.getElementById("planSettingsForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const planId = Number(form.get("plan_id"));
  const result = await api(`/api/learning/plans/${planId}`, {
    method: "PATCH",
    body: JSON.stringify({
      duration_days: Number(form.get("duration_days")),
      daily_minutes: Number(form.get("daily_minutes")),
    }),
  });
  const message = document.getElementById("planSettingsMessage");
  message.textContent = result.ok ? "计划设置已更新。" : result.message || "更新失败。";
  message.className = `form-message show ${result.ok ? "" : "warning"}`;
  await openLearningDetail(planId);
  await refreshDashboard();
});

document.getElementById("learningChatForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.activePlan) return;
  const form = new FormData(event.currentTarget);
  const message = String(form.get("message") || "").trim();
  if (!message) return;
  const chat = document.getElementById("learningChat");
  chat.insertAdjacentHTML("beforeend", `<div class="chat-bubble user">${escapeHtml(message)}</div>`);
  event.currentTarget.reset();
  const result = await api("/api/learning/chat", {
    method: "POST",
    body: JSON.stringify({ plan_id: state.activePlan.id, message, selected_day: state.selectedDay }),
  });
  chat.insertAdjacentHTML("beforeend", `<div class="chat-bubble agent">${escapeHtml(result.answer)}</div>`);
  chat.scrollTop = chat.scrollHeight;
});

function setupChatResize() {
  const chat = document.getElementById("learningChat");
  const handle = document.getElementById("chatResizeHandle");
  const minHeight = 180;
  const maxHeight = 680;
  let startY = 0;
  let startHeight = 0;
  let resizing = false;

  const setHeight = (height) => {
    const next = Math.max(minHeight, Math.min(maxHeight, height));
    chat.style.height = `${next}px`;
  };

  const beginResize = (clientY) => {
    resizing = true;
    startY = clientY;
    startHeight = chat.getBoundingClientRect().height;
    document.body.classList.add("resizing-chat");
  };

  const moveResize = (clientY) => {
    if (!resizing) return;
    setHeight(startHeight + clientY - startY);
  };

  const endResize = () => {
    resizing = false;
    document.body.classList.remove("resizing-chat");
  };

  handle.addEventListener("mousedown", (event) => {
    event.preventDefault();
    beginResize(event.clientY);
  });
  window.addEventListener("mousemove", (event) => moveResize(event.clientY));
  window.addEventListener("mouseup", endResize);

  handle.addEventListener("touchstart", (event) => {
    beginResize(event.touches[0].clientY);
  }, { passive: true });
  window.addEventListener("touchmove", (event) => {
    if (resizing) moveResize(event.touches[0].clientY);
  }, { passive: true });
  window.addEventListener("touchend", endResize);

  handle.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    event.preventDefault();
    const current = chat.getBoundingClientRect().height;
    setHeight(current + (event.key === "ArrowDown" ? 32 : -32));
  });
}

setupChatResize();

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
