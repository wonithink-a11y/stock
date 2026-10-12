/**
 * surgeContext.js — 장중 급등락 알림에 붙이는 맥락(유형·뉴스·공시).
 * 설계: docs/control/장중급등-원인태그-설계-2026-10-13.md. 조회·알림 전용 — 점수·매매에 쓰지 않는다.
 *
 * 유형 이름·문턱은 research/strategy-lab/why_surge.py(분봉 배치)와 같다. 실시간은 10분 스냅샷뿐이라
 * 동료 동반을 '같은 시각 ±10분'이 아니라 '전일 대비 등락'으로 본다(근사).
 * 네트워크 함수는 전부 5초 타임아웃이고 호출자(intraday-check.js)가 예외를 삼킨다 — 맥락 때문에 알림이 멈추면 안 된다.
 */
'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const GAP_SHARE = 0.7;      // 시가 갭이 현재 상승의 70% 이상 → 시초 갭형
const PEER_MOVE = 2.0;      // 동료가 같은 방향으로 ±2% 이상
const PEER_SHARE = 0.3;     // 그런 동료가 30% 이상
const MIN_PEERS = 5;
const TIMEOUT_MS = 5000;

// 주가 움직임 자체를 보도하는 기사 — 원인이 아니다
const RECAP = /특징주|급등|급락|상한가|하한가|강세|약세|신고가|신저가|\d+(?:\.\d+)?%\s*(?:상승|하락|오른|내린|올라|내려|뛴|빠진)|주가\s*.{0,8}(?:휘청|들썩|출렁|껑충|뚝)/;

function isMarketRecap(title) {
  return RECAP.test(String(title || ''));
}

/**
 * dailyPct·gapPct 는 % 단위. peerMoves = 동료들의 전일 대비 %. hasDisclosure: true/false/null(모름).
 */
function classifySurge({ dailyPct, gapPct }, peerMoves, hasDisclosure) {
  const dir = Math.sign(dailyPct) || 1;
  const n = peerMoves.length;
  const same = peerMoves.filter((p) => dir * p >= PEER_MOVE).length;
  if (typeof gapPct === 'number' && dir * gapPct > 0 && dir * gapPct >= GAP_SHARE * dir * dailyPct) {
    return { kind: '시초 갭형', same, n };
  }
  if (n >= MIN_PEERS && same / n >= PEER_SHARE) return { kind: '장중 무리형', same, n };
  if (hasDisclosure === true) return { kind: '단독+공시', same, n };
  return { kind: '단독', same, n };
}

/** 동료 색인: 테마 트리 소그룹 ∪ sector-strength 업종(g). 파일이 없으면 빈 색인(동반 판정 안 함). */
function loadPeerIndex(root = ROOT) {
  const groupsOf = new Map();
  const members = new Map();
  const add = (key, t) => {
    if (!members.has(key)) members.set(key, new Set());
    members.get(key).add(t);
    if (!groupsOf.has(t)) groupsOf.set(t, []);
    groupsOf.get(t).push(key);
  };
  try {
    const themes = JSON.parse(fs.readFileSync(path.join(root, 'config', 'themeTree.json'), 'utf-8')).themes;
    for (const [big, groups] of Object.entries(themes)) {
      for (const [g, list] of Object.entries(groups)) for (const x of list) add(`테마:${big}/${g}`, x.t);
    }
  } catch (e) { /* 테마 없음 */ }
  try {
    const ss = JSON.parse(fs.readFileSync(path.join(root, 'docs', 'data', 'sector-strength.json'), 'utf-8'));
    for (const s of ss.stocks || []) if (s.g) add(`업종:${s.g}`, s.t);
  } catch (e) { /* 업종 없음 */ }
  return { groupsOf, members };
}

/** 동료 코드와 표시 이름(첫 테마 소그룹, 없으면 업종). */
function peersOf(index, ticker) {
  const keys = index.groupsOf.get(ticker) || [];
  const peers = new Set();
  for (const k of keys) for (const t of index.members.get(k)) if (t !== ticker) peers.add(t);
  const label = (keys.find((k) => k.startsWith('테마:')) || keys[0] || '').replace(/^(테마|업종):/, '').split('/').pop();
  return { peers: [...peers], label };
}

/** 직전 국내 정규장 마감(전 평일 15:30 KST) 시각(ms). 공휴일은 무시 — 창이 넓어질 뿐이다. */
function prevCloseMs(now = Date.now()) {
  const kst = new Date(now + 9 * 3600e3);
  const d = new Date(Date.UTC(kst.getUTCFullYear(), kst.getUTCMonth(), kst.getUTCDate(), 15, 30) - 9 * 3600e3);
  if (now < d.getTime()) d.setUTCDate(d.getUTCDate() - 1);
  while ([0, 6].includes(new Date(d.getTime() + 9 * 3600e3).getUTCDay())) d.setUTCDate(d.getUTCDate() - 1);
  return d.getTime();
}

/** 기사 목록 → {cause, recap, total}. 제목에 종목명이 있는 기사만, since 이후만. */
function pickCauseArticle(items, sinceMs, name) {
  const fresh = (items || [])
    .map((it) => ({ title: String(it.title || ''), at: typeof it.at === 'number' ? it.at : Date.parse(it.pubDate) }))
    .filter((it) => Number.isFinite(it.at) && it.at >= sinceMs && it.title.includes(name))
    .sort((a, b) => b.at - a.at);
  const cause = fresh.find((it) => !isMarketRecap(it.title)) || null;
  return { cause, recap: fresh.filter((it) => isMarketRecap(it.title)).length, total: fresh.length };
}

function stripTags(s) {
  return String(s || '').replace(/<[^>]+>/g, '').replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
}

async function searchNaver(name, env = process.env, fetchImpl = fetch) {
  if (!env.NAVER_CLIENT_ID || !env.NAVER_CLIENT_SECRET) return null;
  const url = 'https://openapi.naver.com/v1/search/news.json?' + new URLSearchParams({ query: `"${name}"`, display: '5', sort: 'date' });
  const res = await fetchImpl(url, {
    headers: { 'X-Naver-Client-Id': env.NAVER_CLIENT_ID, 'X-Naver-Client-Secret': env.NAVER_CLIENT_SECRET },
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (!res.ok) throw new Error(`naver HTTP ${res.status}`);
  const j = await res.json();
  return (j.items || []).map((it) => ({ title: stripTags(it.title), at: Date.parse(it.pubDate) }));
}

let corpMap = null;
function corpOf(ticker, root = ROOT) {
  if (!corpMap) {
    corpMap = new Map();
    try {
      for (const line of fs.readFileSync(path.join(root, 'data', 'backfill', 'dart', 'corpcode.jsonl'), 'utf-8').split('\n')) {
        if (!line.trim()) continue;
        const j = JSON.parse(line);
        if (j.ticker) corpMap.set(j.ticker, j.corp);
      }
    } catch (e) { /* 맵 없음 → 공시 확인 안 함 */ }
  }
  return corpMap.get(ticker) || null;
}

/** 오늘 DART 공시 제목. 키·법인코드가 없으면 null(모름 — 없음과 다르다). */
async function fetchDartToday(ticker, ymd, env = process.env, fetchImpl = fetch) {
  const corp = corpOf(ticker);
  if (!env.DART_API_KEY || !corp) return null;
  const url = 'https://opendart.fss.or.kr/api/list.json?' + new URLSearchParams({
    crtfc_key: env.DART_API_KEY, corp_code: corp, bgn_de: ymd, end_de: ymd, page_count: '20' });
  const res = await fetchImpl(url, { signal: AbortSignal.timeout(TIMEOUT_MS) });
  if (!res.ok) throw new Error(`dart HTTP ${res.status}`);
  const j = await res.json();
  if (j.status === '013') return [];
  if (j.status !== '000') throw new Error(`dart status ${j.status}`);
  return (j.list || []).map((x) => String(x.report_nm || '').trim().replace(/\s+/g, ' '));
}

function hhmm(ms) {
  return new Date(ms).toLocaleTimeString('sv-SE', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit' });
}

/** 맥락 한 줄. news: {cause,recap,total} | null(모름) | 'error'. dart: [titles] | null | 'error'. */
function contextLine(cls, label, gapPct, news, dart) {
  // '(추정)': 10분 스냅샷 근사가 분봉 배치 판정과 47% 일치(설계 §6-2, 2026-10-13) — 알림 시점 기준 유형이다
  const parts = [`${cls.kind}(추정)`];
  if (cls.kind === '시초 갭형') parts.push(`시가 갭 ${gapPct > 0 ? '+' : ''}${gapPct}%`);
  else if (cls.n >= MIN_PEERS) parts.push(`${label || '동료'} ${cls.same}/${cls.n} 동반`);
  if (news === 'error') parts.push('뉴스 확인 실패');
  else if (!news) parts.push('뉴스 확인 안 함');
  else if (news.cause) parts.push(`뉴스 ${hhmm(news.cause.at)} "${news.cause.title.slice(0, 40)}"`);
  else if (news.recap) parts.push(`시황 기사만 ${news.recap}건`);
  else parts.push('뉴스 없음');
  if (dart === 'error') parts.push('공시 확인 실패');
  else if (dart === null || dart === undefined) parts.push('공시 확인 안 함');
  else if (dart.length) parts.push(`공시: ${dart[0].slice(0, 30)}${dart.length > 1 ? ` 외 ${dart.length - 1}` : ''}`);
  else parts.push('공시 없음');
  return `   └ ${parts.join(' · ')}`;
}

module.exports = {
  classifySurge, isMarketRecap, loadPeerIndex, peersOf, prevCloseMs, pickCauseArticle,
  searchNaver, fetchDartToday, contextLine, MIN_PEERS, GAP_SHARE,
};
