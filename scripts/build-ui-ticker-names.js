#!/usr/bin/env node
/* ui/data/ticker-names.json 빌더 - 종목코드 -> 회사명 조회용.
   data/backfill/universe/a1a(활성)·a1b(폐지) jsonl을 그대로 재사용한다
   (신규 수집 없음). 차트 탭이 종목코드만 보여주던 걸 보완하기 위해
   2026-08-30 신설. */
"use strict";
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const SOURCES = [
  path.join(ROOT, "data/backfill/universe/a1a/current.jsonl"),
  path.join(ROOT, "data/backfill/universe/a1a/excluded.jsonl"),
  path.join(ROOT, "data/backfill/universe/a1b/delisted.jsonl"),
];
const OUT_PATH = path.join(ROOT, "ui/data/ticker-names.json");

function readJsonl(p) {
  if (!fs.existsSync(p)) return [];
  return fs
    .readFileSync(p, "utf-8")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

const names = {};
for (const src of SOURCES) {
  for (const row of readJsonl(src)) {
    if (row.ticker && row.name && !names[row.ticker]) names[row.ticker] = row.name;
  }
}

fs.mkdirSync(path.dirname(OUT_PATH), { recursive: true });
fs.writeFileSync(OUT_PATH, JSON.stringify(names), "utf-8");
console.log(`저장: ${OUT_PATH} (${Object.keys(names).length}개 종목)`);
