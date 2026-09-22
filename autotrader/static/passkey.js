// autotrader 패스키(지문) — 등록, 조작 확인, 재인증(금액 보기). 서버가 검증한다(이 스크립트는 브라우저 API 호출과 형식 변환만).
// 인라인 스크립트를 쓰지 않는다(CSP script-src 'self'). 값은 data-* 속성으로 받는다.
(function () {
  "use strict";
  var enc = function (buf) {
    var s = "", b = new Uint8Array(buf);
    for (var i = 0; i < b.length; i++) s += String.fromCharCode(b[i]);
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  };
  var dec = function (s) {
    s = s.replace(/-/g, "+").replace(/_/g, "/");
    s += "===".slice(0, (4 - (s.length % 4)) % 4);
    var raw = atob(s), out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out.buffer;
  };
  var post = function (url, obj) {
    return fetch(url, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(obj) }).then(function (r) {
      return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || ("HTTP " + r.status)); return j; });
    });
  };
  var say = function (el, msg, bad) { if (el) { el.textContent = msg; el.className = bad ? "bad" : "ok"; } };

  // ---- 등록
  var reg = document.getElementById("pk-register");
  if (reg) {
    reg.addEventListener("click", function () {
      var base = reg.dataset.base, csrf = reg.dataset.csrf, out = document.getElementById("pk-msg");
      if (!window.PublicKeyCredential) { say(out, "이 브라우저는 패스키를 지원하지 않습니다", true); return; }
      post(base + "/passkey/register-options", { csrf: csrf }).then(function (o) {
        o.challenge = dec(o.challenge);
        o.user.id = dec(o.user.id);
        (o.excludeCredentials || []).forEach(function (c) { c.id = dec(c.id); });
        return navigator.credentials.create({ publicKey: o });
      }).then(function (c) {
        return post(base + "/passkey/register", { csrf: csrf, credential: {
          id: c.id, rawId: enc(c.rawId), type: c.type, authenticatorAttachment: c.authenticatorAttachment || null,
          clientExtensionResults: c.getClientExtensionResults ? c.getClientExtensionResults() : {},
          response: { clientDataJSON: enc(c.response.clientDataJSON), attestationObject: enc(c.response.attestationObject),
                      transports: c.response.getTransports ? c.response.getTransports() : [] } } });
      }).then(function (j) { say(out, j.message, false); setTimeout(function () { location.reload(); }, 1200); })
        .catch(function (e) { say(out, "등록 실패: " + e.message, true); });
    });
  }

  // ---- 서명(조작 확인·재인증 공통)
  var sign = function (o) {
    o.challenge = dec(o.challenge);
    (o.allowCredentials || []).forEach(function (c) { c.id = dec(c.id); });
    return navigator.credentials.get({ publicKey: o }).then(function (c) {
      return { id: c.id, rawId: enc(c.rawId), type: c.type, authenticatorAttachment: c.authenticatorAttachment || null,
        clientExtensionResults: c.getClientExtensionResults ? c.getClientExtensionResults() : {},
        response: { clientDataJSON: enc(c.response.clientDataJSON), authenticatorData: enc(c.response.authenticatorData),
                    signature: enc(c.response.signature),
                    userHandle: c.response.userHandle ? enc(c.response.userHandle) : null } };
    });
  };

  // ---- 재인증(금액·보유 보기)
  var re = document.getElementById("pk-reauth");
  if (re) {
    re.addEventListener("click", function () {
      var base = re.dataset.base, csrf = re.dataset.csrf, out = document.getElementById("pk-reauth-msg");
      post(base + "/passkey/reauth-options", { csrf: csrf }).then(sign).then(function (cred) {
        return post(base + "/passkey/reauth", { csrf: csrf, next: re.dataset.next, credential: cred });
      }).then(function (j) { location.href = j.redirect; })
        .catch(function (e) { say(out, "실패: " + e.message, true); });
    });
  }

  // ---- 조작 확인
  var act = document.getElementById("pk-action");
  if (act) {
    act.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var base = act.dataset.base, csrf = act.dataset.csrf, out = document.getElementById("pk-action-msg");
      var req = { csrf: csrf, p: act.dataset.profile, op: act.elements.op.value, phrase: act.elements.phrase ? act.elements.phrase.value : "" };
      post(base + "/passkey/action-options", req).then(sign).then(function (cred) {
        req.credential = cred;
        return post(base + "/passkey/action", req);
      }).then(function (j) { location.href = j.redirect; })
        .catch(function (e) { say(out, "실패: " + e.message, true); });
    });
  }
})();
