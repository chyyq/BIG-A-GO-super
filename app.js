const DATA_URL = "data/latest.json";
const STORAGE_KEY = "a-share-maintrend-trades-v1";
const PUBLIC_SITE_URL = "https://chyyq.github.io/BIG-A-GO-super/";
const SYNC_CODE_RAW_PREFIX = "BAGS3B.";
const SYNC_CODE_GZIP_PREFIX = "BAGS3G.";
const STRATEGY_TAIL_MAIN = "TAIL_MAIN";
const STRATEGY_AM_TOP = "AM_TOP";
const AUTO_REFRESH_WINDOWS = [
  { start: [9, 25], end: [10, 5] },
  { start: [13, 30], end: [14, 40] },
  { start: [19, 58], end: [20, 10] },
];

const state = {
  data: null,
  trades: [],
  liveQuotes: new Map(),
  historyQuotes: new Map(),
  isRefreshing: false,
  lastAutoRefreshAt: 0,
  syncPayload: null,
  syncImportMode: "merge",
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

document.addEventListener("DOMContentLoaded", async () => {
  bindEvents();
  loadTrades();
  await loadData();
  await refreshPositionQuotes();
  render();
  scheduleNightlyReviewRefresh();
  startAutoRefreshPolling();
  refreshIcons();
});

function bindEvents() {
  $("#refreshButton").addEventListener("click", refreshLatestData);
  $("#notifyButton").addEventListener("click", requestNotifications);
  $("#openTradeButton").addEventListener("click", () => openTradeModal());
  $("#closeTradeModal").addEventListener("click", closeTradeModal);
  $("#cancelTrade").addEventListener("click", closeTradeModal);
  $("#tradeModal").addEventListener("click", (event) => {
    if (event.target.id === "tradeModal") closeTradeModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("#tradeModal").hidden) closeTradeModal();
    if (event.key === "Escape" && !$("#syncModal").hidden) closeSyncModal();
  });
  $("#tradeForm").addEventListener("submit", saveTradeFromForm);
  $("#reviewRefreshButton")?.addEventListener("click", refreshReviewNow);
  $("#exportTradesButton")?.addEventListener("click", exportTradesForSync);
  $("#importTradesButton")?.addEventListener("click", importTradesFromSync);
  $("#closeSyncModal")?.addEventListener("click", closeSyncModal);
  $("#cancelSync")?.addEventListener("click", closeSyncModal);
  $("#syncModal")?.addEventListener("click", (event) => {
    if (event.target.id === "syncModal") closeSyncModal();
  });
  $("#pasteSyncCodeButton")?.addEventListener("click", pasteSyncCode);
  $("#copySyncCodeButton")?.addEventListener("click", copySyncCode);
  $("#shareSyncCodeButton")?.addEventListener("click", shareSyncCode);
  $("#downloadSyncFileButton")?.addEventListener("click", downloadSyncFile);
  $("#selectSyncFileButton")?.addEventListener("click", () => $("#syncFileInput").click());
  $("#syncFileInput")?.addEventListener("change", loadSyncFile);
  $("#applySyncCodeButton")?.addEventListener("click", applySyncImport);
  $("#syncCodeInput")?.addEventListener("input", () => setSyncStatus(""));
  $$("[data-sync-import-mode]").forEach((button) => {
    button.addEventListener("click", () => setSyncImportMode(button.dataset.syncImportMode));
  });
  $("#rulesToggle").addEventListener("click", toggleRules);
  $$(".segment").forEach((button) => {
    button.addEventListener("click", () => switchRecommendationView(button.dataset.view));
  });
}

async function refreshLatestData(options = {}) {
  const silent = Boolean(options.silent);
  if (state.isRefreshing) return;
  state.isRefreshing = true;
  const button = $("#refreshButton");
  const hint = $("#refreshHint");
  const previousGeneratedAt = state.data?.meta?.generatedAt || null;
  if (!silent) {
    button.disabled = true;
    hint.textContent = "正在读取 GitHub Pages 上最新的 data/latest.json，不会影响本地买入记录。";
  }

  await loadData();
  state.liveQuotes.clear();
  await refreshPositionQuotes();
  render();

  const nextGeneratedAt = state.data?.meta?.generatedAt || null;
  const checkedAt = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  if (!silent) {
    hint.textContent =
      nextGeneratedAt && nextGeneratedAt !== previousGeneratedAt
        ? `已读取到新数据，检查时间 ${checkedAt}。`
        : `已检查最新文件，检查时间 ${checkedAt}。如果“数据生成时间”没变，说明 GitHub Actions 还没有生成新数据。`;
    button.disabled = false;
  } else if (nextGeneratedAt && nextGeneratedAt !== previousGeneratedAt) {
    hint.textContent = `自动刷新到新数据，检查时间 ${checkedAt}。`;
  }
  state.isRefreshing = false;
  refreshIcons();
}

async function refreshReviewNow() {
  await refreshLatestData();
}

function scheduleNightlyReviewRefresh() {
  const now = new Date();
  const target = new Date();
  target.setHours(20, 0, 0, 0);
  if (target <= now) target.setDate(target.getDate() + 1);
  window.setTimeout(async () => {
    await refreshLatestData();
    scheduleNightlyReviewRefresh();
  }, target.getTime() - now.getTime());
}

function startAutoRefreshPolling() {
  window.setInterval(() => {
    if (document.hidden || state.isRefreshing) return;
    if (!isAutoRefreshWindow(new Date())) return;
    if (Date.now() - state.lastAutoRefreshAt < 60_000) return;
    state.lastAutoRefreshAt = Date.now();
    refreshLatestData({ silent: true });
  }, 30_000);
}

function isAutoRefreshWindow(date) {
  const minute = date.getHours() * 60 + date.getMinutes();
  return AUTO_REFRESH_WINDOWS.some(({ start, end }) => {
    const startMinute = start[0] * 60 + start[1];
    const endMinute = end[0] * 60 + end[1];
    return minute >= startMinute && minute <= endMinute;
  });
}

async function loadData() {
  try {
    const response = await fetch(`${DATA_URL}?ts=${Date.now()}`, {
      cache: "no-store",
      headers: { "Cache-Control": "no-cache" },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.data = await response.json();
  } catch (error) {
    state.data = fallbackData(error);
  }
}

function fallbackData(error) {
  return {
    meta: {
      generatedAt: null,
      mode: "本地预览",
      errors: [`无法读取 data/latest.json：${error.message}`],
      sourceHealth: [],
    },
    market: { recommendationCount: 0, qualifiedBoardCount: 0 },
    boards: [],
    recommendations: [],
    news: [],
  };
}

function render() {
  renderStatus();
  renderRecommendations();
  renderRecommendationTable();
  renderSectors();
  renderT1Reviews();
  renderNews();
  renderSources();
  refreshIcons();
}

function renderStatus() {
  const meta = state.data?.meta || {};
  const generatedAt = meta.generatedAt ? new Date(meta.generatedAt) : null;
  const dataIssue = getRecommendationDataIssue();
  $("#updatedAt").textContent = generatedAt
    ? generatedAt.toLocaleString("zh-CN", { hour12: false })
    : "--";
  $("#updateMode").textContent = meta.mode || "等待数据";
  $("#recommendationCount").textContent = dataIssue
    ? 0
    : (state.data?.recommendations || []).filter((item) => item.actionable !== false).length;
  $("#sourceCount").textContent = (meta.sourceHealth || []).filter((source) => source.ok).length;
  $("#alertCount").textContent = getPositionAlerts().length;
}

function renderRecommendations() {
  const root = $("#recommendationCards");
  const recommendations = state.data?.recommendations || [];
  const dataIssue = getRecommendationDataIssue();
  if (dataIssue) {
    root.innerHTML = `
      <div class="empty-state">
        <strong>${escapeHtml(dataIssue.title)}</strong>
        <p>${escapeHtml(dataIssue.detail)}</p>
      </div>
    `;
    return;
  }
  if (!recommendations.length) {
    const emptyCopy = getNoRecommendationCopy();
    root.innerHTML = `
      <div class="empty-state">
        <strong>${escapeHtml(emptyCopy.title)}</strong>
        <p>${escapeHtml(emptyCopy.detail)}</p>
      </div>
    `;
    return;
  }

  root.innerHTML = recommendations.map(renderRecommendationCard).join("");
  root.querySelectorAll("[data-action='buy']").forEach((button) => {
    button.addEventListener("click", () => {
      const recommendation = recommendations.find((item) => item.code === button.dataset.code);
      recordRecommendationBuy(recommendation);
    });
  });
}

function getRecommendationDataIssue() {
  const meta = state.data?.meta || {};
  if (["cached-fallback", "no-current-data"].includes(meta.mode)) {
    return {
      title: "行情数据未成功更新，暂不能判断空仓。",
      detail: "当前内容来自历史缓存或数据源失败，请以数据生成时间和下一次 GitHub Actions 结果为准。",
    };
  }
  const snapshotDate = meta.tradingDate || dateKey(meta.generatedAt ? new Date(meta.generatedAt) : null);
  const today = dateKey(new Date());
  if (snapshotDate && today && snapshotDate !== today) {
    return {
      title: "当前不是今天的行情快照，暂不能判断空仓。",
      detail: `快照日期为 ${snapshotDate}，今天为 ${today}；请等待自动任务生成新数据或检查 GitHub Actions。`,
    };
  }
  return null;
}

function getNoRecommendationCopy() {
  const meta = state.data?.meta || {};
  const monitor = state.data?.market?.monitor || {};
  const reason = meta.noRecommendationReason || (monitor.riskLevel === "RISK_OFF" ? "MARKET_RISK_OFF" : null);
  if (reason === "MARKET_RISK_OFF") {
    const limitDown = Number.isFinite(Number(monitor.limitDownCount)) ? `跌停 ${monitor.limitDownCount} 只` : "极端下跌数量偏高";
    const bigDown = Number.isFinite(Number(monitor.bigDownCount)) ? `、大跌 ${monitor.bigDownCount} 只` : "";
    return {
      title: "大盘风控触发，今日按纪律空仓。",
      detail: `${limitDown}${bigDown}，市场处于 RISK_OFF；系统未进入个股推荐阶段。`,
    };
  }
  if (reason === "OUTSIDE_STRATEGY_WINDOW") {
    return {
      title: "当前快照不是买入推荐时段。",
      detail: "晚间更新用于持仓复盘，不代表早盘或尾盘盘中没有出现过候选。",
    };
  }
  return {
    title: "当前时段暂无严格达标推荐。",
    detail: "市场风控未熔断，但没有股票同时通过板块、个股、形态、拥挤度和执行容错 Gate。",
  };
}

function dateKey(date) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return null;
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function renderRecommendationCard(item, index) {
  const rank = item.rank || index + 1;
  const criteria = [...(item.criteria?.board || []), ...(item.criteria?.stock || [])].slice(0, 10);
  const links = item.sourceLinks || [];
  const targetPrice = item.sellPlan?.targetPrice ?? item.sellPlan?.takeProfit;
  const targetTime = item.sellPlan?.targetTime ?? item.sellPlan?.timeWindow ?? "--";
  const stopLoss = item.stopPlan?.stopLoss ?? item.sellPlan?.stopLoss;
  const recorded = isOpenTradeRecorded(item.code);
  const queueOnly = item.executionMode === "QUEUE_ONLY";
  const watchOnly = item.actionable === false || item.executionMode === "WATCH_ONLY" || queueOnly;
  const watchLabel = queueOnly ? "已封板，排队观察" : "早盘策略暂停实盘，仅观察";
  const watchAction = queueOnly ? "封板中，暂不可买" : "暂停实盘，仅观察";

  return `
    <article class="recommendation-card">
      <div class="card-top">
        <div class="rank-badge">#${rank}</div>
        <div>
          <h3 class="stock-name">${escapeHtml(item.name)} <span class="stock-code">${item.code}</span></h3>
          ${watchOnly ? `<span class="tag warn">${watchLabel}</span>` : ""}
          <div class="stock-code">${escapeHtml(item.board?.name || "未分组")} · ${formatPct(item.pct)} · 换手 ${formatPct(item.turnover, false)}</div>
        </div>
        <span class="score-pill">策略分 ${Math.round(item.finalScore || item.winRate || item.confidence || 0)}</span>
      </div>
      <div class="card-body">
        <div>
          <div class="plan-grid plan-grid-four">
            <div class="plan-box">
              <span>买点</span>
              <strong>${escapeHtml(item.buyPlan?.type || "--")}</strong>
              <div class="stock-code">${escapeHtml(item.buyPlan?.timeWindow || "--")}</div>
            </div>
            <div class="plan-box">
              <span>买入区间</span>
              <strong>${formatRange(item.buyPlan?.priceRange)}</strong>
              <div class="stock-code">${escapeHtml(item.buyPlan?.trigger || "")}</div>
            </div>
            <div class="plan-box">
              <span>预估峰值</span>
              <strong>${formatPrice(targetPrice)}</strong>
              <div class="stock-code">${escapeHtml(targetTime)}</div>
            </div>
            <div class="plan-box stop-box">
              <span>止损价</span>
              <strong>${formatPrice(stopLoss)}</strong>
              <div class="stock-code">分时/结构触发即走</div>
            </div>
          </div>
          <div class="criteria-list">
            ${criteria.map((criterion) => `<span class="tag pass">${escapeHtml(criterion)}</span>`).join("")}
          </div>
          <div class="source-links">
            ${links.map((link) => `<a class="tag" href="${link.url}" target="_blank" rel="noopener">${escapeHtml(link.name)}</a>`).join("")}
          </div>
        </div>
      </div>
      <div class="card-actions">
        <button class="ghost-button" type="button" data-action="buy" data-code="${item.code}" ${recorded || watchOnly ? "disabled" : ""}>
          <i data-lucide="${recorded ? "check" : queueOnly ? "clock-3" : watchOnly ? "eye" : "square-pen"}"></i>
          ${recorded ? "已记录" : watchOnly ? watchAction : "一键记录买入"}
        </button>
      </div>
    </article>
  `;
}

function renderRecommendationTable() {
  const rows = state.data?.recommendations || [];
  const body = $("#recommendationTable");
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="8" class="table-empty">暂无严格达标推荐</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map((item, index) => {
      const targetPrice = item.sellPlan?.targetPrice ?? item.sellPlan?.takeProfit;
      const targetTime = item.sellPlan?.targetTime ?? item.sellPlan?.timeWindow ?? "--";
      const stopLoss = item.stopPlan?.stopLoss ?? item.sellPlan?.stopLoss;
      return `
        <tr>
          <td class="col-rank">#${item.rank || index + 1}</td>
          <td class="col-stock"><strong>${escapeHtml(item.name)}</strong><span>${item.code}</span></td>
          <td class="col-score">${Math.round(item.finalScore || item.winRate || item.confidence || 0)}</td>
          <td class="col-plan">${escapeHtml(item.buyPlan?.type || "--")}${item.actionable === false ? `<span class="tag warn">${item.executionMode === "QUEUE_ONLY" ? "排队观察" : "仅观察"}</span>` : ""}<span>${escapeHtml(item.buyPlan?.timeWindow || "")}</span></td>
          <td class="col-price">${formatPrice(targetPrice)}</td>
          <td class="col-time">${escapeHtml(targetTime)}</td>
          <td class="col-price">${formatPrice(stopLoss)}</td>
          <td class="col-board">${escapeHtml(item.board?.name || "--")}</td>
        </tr>
      `;
    })
    .join("");
}

function recordRecommendationBuy(recommendation) {
  if (!recommendation || recommendation.actionable === false || recommendation.executionMode === "WATCH_ONLY") return;
  const targetPrice = recommendation.sellPlan?.targetPrice ?? recommendation.sellPlan?.takeProfit;
  const stopLoss = recommendation.stopPlan?.stopLoss ?? recommendation.sellPlan?.stopLoss;
  const buyPrice = estimateRecordedBuyPrice(recommendation);
  const now = new Date();
  const buyTradingDate = currentTradingDateKey(now);
  const existing = state.trades.find((item) => item.code === recommendation.code && !isTradeClosed(item));
  const trade = {
    id: existing?.id || createId(),
    code: recommendation.code,
    name: recommendation.name,
    buyPrice,
    quantity: null,
    stopLoss: stopLoss || round2(buyPrice * 0.96),
    takeProfit: targetPrice || round2(buyPrice * 1.03),
    note: buildRecommendationNote(recommendation),
    status: "open",
    strategyTag: recommendation.strategyTag || recommendation.buyPlan?.strategyTag || "",
    source: "one_click_recommendation",
    buyTradingDate: existing?.buyTradingDate || buyTradingDate,
    plannedSellTradingDate: existing?.plannedSellTradingDate || nextWeekdayDateKey(buyTradingDate),
    planSnapshot: {
      buyPlan: recommendation.buyPlan,
      sellPlan: recommendation.sellPlan,
      stopPlan: recommendation.stopPlan,
      board: recommendation.board,
      strategyId: recommendation.strategyId,
      candidateStatus: recommendation.candidateStatus,
      finalScore: recommendation.finalScore,
      signalType: recommendation.signalType,
      overnightCrowdingScore: recommendation.overnightCrowdingScore,
      executionToleranceScore: recommendation.executionToleranceScore,
      simpleExecutionScore: recommendation.simpleExecutionScore,
      recoveryAfter0935Score: recommendation.recoveryAfter0935Score,
      initialPlan: recommendation.initialPlan,
      nextDayPlan: recommendation.nextDayPlan,
      entryFeasibilityStatus: recommendation.entryFeasibilityStatus,
      entryFeasibilityScore: recommendation.entryFeasibilityScore,
      executionMode: recommendation.executionMode,
      actionable: recommendation.actionable,
    },
    createdAt: existing?.createdAt || now.toISOString(),
    updatedAt: now.toISOString(),
  };
  if (existing) {
    state.trades = state.trades.map((item) => (item.id === existing.id ? { ...item, ...trade } : item));
  } else {
    state.trades.unshift(trade);
  }
  persistTrades();
  refreshPositionQuotes().then(render);
}

function estimateRecordedBuyPrice(recommendation) {
  const range = recommendation?.buyPlan?.priceRange;
  if (Array.isArray(range) && range.length >= 2) return round2((Number(range[0]) + Number(range[1])) / 2);
  return round2(recommendation?.price || 0);
}

function getTradeStrategyTag(record) {
  const explicit =
    record?.strategyTag ||
    record?.planSnapshot?.buyPlan?.strategyTag ||
    record?.buyPlan?.strategyTag ||
    "";
  if (explicit === STRATEGY_AM_TOP || explicit === STRATEGY_TAIL_MAIN) return explicit;
  const evidence = `${explicit} ${record?.note || ""} ${record?.planSnapshot?.buyPlan?.type || ""}`.toUpperCase();
  if (evidence.includes("AM_TOP") || evidence.includes("早盘")) return STRATEGY_AM_TOP;
  if (evidence.includes("TAIL_MAIN") || evidence.includes("尾盘")) return STRATEGY_TAIL_MAIN;
  return "";
}

function defaultTradeStrategyTag(now = new Date()) {
  const minute = now.getHours() * 60 + now.getMinutes();
  return minute >= 9 * 60 + 20 && minute <= 10 * 60 + 5 ? STRATEGY_AM_TOP : STRATEGY_TAIL_MAIN;
}

function tradeStrategyLabel(trade) {
  const strategyTag = getTradeStrategyTag(trade);
  if (strategyTag === STRATEGY_AM_TOP) return "早盘涨停";
  if (strategyTag === STRATEGY_TAIL_MAIN) return "尾盘 T+1";
  return "策略待确认";
}

function buyDayLimitLabel(outcome) {
  if (outcome === "SEALED_AT_CLOSE") return "买入日封板";
  if (outcome === "TOUCHED_NOT_SEALED") return "买入日触板未封";
  if (outcome === "NO_LIMIT_TOUCH") return "买入日未触板";
  return "";
}

function isOpenTradeRecorded(code) {
  return state.trades.some((trade) => trade.code === code && !isTradeClosed(trade));
}

function renderSectors() {
  const root = $("#sectorList");
  const boards = state.data?.boards || [];
  if (!boards.length) {
    root.innerHTML = `<div class="empty-state">暂无板块数据。等待 GitHub Action 完成首次更新。</div>`;
    return;
  }
  root.innerHTML = boards
    .slice(0, 8)
    .map((board) => {
      const score = Math.round(board.score || 0);
      return `
        <article class="sector-item">
          <div class="sector-head">
            <div>
              <strong>${escapeHtml(board.name)}</strong>
              <div class="stock-code">${formatPct(board.pct)} · 涨停 ${board.limitUpCount || 0} · 大涨 ${board.bigUpCount || 0}</div>
            </div>
            <span class="tag ${board.qualified ? "pass" : "warn"}">${board.passed || 0}/5</span>
          </div>
          <div class="progress-track"><div class="progress-bar" style="width:${Math.min(100, score)}%"></div></div>
        </article>
      `;
    })
    .join("");
}

function renderT1Reviews() {
  const root = $("#t1ReviewList");
  const meta = $("#reviewMeta");
  if (!root || !meta) return;
  const reviewTrades = state.trades;
  const generatedAt = state.data?.meta?.generatedAt ? new Date(state.data.meta.generatedAt) : null;
  meta.textContent = generatedAt
    ? `行情快照 ${generatedAt.toLocaleString("zh-CN", { hour12: false })}；按 20:00 复盘纪律生成`
    : "等待 20:00 行情快照或手动刷新";

  if (!reviewTrades.length) {
    root.innerHTML = `<div class="empty-state">暂无已记录买入。推荐卡片点“一键记录买入”后，这里会生成明天 T+1 卖出策略。</div>`;
    return;
  }

  const now = new Date();
  const reviews = reviewTrades.map((trade) => buildT1Review(trade, now));
  if (captureOvernightReviewSnapshots(reviews, now) || reviews.some((review) => review.executionMemoryChanged)) {
    persistTrades();
  }
  root.innerHTML = reviews.map(renderT1ReviewCard).join("");
  root.querySelectorAll("[data-action='edit']").forEach((button) => {
    const trade = state.trades.find((item) => item.id === button.dataset.id);
    button.addEventListener("click", () => openTradeModal(null, trade));
  });
  root.querySelectorAll("[data-action='take-profit']").forEach((button) => {
    button.addEventListener("click", () => markTradeOutcome(button.dataset.id, "take_profit"));
  });
  root.querySelectorAll("[data-action='stop-loss']").forEach((button) => {
    button.addEventListener("click", () => markTradeOutcome(button.dataset.id, "stop_loss"));
  });
  root.querySelectorAll("[data-action='delete']").forEach((button) => {
    button.addEventListener("click", () => deleteTrade(button.dataset.id));
  });
}

function buildT1Review(trade, now = new Date()) {
  const quote = getQuoteForTrade(trade) || {};
  const closed = isTradeClosed(trade);
  const buyPrice = Number(trade.buyPrice || quote.price || 0);
  const livePrice = Number(quote.price || trade.lastPrice || buyPrice);
  const displayPrice = closed ? Number(trade.sellPrice || 0) || null : livePrice;
  const closePrice = Number(displayPrice || livePrice);
  const openPrice = Number(quote.open || closePrice);
  const highPrice = Number(quote.high || Math.max(openPrice, closePrice));
  const lowPrice = Number(quote.low || Math.min(openPrice, closePrice));
  const preClose = Number(quote.preClose || buyPrice || closePrice);
  const phase = getT1ExecutionPhase(trade, now);
  const avgPrice = Number(quote.avgPrice || quote.ma5 || (highPrice + lowPrice + closePrice) / 3 || closePrice);
  const ma5 = Number(quote.ma5 || avgPrice || closePrice);
  const ma10 = Number(quote.ma10 || ma5 || closePrice);
  const amount = Number(quote.amount || 0);
  const amountMA5 = Number(quote.amountMA5 || amount || 1);
  const turnover = Number(quote.turnover || 0);
  const mainNet = Number(quote.mainNet || 0);
  const superNet = Number(quote.superNet || 0);
  const rangePosition = calcRangePosition(closePrice, highPrice, lowPrice);
  const tailDrawdown = highPrice ? Math.max(0, (highPrice - closePrice) / highPrice) : 0;
  const upperShadow = calcUpperShadowRatio(openPrice, closePrice, highPrice, preClose);
  const frozenReview = phase === "PREP" ? null : trade.reviewSnapshot;
  const referenceClose = Number(frozenReview?.referenceClose || (phase === "PREP" ? closePrice : preClose) || closePrice);
  const referenceAvgPrice = Number(frozenReview?.avgPrice || avgPrice || referenceClose);
  const referenceMa5 = Number(frozenReview?.ma5 || ma5 || referenceAvgPrice);
  const limitUpPrice = calcLimitUpPrice(trade.code, referenceClose);
  const marketScore = getMarketEmotionScore();
  const sectorScore = calcReviewSectorScore(trade, quote);
  const tailSupportScore = calcReviewTailSupportScore({ closePrice, avgPrice, tailDrawdown, mainNet, superNet });
  const positionRiskScore = calcReviewPositionRiskScore({
    openPrice,
    closePrice,
    ma5,
    turnover,
    amount,
    amountMA5,
    tailDrawdown,
    upperShadow,
  });
  const structureScore = calcReviewStructureScore({ closePrice, lowPrice, highPrice, ma5, ma10, avgPrice, buyPrice });
  const liveScores = {
    marketEmotionScore: marketScore,
    sectorStrengthScore: sectorScore,
    tailSupportScore,
    positionRiskScore,
    structureIntegrityScore: structureScore,
  };
  const scores = frozenReview?.scores || liveScores;
  const stockState = frozenReview?.stockState || classifyT1ReviewState(trade, scores);
  const initialPlan = frozenReview?.initialPlan || selectInitialT1Plan(trade, scores, stockState);
  const realtimeState = phase === "PREP"
    ? null
    : classifyOpeningRealtime({
        quote,
        closePrice,
        openPrice: Number(quote.open || 0),
        lowPrice,
        avgPrice,
        referenceClose,
        limitUpPrice,
        sectorScore,
        phase,
      });
  const dateInfo = getTradeDateInfo(trade, now);
  const riskMemory = updateT1ExecutionMemory(trade, {
    now,
    dateInfo,
    phase,
    realtimeState,
    initialPlan,
  });
  const pricePlan = frozenReview?.pricePlan || buildT1PricePlan({
    buyPrice,
    referenceClose,
    ma5: referenceMa5,
    avgPrice: referenceAvgPrice,
    limitUpPrice,
    trade,
    scores,
    initialPlan,
  });
  const execution = buildOpeningExecution({ phase, realtimeState, initialPlan, riskMemory });
  const outcomeState = getTradeOutcomeState(trade);
  const activeAction = buildNextMorningAction({ realtimeState, initialPlan, phase, pricePlan, riskMemory });
  const liveDisplayState = outcomeState || realtimeState || initialPlan;
  const displayState =
    !outcomeState && riskMemory.active && realtimeState && realtimeState !== "WEAK"
      ? `WEAK→${realtimeState}`
      : liveDisplayState;
  return {
    trade,
    quote,
    buyPrice,
    closePrice,
    displayPrice,
    pnlPct: buyPrice && displayPrice ? ((displayPrice - buyPrice) / buyPrice) * 100 : null,
    stockState,
    displayState,
    closed,
    dateInfo,
    initialPlan,
    phase,
    realtimeState,
    scores,
    referenceClose,
    referenceAvgPrice,
    referenceMa5,
    pricePlan,
    execution,
    riskMemory,
    executionMemoryChanged: riskMemory.changed,
    buyDayLimitOutcome: trade.reviewSnapshot?.buyDayLimitOutcome || null,
    action: closed
      ? buildClosedOutcomeAction(trade, displayPrice, buyPrice)
      : dateInfo.overdue
        ? `日期提醒：计划卖出日已过，请先标记止盈或止损；未标记前该笔不会计入学习胜率。${activeAction}`
        : activeAction,
    reasonTags: buildReviewReasonTags(scores, rangePosition, tailDrawdown),
    hardTags: buildReviewHardTags(scores),
  };
}

function captureOvernightReviewSnapshots(reviews, now) {
  const minute = now.getHours() * 60 + now.getMinutes();
  if (minute < 15 * 60) return false;
  let changed = false;
  reviews.forEach((review) => {
    if (review.closed || review.phase !== "PREP" || !isSameLocalDate(review.trade.createdAt, now)) return;
    const strategyTag = getTradeStrategyTag(review.trade);
    const preClose = Number(review.quote?.preClose || 0);
    const highPrice = Number(review.quote?.high || review.closePrice || 0);
    const limitUpPrice = preClose ? calcLimitUpPrice(review.trade.code, preClose) : 0;
    let buyDayLimitOutcome = null;
    if (strategyTag === STRATEGY_AM_TOP && limitUpPrice) {
      const touched = highPrice >= limitUpPrice * 0.998;
      const sealed = review.closePrice >= limitUpPrice * 0.998;
      buyDayLimitOutcome = sealed ? "SEALED_AT_CLOSE" : touched ? "TOUCHED_NOT_SEALED" : "NO_LIMIT_TOUCH";
    }
    const snapshot = {
      tradingDate: localDateKey(now),
      capturedAt: now.toISOString(),
      strategyTag,
      referenceClose: review.referenceClose,
      avgPrice: review.referenceAvgPrice,
      ma5: review.referenceMa5,
      scores: review.scores,
      stockState: review.stockState,
      initialPlan: review.initialPlan,
      pricePlan: review.pricePlan,
      buyDayLimitOutcome,
    };
    const previous = review.trade.reviewSnapshot;
    const unchanged =
      previous?.tradingDate === snapshot.tradingDate &&
      previous?.referenceClose === snapshot.referenceClose &&
      previous?.initialPlan === snapshot.initialPlan &&
      previous?.strategyTag === snapshot.strategyTag &&
      previous?.buyDayLimitOutcome === snapshot.buyDayLimitOutcome &&
      JSON.stringify(previous?.pricePlan) === JSON.stringify(snapshot.pricePlan) &&
      JSON.stringify(previous?.scores) === JSON.stringify(snapshot.scores);
    if (unchanged) return;
    review.trade.reviewSnapshot = snapshot;
    changed = true;
  });
  return changed;
}

function renderT1ReviewCard(review) {
  const weakSequence = String(review.displayState || "").startsWith("WEAK→");
  const stateClass =
    review.trade.outcome === "take_profit" ||
    review.displayState === "PLAN_T" ||
    review.displayState === "STRONG" ||
    review.displayState === "RECOVERY" ||
    review.displayState === "LIMIT_UP"
      ? "pass"
      : review.trade.outcome === "stop_loss" ||
          review.displayState === "REMOVE" ||
          review.displayState === "WEAK" ||
          weakSequence ||
          review.displayState === "PLAN_D"
        ? "alert-pill"
        : "warn";
  const outcome = review.trade.outcome || "";
  const strategyTag = getTradeStrategyTag(review.trade);
  const limitOutcomeLabel = buyDayLimitLabel(review.buyDayLimitOutcome);
  return `
    <article class="review-card">
      <div class="review-head">
        <div>
          <strong>${escapeHtml(review.trade.name)} <span class="stock-code">${review.trade.code}</span></strong>
          <div class="stock-code">买入 ${formatPrice(review.buyPrice)} · ${review.closed ? "卖出标记价" : "收盘/现价"} ${formatPrice(review.displayPrice)} · ${review.closed ? "结果收益" : "浮盈"} ${formatPct(review.pnlPct, false)}</div>
          <div class="review-dates ${review.dateInfo.overdue ? "overdue" : ""}">
            买入日 ${escapeHtml(review.dateInfo.buyDate)} · 计划卖出日 ${escapeHtml(review.dateInfo.plannedSellDate)}
            ${review.dateInfo.actualSellDate ? ` · 实际卖出日 ${escapeHtml(review.dateInfo.actualSellDate)}` : ""}
            ${limitOutcomeLabel ? ` · ${escapeHtml(limitOutcomeLabel)}` : ""}
          </div>
        </div>
        <div class="review-tag-group">
          <span class="tag ${strategyTag === STRATEGY_AM_TOP ? "morning" : strategyTag === STRATEGY_TAIL_MAIN ? "pass" : "warn"}">${escapeHtml(tradeStrategyLabel(review.trade))}</span>
          <span class="${stateClass === "alert-pill" ? "alert-pill" : `tag ${stateClass}`}">${review.displayState}</span>
        </div>
      </div>
      <div class="review-plan">
        <div>
          <span>开盘卖区 · ${escapeHtml(review.execution.ratioLabel)}</span>
          <strong>${formatRange(review.pricePlan.tp1Range)}</strong>
          <small>09:30-09:35 条件触发</small>
        </div>
        <div>
          <span>趋势延伸止盈</span>
          <strong>${formatRange(review.pricePlan.tp2Range)}</strong>
          <small>09:35分类后</small>
        </div>
        <div>
          <span>极强/涨停参考</span>
          <strong>${formatPrice(review.pricePlan.tp3)}</strong>
          <small>10:00边界例外</small>
        </div>
      </div>
      <p class="review-action">${escapeHtml(review.action)}</p>
      <div class="position-actions review-actions">
        <button class="ghost-button" type="button" data-action="edit" data-id="${review.trade.id}">
          <i data-lucide="pencil"></i>
          编辑
        </button>
        <button class="ghost-button outcome-button take-profit ${outcome === "take_profit" ? "selected" : ""}" type="button" data-action="take-profit" data-id="${review.trade.id}">
          <i data-lucide="circle-dollar-sign"></i>
          ${outcome === "take_profit" ? "已记止盈" : "止盈卖出"}
        </button>
        <button class="ghost-button outcome-button stop-loss ${outcome === "stop_loss" ? "selected" : ""}" type="button" data-action="stop-loss" data-id="${review.trade.id}">
          <i data-lucide="shield-alert"></i>
          ${outcome === "stop_loss" ? "已记止损" : "止损卖出"}
        </button>
        <button class="ghost-button" type="button" data-action="delete" data-id="${review.trade.id}">
          <i data-lucide="trash-2"></i>
          删除
        </button>
      </div>
    </article>
  `;
}

function calcReviewSectorScore(trade, quote) {
  const recommendation = (state.data?.recommendations || []).find((item) => item.code === trade.code);
  const board = recommendation?.board || trade.planSnapshot?.board;
  const boardScore = Number(board?.score || 0);
  const boardPassed = Number(board?.passed || 0);
  let score = boardScore ? Math.min(75, boardScore * 0.75) : 45;
  if (boardPassed >= 5) score += 15;
  else if (boardPassed >= 4) score += 10;
  if ((quote?.mainNet || 0) > 0) score += 5;
  return clampScore(score);
}

function calcReviewTailSupportScore({ closePrice, avgPrice, tailDrawdown, mainNet, superNet }) {
  let score = 0;
  if (closePrice >= avgPrice) score += 55;
  if (tailDrawdown <= 0.02) score += 20;
  else if (tailDrawdown <= 0.035) score += 10;
  if (mainNet > 0) score += 15;
  if (superNet > 0) score += 10;
  return clampScore(score);
}

function calcReviewPositionRiskScore({ openPrice, closePrice, ma5, turnover, amount, amountMA5, tailDrawdown, upperShadow }) {
  let score = 0;
  if (upperShadow >= 1.0) score += 25;
  if (amountMA5 && amount / amountMA5 >= 2.5 && openPrice && (closePrice - openPrice) / openPrice < 0.03) score += 25;
  if (ma5 && (closePrice - ma5) / ma5 >= 0.12) score += 20;
  if (turnover >= 35) score += 15;
  if (tailDrawdown >= 0.04) score += 15;
  return clampScore(score);
}

function calcReviewStructureScore({ closePrice, lowPrice, highPrice, ma5, ma10, avgPrice, buyPrice }) {
  const breakoutLevel = Math.max(buyPrice || 0, avgPrice || 0);
  const keySupport = Math.max(ma5 || 0, avgPrice || 0, buyPrice || 0);
  let score = 0;
  if (closePrice >= breakoutLevel) score += 30;
  if (closePrice >= ma5) score += 25;
  if (closePrice >= ma10) score += 20;
  if (lowPrice >= keySupport * 0.98) score += 15;
  if (closePrice >= lowPrice + (highPrice - lowPrice) * 0.5) score += 10;
  return clampScore(score);
}

function classifyT1ReviewState(trade, scores) {
  const status = trade.positionStatus || trade.status || "open";
  const stoppedOrWatch = status === "stopped" || status === "watch";
  const hardKill =
    scores.marketEmotionScore < 40 ||
    scores.positionRiskScore > 75 ||
    scores.structureIntegrityScore < 45;
  if (hardKill) return stoppedOrWatch ? "REMOVE" : "T1_WEAK";
  if (stoppedOrWatch) {
    if (scores.structureIntegrityScore >= 60 && scores.sectorStrengthScore >= 50) return "REENTRY_WATCH";
    return "REMOVE";
  }
  if (
    scores.marketEmotionScore >= 60 &&
    scores.sectorStrengthScore >= 60 &&
    scores.tailSupportScore >= 60 &&
    scores.positionRiskScore <= 60 &&
    scores.structureIntegrityScore >= 65
  ) {
    return "T1_PREMIUM";
  }
  return "T1_WEAK";
}

function selectInitialT1Plan(trade, scores, stockState) {
  const snapshotPlan = trade.planSnapshot?.initialPlan;
  const hardDefensive =
    stockState === "REMOVE" ||
    scores.marketEmotionScore < 40 ||
    scores.positionRiskScore > 75 ||
    scores.structureIntegrityScore < 45;
  if (hardDefensive) return "PLAN_D";
  if (
    stockState === "T1_PREMIUM" &&
    scores.positionRiskScore <= 60 &&
    Number(trade.planSnapshot?.overnightCrowdingScore ?? 44) < 45 &&
    (snapshotPlan === "PLAN_T" || Number(trade.planSnapshot?.finalScore || 0) >= 84)
  ) {
    return "PLAN_T";
  }
  return "PLAN_S";
}

function getT1ExecutionPhase(trade, now) {
  const created = trade.createdAt ? new Date(trade.createdAt) : null;
  if (created && isSameLocalDate(created, now)) return "PREP";
  const minute = now.getHours() * 60 + now.getMinutes();
  if (minute < 9 * 60 + 25) return "PREP";
  if (minute < 9 * 60 + 30) return "AUCTION";
  if (minute < 9 * 60 + 35) return "OPEN_CONFIRM";
  if (minute < 10 * 60) return "CLASSIFY";
  return "FINAL";
}

function weakInstructionRatio(initialPlan) {
  if (initialPlan === "PLAN_D") return { label: "100%", fullExit: true };
  if (initialPlan === "PLAN_T") return { label: "40%-50%", fullExit: false };
  return { label: "60%-70%", fullExit: false };
}

function updateT1ExecutionMemory(trade, { now, dateInfo, phase, realtimeState, initialPlan }) {
  const tradingDate = localDateKey(now);
  const previous = trade.t1ExecutionMemory;
  const active = previous?.tradingDate === tradingDate && Boolean(previous.weakTriggeredAt);
  const minute = now.getHours() * 60 + now.getMinutes();
  const canLatch =
    !isTradeClosed(trade) &&
    dateInfo.plannedSellDate === tradingDate &&
    minute >= 9 * 60 + 30 &&
    minute < 10 * 60 &&
    ["OPEN_CONFIRM", "CLASSIFY"].includes(phase);
  if (active || !canLatch || realtimeState !== "WEAK") {
    return { ...(active ? previous : {}), active, changed: false };
  }

  const instruction = weakInstructionRatio(initialPlan);
  const memory = {
    tradingDate,
    weakTriggeredAt: now.toISOString(),
    weakTriggerTime: now.toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }),
    weakTriggerRatio: instruction.label,
    fullExitInstruction: instruction.fullExit,
    initialPlan,
  };
  trade.t1ExecutionMemory = memory;
  trade.updatedAt = now.toISOString();
  return { ...memory, active: true, changed: true };
}

function classifyOpeningRealtime({
  quote,
  closePrice,
  openPrice,
  lowPrice,
  avgPrice,
  referenceClose,
  limitUpPrice,
  sectorScore,
  phase,
}) {
  if (!closePrice || !referenceClose) return "NEUTRAL";
  if (limitUpPrice && closePrice >= limitUpPrice * 0.998 && sectorScore >= 55) return "LIMIT_UP";
  const gap = openPrice ? (openPrice - referenceClose) / referenceClose : (closePrice - referenceClose) / referenceClose;
  const gain = (closePrice - referenceClose) / referenceClose;
  if (phase === "AUCTION") {
    if (gain >= 0.025) return "STRONG";
    if (gain <= -0.02) return "WEAK";
    return "NEUTRAL";
  }

  const mainNet = Number(quote.mainNet || 0);
  const superNet = Number(quote.superNet || 0);
  const highPrice = Number(quote.high || closePrice);
  const pullback = highPrice ? Math.max(0, (highPrice - closePrice) / highPrice) : 0;
  const aboveOpen = !openPrice || closePrice >= openPrice * 0.998;
  const aboveAvg = !avgPrice || closePrice >= avgPrice * 0.998;
  const flowPositive = mainNet > 0 || superNet > 0;
  const flowNegative = mainNet < 0 && superNet < 0;
  const fastRecovery =
    gap < 0 &&
    closePrice >= referenceClose * 0.998 &&
    (!openPrice || closePrice >= openPrice * 1.008) &&
    aboveAvg;
  if (fastRecovery && pullback <= 0.018) return "RECOVERY";
  if (
    gain >= 0.008 &&
    aboveOpen &&
    aboveAvg &&
    pullback <= 0.018 &&
    (flowPositive || sectorScore >= 55 || gain >= 0.035)
  ) {
    return "STRONG";
  }

  const lostGapAdvantage = gap >= 0.005 && closePrice < referenceClose * 1.002 && !aboveOpen;
  const failedFollowThrough = !aboveOpen && !aboveAvg && (pullback >= 0.012 || flowNegative);
  const nearLowWithPressure = closePrice <= lowPrice * 1.004 && !aboveAvg && (flowNegative || sectorScore < 50);
  if (gain <= -0.015 || lostGapAdvantage || failedFollowThrough || nearLowWithPressure) return "WEAK";
  return "NEUTRAL";
}

function buildOpeningExecution({ phase, realtimeState, initialPlan, riskMemory }) {
  if (phase === "PREP") return { ratioLabel: "待开盘确认" };
  if (phase === "AUCTION") return { ratioLabel: "竞价仅定级" };
  if (riskMemory?.active && realtimeState !== "WEAK") {
    return {
      ratioLabel: riskMemory.fullExitInstruction
        ? `WEAK已触发${riskMemory.weakTriggerRatio}`
        : "仅管理未卖余仓",
    };
  }
  if (realtimeState === "LIMIT_UP" || realtimeState === "STRONG" || realtimeState === "RECOVERY") {
    return { ratioLabel: "暂缓卖出" };
  }
  if (realtimeState === "WEAK") {
    if (initialPlan === "PLAN_D") return { ratioLabel: "100%" };
    if (initialPlan === "PLAN_T") return { ratioLabel: "40%-50%" };
    return { ratioLabel: "60%-70%" };
  }
  if (initialPlan === "PLAN_D") return { ratioLabel: "50%-70%" };
  if (initialPlan === "PLAN_T") return { ratioLabel: "20%-30%" };
  return { ratioLabel: "30%-40%" };
}

function buildT1PricePlan({ buyPrice, referenceClose, ma5, avgPrice, limitUpPrice, trade, scores, initialPlan }) {
  const base = buyPrice || referenceClose;
  const reference = referenceClose || base;
  const costStop = base * 0.96;
  const rawStructureStop = Math.max(Number(trade.stopLoss || 0), ma5 || 0, avgPrice || 0) * 0.992;
  const structureStop = rawStructureStop ? Math.min(rawStructureStop, reference * 0.997) : 0;
  const savedTarget = Number(trade.takeProfit || trade.planSnapshot?.sellPlan?.targetPrice || 0);
  const savedGain = savedTarget > reference ? (savedTarget - reference) / reference : null;
  let scoreGain = 0.008;
  scoreGain += Math.max(-0.003, Math.min(0.004, (scores.marketEmotionScore - 50) * 0.0002));
  scoreGain += Math.max(0, Math.min(0.007, (scores.sectorStrengthScore - 50) * 0.00025));
  scoreGain += Math.max(0, Math.min(0.008, (scores.tailSupportScore - 50) * 0.0003));
  scoreGain += Math.max(0, Math.min(0.007, (scores.structureIntegrityScore - 55) * 0.00025));
  scoreGain -= Math.max(0, (scores.positionRiskScore - 50) * 0.0002);
  if (initialPlan === "PLAN_T") scoreGain += 0.008;
  if (initialPlan === "PLAN_D") scoreGain = Math.min(scoreGain, 0.008);
  scoreGain = Math.max(0.006, Math.min(0.05, scoreGain));

  let targetGain = savedGain !== null
    ? Math.max(0.006, Math.min(0.08, savedGain * 0.65 + scoreGain * 0.35))
    : scoreGain;
  const firstTargetCap = initialPlan === "PLAN_D" ? 0.008 : initialPlan === "PLAN_T" ? 0.025 : 0.01;
  targetGain = Math.min(targetGain, firstTargetCap);
  const extensionBonus =
    0.006 +
    Math.max(0, (scores.tailSupportScore - 60) * 0.0002) +
    Math.max(0, (scores.sectorStrengthScore - 60) * 0.00015);
  const extensionGain = Math.min(0.085, targetGain + extensionBonus);
  const upsideCap = limitUpPrice || reference * 1.1;
  const closeAnchor = reference;
  const overnightFloorGain = initialPlan === "PLAN_D" ? 0 : initialPlan === "PLAN_T" ? 0.012 : 0.006;
  const recoveryAnchor = initialPlan === "PLAN_D"
    ? closeAnchor
    : Math.max(closeAnchor, Math.min(base, closeAnchor * (initialPlan === "PLAN_T" ? 1.025 : 1.02)));
  const tp1Candidate = initialPlan === "PLAN_D"
    ? closeAnchor * (1 + Math.min(0.008, targetGain))
    : Math.max(recoveryAnchor * (1 + targetGain), closeAnchor * (1 + overnightFloorGain));
  const tp2Step = initialPlan === "PLAN_T" ? 0.012 : 0.008;
  const tp2Candidate = Math.max(recoveryAnchor * (1 + extensionGain), tp1Candidate * (1 + tp2Step));
  const tp1 = round2(Math.min(tp1Candidate, upsideCap));
  const tp2 = round2(Math.min(tp2Candidate, upsideCap));
  const tp1Tolerance = initialPlan === "PLAN_D" ? 0.005 : 0.003;
  const tp1Low = initialPlan === "PLAN_D"
    ? Math.min(reference * 0.995, tp1 * (1 - tp1Tolerance))
    : tp1 * (1 - tp1Tolerance);
  return {
    tp1,
    tp1Range: [round2(tp1Low), tp1],
    tp2,
    tp2Range: [round2(tp2 * 0.997), tp2],
    tp3: round2(upsideCap),
    finalStop: round2(Math.max(costStop, structureStop || costStop)),
  };
}

function buildNextMorningAction({ realtimeState, initialPlan, phase, pricePlan, riskMemory }) {
  const stopText = `结构止损 ${formatPrice(pricePlan.finalStop)}`;
  if (phase === "PREP") {
    const bias = initialPlan === "PLAN_D" ? "防守" : initialPlan === "PLAN_T" ? "趋势" : "平衡";
    return `夜间${bias}预案：09:25竞价只定级；09:30后看3-5分钟承接，强修复可暂缓首卖，弱开且不能收复开盘价/VWAP再执行减仓；${stopText}。`;
  }
  if (phase === "AUCTION") {
    if (realtimeState === "STRONG" || realtimeState === "LIMIT_UP") {
      return "竞价偏强：先不挂机械卖单，等09:30后3分钟确认是否有真实承接。";
    }
    if (realtimeState === "WEAK") {
      return `竞价偏弱：不在09:25直接砍仓；09:30后若仍低于开盘价/VWAP，按防守比例执行；${stopText}。`;
    }
    return `竞价中性：等待09:30-09:35方向确认，不因单一竞价价格卖出；${stopText}。`;
  }
  if (riskMemory?.active && realtimeState !== "WEAK") {
    if (riskMemory.fullExitInstruction) {
      return `${riskMemory.weakTriggerTime || "开盘后"}已触发WEAK全卖指令：若已执行，本笔交易已结束；当前${realtimeState || "状态变化"}只作复盘，不回补、不重新建立仓位。`;
    }
    return `${riskMemory.weakTriggerTime || "开盘后"}已触发WEAK减仓${riskMemory.weakTriggerRatio}：已卖部分不回补；当前${realtimeState || "状态变化"}只管理尚未卖出的余仓。`;
  }
  if (phase === "FINAL") {
    return realtimeState === "LIMIT_UP"
      ? "稳定涨停且板块同步：例外持有；开板或封单恶化立即卖出。"
      : "10:00纪律边界已到：卖出全部非涨停残仓，不延长到午后。";
  }
  if (phase === "OPEN_CONFIRM") {
    if (realtimeState === "LIMIT_UP" || realtimeState === "STRONG" || realtimeState === "RECOVERY") {
      return `开盘承接有效：暂缓第一卖点，持有到09:35再分类；跌回开盘价与VWAP下方则取消强修复；${stopText}。`;
    }
    if (realtimeState === "WEAK") {
      const ratio = initialPlan === "PLAN_D" ? "全部" : initialPlan === "PLAN_T" ? "40%-50%" : "60%-70%";
      return `开盘跟随失败：09:30-09:35卖出${ratio}；09:35仍弱则清余仓，不等反抽；${stopText}。`;
    }
    return `开盘尚未定向：按预案小幅减仓并等到09:35；一旦同时跌破开盘价和VWAP，转WEAK处理；${stopText}。`;
  }
  if (realtimeState === "WEAK") {
    return `09:35 WEAK：立即卖出全部余仓，不等反抽，不加仓；${stopText}。`;
  }
  if (realtimeState === "NEUTRAL") {
    const remainder = initialPlan === "PLAN_T" ? "30%" : "20%";
    return `09:35 NEUTRAL：将总仓降至${remainder}，仅等至10:00；非稳定涨停全部卖出。`;
  }
  if (realtimeState === "STRONG" || realtimeState === "RECOVERY") {
    const remainder = initialPlan === "PLAN_T" ? "保留50%-70%" : "保留第一节点后的余仓";
    return `09:35 STRONG：${remainder}至10:00；届时除稳定涨停外全部卖出。`;
  }
  if (realtimeState === "LIMIT_UP") {
    return "09:35 LIMIT_UP：稳定封板且板块同步可例外持有；开板或封单恶化立即卖出。";
  }
  return `09:35按实时强弱分类，10:00清理全部非涨停残仓；${stopText}。`;
}

function buildReviewReasonTags(scores, rangePosition, tailDrawdown) {
  const tags = [];
  if (scores.marketEmotionScore >= 60) tags.push("market_ok");
  if (scores.sectorStrengthScore >= 60) tags.push("sector_supported");
  if (scores.tailSupportScore >= 60) tags.push("tail_support");
  if (scores.structureIntegrityScore >= 65) tags.push("structure_valid");
  if (scores.positionRiskScore <= 60) tags.push("risk_controlled");
  if (rangePosition >= 0.65) tags.push("close_upper_half");
  if (tailDrawdown <= 0.03) tags.push("no_tail_fade");
  return tags.slice(0, 8);
}

function buildReviewHardTags(scores) {
  const tags = [];
  if (scores.marketEmotionScore < 40) tags.push("market_risk_off");
  if (scores.positionRiskScore > 75) tags.push("position_overheated");
  if (scores.structureIntegrityScore < 45) tags.push("structure_broken");
  return tags;
}

function renderNews() {
  const root = $("#newsList");
  const news = state.data?.news || [];
  if (!news.length) {
    root.innerHTML = `<div class="empty-state">暂无新闻线索。数据脚本会优先抓取东方财富、同花顺、第一财经。</div>`;
    return;
  }
  root.innerHTML = news
    .slice(0, 8)
    .map(
      (item) => `
      <article class="news-item">
        <span>${escapeHtml(item.source || "来源")}</span>
        <strong><a href="${item.url}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a></strong>
        <time>${escapeHtml(item.time || "")}</time>
      </article>
    `,
    )
    .join("");
}

function renderSources() {
  const root = $("#sourceList");
  const sources = state.data?.meta?.sourceHealth || [];
  if (!sources.length) {
    root.innerHTML = `<div class="empty-state">暂无来源状态。</div>`;
    return;
  }
  root.innerHTML = sources
    .map(
      (source) => `
      <article class="source-item ${source.ok ? "ok" : "warn"}">
        <div class="source-head">
          <strong>${escapeHtml(source.name)}</strong>
          <span class="tag ${source.ok ? "pass" : "warn"}">${source.ok ? "正常" : "异常"}</span>
        </div>
        <div class="stock-code">${escapeHtml(source.note || source.url || "")}</div>
      </article>
    `,
    )
    .join("");
}

function switchRecommendationView(view) {
  $$(".segment").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  $("#recommendationCards").classList.toggle("hidden", view !== "cards");
  $("#recommendationTableWrap").classList.toggle("hidden", view !== "table");
}

function toggleRules() {
  const content = $("#rulesContent");
  const button = $("#rulesToggle");
  const isOpen = button.getAttribute("aria-expanded") === "true";
  button.setAttribute("aria-expanded", String(!isOpen));
  content.hidden = isOpen;
}

function openTradeModal(recommendation = null, trade = null) {
  const modal = $("#tradeModal");
  const targetPrice = recommendation?.sellPlan?.targetPrice ?? recommendation?.sellPlan?.takeProfit;
  const stopLoss = recommendation?.stopPlan?.stopLoss ?? recommendation?.sellPlan?.stopLoss;
  $("#tradeId").value = trade?.id || "";
  $("#tradeCode").value = trade?.code || recommendation?.code || "";
  $("#tradeName").value = trade?.name || recommendation?.name || "";
  $("#tradeStrategyTag").value =
    getTradeStrategyTag(trade || recommendation) || defaultTradeStrategyTag(new Date());
  $("#tradeBuyPrice").value = valueForInput(trade?.buyPrice || recommendation?.buyPlan?.priceRange?.[0] || recommendation?.price);
  $("#tradeQuantity").value = valueForInput(trade?.quantity);
  $("#tradeStopLoss").value = valueForInput(trade?.stopLoss || stopLoss);
  $("#tradeTakeProfit").value = valueForInput(trade?.takeProfit || targetPrice);
  $("#tradeNote").value = trade?.note || buildRecommendationNote(recommendation);
  modal.hidden = false;
  $("#tradeCode").focus();
}

function closeTradeModal() {
  $("#tradeModal").hidden = true;
  $("#tradeForm").reset();
}

function saveTradeFromForm(event) {
  event.preventDefault();
  const existingId = $("#tradeId").value;
  const existing = state.trades.find((item) => item.id === existingId);
  const code = $("#tradeCode").value.trim();
  const quote = state.liveQuotes.get(code) || findRecommendationQuote(code) || {};
  const buyPrice = Number($("#tradeBuyPrice").value) || existing?.buyPrice || quote.price || 0;
  const stopLoss = Number($("#tradeStopLoss").value) || round2(buyPrice * 0.96);
  const now = new Date();
  const buyTradingDate = existing?.buyTradingDate || currentTradingDateKey(now);
  const trade = {
    id: existingId || createId(),
    code,
    name: $("#tradeName").value.trim(),
    buyPrice,
    quantity: Number($("#tradeQuantity").value) || null,
    stopLoss,
    takeProfit: Number($("#tradeTakeProfit").value) || null,
    note: $("#tradeNote").value.trim(),
    status: existing?.status || "open",
    strategyTag: $("#tradeStrategyTag").value,
    buyTradingDate,
    plannedSellTradingDate: existing?.plannedSellTradingDate || nextWeekdayDateKey(buyTradingDate),
    createdAt: existing?.createdAt || now.toISOString(),
    updatedAt: now.toISOString(),
  };
  const index = state.trades.findIndex((item) => item.id === trade.id);
  if (index >= 0) state.trades[index] = { ...state.trades[index], ...trade };
  else state.trades.unshift(trade);
  persistTrades();
  closeTradeModal();
  refreshPositionQuotes().then(render);
}

function buildRecommendationNote(recommendation) {
  if (!recommendation) return "";
  const buyType = recommendation.buyPlan?.type || "计划买点";
  const board = recommendation.board?.name || "主升板块";
  const targetTime = recommendation.sellPlan?.targetTime || recommendation.sellPlan?.timeWindow || "";
  return `${board}；${buyType}；预估时间 ${targetTime}`;
}

function loadTrades() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    state.trades = normalizeImportedTrades(stored);
  } catch {
    state.trades = [];
  }
}

function persistTrades() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.trades));
}

async function exportTradesForSync() {
  const payload = {
    version: 3,
    source: PUBLIC_SITE_URL,
    exportedAt: new Date().toISOString(),
    tradeCount: state.trades.length,
    trades: state.trades,
  };
  state.syncPayload = payload;
  const syncCode = await encodeSyncPayload(payload);
  openSyncModal("export", syncCode);
  const copied = await writeTextToClipboard(syncCode);
  setSyncStatus(
    copied
      ? `已复制 ${state.trades.length} 条记录的同步码，可直接到另一台设备粘贴。`
      : `已生成 ${state.trades.length} 条记录的同步码，请长按文本复制，或使用分享/JSON。`,
    copied ? "success" : "",
  );
}

function importTradesFromSync() {
  state.syncPayload = null;
  openSyncModal("import", "");
}

function openSyncModal(mode, syncCode = "") {
  const isExport = mode === "export";
  const modal = $("#syncModal");
  modal.dataset.mode = mode;
  $("#syncModalTitle").textContent = isExport ? "导出交易记录" : "导入交易记录";
  $("#syncDescription").textContent = isExport
    ? "同步码已包含买入日、计划卖出日、实际卖出日及止盈/止损标记。"
    : "可粘贴新同步码、旧版同步码或 JSON，也可以直接选择导出的 JSON 文件。";
  $("#syncCodeLabel").textContent = isExport ? "本次同步码" : "粘贴同步码";
  $("#syncCodeInput").value = syncCode;
  $("#syncCodeInput").readOnly = isExport;
  $("#syncImportMode").hidden = isExport;
  $$("#syncModal .export-only").forEach((element) => {
    element.hidden = !isExport;
  });
  $$("#syncModal .import-only").forEach((element) => {
    element.hidden = isExport;
  });
  $("#shareSyncCodeButton").hidden = !isExport || typeof navigator.share !== "function";
  setSyncImportMode("merge");
  setSyncStatus("");
  modal.hidden = false;
  refreshIcons();
  window.setTimeout(() => {
    $("#syncCodeInput").focus();
    if (isExport) $("#syncCodeInput").select();
  }, 0);
}

function closeSyncModal() {
  $("#syncModal").hidden = true;
  $("#syncCodeInput").value = "";
  $("#syncFileInput").value = "";
  state.syncPayload = null;
  setSyncStatus("");
}

function setSyncImportMode(mode) {
  state.syncImportMode = mode === "replace" ? "replace" : "merge";
  $$("[data-sync-import-mode]").forEach((button) => {
    const active = button.dataset.syncImportMode === state.syncImportMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function setSyncStatus(message, tone = "") {
  const status = $("#syncStatus");
  status.textContent = message;
  status.className = `sync-status${tone ? ` ${tone}` : ""}`;
}

async function pasteSyncCode() {
  try {
    if (!navigator.clipboard?.readText) throw new Error("Clipboard read is unavailable");
    const value = (await navigator.clipboard.readText()).trim();
    if (!value) throw new Error("Clipboard is empty");
    $("#syncCodeInput").value = value;
    setSyncStatus("已从剪贴板粘贴，可以开始同步。", "success");
  } catch {
    $("#syncCodeInput").focus();
    setSyncStatus("浏览器未允许读取剪贴板，请长按输入框后选择“粘贴”。", "error");
  }
}

async function copySyncCode() {
  const value = $("#syncCodeInput").value.trim();
  if (!value) return;
  const copied = await writeTextToClipboard(value);
  setSyncStatus(copied ? "同步码已复制。" : "请长按同步码并选择“复制”。", copied ? "success" : "error");
}

async function writeTextToClipboard(value) {
  try {
    if (navigator.clipboard?.writeText) {
      await Promise.race([
        navigator.clipboard.writeText(value),
        new Promise((_, reject) => window.setTimeout(() => reject(new Error("Clipboard timeout")), 900)),
      ]);
      return true;
    }
  } catch {
    // Fall through to selection-based copying for older mobile browsers.
  }
  const input = $("#syncCodeInput");
  input.focus();
  input.select();
  try {
    return Boolean(document.execCommand?.("copy"));
  } catch {
    return false;
  }
}

async function shareSyncCode() {
  if (typeof navigator.share !== "function") return;
  const syncCode = $("#syncCodeInput").value.trim();
  try {
    const file = createSyncExportFile();
    if (navigator.canShare?.({ files: [file] })) {
      await navigator.share({ title: "BIG A GO 交易记录", files: [file] });
    } else {
      await navigator.share({ title: "BIG A GO 交易记录", text: `BIG A GO 同步码\n${syncCode}` });
    }
    setSyncStatus("已打开系统分享。", "success");
  } catch (error) {
    if (error?.name !== "AbortError") setSyncStatus("系统分享未完成，可改用复制或导出 JSON。", "error");
  }
}

function createSyncExportFile() {
  const content = JSON.stringify(state.syncPayload || { version: 3, source: PUBLIC_SITE_URL, trades: [] }, null, 2);
  return new File([content], syncExportFilename(), { type: "application/json" });
}

function syncExportFilename() {
  const now = new Date();
  const stamp = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0"),
  ].join("-");
  return `BIG-A-GO-trades-${stamp}.json`;
}

function downloadSyncFile() {
  const file = createSyncExportFile();
  const url = URL.createObjectURL(file);
  const link = document.createElement("a");
  link.href = url;
  link.download = file.name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  setSyncStatus(`已导出 ${file.name}。`, "success");
}

async function loadSyncFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    $("#syncCodeInput").value = (await file.text()).trim();
    setSyncStatus(`已读取 ${file.name}，可以开始同步。`, "success");
  } catch {
    setSyncStatus("文件读取失败，请重新选择 JSON 或 TXT 文件。", "error");
  } finally {
    event.target.value = "";
  }
}

async function applySyncImport() {
  const input = $("#syncCodeInput").value.trim();
  if (!input) {
    setSyncStatus("请先粘贴同步码或选择 JSON 文件。", "error");
    return;
  }
  const button = $("#applySyncCodeButton");
  button.disabled = true;
  try {
    const payload = await decodeSyncPayload(input);
    if (!Array.isArray(payload?.trades)) throw new Error("Missing trades");
    const importedTrades = normalizeImportedTrades(payload.trades);
    if (!importedTrades.length) {
      setSyncStatus("导入内容中没有交易记录，未修改当前设备。", "error");
      return;
    }

    let result;
    if (state.syncImportMode === "replace") {
      const previousCount = state.trades.length;
      state.trades = importedTrades;
      result = {
        added: importedTrades.length,
        updated: 0,
        kept: 0,
        removed: Math.max(0, previousCount - importedTrades.length),
      };
    } else {
      result = mergeImportedTrades(importedTrades);
    }

    persistTrades();
    state.liveQuotes.clear();
    state.historyQuotes.clear();
    await refreshPositionQuotes();
    render();
    const summary =
      state.syncImportMode === "replace"
        ? `同步完成：当前设备现有 ${state.trades.length} 条记录。`
        : `同步完成：新增 ${result.added} 条，更新 ${result.updated} 条，本机较新 ${result.kept} 条。`;
    setSyncStatus(summary, "success");
  } catch {
    setSyncStatus("无法识别导入内容，请确认同步码完整，或改用 JSON 文件。", "error");
  } finally {
    button.disabled = false;
    refreshIcons();
  }
}

async function encodeSyncPayload(payload) {
  const bytes = new TextEncoder().encode(JSON.stringify(payload));
  if (typeof CompressionStream === "function") {
    try {
      const stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream("gzip"));
      const compressed = new Uint8Array(await new Response(stream).arrayBuffer());
      return `${SYNC_CODE_GZIP_PREFIX}${bytesToBase64Url(compressed)}`;
    } catch {
      // Uncompressed Base64URL remains compatible with older browsers.
    }
  }
  return `${SYNC_CODE_RAW_PREFIX}${bytesToBase64Url(bytes)}`;
}

async function decodeSyncPayload(syncCode) {
  const input = String(syncCode || "").replace(/^\uFEFF/, "").trim();
  if (!input) throw new Error("Empty sync payload");
  if (input.startsWith("{")) return JSON.parse(input);

  const prefixed = input.match(/BAGS3[BG]\.[A-Za-z0-9_-]+/);
  if (prefixed) {
    const token = prefixed[0];
    const isCompressed = token.startsWith(SYNC_CODE_GZIP_PREFIX);
    const encoded = token.slice(isCompressed ? SYNC_CODE_GZIP_PREFIX.length : SYNC_CODE_RAW_PREFIX.length);
    let bytes = base64UrlToBytes(encoded);
    if (isCompressed) {
      if (typeof DecompressionStream !== "function") throw new Error("Gzip is unavailable");
      const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
      bytes = new Uint8Array(await new Response(stream).arrayBuffer());
    }
    return JSON.parse(new TextDecoder().decode(bytes));
  }

  const binary = atob(input.replace(/\s+/g, ""));
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return JSON.parse(new TextDecoder().decode(bytes));
}

function bytesToBase64Url(bytes) {
  let binary = "";
  for (let index = 0; index < bytes.length; index += 32768) {
    binary += String.fromCharCode(...bytes.subarray(index, index + 32768));
  }
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function base64UrlToBytes(value) {
  const base64 = value.replaceAll("-", "+").replaceAll("_", "/");
  const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, "=");
  const binary = atob(padded);
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

function normalizeImportedTrades(trades) {
  if (!Array.isArray(trades)) return [];
  return trades
    .filter((trade) => trade && trade.code && trade.name)
    .map((trade) => {
      const buyTradingDate = trade.buyTradingDate || safeLocalDateKey(trade.createdAt) || currentTradingDateKey();
      return {
        ...trade,
        id: trade.id || createId(),
        code: String(trade.code).trim(),
        name: String(trade.name).trim(),
        buyPrice: Number(trade.buyPrice) || 0,
        quantity: Number(trade.quantity) || null,
        stopLoss: Number(trade.stopLoss) || null,
        takeProfit: Number(trade.takeProfit) || null,
        strategyTag: getTradeStrategyTag(trade),
        status: trade.status || "open",
        outcome: trade.outcome || null,
        buyTradingDate,
        plannedSellTradingDate: trade.plannedSellTradingDate || nextWeekdayDateKey(buyTradingDate),
        sellTradingDate: trade.sellTradingDate || safeLocalDateKey(trade.soldAt) || null,
        sellPrice: Number(trade.sellPrice) || null,
        importedAt: trade.importedAt || new Date().toISOString(),
      };
    });
}

function mergeImportedTrades(importedTrades) {
  const merged = [...state.trades];
  const result = { added: 0, updated: 0, kept: 0, removed: 0 };
  importedTrades.forEach((incoming) => {
    const sameTrade = merged.findIndex(
      (trade) =>
        trade.id === incoming.id ||
        (trade.code === incoming.code &&
          trade.buyTradingDate &&
          incoming.buyTradingDate &&
          trade.buyTradingDate === incoming.buyTradingDate),
    );
    if (sameTrade >= 0) {
      const local = merged[sameTrade];
      const useIncoming = shouldUseIncomingTrade(local, incoming);
      merged[sameTrade] = useIncoming
        ? { ...local, ...incoming, id: local.id }
        : { ...incoming, ...local, id: local.id };
      result[useIncoming ? "updated" : "kept"] += 1;
      return;
    }
    merged.unshift(incoming);
    result.added += 1;
  });
  state.trades = merged;
  return result;
}

function shouldUseIncomingTrade(local, incoming) {
  const localTime = tradeModifiedAt(local);
  const incomingTime = tradeModifiedAt(incoming);
  if (incomingTime !== localTime) return incomingTime > localTime;
  if (isTradeClosed(incoming) !== isTradeClosed(local)) return isTradeClosed(incoming);
  return Boolean(incoming.resultMarkedAt && !local.resultMarkedAt);
}

function tradeModifiedAt(trade) {
  return Math.max(
    0,
    ...["resultMarkedAt", "updatedAt", "soldAt", "createdAt"]
      .map((field) => Date.parse(trade?.[field] || ""))
      .filter(Number.isFinite),
  );
}

function markTradeOutcome(id, outcome) {
  const trade = state.trades.find((item) => item.id === id);
  if (!trade || !["take_profit", "stop_loss"].includes(outcome)) return;
  if (trade.status === "closed" && trade.outcome === outcome) return;
  const now = new Date();
  const quote = getQuoteForTrade(trade) || {};
  const markedTradingDate = currentTradingDateKey(now);
  const plannedSellTradingDate =
    trade.plannedSellTradingDate ||
    nextWeekdayDateKey(trade.buyTradingDate || safeLocalDateKey(trade.createdAt));
  if (plannedSellTradingDate && markedTradingDate < plannedSellTradingDate) {
    alert(`计划卖出日为 ${plannedSellTradingDate}，尚未到T+1，暂不记录交易结果。`);
    return;
  }
  const markedLate = Boolean(plannedSellTradingDate && markedTradingDate > plannedSellTradingDate);
  trade.status = "closed";
  trade.outcome = outcome;
  trade.soldAt = now.toISOString();
  trade.resultMarkedAt = now.toISOString();
  trade.sellTradingDate = markedLate ? plannedSellTradingDate : markedTradingDate;
  trade.outcomeDateSource = markedLate ? "planned_t1_backfill" : "marked_live";
  trade.sellPrice = markedLate
    ? Number(trade.sellPrice || 0) || null
    : Number(quote.price || trade.lastPrice || trade.buyPrice || 0) || null;
  trade.lastPrice = trade.sellPrice;
  trade.updatedAt = now.toISOString();
  persistTrades();
  render();
}

function deleteTrade(id) {
  state.trades = state.trades.filter((item) => item.id !== id);
  persistTrades();
  render();
}

async function refreshPositionQuotes() {
  const openCodes = state.trades.filter((trade) => !isTradeClosed(trade)).map((trade) => trade.code);
  await Promise.all(openCodes.map(fetchLiveQuote).slice(0, 20));
  await Promise.all(openCodes.map(fetchHistoryQuote).slice(0, 20));
  const alerts = getPositionAlerts();
  if (alerts.length) notifyAlerts(alerts);
}

async function fetchLiveQuote(code) {
  if (!code || state.liveQuotes.has(code)) return state.liveQuotes.get(code);
  const secid = getSecid(code);
  const url = `https://push2.eastmoney.com/api/qt/stock/get?secid=${secid}&fields=f43,f44,f45,f46,f47,f48,f50,f57,f58,f60,f62,f66,f168,f170`;
  try {
    const data = await jsonp(url);
    const item = data?.data;
    if (!item) return null;
    const volume = Number(item.f47) || 0;
    const amount = Number(item.f48) || 0;
    const quote = {
      code,
      price: normalizeEastMoneyPrice(item.f43),
      high: normalizeEastMoneyPrice(item.f44),
      low: normalizeEastMoneyPrice(item.f45),
      open: normalizeEastMoneyPrice(item.f46),
      volume,
      amount,
      avgPrice: averagePrice(amount, volume),
      pct: normalizeEastMoneyPrice(item.f170),
      turnover: normalizeEastMoneyPrice(item.f168),
      volumeRatio: normalizeEastMoneyPrice(item.f50),
      preClose: normalizeEastMoneyPrice(item.f60),
      mainNet: Number(item.f62) || 0,
      superNet: Number(item.f66) || 0,
      name: item.f58,
    };
    state.liveQuotes.set(code, quote);
    return quote;
  } catch {
    return null;
  }
}

async function fetchHistoryQuote(code) {
  if (!code || state.historyQuotes.has(code)) return state.historyQuotes.get(code);
  const secid = getSecid(code);
  const url = `https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=${secid}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=1&end=20500101&lmt=20`;
  try {
    const data = await jsonp(url);
    const rows = data?.data?.klines || [];
    const parsed = rows
      .map((line) => {
        const parts = String(line).split(",");
        return {
          date: parts[0],
          open: Number(parts[1]),
          close: Number(parts[2]),
          high: Number(parts[3]),
          low: Number(parts[4]),
          volume: Number(parts[5]),
          amount: Number(parts[6]),
          turnover: Number(parts[10]),
        };
      })
      .filter((item) => item.close);
    if (!parsed.length) return null;
    const closes = parsed.map((item) => item.close);
    const amounts = parsed.map((item) => item.amount || 0);
    const latest = parsed[parsed.length - 1];
    const history = {
      ma5: average(closes.slice(-5)),
      ma10: average(closes.slice(-10)),
      amountMA5: average(amounts.slice(-5)),
      prevClose: parsed.length >= 2 ? parsed[parsed.length - 2].close : null,
      historyClose: latest.close,
      historyOpen: latest.open,
      historyHigh: latest.high,
      historyLow: latest.low,
      historyTurnover: latest.turnover,
    };
    state.historyQuotes.set(code, history);
    return history;
  } catch {
    return null;
  }
}

function jsonp(url) {
  return new Promise((resolve, reject) => {
    const callbackName = `jsonp_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    const script = document.createElement("script");
    const separator = url.includes("?") ? "&" : "?";
    script.src = `${url}${separator}cb=${callbackName}`;
    script.async = true;
    window[callbackName] = (payload) => {
      delete window[callbackName];
      script.remove();
      resolve(payload);
    };
    script.onerror = () => {
      delete window[callbackName];
      script.remove();
      reject(new Error("JSONP failed"));
    };
    document.body.appendChild(script);
  });
}

function getPositionAlerts() {
  return state.trades
    .filter((trade) => !isTradeClosed(trade))
    .map((trade) => {
      const quote = getQuoteForTrade(trade);
      const current = quote?.price || trade.lastPrice || trade.buyPrice;
      const alert = getAlertForTrade(trade, current);
      return alert ? { trade, current, alert } : null;
    })
    .filter(Boolean);
}

function getAlertForTrade(trade, currentPrice) {
  if (isTradeClosed(trade)) return "";
  if (trade.stopLoss && currentPrice <= trade.stopLoss) return "到止损";
  if (trade.takeProfit && currentPrice >= trade.takeProfit) return "到卖点";
  if (currentPrice <= trade.buyPrice * 0.95) return "亏损5%";
  return "";
}

function getQuoteForTrade(trade) {
  const recommendation = findRecommendationQuote(trade.code) || {};
  const history = state.historyQuotes.get(trade.code) || {};
  const live = state.liveQuotes.get(trade.code) || {};
  const merged = { ...recommendation, ...history, ...live };
  return Object.keys(merged).length ? merged : null;
}

function findRecommendationQuote(code) {
  const item = (state.data?.recommendations || []).find((recommendation) => recommendation.code === code);
  return item
    ? {
        price: item.price,
        pct: item.pct,
        name: item.name,
        amount: item.amount,
        turnover: item.turnover,
        industry: item.industry,
      }
    : null;
}

function requestNotifications() {
  if (!("Notification" in window)) return;
  if (Notification.permission === "granted") {
    notifyAlerts(getPositionAlerts());
    return;
  }
  Notification.requestPermission().then((permission) => {
    if (permission === "granted") notifyAlerts(getPositionAlerts());
  });
}

function notifyAlerts(alerts) {
  if (!alerts.length || !("Notification" in window) || Notification.permission !== "granted") return;
  alerts.slice(0, 3).forEach(({ trade, current, alert }) => {
    new Notification(`${trade.name} ${alert}`, {
      body: `现价 ${formatPrice(current)}，买入 ${formatPrice(trade.buyPrice)}`,
      tag: `${trade.id}-${alert}`,
    });
  });
}

function getSecid(code) {
  if (/^(6|9)/.test(code)) return `1.${code}`;
  return `0.${code}`;
}

function normalizeEastMoneyPrice(value) {
  if (value === undefined || value === null || value === "-") return null;
  return Number(value) / 100;
}

function averagePrice(amount, volume) {
  if (!amount || !volume) return null;
  return round2(amount / (volume * 100));
}

function average(values) {
  const valid = values.filter((value) => Number.isFinite(value));
  if (!valid.length) return null;
  return round2(valid.reduce((sum, value) => sum + value, 0) / valid.length);
}

function getMarketEmotionScore() {
  const monitor = state.data?.market?.monitor;
  if (monitor?.emotionScore !== undefined) return Number(monitor.emotionScore);
  let score = 50;
  const recommendationCount = state.data?.market?.recommendationCount || state.data?.recommendations?.length || 0;
  const qualifiedBoardCount = state.data?.market?.qualifiedBoardCount || 0;
  if (recommendationCount >= 8) score += 10;
  if (qualifiedBoardCount >= 6) score += 10;
  if ((state.data?.boards || [])[0]?.pct > 1) score += 10;
  return clampScore(score);
}

function calcRangePosition(price, high, low) {
  if (!price || !high || !low || high <= low) return 0.5;
  return Math.max(0, Math.min(1, (price - low) / (high - low)));
}

function calcUpperShadowRatio(openPrice, closePrice, highPrice, preClose) {
  if (!openPrice || !closePrice || !highPrice) return 0;
  const body = Math.abs(closePrice - openPrice);
  const upper = Math.max(0, highPrice - Math.max(openPrice, closePrice));
  const minBody = Math.max((preClose || closePrice) * 0.002, 0.01);
  return upper / Math.max(body, minBody);
}

function calcLimitUpPrice(code, preClose) {
  if (!preClose) return null;
  if (/^(30|68)/.test(code)) return round2(preClose * 1.2);
  return round2(preClose * 1.1);
}

function isTradeClosed(trade) {
  return trade?.status === "closed" || trade?.status === "sold" || Boolean(trade?.outcome);
}

function getTradeOutcomeState(trade) {
  if (trade.outcome === "take_profit") return "止盈完成";
  if (trade.outcome === "stop_loss") return "止损完成";
  if (trade.status === "sold" || trade.status === "closed") return "已卖出";
  return "";
}

function getTradeDateInfo(trade, now = new Date()) {
  const buyDate = trade.buyTradingDate || safeLocalDateKey(trade.createdAt) || "--";
  const plannedSellDate =
    trade.plannedSellTradingDate ||
    (buyDate !== "--" ? nextWeekdayDateKey(buyDate) : "--");
  const actualSellDate = trade.sellTradingDate || safeLocalDateKey(trade.soldAt) || "";
  const today = currentTradingDateKey(now);
  return {
    buyDate,
    plannedSellDate,
    actualSellDate,
    overdue: !isTradeClosed(trade) && plannedSellDate !== "--" && today > plannedSellDate,
  };
}

function buildClosedOutcomeAction(trade, sellPrice, buyPrice) {
  const result =
    trade.outcome === "take_profit"
      ? "止盈卖出"
      : trade.outcome === "stop_loss"
        ? "止损卖出"
        : "卖出";
  const pnl = buyPrice && sellPrice ? ((sellPrice - buyPrice) / buyPrice) * 100 : null;
  const markedLate = trade.outcomeDateSource === "planned_t1_backfill";
  const timing = markedLate ? "结果在T+1后补标，卖出日按原计划T+1日保存" : "卖出日已按标记日保存";
  return `${result}已记录，${timing}；该样本会保留用于学习，只有“删除”会移除记录${pnl === null ? "" : `；标记价格相对买入 ${formatPct(pnl, false)}`}。`;
}

function safeLocalDateKey(value) {
  if (!value) return "";
  const parsed = value instanceof Date ? value : new Date(value);
  return Number.isNaN(parsed.getTime()) ? "" : localDateKey(parsed);
}

function currentTradingDateKey(now = new Date()) {
  const today = localDateKey(now);
  const snapshotDate = state.data?.meta?.tradingDate;
  if (snapshotDate === today) return snapshotDate;
  if (now.getDay() === 0 || now.getDay() === 6) {
    const previous = new Date(now);
    do {
      previous.setDate(previous.getDate() - 1);
    } while (previous.getDay() === 0 || previous.getDay() === 6);
    return localDateKey(previous);
  }
  return today;
}

function nextWeekdayDateKey(dateKey) {
  const [year, month, day] = String(dateKey).split("-").map(Number);
  const value = new Date(year, month - 1, day, 12, 0, 0);
  if (Number.isNaN(value.getTime())) return "";
  do {
    value.setDate(value.getDate() + 1);
  } while (value.getDay() === 0 || value.getDay() === 6);
  return localDateKey(value);
}

function isSameLocalDate(value, date) {
  const left = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(left.getTime()) || Number.isNaN(date.getTime())) return false;
  return localDateKey(left) === localDateKey(date);
}

function localDateKey(date) {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function clampScore(value) {
  return Math.round(Math.max(0, Math.min(100, Number(value) || 0)));
}

function valueForInput(value) {
  return value === undefined || value === null || Number.isNaN(Number(value)) ? "" : String(value);
}

function formatRange(range) {
  if (!Array.isArray(range) || range.length < 2) return "--";
  return `${formatPrice(range[0])} - ${formatPrice(range[1])}`;
}

function formatPrice(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return "--";
  return Number(value).toFixed(2);
}

function formatPct(value, signed = true) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return "--";
  const prefix = signed && Number(value) > 0 ? "+" : "";
  return `${prefix}${Number(value).toFixed(2)}%`;
}

function round2(value) {
  return Math.round(Number(value) * 100) / 100;
}

function createId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `trade-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function refreshIcons() {
  if (window.lucide) window.lucide.createIcons();
}
