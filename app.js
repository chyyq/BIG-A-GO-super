const DATA_URL = "data/latest.json";
const STORAGE_KEY = "a-share-maintrend-trades-v1";
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
  });
  $("#tradeForm").addEventListener("submit", saveTradeFromForm);
  $("#reviewRefreshButton")?.addEventListener("click", refreshReviewNow);
  $("#exportTradesButton")?.addEventListener("click", exportTradesForSync);
  $("#importTradesButton")?.addEventListener("click", importTradesFromSync);
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
  $("#recommendationCount").textContent = dataIssue ? 0 : state.data?.recommendations?.length || 0;
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

  return `
    <article class="recommendation-card">
      <div class="card-top">
        <div class="rank-badge">#${rank}</div>
        <div>
          <h3 class="stock-name">${escapeHtml(item.name)} <span class="stock-code">${item.code}</span></h3>
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
        <button class="ghost-button" type="button" data-action="buy" data-code="${item.code}" ${recorded ? "disabled" : ""}>
          <i data-lucide="${recorded ? "check" : "square-pen"}"></i>
          ${recorded ? "已记录" : "一键记录买入"}
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
          <td class="col-plan">${escapeHtml(item.buyPlan?.type || "--")}<span>${escapeHtml(item.buyPlan?.timeWindow || "")}</span></td>
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
  if (!recommendation) return;
  const targetPrice = recommendation.sellPlan?.targetPrice ?? recommendation.sellPlan?.takeProfit;
  const stopLoss = recommendation.stopPlan?.stopLoss ?? recommendation.sellPlan?.stopLoss;
  const buyPrice = estimateRecordedBuyPrice(recommendation);
  const existing = state.trades.find((item) => item.code === recommendation.code && item.status !== "sold");
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
    },
    createdAt: existing?.createdAt || new Date().toISOString(),
    updatedAt: new Date().toISOString(),
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

function isOpenTradeRecorded(code) {
  return state.trades.some((trade) => trade.code === code && trade.status !== "sold");
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
  const openTrades = state.trades.filter((trade) => trade.status !== "sold");
  const generatedAt = state.data?.meta?.generatedAt ? new Date(state.data.meta.generatedAt) : null;
  meta.textContent = generatedAt
    ? `行情快照 ${generatedAt.toLocaleString("zh-CN", { hour12: false })}；按 20:00 复盘纪律生成`
    : "等待 20:00 行情快照或手动刷新";

  if (!openTrades.length) {
    root.innerHTML = `<div class="empty-state">暂无已记录买入。推荐卡片点“一键记录买入”后，这里会生成明天 T+1 卖出策略。</div>`;
    return;
  }

  const reviews = openTrades.map(buildT1Review);
  root.innerHTML = reviews.map(renderT1ReviewCard).join("");
  root.querySelectorAll("[data-action='edit']").forEach((button) => {
    const trade = state.trades.find((item) => item.id === button.dataset.id);
    button.addEventListener("click", () => openTradeModal(null, trade));
  });
  root.querySelectorAll("[data-action='sell']").forEach((button) => {
    button.addEventListener("click", () => markTradeSold(button.dataset.id));
  });
  root.querySelectorAll("[data-action='delete']").forEach((button) => {
    button.addEventListener("click", () => deleteTrade(button.dataset.id));
  });
}

function buildT1Review(trade) {
  const quote = getQuoteForTrade(trade) || {};
  const buyPrice = Number(trade.buyPrice || quote.price || 0);
  const closePrice = Number(quote.price || trade.lastPrice || buyPrice);
  const openPrice = Number(quote.open || closePrice);
  const highPrice = Number(quote.high || Math.max(openPrice, closePrice));
  const lowPrice = Number(quote.low || Math.min(openPrice, closePrice));
  const preClose = Number(quote.preClose || buyPrice || closePrice);
  const phase = getT1ExecutionPhase(trade, new Date());
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
  const limitUpBase = phase === "PREP" ? closePrice : preClose;
  const limitUpPrice = calcLimitUpPrice(trade.code, limitUpBase);
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
  const scores = {
    marketEmotionScore: marketScore,
    sectorStrengthScore: sectorScore,
    tailSupportScore,
    positionRiskScore,
    structureIntegrityScore: structureScore,
  };
  const stockState = classifyT1ReviewState(trade, scores);
  const initialPlan = selectInitialT1Plan(trade, scores, stockState);
  const state0935 = phase === "CLASSIFY" || phase === "FINAL"
    ? classify0935Realtime({ quote, closePrice, openPrice, lowPrice, avgPrice, limitUpPrice, sectorScore })
    : null;
  const pricePlan = buildT1PricePlan({ buyPrice, closePrice, ma5, avgPrice, limitUpPrice, trade, scores, initialPlan });
  return {
    trade,
    quote,
    buyPrice,
    closePrice,
    pnlPct: buyPrice ? ((closePrice - buyPrice) / buyPrice) * 100 : 0,
    stockState,
    displayState: state0935 || initialPlan,
    initialPlan,
    phase,
    state0935,
    scores,
    pricePlan,
    action: buildNextMorningAction({ stockState, state0935, initialPlan, phase, pricePlan }),
    reasonTags: buildReviewReasonTags(scores, rangePosition, tailDrawdown),
    hardTags: buildReviewHardTags(scores),
  };
}

function renderT1ReviewCard(review) {
  const stateClass =
    review.displayState === "PLAN_T" || review.displayState === "STRONG" || review.displayState === "LIMIT_UP"
      ? "pass"
      : review.displayState === "REMOVE" || review.displayState === "WEAK" || review.displayState === "PLAN_D"
        ? "alert-pill"
        : "warn";
  return `
    <article class="review-card">
      <div class="review-head">
        <div>
          <strong>${escapeHtml(review.trade.name)} <span class="stock-code">${review.trade.code}</span></strong>
          <div class="stock-code">买入 ${formatPrice(review.buyPrice)} · 收盘/现价 ${formatPrice(review.closePrice)} · 浮盈 ${formatPct(review.pnlPct, false)}</div>
        </div>
        <span class="${stateClass === "alert-pill" ? "alert-pill" : `tag ${stateClass}`}">${review.displayState}</span>
      </div>
      <div class="review-plan">
        <div>
          <span>第一卖点 · ${firstSellRatioLabel(review.initialPlan)}</span>
          <strong>${formatPrice(review.pricePlan.tp1)}</strong>
          <small>09:25-09:31</small>
        </div>
        <div>
          <span>趋势延伸止盈</span>
          <strong>${formatPrice(review.pricePlan.tp2)}</strong>
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
        <button class="ghost-button" type="button" data-action="sell" data-id="${review.trade.id}">
          <i data-lucide="circle-check"></i>
          记为卖出
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
  if (created && created.toLocaleDateString("zh-CN") === now.toLocaleDateString("zh-CN")) return "PREP";
  const minute = now.getHours() * 60 + now.getMinutes();
  if (minute < 9 * 60 + 25) return "PREP";
  if (minute < 9 * 60 + 35) return "FIRST_NODE";
  if (minute < 10 * 60) return "CLASSIFY";
  return "FINAL";
}

function classify0935Realtime({ quote, closePrice, openPrice, lowPrice, avgPrice, limitUpPrice, sectorScore }) {
  if (limitUpPrice && closePrice >= limitUpPrice * 0.998 && sectorScore >= 55) return "LIMIT_UP";
  const mainNet = Number(quote.mainNet || 0);
  const superNet = Number(quote.superNet || 0);
  const fastReclaim = closePrice >= avgPrice || closePrice >= openPrice;
  const weakPoints = [
    closePrice < openPrice,
    closePrice < avgPrice,
    closePrice <= lowPrice * 1.004,
    mainNet < 0 && superNet < 0,
    sectorScore < 50,
  ].filter(Boolean).length;
  const strongPoints = [
    closePrice >= openPrice || closePrice >= avgPrice,
    closePrice > lowPrice * 1.008,
    mainNet > 0 || superNet > 0,
    sectorScore >= 60,
  ].filter(Boolean).length;
  if (weakPoints >= 2 && !fastReclaim) return "WEAK";
  if (strongPoints >= 2) return "STRONG";
  return "NEUTRAL";
}

function firstSellRatioLabel(initialPlan) {
  if (initialPlan === "PLAN_D") return "100%";
  if (initialPlan === "PLAN_T") return "20%-30%";
  return "40%-50%";
}

function buildT1PricePlan({ buyPrice, closePrice, ma5, avgPrice, limitUpPrice, trade, scores, initialPlan }) {
  const base = buyPrice || closePrice;
  const costStop = base * 0.96;
  const structureStop = Math.max(Number(trade.stopLoss || 0), ma5 || 0, avgPrice || 0) * 0.992;
  const savedTarget = Number(trade.takeProfit || trade.planSnapshot?.sellPlan?.targetPrice || 0);
  const savedGain = savedTarget > base ? (savedTarget - base) / base : null;
  let scoreGain = 0.008;
  scoreGain += Math.max(-0.003, Math.min(0.004, (scores.marketEmotionScore - 50) * 0.0002));
  scoreGain += Math.max(0, Math.min(0.007, (scores.sectorStrengthScore - 50) * 0.00025));
  scoreGain += Math.max(0, Math.min(0.008, (scores.tailSupportScore - 50) * 0.0003));
  scoreGain += Math.max(0, Math.min(0.007, (scores.structureIntegrityScore - 55) * 0.00025));
  scoreGain -= Math.max(0, (scores.positionRiskScore - 50) * 0.0002);
  if (initialPlan === "PLAN_T") scoreGain += 0.008;
  if (initialPlan === "PLAN_D") scoreGain = Math.min(scoreGain, 0.008);
  scoreGain = Math.max(0.006, Math.min(0.05, scoreGain));

  const targetGain = savedGain !== null
    ? Math.max(0.006, Math.min(0.08, savedGain * 0.65 + scoreGain * 0.35))
    : scoreGain;
  const extensionBonus =
    0.006 +
    Math.max(0, (scores.tailSupportScore - 60) * 0.0002) +
    Math.max(0, (scores.sectorStrengthScore - 60) * 0.00015);
  const extensionGain = Math.min(0.085, targetGain + extensionBonus);
  const upsideCap = limitUpPrice || base * 1.1;
  const closeAnchor = closePrice || base;
  const overnightFloorGain = initialPlan === "PLAN_D" ? 0 : initialPlan === "PLAN_T" ? 0.012 : 0.006;
  const tp1Candidate = Math.max(base * (1 + targetGain), closeAnchor * (1 + overnightFloorGain));
  const tp2Step = initialPlan === "PLAN_T" ? 0.012 : 0.008;
  const tp2Candidate = Math.max(base * (1 + extensionGain), tp1Candidate * (1 + tp2Step));
  return {
    tp1: round2(Math.min(tp1Candidate, upsideCap)),
    tp2: round2(Math.min(tp2Candidate, upsideCap)),
    tp3: round2(upsideCap),
    finalStop: round2(Math.max(costStop, structureStop || costStop)),
  };
}

function buildNextMorningAction({ state0935, initialPlan, phase, pricePlan }) {
  const stopText = `结构止损 ${formatPrice(pricePlan.finalStop)}`;
  if (initialPlan === "PLAN_D") {
    return `PLAN_D：09:25-09:31 卖出100%，不等待09:35；${stopText}。`;
  }
  if (phase === "FINAL") {
    return state0935 === "LIMIT_UP"
      ? "稳定涨停且板块同步：例外持有；开板或封单恶化立即卖出。"
      : "10:00纪律边界已到：卖出全部非涨停残仓，不延长到午后。";
  }
  if (state0935 === "WEAK") {
    return `09:35 WEAK：立即卖出全部余仓，不等反抽，不加仓；${stopText}。`;
  }
  if (state0935 === "NEUTRAL") {
    const remainder = initialPlan === "PLAN_T" ? "30%" : "20%";
    return `09:35 NEUTRAL：将总仓降至${remainder}，仅等至10:00；非稳定涨停全部卖出。`;
  }
  if (state0935 === "STRONG") {
    const remainder = initialPlan === "PLAN_T" ? "保留50%-70%" : "保留第一节点后的余仓";
    return `09:35 STRONG：${remainder}至10:00；届时除稳定涨停外全部卖出。`;
  }
  if (state0935 === "LIMIT_UP") {
    return "09:35 LIMIT_UP：稳定封板且板块同步可例外持有；开板或封单恶化立即卖出。";
  }
  if (initialPlan === "PLAN_T") {
    return `PLAN_T：09:25-09:31 先卖20%-30%；09:35再分类，10:00清非涨停残仓；${stopText}。`;
  }
  return `PLAN_S：09:25-09:31 先卖40%-50%；09:35再分类，10:00清非涨停残仓；${stopText}。`;
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
    createdAt: existing?.createdAt || new Date().toISOString(),
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
    state.trades = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
  } catch {
    state.trades = [];
  }
}

function persistTrades() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.trades));
}

async function exportTradesForSync() {
  const payload = {
    version: 1,
    exportedAt: new Date().toISOString(),
    trades: state.trades,
  };
  const syncCode = encodeSyncPayload(payload);
  const message = "已生成同步码。请在手机端打开网页，点击“导入同步码”后粘贴。";
  try {
    await navigator.clipboard.writeText(syncCode);
    alert(`${message}\n同步码已复制到剪贴板。`);
  } catch {
    window.prompt(message, syncCode);
  }
}

function importTradesFromSync() {
  const syncCode = window.prompt("粘贴从另一台设备导出的同步码");
  if (!syncCode) return;
  try {
    const payload = decodeSyncPayload(syncCode);
    const importedTrades = normalizeImportedTrades(payload?.trades);
    if (!importedTrades.length) {
      alert("同步码里没有可导入的买入记录。");
      return;
    }
    mergeImportedTrades(importedTrades);
    persistTrades();
    refreshPositionQuotes().then(() => {
      render();
      alert(`已导入 ${importedTrades.length} 条记录，持仓和晚间复盘已刷新。`);
    });
  } catch {
    alert("同步码无法识别，请确认完整复制后再导入。");
  }
}

function encodeSyncPayload(payload) {
  const json = JSON.stringify(payload);
  const bytes = new TextEncoder().encode(json);
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

function decodeSyncPayload(syncCode) {
  const binary = atob(syncCode.trim());
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return JSON.parse(new TextDecoder().decode(bytes));
}

function normalizeImportedTrades(trades) {
  if (!Array.isArray(trades)) return [];
  return trades
    .filter((trade) => trade && trade.code && trade.name)
    .map((trade) => ({
      ...trade,
      id: trade.id || createId(),
      code: String(trade.code).trim(),
      name: String(trade.name).trim(),
      buyPrice: Number(trade.buyPrice) || 0,
      quantity: Number(trade.quantity) || null,
      stopLoss: Number(trade.stopLoss) || null,
      takeProfit: Number(trade.takeProfit) || null,
      status: trade.status || "open",
      importedAt: new Date().toISOString(),
    }));
}

function mergeImportedTrades(importedTrades) {
  const merged = [...state.trades];
  importedTrades.forEach((incoming) => {
    const sameId = merged.findIndex((trade) => trade.id === incoming.id);
    if (sameId >= 0) {
      merged[sameId] = { ...merged[sameId], ...incoming };
      return;
    }
    const sameOpenCode = merged.findIndex(
      (trade) => trade.code === incoming.code && trade.status !== "sold" && incoming.status !== "sold",
    );
    if (sameOpenCode >= 0) {
      merged[sameOpenCode] = { ...merged[sameOpenCode], ...incoming, id: merged[sameOpenCode].id };
      return;
    }
    merged.unshift(incoming);
  });
  state.trades = merged;
}

function markTradeSold(id) {
  const trade = state.trades.find((item) => item.id === id);
  if (!trade) return;
  trade.status = "sold";
  trade.soldAt = new Date().toISOString();
  persistTrades();
  render();
}

function deleteTrade(id) {
  state.trades = state.trades.filter((item) => item.id !== id);
  persistTrades();
  render();
}

function clearClosedTrades() {
  state.trades = state.trades.filter((item) => item.status !== "sold");
  persistTrades();
  render();
}

async function refreshPositionQuotes() {
  const openCodes = state.trades.filter((trade) => trade.status !== "sold").map((trade) => trade.code);
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
    .filter((trade) => trade.status !== "sold")
    .map((trade) => {
      const quote = getQuoteForTrade(trade);
      const current = quote?.price || trade.lastPrice || trade.buyPrice;
      const alert = getAlertForTrade(trade, current);
      return alert ? { trade, current, alert } : null;
    })
    .filter(Boolean);
}

function getAlertForTrade(trade, currentPrice) {
  if (trade.status === "sold") return "";
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
