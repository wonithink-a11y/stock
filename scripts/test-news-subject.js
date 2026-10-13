'use strict';
const assert = require('assert');
const { isSubject } = require('../lib/newsSubject');

assert.strictEqual(isSubject("농심, 소비자 레시피 담은 '감바스짜파게티' 선봬…이마트 선출시", '이마트'), false);
assert.strictEqual(isSubject('쿠쿠, 대우건설 빌트인 정수기 수주', '대우건설'), false);
assert.strictEqual(isSubject('[특징주] 에코프로, 2차전지 강세에 7% 급등', '에코프로'), true);
assert.strictEqual(isSubject('삼성전자·SK하이닉스, 반도체 강세', 'SK하이닉스'), true);
assert.strictEqual(isSubject('로봇주 장중 동반 상승…휴림로봇 4%대', '휴림로봇'), true);
assert.strictEqual(isSubject('하나증권, 키움증권 목표가 하향…“3분기 실적 부진 전망”', '키움증권'), true);
assert.strictEqual(isSubject('키움證 "현대모비스, 현대차·기아 파업 부담…목표가 14.7%↓"', '기아'), false);
console.log('test-news-subject: 7/7 통과');
