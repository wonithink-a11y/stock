'use strict';
// 제목의 주인공이 이 종목인가. 주어 자리 = 맨 앞 [말머리] 를 떼고 첫 쉼표 앞 20자 이내.
// 거기에 다른 회사만 있으면 남의 기사('농심, … 이마트 선출시'). 쉼표 없는 제목은 통과.
// 증권사 리포트('하나증권, 키움증권 목표가 하향')는 증권사 주어를 떼고 그 뒤를 다시 본다.
// 짝: research/strategy-lab/run_news_minute_forward.py is_subject — 바꾸면 둘 다 바꾼다.
const SUBJ = /^\s*(?:\[[^\]]*\]\s*)*([^,，…]{1,20}?)\s*[,，]/;
const BROKER = /^\S*(증권|證)$/;

function isSubject(title, name) {
  let t = String(title || '');
  let m = t.match(SUBJ);
  while (m && BROKER.test(m[1].trim())) {
    t = t.slice(m[0].length);
    m = t.match(SUBJ);
  }
  return !m || m[1].includes(name);
}

module.exports = { isSubject };
