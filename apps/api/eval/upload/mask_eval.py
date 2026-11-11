"""업로드 개인정보 가리기 평가: 서비스의 llm_ingest.mask 를 그대로 불러 가짜 개인정보가 심긴 생활 문서에서 놓침·과하게 가림을 센다.

    # 1) 평가 문서 만들기(헤드리스 Claude Code, API 비용 없음). 정답(심은 값)을 data/mask_set.json 에 잠그고 sha256 을 data/mask_set.sha256 에 적는다
    python eval/upload/mask_eval.py gen [--seed 11] [--force]
    # 2) 평가(서비스 mask 호출, API 비용 발생)
    PYTHONPATH=. python eval/upload/mask_eval.py run --name haiku_base --max-usd 0.5 [--limit 40]
    # 3) 호출 없이 저장된 가린 글만 다시 채점
    PYTHONPATH=. python eval/upload/mask_eval.py run --name haiku_base --max-usd 0.5 --rescore

문서 만들기: 헤드리스 모델은 `[[NAME1]]`·`[[PHONE1]]` 같은 자리표시만 넣은 문서 틀을 쓰고, 값은 이 파일의 코드가 시드로 만든 가짜 값(주민번호는 검증 숫자가 틀린 값, 카드는 9999 로 시작하는 가짜 번호,
계좌는 000 으로 시작, 전화는 5550 대역, 주소는 가짜 구·도로)으로 채운다. 그래서 정답은 모델의 기억이 아니라 코드가 안다.
채점은 전부 코드: 심은 값이 가린 글에 그대로 남아 있으면 놓침, 지켜야 할 값(금액·날짜·상호·주문번호)이 사라졌으면 과하게 가림.
가족 이름은 family 인자(FamilyTagger)로 넘기고, 가린 글에 `[가족:<id>]` 로 바뀌었는지 본다. 정답과 채점 기준은 점수를 보고 고치지 않는다."""

import argparse
import collections
import hashlib
import json
import random
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import common

SET_PATH = common.DATA / "mask_set.json"
SHA_PATH = common.DATA / "mask_set.sha256"

# 가상 가족(앱에 등록된 구성원): user_id, 이름
FAMILY = [("u-mom", "한서진"), ("u-dad", "오태윤"), ("u-son", "오지안"), ("u-daughter", "오하은")]

DOC_KINDS = [
    "병원 진료비 영수증",
    "약국 조제 영수증",
    "학교 가정통신문(담임 연락처 포함)",
    "학원 수강 등록 확인서",
    "택배 송장·배송 알림",
    "은행 이체 확인증",
    "카드 이용 내역 안내",
    "월세 임대차 계약 요약",
    "관리비 고지서",
    "보험 청구 접수 안내",
    "가족 단톡방 대화(반말, 이름만 부름)",
    "친구와 주고받은 문자 대화",
    "이력서·자기소개서 앞장",
    "관공서 민원 접수증",
    "예방접종 안내문",
    "여행 예약 확인서",
    "쇼핑몰 주문 확인 메일",
    "통신요금 청구서",
    "이사 업체 견적서",
    "미용실·세탁소 예약 메모",
    "아이 알레르기 안내(학교 제출용)",
    "자동차 정비 영수증",
    "헬스장 회원 가입서",
    "도서관 대출 안내",
    "경조사 봉투 명단 메모",
    "중고거래 채팅",
    "반려동물 병원 진료 메모",
    "보험 가입 증명서",
    "학부모 상담 신청서",
    "가족 간 용돈 입금 요청 문자",
    "수리 기사 방문 확인 문자",
    "동네 소모임 공지",
    "아파트 입주민 안내문",
    "병원 예약 확인 문자",
    "렌터카 예약 확인서",
    "육아 일기",
    "가계부 메모",
    "학교 비상연락망",
    "은행 대출 상담 안내",
    "택배 반품 접수 확인",
]  # 40 종. 5번에 나눠 8종씩 만들어 달라고 한다

PII_TYPES = ["NAME", "FAMILY", "PHONE", "RRN", "ACCOUNT", "CARD", "ADDR", "EMAIL", "BIRTH"]
KEEP_TYPES = ["AMOUNT", "DATE", "SHOP", "ORDERNO"]
PLACEHOLDER = re.compile(r"\[\[([A-Z]+)(\d+)(?::(G))?\]\]")

GEN_SYSTEM = (
    "당신은 개인정보 가리기 기능을 시험할 가상의 한국어 생활 문서를 쓰는 작가입니다. 실제 사람·업체·번호를 쓰지 않습니다.\n"
    "규칙\n"
    "- 값은 직접 쓰지 말고 자리표시만 씁니다. 자리표시 종류: [[NAME1]] 가족이 아닌 다른 사람 이름(성+이름), [[FAMILY1]]~[[FAMILY4]] 우리 가족 구성원 이름"
    "(FAMILY1 엄마, FAMILY2 아빠, FAMILY3 아들, FAMILY4 딸), [[PHONE1]] 전화번호, [[RRN1]] 주민등록번호, [[ACCOUNT1]] 계좌번호(은행 이름은 직접 씁니다), "
    "[[CARD1]] 카드번호, [[ADDR1]] 집·배송지 주소, [[EMAIL1]] 이메일, [[BIRTH1]] 생년월일, "
    "[[AMOUNT1]] 금액('원' 포함), [[DATE1]] 날짜, [[SHOP1]] 가게·기관 이름, [[ORDERNO1]] 주문·접수·거래 번호.\n"
    "- 같은 종류가 여러 개면 번호를 올립니다(NAME1, NAME2). 같은 값을 다시 쓰면 같은 자리표시를 씁니다.\n"
    "- 대화체 문서에서는 이름만 부르는 말에 [[NAME1:G]]·[[FAMILY3:G]] 처럼 ':G' 를 붙입니다(성을 뗀 이름만 들어갑니다). 호칭·조사는 자리표시 밖에 직접 씁니다(예: [[FAMILY3:G]]이는).\n"
    "- 문서마다 개인정보 자리표시(NAME·FAMILY·PHONE·RRN·ACCOUNT·CARD·ADDR·EMAIL·BIRTH)를 2~6개, 지켜져야 할 값(AMOUNT·DATE·SHOP·ORDERNO)을 2개 이상 넣습니다. 문서 종류에 어울리는 것만 자연스럽게 씁니다.\n"
    "- 문서 본문은 사진·스캔에서 읽은 것처럼 5~14줄, 줄바꿈은 \\n. 라벨('성명:', '연락처:', '주문번호:')을 실제 문서처럼 씁니다.\n"
    '- 출력은 JSON 배열 하나만: [{"kind": "요청한 문서 종류", "text": "본문"}, ...]. 설명·코드블록 표시 없이.'
)


# ---------- 가짜 값 만들기 ----------
SURNAMES = list("김이박최정강조윤장임한오서신권황안송류홍")
GIVENS = [
    "도현",
    "서아",
    "민재",
    "유나",
    "지후",
    "하윤",
    "시우",
    "예린",
    "준서",
    "소율",
    "건우",
    "다온",
    "태오",
    "나윤",
    "재민",
    "수빈",
    "은우",
    "세아",
    "현우",
    "아린",
]
SHOPS = [
    "초록약국",
    "달빛베이커리",
    "소담마트",
    "하늘안경원",
    "별빛서점",
    "푸른세탁소",
    "해오름학원",
    "나무치과",
    "새봄문구",
    "온누리정비소",
    "바람꽃미용실",
    "다솜동물병원",
]
BANKS = ["농협", "국민은행", "신한은행", "우리은행", "하나은행", "카카오뱅크", "토스뱅크"]
REGIONS = ["서울특별시", "경기도", "부산광역시", "대전광역시", "인천광역시"]
FAMILY_GIVENS = {n[1:] for _, n in FAMILY}
FAMILY_FULL = {n for _, n in FAMILY}


def _digits(rng: random.Random, n: int) -> str:
    return "".join(str(rng.randrange(10)) for _ in range(n))


def _rrn(rng: random.Random) -> str:
    """주민번호 모양(6-7). 검증 숫자가 틀리게 만들어 실제 번호가 될 수 없다."""
    while True:
        year = rng.randrange(1980, 2014)
        head = f"{year % 100:02d}{rng.randrange(1, 13):02d}{rng.randrange(1, 29):02d}"
        tail = str((1 if year < 2000 else 3) + rng.randrange(2)) + _digits(rng, 6)
        digits = head + tail
        weights = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
        check = (11 - sum(int(d) * w for d, w in zip(digits[:12], weights, strict=True)) % 11) % 10
        if int(digits[12]) != check:
            return f"{head}-{tail}"


def _card(rng: random.Random) -> str:
    """9999 로 시작하는 가짜 카드번호(발급사 없는 대역). 형식 검사(Luhn)는 통과한다."""
    body = [9, 9, 9, 9] + [rng.randrange(10) for _ in range(11)]
    total = 0
    for i, d in enumerate(
        reversed(body)
    ):  # 검증 자리는 맨 끝에 붙으니 지금 맨 끝 숫자는 뒤에서 2번째 자리
        d = d * 2 if i % 2 == 0 else d
        total += d - 9 if d > 9 else d
    digits = "".join(map(str, body)) + str((10 - total % 10) % 10)
    return "-".join(digits[i : i + 4] for i in range(0, 16, 4))


def _date_text(rng: random.Random, year: int) -> tuple[str, str]:
    y, m, d = year, rng.randrange(1, 13), rng.randrange(1, 29)
    style = rng.randrange(3)
    text = (f"{y}년 {m}월 {d}일", f"{y}.{m:02d}.{d:02d}", f"{y}-{m:02d}-{d:02d}")[style]
    return text, f"{y}{m:02d}{d:02d}"


def make_value(rng: random.Random, kind: str, given_only: bool, used: set[str]) -> dict:
    """자리표시 한 종류의 가짜 값. {"value": 글에 들어갈 글자, ...채점용 부가 정보}"""
    if kind == "NAME":
        while True:
            full = rng.choice(SURNAMES) + rng.choice(GIVENS)
            if full not in FAMILY_FULL and full[1:] not in FAMILY_GIVENS and full not in used:
                return {"value": full[1:] if given_only else full, "given": full[1:]}
    if kind == "PHONE":
        return {"value": f"010-555{rng.randrange(10)}-{_digits(rng, 4)}"}
    if kind == "RRN":
        return {"value": _rrn(rng)}
    if kind == "CARD":
        return {"value": _card(rng)}
    if kind == "ACCOUNT":
        value = (
            f"000-{_digits(rng, 2)}-{_digits(rng, 6)}"
            if rng.random() < 0.5
            else f"000-{_digits(rng, 6)}-{_digits(rng, 2)}-{_digits(rng, 3)}"
        )
        return {"value": value}
    if kind == "ADDR":
        road, no = rng.choice(["샘플로", "예시로", "테스트길"]), rng.randrange(3, 190)
        value = f"{rng.choice(REGIONS)} {rng.choice(['예시구', '샘플구', '가상구'])} {road} {no}, {rng.randrange(101, 112)}동 {rng.randrange(101, 2004)}호"
        return {"value": value, "core": f"{road} {no}"}
    if kind == "EMAIL":
        return {
            "value": f"{rng.choice(['sample.user', 'test.family', 'demo.mom', 'hello.kid'])}{rng.randrange(10, 99)}@example.com"
        }
    if kind == "BIRTH":
        text, norm = _date_text(rng, rng.randrange(1975, 2020))
        return {"value": text, "norm": norm}
    if kind == "AMOUNT":
        return {"value": f"{rng.randrange(350, 240000) * 10:,}원"}
    if kind == "DATE":
        text, norm = _date_text(rng, 2026)
        return {"value": text, "norm": norm}
    if kind == "SHOP":
        return {"value": rng.choice(SHOPS)}
    if kind == "ORDERNO":
        return {"value": f"2026{rng.randrange(1, 13):02d}-{_digits(rng, 5)}"}
    raise ValueError(kind)


def fill_template(template: str, rng: random.Random) -> tuple[str, list[dict], list[dict]] | None:
    """자리표시를 값으로 채운다. (글, 개인정보 정답, 지킬 값 정답). 모르는 자리표시가 있으면 None."""
    values: dict[tuple[str, str, bool], dict] = {}
    used_names: set[str] = set()
    bad = False

    def sub(m: re.Match) -> str:
        nonlocal bad
        kind, num, g = m.group(1), m.group(2), bool(m.group(3))
        if kind == "FAMILY":
            idx = int(num) - 1
            if not 0 <= idx < len(FAMILY) or g not in (True, False):
                bad = True
                return ""
            uid, full = FAMILY[idx]
            key = (kind, num, g)
            values.setdefault(
                key, {"value": full[1:] if g else full, "family_uid": uid, "given": full[1:]}
            )
            return values[key]["value"]
        if kind not in PII_TYPES + KEEP_TYPES:
            bad = True
            return ""
        if g and kind != "NAME":
            g = False
        base = (kind, num, False)  # 같은 번호의 이름은 같은 사람(성 붙은 꼴·뗀 꼴 모두)
        if base not in values:
            made = make_value(rng, kind, False, used_names)
            values[base] = made
            if kind == "NAME":
                used_names.add(made["value"])
        v = values[base]
        return v["given"] if g and kind == "NAME" else v["value"]

    text = PLACEHOLDER.sub(sub, template)
    if bad:
        return None
    pii: dict[tuple[str, str], dict] = {}
    keep: dict[str, dict] = {}
    for m in PLACEHOLDER.finditer(template):
        kind, num, g = m.group(1), m.group(2), bool(m.group(3))
        if kind == "FAMILY":
            v = values[(kind, num, g)]
            pii[(v["value"], kind)] = {
                "type": kind,
                "value": v["value"],
                "family_uid": v["family_uid"],
                "given": v["given"],
            }
        elif kind in PII_TYPES:
            v = values[(kind, num, False)]
            shown = v["given"] if (g and kind == "NAME") else v["value"]
            pii[(shown, kind)] = {
                "type": kind,
                "value": shown,
                **{k: x for k, x in v.items() if k not in ("value",)},
            }
        else:
            v = values[(kind, num, False)]
            keep[v["value"]] = {
                "type": kind,
                "value": v["value"],
                **{k: x for k, x in v.items() if k != "value"},
            }
    return text, list(pii.values()), list(keep.values())


# ---------- 문서 만들기(gen) ----------
def _json_array(text: str) -> list:
    match = re.search(r"\[.*\]", text, re.S)
    if match is None:
        raise ValueError("JSON 배열 없음")
    return json.loads(match.group(0))


def generate(seed: int, force: bool) -> None:
    if SET_PATH.exists() and not force:
        raise SystemExit(
            f"{SET_PATH.name} 이 이미 있어요(정답은 잠겨 있어요). 다시 만들려면 --force"
        )
    groups = [DOC_KINDS[i : i + 8] for i in range(0, len(DOC_KINDS), 8)]

    def ask(kinds: list[str]) -> tuple[list, float]:
        user = f"다음 문서 종류마다 한 건씩, 총 {len(kinds)}건을 쓰세요(종류마다 내용이 서로 다르게).\n"
        user += "\n".join(f"- {k}" for k in kinds)
        user += (
            "\n이 중 최소 2건은 주민등록번호([[RRN1]]), 최소 2건은 카드번호([[CARD1]]), "
            "최소 2건은 이메일([[EMAIL1]])이 어울리는 방식으로 넣으세요(문서 종류에 맞게 라벨과 함께)."
        )
        for _ in range(3):
            try:
                out, usd = common.headless(GEN_SYSTEM, user)
                return _json_array(out), usd
            except (ValueError, json.JSONDecodeError, KeyError):
                continue
        raise SystemExit("문서 틀을 만들지 못했어요(헤드리스 응답 형식 오류 3회)")

    with ThreadPoolExecutor(max_workers=len(groups)) as ex:
        results = list(ex.map(ask, groups))
    templates = [t for arr, _ in results for t in arr if isinstance(t, dict) and t.get("text")]
    docs, dropped = [], 0
    for t in templates:
        rng = random.Random(f"{seed}-{len(docs)}")
        filled = fill_template(str(t["text"]), rng)
        if filled is None:
            dropped += 1
            continue
        text, pii, keep = filled
        if len(pii) < 1 or len(keep) < 1:
            dropped += 1
            continue
        docs.append(
            {
                "id": f"m{len(docs):02d}",
                "kind": str(t.get("kind", "")),
                "text": text,
                "pii": pii,
                "keep": keep,
            }
        )
    payload = {
        "meta": {
            "seed": seed,
            "generated": datetime.now().isoformat(timespec="seconds"),
            "generator": "claude -p --model sonnet (헤드리스, API 키 제외)",
            "headless_calls": len(groups),
            "headless_notional_usd": round(sum(u for _, u in results), 4),
            "dropped_templates": dropped,
            "family": [{"user_id": u, "name": n} for u, n in FAMILY],
        },
        "docs": docs,
    }
    common.save_json(SET_PATH, payload)
    digest = hashlib.sha256(SET_PATH.read_bytes()).hexdigest()
    SHA_PATH.write_text(digest + "\n", encoding="utf-8")
    kinds = collections.Counter(p["type"] for d in docs for p in d["pii"])
    print(
        f"문서 {len(docs)}건 (버린 틀 {dropped}), 심은 개인정보 {sum(kinds.values())}: {dict(kinds)}"
    )
    print(f"sha256 {digest}")


def load_locked_set() -> dict:
    if not SET_PATH.exists() or not SHA_PATH.exists():
        raise SystemExit("평가 문서가 없어요. 먼저: python eval/upload/mask_eval.py gen")
    digest = hashlib.sha256(SET_PATH.read_bytes()).hexdigest()
    if digest != SHA_PATH.read_text(encoding="utf-8").strip():
        raise SystemExit(
            "mask_set.json 이 잠근 sha256 과 달라요(정답이 바뀐 것 같아요). 평가를 멈춥니다."
        )
    return json.loads(SET_PATH.read_text(encoding="utf-8"))


# ---------- 채점 ----------
TOKEN_RE = re.compile(
    r"\[(?:이름|주소|연락처|이메일|주민번호|카드번호|계좌번호|생년월일|신분증번호|비밀번호|가족:[^\]]+|확인필요:[^\]]+)\]"
)


def _digits_only(text: str) -> str:
    return re.sub(r"\D", "", text)


def leaked(item: dict, masked: str) -> str:
    """심은 값이 가린 글에 남았나. 'none' | 'partial' | 'full'."""
    kind, value = item["type"], item["value"]
    if value in masked:
        return "full"
    if kind in ("NAME", "FAMILY"):
        given = item.get("given", value[1:])
        return "partial" if len(given) >= 2 and given in masked else "none"
    if kind in ("RRN", "CARD", "ACCOUNT", "PHONE"):
        return "full" if _digits_only(value) in _digits_only(masked) else "none"
    if kind == "BIRTH":
        return "full" if item["norm"] in re.sub(r"\D", "", masked) else "none"
    if kind == "ADDR":
        return "partial" if item["core"] in masked else "none"
    return "none"


def score_doc(doc: dict, masked: str, counts: dict) -> dict:
    """한 문서의 채점 원자료."""
    out: dict = {"leak": {}, "keep": {}, "family": {}}
    for item in doc["pii"]:
        status = leaked(item, masked)
        row = out["leak"].setdefault(item["type"], {"n": 0, "full": 0, "partial": 0})
        row["n"] += 1
        if status != "none":
            row[status] += 1
        if item["type"] == "FAMILY":
            tag = f"[가족:{item['family_uid']}]"
            f = out["family"].setdefault(
                "n", {"n": 0, "tagged": 0, "left_raw": 0, "wrong_token": 0}
            )
            f["n"] += 1
            if status != "none":
                f["left_raw"] += 1
            elif tag in masked:
                f["tagged"] += 1
            else:
                f["wrong_token"] += (
                    1  # 글자는 사라졌지만 [가족:id] 가 아니다([이름] 등으로 일반 이름처럼 가림)
                )
    for item in doc["keep"]:
        row = out["keep"].setdefault(item["type"], {"n": 0, "removed": 0})
        row["n"] += 1
        row["removed"] += item["value"] not in masked
    expected = len(doc["pii"])
    out["tokens"] = len(TOKEN_RE.findall(masked))
    out["expected_tokens_min"] = expected
    out["counts"] = counts
    return out


def summarize(rows: list[dict]) -> dict:
    leak: dict = collections.defaultdict(lambda: collections.Counter())
    keep: dict = collections.defaultdict(lambda: collections.Counter())
    fam: collections.Counter = collections.Counter()
    extra_tokens = docs_with_extra = 0
    for r in rows:
        for k, v in r["leak"].items():
            leak[k].update(v)
        for k, v in r["keep"].items():
            keep[k].update(v)
        fam.update(r["family"].get("n", {}))
        # 같은 값이 여러 번 나오면 토큰이 더 많아져서, 문서마다 토큰 수가 심은 값 수보다 많은 만큼만 센다(대략치)
        extra = max(0, r["tokens"] - r["expected_tokens_min"])
        extra_tokens += extra
        docs_with_extra += extra > 0
    pii_n = sum(v["n"] for v in leak.values())
    pii_full = sum(v["full"] for v in leak.values())
    pii_part = sum(v["partial"] for v in leak.values())
    keep_n = sum(v["n"] for v in keep.values())
    keep_removed = sum(v["removed"] for v in keep.values())
    return {
        "docs": len(rows),
        "pii_n": pii_n,
        "recall_pct": round(100 * (pii_n - pii_full - pii_part) / max(1, pii_n), 1),
        "recall_lenient_pct": round(100 * (pii_n - pii_full) / max(1, pii_n), 1),
        "missed_full": pii_full,
        "missed_partial": pii_part,
        "by_type": {
            k: {
                "n": v["n"],
                "missed_full": v["full"],
                "missed_partial": v["partial"],
                "recall_pct": round(100 * (v["n"] - v["full"] - v["partial"]) / max(1, v["n"]), 1),
            }
            for k, v in sorted(leak.items())
        },
        "keep_n": keep_n,
        "overmask_pct": round(100 * keep_removed / max(1, keep_n), 1),
        "overmask_by_type": {
            k: {"n": v["n"], "removed": v["removed"]} for k, v in sorted(keep.items())
        },
        "family": {
            "n": fam["n"],
            "tagged_ok": fam["tagged"],
            "left_raw": fam["left_raw"],
            "wrong_token": fam["wrong_token"],
            "tagged_pct": round(100 * fam["tagged"] / max(1, fam["n"]), 1),
        },
        "extra_tokens_approx": extra_tokens,
        "docs_with_extra_tokens": docs_with_extra,
    }


# ---------- 평가(run) ----------
_acc = threading.local()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen", help="평가 문서와 정답 만들기(헤드리스)")
    g.add_argument("--seed", type=int, default=11)
    g.add_argument("--force", action="store_true")
    r = sub.add_parser("run", help="서비스 mask 로 평가")
    r.add_argument("--name", required=True, help="결과 파일 이름: runs/mask_<이름>.json")
    r.add_argument(
        "--max-usd",
        type=float,
        required=True,
        help="누적 API 비용 상한(닿으면 새 문서를 시작하지 않는다)",
    )
    r.add_argument("--limit", type=int, default=0, help="앞에서 이 수만큼만(시범용). 0 이면 전부")
    r.add_argument("--workers", type=int, default=2)
    r.add_argument("--no-family", action="store_true", help="family 인자를 넘기지 않는다")
    r.add_argument("--rescore", action="store_true")
    args = ap.parse_args()

    if args.cmd == "gen":
        generate(args.seed, args.force)
        return

    data = load_locked_set()
    docs = data["docs"][: args.limit] if args.limit else data["docs"]
    sha = SHA_PATH.read_text(encoding="utf-8").strip()

    common.prepare_service_import()
    from app.features.ai_assistant.family_names import FamilyTagger, Member
    from app.features.ai_assistant.ingest import llm_ingest
    from app.shared.config import settings
    from app.shared.llm import doc_ai

    model = settings.ingest_mask_model or settings.llm_model
    price_in, price_out = common.price_of(model)
    real_find = doc_ai.find_pii

    def counted_find(text, candidates=None):
        found = real_find(text, candidates)
        acc = getattr(_acc, "v", None)
        if acc is not None:
            acc[0] += found.input_tokens
            acc[1] += found.output_tokens
            acc[2] += 1
        return found

    doc_ai.find_pii = counted_find  # 서비스 코드는 그대로, 토큰만 센다

    meta = {
        "model": model,
        "price_per_mtok": {"in": price_in, "out": price_out},
        "set_sha256": sha,
        "set_seed": data["meta"]["seed"],
        "family_arg": not args.no_family,
        "docs": len(docs),
    }
    path = common.RUNS / f"mask_{args.name}.json"
    run = {"meta": meta, "docs": {}}
    if path.exists():
        prev = common.load_json(path)
        if any(
            prev["meta"].get(k) != meta[k] for k in ("model", "set_sha256", "family_arg", "docs")
        ):
            raise SystemExit(
                f"{path.name} 의 설정(모델·문서 세트·family·문서 수)이 달라요. 다른 --name 을 쓰세요."
            )
        run = prev
    run["meta"]["updated"] = datetime.now().isoformat(timespec="seconds")
    done = run["docs"]
    budget = common.Budget(args.max_usd, sum(d.get("usd", 0) for d in done.values()))
    members = [Member(uid, name) for uid, name in FAMILY]
    todo = [d for d in docs if d["id"] not in done or "error" in done[d["id"]]]
    if args.rescore:
        todo = []
    print(
        f"문서 {len(docs)}건, 남은 {len(todo)}건, 모델 {model}, family {'없음' if args.no_family else '4명'}"
    )
    stopped = False

    def work(doc: dict) -> None:
        nonlocal stopped
        if budget.exhausted():
            stopped = True
            return
        _acc.v = [0, 0, 0]
        try:
            family = None if args.no_family else FamilyTagger(members)
            masked, counts, _sensitive = llm_ingest.mask(doc["text"], family)
            tin, tout, calls = _acc.v
            row = {
                "masked": masked,
                "counts": counts,
                "in": tin,
                "out": tout,
                "calls": calls,
                "usd": round(common.cost_of(model, tin, tout), 6),
            }
            budget.add(row["usd"])
        except Exception as exc:  # 종류만 적는다
            tin, tout, _ = _acc.v
            row = {"error": type(exc).__name__, "usd": round(common.cost_of(model, tin, tout), 6)}
            budget.add(row["usd"])
        done[doc["id"]] = row
        common.save_json(path, run)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(work, todo))

    ok = [d for d in docs if d["id"] in done and "error" not in done[d["id"]]]
    scored = {d["id"]: score_doc(d, done[d["id"]]["masked"], done[d["id"]]["counts"]) for d in ok}
    by_kind: dict[str, list] = collections.defaultdict(list)
    for d in ok:
        by_kind[d["kind"]].append(scored[d["id"]])
    run["metrics"] = summarize(list(scored.values())) if scored else {}
    run["per_doc"] = {
        k: {"leak": v["leak"], "keep": v["keep"], "tokens": v["tokens"]} for k, v in scored.items()
    }
    run["cost"] = {
        "api_usd": round(sum(d.get("usd", 0) for d in done.values()), 5),
        "input_tokens": sum(d.get("in", 0) for d in done.values()),
        "output_tokens": sum(d.get("out", 0) for d in done.values()),
        "max_usd": args.max_usd,
        "stopped_by_budget": stopped,
        "docs_done": len(ok),
        "docs_failed": [d["id"] for d in docs if d["id"] in done and "error" in done[d["id"]]],
        "docs_not_started": [d["id"] for d in docs if d["id"] not in done],
    }
    common.save_json(path, run)

    m = run["metrics"]
    print(
        f"\n완료 {len(ok)}건, 실패 {len(run['cost']['docs_failed'])}, 미시작 {len(run['cost']['docs_not_started'])}, API 비용 ${run['cost']['api_usd']} (상한 ${args.max_usd})"
    )
    if m:
        print(
            f"재현율 {m['recall_pct']}% (일부 남음 포함 {m['recall_lenient_pct']}%), 놓침 전부 {m['missed_full']} / 일부 {m['missed_partial']} / 심은 값 {m['pii_n']}"
        )
        for k, v in m["by_type"].items():
            print(
                f"  {k:8s} n={v['n']:3d} 재현율 {v['recall_pct']}% (놓침 {v['missed_full']}, 일부 {v['missed_partial']})"
            )
        print(
            f"과하게 가림(지킬 값 사라짐) {m['overmask_pct']}% / {m['keep_n']}  {m['overmask_by_type']}"
        )
        print(f"가족 이름 {m['family']}")
    print(f"저장: {path}")


if __name__ == "__main__":
    main()
