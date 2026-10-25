// PostToolUse(Bash): git commit 직후 인수인계 메모 + 한도 점검을 상기시킨다. 알림만 — 직접 쓰지 않는다.
let s = '';
process.stdin.on('data', (d) => (s += d)).on('end', () => {
  let cmd = '';
  try { cmd = JSON.parse(s).tool_input.command || ''; } catch { return; }
  if (!/\bgit\s+commit\b/.test(cmd)) return;
  console.log(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PostToolUse',
      additionalContext:
        '[session-wrapup] 방금 커밋했다. 오늘 인수인계 파일에 2~3줄 덧붙였는지 확인하고(없으면 만든다, 커밋은 마감 때), ' +
        'mcp__ccd_session_mgmt__get_usage 로 5시간 한도가 90% 를 넘었으면 최소 마감(한 장 요약+미확인) 후 멈춘다.',
    },
  }));
});
