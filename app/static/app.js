const toast = document.getElementById("toast");
let toastTimer;

function showToast(message, tone = "default") {
  if (!toast) return;
  window.clearTimeout(toastTimer);
  toast.textContent = message;
  toast.dataset.tone = tone;
  toast.hidden = false;
  toastTimer = window.setTimeout(() => {
    toast.hidden = true;
    toast.dataset.tone = "default";
  }, 4000);
}

async function postJson(url, payload = undefined) {
  const response = await fetch(url, {
    method: "POST",
    headers: payload ? {"Content-Type": "application/json"} : {},
    body: payload ? JSON.stringify(payload) : undefined,
  });
  if (!response.ok) throw new Error(await responseText(response));
  return response.json();
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(await responseText(response));
  return response.json();
}

async function responseText(response) {
  const text = await response.text();
  try {
    const payload = JSON.parse(text);
    return payload.detail || payload.message || text;
  } catch (_) {
    return text;
  }
}

function setButtonLoading(button, isLoading) {
  if (!button) return;
  if (isLoading) {
    button.dataset.originalText = button.textContent;
    button.textContent = button.dataset.loadingText || "处理中";
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
  } else {
    button.textContent = button.dataset.originalText || button.textContent;
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }
}

function setFormFeedback(form, message, tone = "") {
  const feedback = form ? form.querySelector("[data-form-feedback]") : null;
  if (!feedback) return;
  feedback.textContent = message;
  feedback.className = `inline-feedback${tone ? ` ${tone}` : ""}`;
}

function taskResultMessage(taskName, payload) {
  const labels = {
    "screen-market": "候选池扫描完成",
    "update-market-data": "行情更新完成",
    "compute-indicators": "指标计算完成",
    "scan-structures": "结构扫描完成",
    "run-pipeline": "评级与计划刷新完成",
    "run-daily": "每日完整扫描完成",
    "run-60m": "60 分钟监控刷新完成",
    "set-price-alerts": "到价提醒同步完成",
    "run-backtest": "复盘生成完成",
  };
  const detail = Object.entries(payload || {})
    .filter(([, value]) => ["string", "number"].includes(typeof value))
    .slice(0, 2)
    .map(([key, value]) => `${key}: ${value}`)
    .join("，");
  return `${labels[taskName] || "任务完成"}${detail ? `。${detail}` : ""}`;
}

let taskPollTimer;

document.querySelectorAll("[data-task]").forEach((button) => {
  button.addEventListener("click", async () => {
    setButtonLoading(button, true);
    try {
      const payload = await postJson(`/tasks/${button.dataset.task}`);
      if (payload.id && ["PENDING", "RUNNING"].includes(payload.status)) {
        renderTaskProgress(payload);
        setTaskButtonsDisabled(true);
        pollTask(payload.id);
        return;
      }
      showToast(taskResultMessage(button.dataset.task, payload), "success");
      window.setTimeout(() => window.location.reload(), 800);
    } catch (error) {
      showToast(error.message, "error");
      setButtonLoading(button, false);
    }
  });
});

async function restoreActiveTask() {
  if (!document.querySelector("[data-task-progress]")) return;
  try {
    const payload = await getJson("/api/tasks/active");
    if (payload.id && ["PENDING", "RUNNING"].includes(payload.status)) {
      renderTaskProgress(payload);
      setTaskButtonsDisabled(true);
      pollTask(payload.id);
    }
  } catch (_) {
    // The dashboard remains usable if task status cannot be restored.
  }
}

async function pollTask(taskId) {
  window.clearTimeout(taskPollTimer);
  try {
    const payload = await getJson(`/api/tasks/${taskId}`);
    renderTaskProgress(payload);
    if (["PENDING", "RUNNING"].includes(payload.status)) {
      taskPollTimer = window.setTimeout(() => pollTask(taskId), 1000);
      return;
    }
    setTaskButtonsDisabled(false);
    if (payload.status === "SUCCEEDED") {
      const failed = Number(payload.result?.failed || 0);
      const tone = failed ? "error" : "success";
      showToast(
        failed
          ? `行情更新完成，但有 ${failed} 个周期失败。请查看任务结果后重试。`
          : taskResultMessage(payload.name, payload.result),
        tone,
      );
      window.setTimeout(() => window.location.reload(), 1400);
    } else {
      showToast(payload.error || payload.message || "后台任务执行失败", "error");
    }
  } catch (error) {
    setTaskButtonsDisabled(false);
    showToast(`无法读取后台任务状态：${error.message}`, "error");
  }
}

function renderTaskProgress(payload) {
  const container = document.querySelector("[data-task-progress]");
  if (!container) return;
  const labels = {
    "screen-market": "扫描全市场候选池",
    "update-market-data": "更新行情",
    "run-daily": "运行每日完整扫描",
    "run-60m": "刷新 60 分钟监控",
    "set-price-alerts": "同步到价提醒",
    "run-backtest": "生成复盘",
  };
  const percent = Math.max(0, Math.min(100, Number(payload.progress_pct || 0)));
  container.hidden = false;
  container.querySelector("[data-task-progress-title]").textContent = labels[payload.name] || "后台任务";
  container.querySelector("[data-task-progress-message]").textContent =
    payload.error || payload.message || "正在执行";
  container.querySelector("[data-task-progress-value]").textContent = `${percent.toFixed(0)}%`;
  container.querySelector("[data-task-progress-bar]").style.width = `${percent}%`;
  const track = container.querySelector("[role='progressbar']");
  track.setAttribute("aria-valuenow", String(percent));
}

function setTaskButtonsDisabled(disabled) {
  document.querySelectorAll("[data-task]").forEach((button) => {
    button.disabled = disabled;
    if (!disabled) {
      button.removeAttribute("aria-busy");
      button.textContent = button.dataset.originalText || button.textContent;
    }
  });
}

restoreActiveTask();

let livePriceTimer;

async function refreshLivePlanPrices() {
  const priceNodes = document.querySelectorAll("[data-live-price]");
  if (!priceNodes.length) return;
  const statusNodes = document.querySelectorAll("[data-live-price-status]");
  try {
    const payload = await getJson("/api/trade-plans/prices");
    priceNodes.forEach((node) => {
      const price = payload.prices?.[node.dataset.livePrice];
      if (Number.isFinite(Number(price)) && Number(price) > 0) {
        node.textContent = Number(price).toFixed(2);
      }
    });
    const changedGate = [...document.querySelectorAll("[data-plan-symbol]")].some((card) => {
      const price = Number(payload.prices?.[card.dataset.planSymbol] || 0);
      const entry = Number(card.dataset.entryPrice || 0);
      const noChase = Number(card.dataset.noChaseAbove || 0);
      const priceReady = price > 0 && entry > 0 && price >= entry && (!noChase || price <= noChase);
      const statusChanged = payload.statuses?.[card.dataset.planSymbol]
        && payload.statuses[card.dataset.planSymbol] !== card.dataset.planStatus;
      return String(priceReady) !== card.dataset.priceReady || statusChanged;
    });
    if (changedGate) {
      window.location.reload();
      return;
    }
    const updatedAt = payload.updated_at
      ? new Intl.DateTimeFormat("zh-CN", {hour: "2-digit", minute: "2-digit", second: "2-digit"}).format(new Date(payload.updated_at))
      : "刚刚";
    statusNodes.forEach((node) => {
      node.textContent = `OpenD 实时价已更新 · ${updatedAt}`;
      node.dataset.tone = "success";
    });
  } catch (error) {
    statusNodes.forEach((node) => {
      node.textContent = `实时价更新失败，页面保留最后有效价 · ${error.message}`;
      node.dataset.tone = "error";
    });
  } finally {
    window.clearTimeout(livePriceTimer);
    livePriceTimer = window.setTimeout(refreshLivePlanPrices, 15000);
  }
}

refreshLivePlanPrices();

document.querySelectorAll("[data-logout]").forEach((button) => {
  button.addEventListener("click", async () => {
    setButtonLoading(button, true);
    try {
      await postJson("/api/auth/logout");
      window.location.href = "/login";
    } catch (error) {
      setButtonLoading(button, false);
      showToast(error.message, "error");
    }
  });
});

const navToggle = document.querySelector("[data-nav-toggle]");
const navClose = document.querySelector("[data-nav-close]");

function setNavigationOpen(isOpen) {
  document.body.classList.toggle("nav-open", isOpen);
  if (navToggle) {
    navToggle.setAttribute("aria-expanded", String(isOpen));
    navToggle.setAttribute("aria-label", isOpen ? "关闭导航" : "打开导航");
  }
}

if (navToggle) {
  navToggle.addEventListener("click", () => setNavigationOpen(!document.body.classList.contains("nav-open")));
}

if (navClose) {
  navClose.addEventListener("click", () => setNavigationOpen(false));
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    setNavigationOpen(false);
    document.querySelectorAll("details[open]").forEach((details) => {
      details.removeAttribute("open");
    });
  }
});

const loginForm = document.getElementById("login-form");
if (loginForm) {
  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(loginForm);
    const button = loginForm.querySelector("button[type='submit']");
    setFormFeedback(loginForm, "");
    setButtonLoading(button, true);
    try {
      await postJson("/api/auth/login", {password: formData.get("password")});
      window.location.href = "/";
    } catch (error) {
      setButtonLoading(button, false);
      setFormFeedback(loginForm, error.message, "error");
      showToast(error.message, "error");
    }
  });
}

const setupPasswordForm = document.getElementById("setup-password-form");
if (setupPasswordForm) {
  setupPasswordForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(setupPasswordForm);
    const password = String(formData.get("password") || "");
    const confirmPassword = String(formData.get("confirm_password") || "");
    const button = setupPasswordForm.querySelector("button[type='submit']");
    setFormFeedback(setupPasswordForm, "");
    if (password !== confirmPassword) {
      setFormFeedback(setupPasswordForm, "两次输入的密码不一致", "error");
      return;
    }
    setButtonLoading(button, true);
    try {
      await postJson("/api/auth/setup-password", {password});
      window.location.href = "/";
    } catch (error) {
      setButtonLoading(button, false);
      setFormFeedback(setupPasswordForm, error.message, "error");
      showToast(error.message, "error");
    }
  });
}

document.querySelectorAll("[data-approve]").forEach((button) => {
  button.addEventListener("click", async () => {
    setButtonLoading(button, true);
    try {
      await postJson(`/api/signals/${button.dataset.approve}/approve`);
      showToast("建议已批准，模拟持仓已更新", "success");
      window.setTimeout(() => window.location.reload(), 600);
    } catch (error) {
      setButtonLoading(button, false);
      showToast(error.message, "error");
    }
  });
});

document.querySelectorAll("[data-reject]").forEach((button) => {
  button.addEventListener("click", async () => {
    if (!window.confirm("确认拒绝这条交易建议？")) return;
    setButtonLoading(button, true);
    try {
      await postJson(`/api/signals/${button.dataset.reject}/reject`);
      showToast("建议已拒绝", "success");
      window.setTimeout(() => window.location.reload(), 600);
    } catch (error) {
      setButtonLoading(button, false);
      showToast(error.message, "error");
    }
  });
});

const riskForm = document.getElementById("risk-form");
if (riskForm) {
  riskForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(riskForm);
    const payload = {};
    const button = riskForm.querySelector("button[type='submit']");
    setFormFeedback(riskForm, "");
    for (const [key, value] of formData.entries()) {
      payload[key] = key.includes("positions") || key.includes("days") ? Number.parseInt(value, 10) : Number.parseFloat(value);
    }
    setButtonLoading(button, true);
    try {
      await postJson("/api/risk", payload);
      setFormFeedback(riskForm, "风控参数已保存", "success");
      showToast("风控参数已保存", "success");
    } catch (error) {
      setFormFeedback(riskForm, error.message, "error");
      showToast(error.message, "error");
    } finally {
      setButtonLoading(button, false);
    }
  });
}

document.querySelectorAll("[data-opend-action]").forEach((button) => {
  button.addEventListener("click", async () => {
    if (button.dataset.confirm && !window.confirm(button.dataset.confirm)) return;
    await runOpenDAction(button, `/api/opend/${button.dataset.opendAction}`);
  });
});

document.querySelectorAll("[data-opend-refresh]").forEach((button) => {
  button.addEventListener("click", async () => {
    setButtonLoading(button, true);
    try {
      const payload = await getJson("/api/opend/status");
      renderOpenDStatus(payload);
      showToast(payload.message || "OpenD 状态已刷新", payload.ok === false ? "error" : "success");
    } catch (error) {
      showToast(error.message, "error");
    } finally {
      setButtonLoading(button, false);
    }
  });
});

document.querySelectorAll("[data-opend-diagnostics]").forEach((button) => {
  button.addEventListener("click", async () => {
    setButtonLoading(button, true);
    try {
      const payload = await getJson("/api/opend/diagnostics");
      renderOpenDStatus(payload);
      showToast(payload.message || "诊断日志已读取", payload.ok === false ? "error" : "success");
    } catch (error) {
      showToast(error.message, "error");
    } finally {
      setButtonLoading(button, false);
    }
  });
});

const openDConfigForm = document.getElementById("opend-config-form");
if (openDConfigForm) {
  openDConfigForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(openDConfigForm);
    const payload = {
      login_account: String(formData.get("login_account") || ""),
      login_password: String(formData.get("login_password") || ""),
      trd_unlock_password: String(formData.get("trd_unlock_password") || ""),
    };
    setFormFeedback(openDConfigForm, "");
    const result = await runOpenDAction(openDConfigForm.querySelector("button"), "/api/opend/configure", payload);
    setFormFeedback(openDConfigForm, result.ok ? "登录配置已保存" : result.message, result.ok ? "success" : "error");
    openDConfigForm.querySelectorAll("input[type='password']").forEach((input) => { input.value = ""; });
  });
}

const phoneCodeForm = document.getElementById("opend-phone-code-form");
if (phoneCodeForm) {
  phoneCodeForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(phoneCodeForm);
    setFormFeedback(phoneCodeForm, "");
    const result = await runOpenDAction(phoneCodeForm.querySelector("button"), "/api/opend/verify-code", {
      kind: "phone",
      code: String(formData.get("code") || ""),
    });
    setFormFeedback(phoneCodeForm, result.message, result.ok ? "success" : "error");
    phoneCodeForm.reset();
  });
}

const captchaCodeForm = document.getElementById("opend-captcha-code-form");
if (captchaCodeForm) {
  captchaCodeForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(captchaCodeForm);
    setFormFeedback(captchaCodeForm, "");
    const result = await runOpenDAction(captchaCodeForm.querySelector("button"), "/api/opend/verify-code", {
      kind: "captcha",
      code: String(formData.get("code") || ""),
    });
    setFormFeedback(captchaCodeForm, result.message, result.ok ? "success" : "error");
    captchaCodeForm.reset();
  });
}

async function runOpenDAction(button, url, payload = undefined) {
  setButtonLoading(button, true);
  try {
    const result = await postJson(url, payload);
    renderOpenDStatus(result);
    showToast(result.message || "OpenD 操作已完成", result.ok === false ? "error" : "success");
    return result;
  } catch (error) {
    showToast(error.message, "error");
    return {ok: false, message: error.message};
  } finally {
    setButtonLoading(button, false);
  }
}

function renderOpenDStatus(payload) {
  const message = document.getElementById("opend-message");
  const status = document.getElementById("opend-status");
  if (message) message.textContent = payload.message || "";
  if (!status) return;
  const socketConnected = payload.socket_health && payload.socket_health.connected;
  status.innerHTML = `
    <dl class="metric-grid">
      <div><dt>安装状态</dt><dd>${payload.installed ? "已安装" : "未安装"}</dd></div>
      <div><dt>服务状态</dt><dd>${escapeHtml(payload.service_active || "unknown")}</dd></div>
      <div><dt>API 端口</dt><dd>${payload.api_port_open ? "开放" : "关闭"}</dd></div>
      <div><dt>Telnet 端口</dt><dd>${payload.telnet_port_open ? "开放" : "关闭"}</dd></div>
      <div><dt>登录配置</dt><dd>${payload.credentials_configured ? "已配置" : "未配置"}</dd></div>
      <div><dt>后端连接</dt><dd>${socketConnected ? "已连接" : "未连接"}</dd></div>
      <div><dt>验证码状态</dt><dd>${payload.needs_phone_code ? "需要手机验证码" : (payload.needs_captcha_code ? "需要图形验证码" : "暂无提示")}</dd></div>
    </dl>
    <pre class="log-box">${escapeHtml(payload.telnet_reply || payload.recent_log || "诊断日志按需读取，避免阻塞页面加载。")}</pre>
  `;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

document.addEventListener("click", (event) => {
  document.querySelectorAll(".action-menu[open]").forEach((menu) => {
    if (!menu.contains(event.target)) menu.removeAttribute("open");
  });
});

const workbenchRoot = document.querySelector("[data-workbench]");
if (workbenchRoot) {
  initializeWorkbench(workbenchRoot);
}

async function initializeWorkbench(root) {
  const symbol = root.dataset.symbol;
  const endpoints = ["frames", "state", "events", "signals", "debug"];
  const model = {symbol, payloads: {}, replayIndex: null, replayTimer: null};

  bindWorkbenchFilters(root);
  bindInspectorTabs(root);
  bindReplayControls(root, model);
  root.querySelector("[data-workbench-refresh]")?.addEventListener("click", (event) => {
    loadWorkbench(root, model, endpoints, event.currentTarget);
  });
  const auxiliary = root.querySelector(".auxiliary-frame");
  auxiliary?.addEventListener("toggle", () => {
    if (auxiliary.open && model.payloads.frames) renderWorkbenchCharts(root, model);
  });
  window.addEventListener("resize", debounce(() => {
    if (model.payloads.frames) renderWorkbenchCharts(root, model);
  }, 120));

  await loadWorkbench(root, model, endpoints);
}

async function loadWorkbench(root, model, endpoints, button = null) {
  setButtonLoading(button, true);
  root.querySelector("[data-workbench-data-state]").textContent = "正在读取";
  try {
    const results = await Promise.all(
      endpoints.map((endpoint) => getJson(`/api/workbench/${model.symbol}/${endpoint}`))
    );
    endpoints.forEach((endpoint, index) => {
      model.payloads[endpoint] = results[index];
    });
    model.replayIndex = null;
    renderWorkbenchCharts(root, model);
    renderWorkbenchInspector(root, model);
    root.querySelector("[data-workbench-data-state]").textContent =
      model.payloads.state.data.ok ? "核心数据正常" : "核心数据异常";
    root.querySelector("[data-workbench-data-state]").className =
      `state ${model.payloads.state.data.ok ? "state-success" : "state-danger"}`;
    if (button) showToast("工作台已刷新", "success");
  } catch (error) {
    root.querySelector("[data-workbench-data-state]").textContent = "读取失败";
    root.querySelectorAll("[data-inspector-panel]").forEach((panel) => {
      panel.innerHTML = `<div class="empty"><strong>工作台读取失败</strong><span>${escapeHtml(error.message)}</span></div>`;
    });
    showToast(error.message, "error");
  } finally {
    setButtonLoading(button, false);
  }
}

function bindWorkbenchFilters(root) {
  const filter = root.querySelector("[data-workbench-filter]");
  if (!filter) return;
  filter.addEventListener("change", () => {
    let visibleCount = 0;
    root.querySelectorAll(".watchlist-item").forEach((item) => {
      const matches = filter.value === "all"
        || (filter.value === "DATA_ANOMALY" && item.dataset.dataOk === "false")
        || item.dataset.state === filter.value;
      item.hidden = !matches;
      if (matches) visibleCount += 1;
    });
    const empty = root.querySelector("[data-watchlist-empty]");
    if (empty) empty.hidden = visibleCount > 0;
  });
}

function bindInspectorTabs(root) {
  root.querySelectorAll("[data-inspector-tab]").forEach((tab) => {
    tab.addEventListener("click", () => {
      root.querySelectorAll("[data-inspector-tab]").forEach((candidate) => {
        candidate.setAttribute("aria-selected", String(candidate === tab));
      });
      root.querySelectorAll("[data-inspector-panel]").forEach((panel) => {
        panel.hidden = panel.dataset.inspectorPanel !== tab.dataset.inspectorTab;
      });
      root.querySelector(`[data-inspector-panel="${tab.dataset.inspectorTab}"]`)?.focus();
    });
  });
}

function renderWorkbenchCharts(root, model) {
  const frameMap = model.payloads.frames.frames;
  root.querySelectorAll("[data-timeframe]").forEach((container) => {
    const frame = frameMap[container.dataset.timeframe];
    const canvas = container.querySelector("[data-kline-canvas]");
    const empty = container.querySelector("[data-chart-empty]");
    const status = container.querySelector("[data-chart-status]");
    const summary = container.querySelector("[data-chart-summary]");
    if (!frame || !frame.available) {
      canvas.hidden = true;
      empty.hidden = false;
      empty.textContent = container.dataset.timeframe === "5m"
        ? "暂无 5 分钟行情。该周期仅用于辅助观察，不阻塞日线、60 分钟和 15 分钟决策链路。"
        : "当前周期暂无行情，请先更新市场数据并计算指标。";
      status.textContent = "暂无数据";
      status.className = "state state-warning";
      summary.textContent = "0 根 K 线";
      return;
    }
    canvas.hidden = false;
    empty.hidden = true;
    const visibleFrame = replayFrame(frame, model);
    drawKlineChart(canvas, visibleFrame);
    status.textContent = frame.data_ok ? "数据正常" : "存在异常";
    status.className = `state ${frame.data_ok ? "state-success" : "state-danger"}`;
    const last = visibleFrame.bars.at(-1);
    summary.textContent = `${visibleFrame.bars.length} 根 · 最新 ${formatChartTime(last?.ts)} · 收盘 ${formatNumber(last?.close)}`;
  });
  updateReplaySummary(root, model);
}

function replayFrame(frame, model) {
  if (model.replayIndex === null) return frame;
  const anchorCount = Math.max(model.payloads.frames.frames["15m"].bars.length, 1);
  const ratio = Math.min(1, (model.replayIndex + 1) / anchorCount);
  const count = Math.max(1, Math.ceil(frame.bars.length * ratio));
  const bars = frame.bars.slice(0, count);
  const lastTs = bars.at(-1)?.ts || "";
  return {
    ...frame,
    bars,
    events: frame.events.filter((event) => event.ts <= lastTs),
    signals: frame.signals.filter((signal) => signal.ts <= lastTs),
  };
}

function drawKlineChart(canvas, frame) {
  const bounds = canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.max(1, Math.floor(bounds.width * dpr));
  canvas.height = Math.max(1, Math.floor(bounds.height * dpr));
  const context = canvas.getContext("2d");
  context.scale(dpr, dpr);
  const width = bounds.width;
  const height = bounds.height;
  const styles = getComputedStyle(document.documentElement);
  const colors = {
    surface: styles.getPropertyValue("--color-surface").trim(),
    grid: styles.getPropertyValue("--color-border").trim(),
    text: styles.getPropertyValue("--color-text-muted").trim(),
    primary: styles.getPropertyValue("--color-primary").trim(),
    success: styles.getPropertyValue("--color-success").trim(),
    warning: styles.getPropertyValue("--color-warning").trim(),
    danger: styles.getPropertyValue("--color-danger").trim(),
    muted: styles.getPropertyValue("--color-text-secondary").trim(),
  };
  context.fillStyle = colors.surface;
  context.fillRect(0, 0, width, height);
  if (!frame.bars.length) return;

  const margin = {top: 16, right: 48, bottom: 20, left: 8};
  const priceBottom = Math.floor(height * 0.72);
  const priceValues = frame.bars.flatMap((bar) => [bar.high, bar.low, bar.ma20, bar.ma60]).filter(isFiniteNumber);
  frame.levels.forEach((level) => priceValues.push(level.price));
  const minimum = Math.min(...priceValues);
  const maximum = Math.max(...priceValues);
  const padding = Math.max((maximum - minimum) * 0.08, maximum * 0.002, 0.01);
  const low = minimum - padding;
  const high = maximum + padding;
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = priceBottom - margin.top;
  const step = plotWidth / Math.max(frame.bars.length, 1);
  const xFor = (index) => margin.left + step * index + step / 2;
  const yFor = (price) => margin.top + ((high - price) / Math.max(high - low, 0.0001)) * plotHeight;

  context.strokeStyle = colors.grid;
  context.fillStyle = colors.text;
  context.font = "11px -apple-system, BlinkMacSystemFont, sans-serif";
  context.lineWidth = 1;
  for (let index = 0; index <= 4; index += 1) {
    const y = margin.top + (plotHeight / 4) * index;
    context.beginPath();
    context.moveTo(margin.left, y);
    context.lineTo(width - margin.right, y);
    context.stroke();
    const value = high - ((high - low) / 4) * index;
    context.fillText(formatNumber(value), width - margin.right + 6, y + 4);
  }

  const candleWidth = Math.max(2, Math.min(8, step * 0.62));
  frame.bars.forEach((bar, index) => {
    const x = xFor(index);
    const rising = bar.close >= bar.open;
    context.strokeStyle = rising ? colors.success : colors.danger;
    context.fillStyle = rising ? colors.success : colors.danger;
    context.beginPath();
    context.moveTo(x, yFor(bar.high));
    context.lineTo(x, yFor(bar.low));
    context.stroke();
    const top = yFor(Math.max(bar.open, bar.close));
    const bottom = yFor(Math.min(bar.open, bar.close));
    context.fillRect(x - candleWidth / 2, top, candleWidth, Math.max(1, bottom - top));
  });

  drawSeries(context, frame.bars, "ma20", xFor, yFor, colors.primary);
  drawSeries(context, frame.bars, "ma60", xFor, yFor, colors.warning);
  drawMacd(context, frame.bars, xFor, priceBottom + 12, height - margin.bottom, colors);

  frame.levels.forEach((level) => {
    context.save();
    context.setLineDash(level.kind === "stop" || level.kind === "trail" ? [5, 4] : [2, 3]);
    context.strokeStyle = level.kind === "entry" ? colors.primary : colors.danger;
    context.beginPath();
    context.moveTo(margin.left, yFor(level.price));
    context.lineTo(width - margin.right, yFor(level.price));
    context.stroke();
    context.fillStyle = context.strokeStyle;
    context.fillText(level.label, margin.left + 4, yFor(level.price) - 4);
    context.restore();
  });

  drawMarkers(context, frame.bars, frame.events, xFor, yFor, colors.success, "structure");
  drawMarkers(context, frame.bars, frame.signals, xFor, yFor, colors.danger, "signal");
}

function drawSeries(context, bars, key, xFor, yFor, color) {
  context.beginPath();
  context.strokeStyle = color;
  context.lineWidth = 1.5;
  let started = false;
  bars.forEach((bar, index) => {
    if (!isFiniteNumber(bar[key])) return;
    const x = xFor(index);
    const y = yFor(bar[key]);
    if (!started) context.moveTo(x, y);
    else context.lineTo(x, y);
    started = true;
  });
  if (started) context.stroke();
}

function drawMacd(context, bars, xFor, top, bottom, colors) {
  const values = bars.map((bar) => bar.macd_hist).filter(isFiniteNumber);
  if (!values.length) return;
  const amplitude = Math.max(...values.map(Math.abs), 0.0001);
  const middle = (top + bottom) / 2;
  context.strokeStyle = colors.grid;
  context.beginPath();
  context.moveTo(8, middle);
  context.lineTo(context.canvas.clientWidth - 48, middle);
  context.stroke();
  bars.forEach((bar, index) => {
    if (!isFiniteNumber(bar.macd_hist)) return;
    const barHeight = (Math.abs(bar.macd_hist) / amplitude) * ((bottom - top) / 2);
    context.fillStyle = bar.macd_hist >= 0 ? colors.success : colors.danger;
    context.fillRect(xFor(index) - 1, bar.macd_hist >= 0 ? middle - barHeight : middle, 2, Math.max(1, barHeight));
  });
  context.fillStyle = colors.text;
  context.fillText("MACD", 10, top + 10);
}

function drawMarkers(context, bars, markers, xFor, yFor, color, kind) {
  markers.forEach((marker) => {
    if (!isFiniteNumber(marker.price)) return;
    const index = nearestBarIndex(bars, marker.ts);
    if (index < 0) return;
    const x = xFor(index);
    const y = yFor(marker.price);
    context.fillStyle = color;
    context.beginPath();
    if (kind === "signal") {
      context.rect(x - 4, y - 4, 8, 8);
    } else {
      context.moveTo(x, y - 6);
      context.lineTo(x + 6, y + 5);
      context.lineTo(x - 6, y + 5);
      context.closePath();
    }
    context.fill();
  });
}

function nearestBarIndex(bars, timestamp) {
  const target = new Date(timestamp).getTime();
  let bestIndex = -1;
  let bestDistance = Number.POSITIVE_INFINITY;
  bars.forEach((bar, index) => {
    const distance = Math.abs(new Date(bar.ts).getTime() - target);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  });
  return bestIndex;
}

function renderWorkbenchInspector(root, model) {
  const state = model.payloads.state;
  const events = model.payloads.events.events;
  const signals = model.payloads.signals.signals;
  setInspectorHtml(root, "state", `
    <div class="inspector-section">
      <h2>当前决策状态</h2>
      <dl class="inspector-list">
        ${inspectorRow("市场环境", state.market.label, state.market.reason)}
        ${inspectorRow("个股趋势", state.trend.label, state.trend.reason)}
        ${inspectorRow("交易状态", state.trading_state.label, state.trading_state.reason)}
        ${inspectorRow("下一步等待", state.next_wait)}
        ${inspectorRow("数据质量", state.data.ok ? "核心数据正常" : "核心数据异常", state.data.reason)}
        ${inspectorRow("冷却期", state.cooldown_until || "当前不在冷却期")}
      </dl>
    </div>
    <div class="inspector-section">
      <h2>市场过滤明细</h2>
      ${state.market_checks.map((check) => `
        <article class="inspector-event">
          <strong>${escapeHtml(check.symbol)} · ${check.passed ? "通过" : (check.ready ? "未通过" : "数据不足")}</strong>
          <small>${escapeHtml(check.reason || "等待市场诊断")}</small>
        </article>
      `).join("") || emptyInspector("暂无市场过滤明细")}
    </div>
  `);
  setInspectorHtml(root, "events", `
    <div class="inspector-section">
      <h2>结构事件</h2>
      ${events.map((event) => `
        <article class="inspector-event">
          <strong>${escapeHtml(event.timeframe_label)} · ${escapeHtml(event.label)}</strong>
          <small>${formatChartTime(event.ts)} · ${formatNumber(event.price)}</small>
          <span>${escapeHtml(event.reason)}</span>
        </article>
      `).join("") || emptyInspector("暂无结构事件")}
    </div>
  `);
  setInspectorHtml(root, "playbook", state.playbooks.map((playbook) => `
    <div class="inspector-section">
      <h2>${escapeHtml(playbook.name)}</h2>
      <span class="state ${playbook.active ? "state-success" : ""}">${playbook.active ? "当前剧本" : "尚未激活"}</span>
      <ul class="condition-list">
        ${playbook.conditions.map((condition) => `
          <li class="${condition.passed ? "passed" : "failed"}">${escapeHtml(condition.label)}</li>
        `).join("")}
      </ul>
    </div>
  `).join(""));
  const risk = state.pending_signal || state.position;
  setInspectorHtml(root, "risk", `
    <div class="inspector-section">
      <h2>${state.pending_signal ? "待审批建议风控" : (state.position ? "当前持仓风控" : "暂无活动风险单元")}</h2>
      ${risk ? `<dl class="inspector-list">
        ${inspectorRow("入场 / 成本", formatNumber(risk.entry_price))}
        ${inspectorRow("初始止损", formatNumber(risk.stop_price))}
        ${inspectorRow("滑动止盈", formatNumber(risk.trailing_stop))}
        ${inspectorRow("建议 / 持仓股数", risk.shares ? `${risk.shares} 股` : "-")}
        ${inspectorRow("风险金额", risk.risk_amount ? `$${formatNumber(risk.risk_amount)}` : "-")}
        ${inspectorRow("当前 R", isFiniteNumber(risk.current_r) ? `${risk.current_r.toFixed(2)}R` : (isFiniteNumber(risk.risk_r) ? `${risk.risk_r.toFixed(2)}R` : "-"))}
      </dl>` : emptyInspector("状态机尚未生成带止损的入场建议，也没有模拟持仓。")}
    </div>
    <div class="inspector-section">
      <h2>交易建议历史</h2>
      ${signals.slice(0, 8).map((signal) => `
        <article class="inspector-event">
          <strong>${escapeHtml(signal.type_label)} · ${escapeHtml(signal.status_label)}</strong>
          <small>${formatChartTime(signal.created_at)} · ${escapeHtml(signal.trigger_timeframe_label)}</small>
          <span>${escapeHtml(signal.reason)}</span>
        </article>
      `).join("") || emptyInspector("暂无交易建议")}
    </div>
  `);
  setInspectorHtml(root, "debug", `<pre class="debug-json">${escapeHtml(JSON.stringify(model.payloads.debug, null, 2))}</pre>`);
}

function setInspectorHtml(root, key, html) {
  const panel = root.querySelector(`[data-inspector-panel="${key}"]`);
  if (panel) panel.innerHTML = html;
}

function inspectorRow(label, value, detail = "") {
  return `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value ?? "-")}${detail ? `<small>${escapeHtml(detail)}</small>` : ""}</dd></div>`;
}

function emptyInspector(message) {
  return `<div class="empty compact-note"><span>${escapeHtml(message)}</span></div>`;
}

function bindReplayControls(root, model) {
  const toggle = root.querySelector("[data-replay-toggle]");
  const step = root.querySelector("[data-replay-step]");
  const reset = root.querySelector("[data-replay-reset]");
  const speed = root.querySelector("[data-replay-speed]");
  const exportButton = root.querySelector("[data-export-frame]");
  toggle?.addEventListener("click", () => {
    if (model.replayTimer) {
      stopReplay(model, toggle);
      return;
    }
    if (model.replayIndex === null) model.replayIndex = Math.min(19, replayLength(model) - 1);
    toggle.textContent = "暂停回放";
    model.replayTimer = window.setInterval(() => {
      if (!advanceReplay(root, model)) stopReplay(model, toggle);
    }, Number(speed?.value || 700));
  });
  step?.addEventListener("click", () => {
    stopReplay(model, toggle);
    if (model.replayIndex === null) model.replayIndex = Math.min(19, replayLength(model) - 1);
    else advanceReplay(root, model);
    renderWorkbenchCharts(root, model);
  });
  reset?.addEventListener("click", () => {
    stopReplay(model, toggle);
    model.replayIndex = null;
    renderWorkbenchCharts(root, model);
  });
  speed?.addEventListener("change", () => {
    if (!model.replayTimer) return;
    stopReplay(model, toggle);
    toggle.click();
  });
  exportButton?.addEventListener("click", () => exportReplayFrame(model));
}

function advanceReplay(root, model) {
  if (model.replayIndex >= replayLength(model) - 1) return false;
  model.replayIndex += 1;
  renderWorkbenchCharts(root, model);
  return true;
}

function stopReplay(model, button) {
  window.clearInterval(model.replayTimer);
  model.replayTimer = null;
  if (button) button.textContent = "开始回放";
}

function replayLength(model) {
  return model.payloads.frames?.frames?.["15m"]?.bars?.length || 0;
}

function updateReplaySummary(root, model) {
  const anchor = model.payloads.frames.frames["15m"];
  const index = model.replayIndex === null ? anchor.bars.length - 1 : model.replayIndex;
  const current = anchor.bars[index];
  const status = model.replayIndex === null ? "完整窗口" : `第 ${index + 1} / ${anchor.bars.length} 根`;
  const time = current ? formatChartTime(current.ts) : "暂无 15 分钟行情";
  const label = root.querySelector("[data-replay-time]");
  if (label) label.textContent = `${status} · ${time}`;
  const summary = root.querySelector("[data-replay-summary]");
  if (summary) {
    summary.innerHTML = `
      ${inspectorRow("回放状态", model.replayTimer ? "自动播放中" : (model.replayIndex === null ? "完整窗口" : "已暂停"))}
      ${inspectorRow("当前时间", time)}
      ${inspectorRow("可见窗口", status)}
      ${inspectorRow("说明", "回放只调整可见数据，不重新计算或改写交易状态。")}
    `;
  }
}

function exportReplayFrame(model) {
  if (!model.payloads.frames) return;
  const payload = {
    symbol: model.symbol,
    replay_index: model.replayIndex,
    frames: Object.fromEntries(
      Object.entries(model.payloads.frames.frames).map(([key, frame]) => [key, replayFrame(frame, model)])
    ),
    state: model.payloads.state,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], {type: "application/json"});
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${model.symbol}-workbench-frame.json`;
  link.click();
  URL.revokeObjectURL(link.href);
  showToast("当前回放帧已导出", "success");
}

function formatChartTime(value) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatNumber(value) {
  return isFiniteNumber(value) ? Number(value).toFixed(2) : "-";
}

function isFiniteNumber(value) {
  return value !== null && value !== undefined && Number.isFinite(Number(value));
}

function debounce(callback, delay) {
  let timer;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => callback(...args), delay);
  };
}
