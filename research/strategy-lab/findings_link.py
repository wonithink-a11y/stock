"""사전등록 문서 ↔ 결과 파일 연결, 연구가 아닌 문서 판별 (리서치랩·대시보드 연구 목록 공용).

사전등록은 실행 전 설계 문서이고 결과는 별도 파일이라, 둘을 따로 세면 같은 연구가 이중 집계되고 사전등록은 판정이 없어 보인다.
이름으로 연결한다: X-preregistration-YYYY-MM.md ↔ X-results-YYYY-MM.md (정확히 같은 줄기만, 접두 일치는 12자 이상·'-' 경계일 때만).
"""
import re

_NOT_RESULT = ("PREREGISTERED", "UNCLASSIFIED")


def _stem_pre(f):
    s = re.sub(r"\.md$", "", f)
    s = re.sub(r"-(preregistration|prereg|pre-registration|preregister)", "", s)
    return re.sub(r"-20\d\d-\d\d$", "", s)


def _stem_res(f):
    s = re.sub(r"\.md$", "", f)
    s = re.sub(r"-(results?|result)", "", s)
    return re.sub(r"-20\d\d-\d\d$", "", s)


def link_prereg(items):
    """items: [{'file': 이름, 'verdict': 선언 판정(짧은 낱말), 'date': ...}] → {사전등록 파일: [결과 항목, ...]} (연결된 것만)"""
    res = {}
    for r in items:
        if r["verdict"] in _NOT_RESULT:
            continue
        res.setdefault(_stem_res(r["file"]), []).append(r)
    out = {}
    for p in items:
        if p["verdict"] != "PREREGISTERED":
            continue
        s = _stem_pre(p["file"])
        m = list(res.get(s, []))
        if not m:
            for k, v in res.items():
                short, long_ = sorted((k, s), key=len)
                if len(short) >= 12 and long_.startswith(short + "-"):
                    m += v
        if m:
            out[p["file"]] = sorted(m, key=lambda x: x.get("date") or "", reverse=True)
    return out


def is_doc(file):
    """연구 결과가 아닌 문서: 하위 폴더 파일, README."""
    return "/" in file or file.lower().startswith("readme")


def selftest():
    items = [dict(file="a-preregistration-2026-10.md", verdict="PREREGISTERED"), dict(file="a-results-2026-10.md", verdict="REJECT", date="2026-10-02"),
             dict(file="b-forward-preregistration-2026-10.md", verdict="PREREGISTERED"), dict(file="zz-preregistration-2026-10.md", verdict="PREREGISTERED"),
             dict(file="zz-extra-results-2026-10.md", verdict="HOLD")]
    m = link_prereg(items)
    assert m["a-preregistration-2026-10.md"][0]["verdict"] == "REJECT"
    assert "b-forward-preregistration-2026-10.md" not in m
    assert "zz-preregistration-2026-10.md" not in m   # 짧은 줄기('zz')는 접두 일치로 잇지 않는다
    assert is_doc("a3d/README.md") and not is_doc("x-results-2026-10.md")
    print("OK")


if __name__ == "__main__":
    selftest()
