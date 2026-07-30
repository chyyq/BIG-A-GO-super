import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../app.js", import.meta.url), "utf8");
const sandbox = {
  console,
  TextDecoder,
  TextEncoder,
  URL,
  atob,
  btoa,
  document: {
    addEventListener() {},
    querySelector() {
      return null;
    },
    querySelectorAll() {
      return [];
    },
  },
  navigator: {},
  localStorage: {
    getItem() {
      return null;
    },
    setItem() {},
  },
  window: {
    crypto: globalThis.crypto,
    setTimeout,
  },
};
sandbox.globalThis = sandbox;

vm.runInNewContext(
  `${source}
  globalThis.__appTest = {
    updateT1ExecutionMemory,
    buildNextMorningAction,
    buildOpeningExecution,
    getTradeStrategyTag,
    tradeStrategyLabel,
  };`,
  sandbox,
);

const {
  updateT1ExecutionMemory,
  buildNextMorningAction,
  buildOpeningExecution,
  getTradeStrategyTag,
  tradeStrategyLabel,
} = sandbox.__appTest;

const trade = {
  status: "open",
  plannedSellTradingDate: "2026-07-30",
};
const weakAt0931 = updateT1ExecutionMemory(trade, {
  now: new Date("2026-07-30T09:31:00+08:00"),
  dateInfo: { plannedSellDate: "2026-07-30" },
  phase: "OPEN_CONFIRM",
  realtimeState: "WEAK",
  initialPlan: "PLAN_D",
});
assert.equal(weakAt0931.active, true);
assert.equal(weakAt0931.fullExitInstruction, true);
assert.equal(weakAt0931.changed, true);

const neutralAt0935 = updateT1ExecutionMemory(trade, {
  now: new Date("2026-07-30T09:35:00+08:00"),
  dateInfo: { plannedSellDate: "2026-07-30" },
  phase: "CLASSIFY",
  realtimeState: "NEUTRAL",
  initialPlan: "PLAN_D",
});
assert.equal(neutralAt0935.active, true);
assert.equal(neutralAt0935.changed, false);
assert.match(
  buildNextMorningAction({
    realtimeState: "NEUTRAL",
    initialPlan: "PLAN_D",
    phase: "CLASSIFY",
    pricePlan: { finalStop: 9.6 },
    riskMemory: neutralAt0935,
  }),
  /不回补/,
);
assert.match(
  buildOpeningExecution({
    phase: "CLASSIFY",
    realtimeState: "NEUTRAL",
    initialPlan: "PLAN_D",
    riskMemory: neutralAt0935,
  }).ratioLabel,
  /WEAK已触发100%/,
);

assert.equal(getTradeStrategyTag({ strategyTag: "AM_TOP" }), "AM_TOP");
assert.equal(tradeStrategyLabel({ strategyTag: "AM_TOP" }), "早盘涨停");
assert.equal(tradeStrategyLabel({ strategyTag: "TAIL_MAIN" }), "尾盘 T+1");

console.log("app logic tests passed");
