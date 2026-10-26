"""문서 분류기 학습 스크립트(개발용 — 서버 런타임에서는 쓰지 않는다).

e5-small 파인튜닝 임베딩(384차원) 과 글자 TF-IDF 를 이어 붙여 로지스틱 회귀를 학습하고,
서버가 numpy 만으로 읽을 수 있는 파일(`app/features/ai_assistant/ingest/doc_classifier.py`)로 저장한다.
scikit-learn·scipy·onnxruntime·tokenizers 가 있는 환경에서 돌린다(서버 의존성에는 넣지 않는다).

    # 평가: 종류 40개로 학습해 시험 점수를 출력한다
    python scripts/train_doc_classifier.py --eval --data ft_data.json ft_data_big.json --real pool_d_raw.json
    # 최종: held-out 6종류까지 46개로 학습해 data/models/doc-classifier 에 저장한다
    python scripts/train_doc_classifier.py --data ft_data.json ft_data_big.json
    # 테스트용 아주 작은 기준 파일(sklearn 출력 포함)을 만든다
    python scripts/train_doc_classifier.py --fixture-out app/features/ai_assistant/ingest/tests/data/doc_classifier

학습 데이터(ft_data*.json)는 저장소에 두지 않고 --data 로 받는다. 산출물(data/models)도 저장소에 올리지 않고 zip 으로 공유한다.
"""

import argparse
import json
import re
import urllib.parse
from pathlib import Path

import numpy as np

API_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = API_ROOT / "data" / "models" / "doc-classifier"
DEFAULT_EMBED_DIR = API_ROOT / "data" / "models" / "e5-small-ft"

NGRAM = (2, 4)
TFIDF_WEIGHT = 0.6
THRESHOLD = 0.7
C = 20
MAX_CHARS = 3000  # 서버가 분류기에 넘기는 글자 수와 같다
UNKNOWN = "(모름)"

# 학습·시험 글에는 "분류: <정답>"·"- 태그:" 줄이 들어 있었다. 서비스에서 분류기가 받는 글(가린 본문)에는 없는 줄이라
# 그대로 두면 정답을 베껴 점수가 부풀려진다 → 모든 글에서 지운다. 스캔 문서 본문에는 제목 줄(# …)도 없어서 제목 없는 글도 같이 배운다
_LEAK = re.compile(r"(?m)^(?:분류\s*:|-\s*태그\s*:).*\n?")
_TITLE = re.compile(r"\A#[^\n]*\n")


def clean_text(text: str) -> str:
    return _LEAK.sub("", text)


def untitled(text: str) -> str:
    return _TITLE.sub("", clean_text(text), count=1)


# 실제 기록(pool_d_raw.json) 중 정답이 있는 파일. None 이면 학습 종류에 없는 문서("모름"이 정답)
REAL_GOLD = {
    "receipt_mart.jpg": "마트 영수증", "bill_electric.jpg": "전기요금 고지서", "prescription.jpg": "약국 처방전",
    "id_card.png": None, "bankbook.jpg": None, "family_relation.jpg": "가족관계증명서",
    "school_notice.jpg": "학교 가정통신문", "hospital_bill.jpg": "병원 진료 내역서",
    "health_checkup_text.pdf": None, "academy_notice_text.pdf": None, "insurance_scan.pdf": None,
    "jeju_trip.pptx": "여행 일정 슬라이드", "household_ledger.xlsx": "가계부 시트", "lease_contract.docx": None,
    "memo_shopping.txt": None, "card_history_cp949.csv": "카드 이용명세서",
    "inject_family_gathering.txt": None, "inject_parent_meeting.docx": "학교 가정통신문",
}  # fmt: skip


# ---------------------------------------------------------------- 임베딩
class E5:
    """서버의 OnnxE5Embedder 와 같은 계산(접두어 "passage: ", 최대 512 토큰, 평균 풀링, L2 정규화)."""

    def __init__(self, model_dir: Path, max_length: int = 512, batch: int = 16) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.session = ort.InferenceSession(
            str(model_dir / "model.onnx"), providers=["CPUExecutionProvider"]
        )
        self.tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tok.no_padding()
        self.tok.enable_truncation(max_length)
        self.pad = self.tok.token_to_id("<pad>") or 1
        self.batch = batch

    def passages(self, texts: list[str]) -> np.ndarray:
        encs = self.tok.encode_batch(["passage: " + t[:MAX_CHARS] for t in texts])
        order = sorted(
            range(len(texts)), key=lambda i: len(encs[i].ids)
        )  # 길이가 비슷한 것끼리 묶어 빠르게
        out = np.zeros((len(texts), 384), np.float32)
        for start in range(0, len(order), self.batch):
            idx = order[start : start + self.batch]
            width = max(len(encs[j].ids) for j in idx)
            ids = np.full((len(idx), width), self.pad, np.int64)
            mask = np.zeros((len(idx), width), np.int64)
            for row, j in enumerate(idx):
                n = len(encs[j].ids)
                ids[row, :n], mask[row, :n] = encs[j].ids, 1
            hidden = self.session.run(None, {"input_ids": ids, "attention_mask": mask})[0]
            m = mask[..., None].astype(np.float32)
            pooled = (hidden * m).sum(1) / np.maximum(m.sum(1), 1e-9)
            pooled /= np.linalg.norm(pooled, axis=1, keepdims=True) + 1e-12
            out[idx] = pooled
        return out


# ---------------------------------------------------------------- 학습
def fit(texts: list[str], emb: np.ndarray, labels: list[str], max_features: int):
    """(TfidfVectorizer, LogisticRegression). 입력 = [임베딩, TF-IDF * 0.6]."""
    from scipy.sparse import csr_matrix, hstack
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression

    tv = TfidfVectorizer(
        analyzer="char_wb", ngram_range=NGRAM, sublinear_tf=True, max_features=max_features
    )
    tfidf = tv.fit_transform([t[:MAX_CHARS] for t in texts])
    x = hstack([csr_matrix(emb * 1.0), tfidf * TFIDF_WEIGHT]).tocsr()
    return tv, LogisticRegression(C=C, max_iter=3000).fit(x, np.array(labels))


def predict_proba(tv, model, texts: list[str], emb: np.ndarray) -> np.ndarray:
    from scipy.sparse import csr_matrix, hstack

    tfidf = tv.transform([t[:MAX_CHARS] for t in texts])
    return model.predict_proba(hstack([csr_matrix(emb * 1.0), tfidf * TFIDF_WEIGHT]).tocsr())


def save(out: Path, tv, model, n_train: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    classes = [str(c) for c in model.classes_]
    vocab = {term: int(i) for term, i in tv.vocabulary_.items()}
    (out / "classes.json").write_text(json.dumps(classes, ensure_ascii=False), encoding="utf-8")
    (out / "vocab.json").write_text(json.dumps(vocab, ensure_ascii=False), encoding="utf-8")
    np.save(out / "coef.npy", model.coef_.astype(np.float32))
    np.save(out / "intercept.npy", model.intercept_.astype(np.float32))
    np.save(out / "idf.npy", tv.idf_.astype(np.float32))
    config = {
        "ngram_range": list(NGRAM),
        "tfidf_weight": TFIDF_WEIGHT,
        "threshold": THRESHOLD,
        "n_classes": len(classes),
        "n_features": len(vocab),
        "embed_dim": 384,
        "max_chars": MAX_CHARS,
        "n_train": n_train,
        "C": C,
    }
    (out / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------- 데이터
def load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def training_set(old: dict, big: dict | None, with_held_out: bool, extra: list[dict] = ()):
    """(글, 종류) 목록. 학습 문서 + 변형 2개씩 + `--extra` 새 종류 문서(split=train).

    최종 모드는 held-out 종류의 test_unseen 문서도 넣는다. 정답 줄은 지우고, 제목 줄이 있는 글은 제목 없는 복사본도 더한다."""
    rows = [(d["text"], d["label"]) for d in old["docs"] if d["split"] == "train"]
    for d in old["docs"]:
        if d["split"] == "train":
            rows += [(v, d["label"]) for v in (d.get("variants") or [])[:2]]
    n_base = len(rows)
    if with_held_out:
        for data in (old, big):
            if data:
                rows += [
                    (d["text"], d["label"]) for d in data["docs"] if d["split"] == "test_unseen"
                ]
    for data in extra:
        rows += [(d["text"], d["label"]) for d in data["docs"] if d["split"] == "train"]
    rows = [(clean_text(t), y) for t, y in rows]
    rows += [(untitled(t), y) for t, y in list(rows) if _TITLE.match(t)]
    return rows, n_base


def get_embeddings(
    embedder_dir: Path, texts: list[str], cache: dict | None, key: str
) -> np.ndarray:
    if cache is not None and key in cache and len(cache[key]) == len(texts):
        return cache[key]
    print(f"  임베딩 계산 {key}: {len(texts)}건", flush=True)
    return E5(embedder_dir).passages(texts)


def run_eval(args, old: dict, big: dict, extra: list[dict]) -> None:
    vocab = {k["label"] for k in old["kinds"] if not k["hold"]} | {
        label for data in extra for label in data["kinds"]
    }
    train, _ = training_set(old, big, with_held_out=False, extra=extra)
    cache = None  # 정답 줄을 지운 글로 다시 계산하므로 예전 임베딩 캐시는 쓰지 않는다
    rng = np.random.RandomState(0)
    big_test = [d["text"] for d in big["docs"] if d["split"] == "test"]
    big_unseen = [d["text"] for d in big["docs"] if d["split"] == "test_unseen"]
    old_unseen = [d["text"] for d in old["docs"] if d["split"] == "test_unseen"]
    bi = rng.choice(len(big_test), 600, replace=False)
    ui = rng.choice(len(big_unseen), 200, replace=False)
    unseen = old_unseen + [big_unseen[i] for i in ui]
    hand = [(d["text"], d["label"] if d["label"] in vocab else None) for d in old["hand_docs"]]
    real = []
    if args.real:
        for r in load_json(args.real):
            f = urllib.parse.unquote(r["file"])
            if f in REAL_GOLD:
                real.append((r["text"], REAL_GOLD[f]))
    pools = {
        "모름합성": ([clean_text(t) for t in unseen], [None] * len(unseen)),
        "B": ([clean_text(t) for t, _ in hand], [g for _, g in hand]),
        "D": ([clean_text(t) for t, _ in real], [g for _, g in real]),
    }
    new_test = [
        (d["text"], d["label"]) for data in extra for d in data["docs"] if d["split"] == "test"
    ]
    if new_test:  # 새 종류의 처음 보는 글 모양(학습에 쓰지 않은 모양)
        pools["새종류"] = ([t for t, _ in new_test], [g for _, g in new_test])
    print(f"학습 {len(train)}건 / 종류 {len(vocab)}개", flush=True)
    # 캐시의 풀 이름은 한글 키라 그대로 맞춘다(구 / 신 은 평가에 쓰지 않는다)
    tr_emb = get_embeddings(args.embed_dir, [t for t, _ in train], cache, "tr")
    pool_emb = {p: get_embeddings(args.embed_dir, v[0], cache, p) for p, v in pools.items()}
    big_test_texts = [clean_text(big_test[i]) for i in bi]
    big_emb = get_embeddings(args.embed_dir, big_test_texts, cache, "신")
    for mf in args.max_features:
        tv, model = fit([t for t, _ in train], tr_emb, [y for _, y in train], mf)
        print(f"== max_features={mf} (실제 {len(tv.vocabulary_)})")
        for name, (texts, gold) in pools.items():
            proba = predict_proba(tv, model, texts, pool_emb[name])
            said = [
                str(model.classes_[p.argmax()]) if p.max() >= THRESHOLD else UNKNOWN for p in proba
            ]
            known = [(s, g) for s, g in zip(said, gold, strict=True) if g is not None]
            unk = [(s, g) for s, g in zip(said, gold, strict=True) if g is None]
            print(
                f"  {name}: 아는 종류 {sum(s == g for s, g in known)}/{len(known)}"
                f"  모름 {sum(s == UNKNOWN for s, _ in unk)}/{len(unk)}"
            )
        gold_big = [d["label"] for d in big["docs"] if d["split"] == "test"]
        gold_big = [gold_big[i] for i in bi]
        proba = predict_proba(tv, model, big_test_texts, big_emb)
        said = [str(model.classes_[p.argmax()]) if p.max() >= THRESHOLD else UNKNOWN for p in proba]
        print(
            f"  신(합성 아는 종류 600): {sum(s == g for s, g in zip(said, gold_big, strict=True))}/600"
        )
        if args.save_eval:
            save(Path(args.save_eval), tv, model, len(train))
            print(f"  저장: {args.save_eval}")


def run_final(args, old: dict, big: dict | None, extra: list[dict]) -> None:
    train, n_base = training_set(old, big, with_held_out=True, extra=extra)
    print(f"학습 {len(train)}건 (기본 {n_base} + 나머지 {len(train) - n_base})", flush=True)
    emb = E5(args.embed_dir).passages([t for t, _ in train])
    mf = args.max_features[0]
    tv, model = fit([t for t, _ in train], emb, [y for _, y in train], mf)
    save(Path(args.out), tv, model, len(train))
    size = sum(f.stat().st_size for f in Path(args.out).iterdir())
    print(f"저장: {args.out} (종류 {len(model.classes_)}개, 합계 {size / 1e6:.1f}MB)")


# ---------------------------------------------------------------- 테스트용 기준 파일
TOY = {
    "병원 진료 안내": [
        "진료 예약 안내 내과 외래 방문 시 신분증을 지참하세요",
        "검사 안내 금식 후 오전 9시까지 병원 접수처로 오세요",
        "입원 및 퇴원 절차 안내 원무과",
        "Hospital visit: bring your ID card",
    ],
    "학교 가정통신문": [
        "학부모님께 현장체험학습 안내 참가 신청서를 제출해 주세요",
        "방과후 학교 수강 신청 안내 담임선생님",
        "급식 식단 안내 및 학교 행사 일정",
        "School notice for parents",
    ],
    "아파트 관리사무소 공지": [
        "관리사무소 공지 승강기 점검으로 운행이 중지됩니다",
        "주차장 도장 공사 안내 차량 이동 부탁드립니다",
        "단지 내 소독 일정 안내 입주민 여러분",
        "Apartment notice: elevator inspection",
    ],
}
TOY_QUERIES = [
    "학부모님 현장체험학습 신청서 제출",
    "내과 진료 예약 방문 안내",
    "엘리베이터 점검 공지  입주민   여러분",
    "A  b C 가 나다 라마바사",
    "병원 PARKING 주차장 공사",
    "x",
    "",
]


def make_fixture(out: Path) -> None:
    rng = np.random.RandomState(7)
    kinds = sorted(TOY)
    centers = {k: rng.randn(384) for k in kinds}

    def fake_embed(label: str, noise: float) -> np.ndarray:
        v = centers[label] + rng.randn(384) * noise
        return (v / np.linalg.norm(v)).astype(np.float32)

    texts, labels, embs = [], [], []
    for k in kinds:
        for t in TOY[k]:
            texts.append(t)
            labels.append(k)
            embs.append(fake_embed(k, 2.0))
    tv, model = fit(texts, np.vstack(embs), labels, 400)
    save(out, tv, model, len(texts))
    # 질문 글마다 가짜 임베딩(서로 다른 종류에 가깝게)을 붙여 sklearn 확률을 기준으로 저장한다
    cases = []
    for i, q in enumerate(TOY_QUERIES):
        e = fake_embed(kinds[i % len(kinds)], 3.0)
        p = predict_proba(tv, model, [q], e[None, :])[0]
        cases.append({"text": q, "emb": [float(x) for x in e], "proba": [float(x) for x in p]})
    ref = {"classes": [str(c) for c in model.classes_], "cases": cases}
    (out / "reference.json").write_text(json.dumps(ref, ensure_ascii=False), encoding="utf-8")
    print(f"기준 파일 저장: {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument(
        "--data", nargs="+", help="학습 JSON 경로들(첫째 ft_data.json, 둘째 ft_data_big.json)"
    )
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="분류기 출력 폴더")
    ap.add_argument("--eval", action="store_true", help="종류 40개로 학습해 점수를 출력한다")
    ap.add_argument("--real", help="평가용 실제 파이프라인 기록(pool_d_raw.json)")
    ap.add_argument(
        "--extra", nargs="*", default=[], help="새 종류 학습 JSON(kinds, docs[label,text,split])"
    )
    ap.add_argument("--emb-cache", help="(쓰지 않음) 정답 줄을 지운 글을 매번 다시 임베딩한다")
    ap.add_argument("--embed-dir", type=Path, default=DEFAULT_EMBED_DIR, help="e5 ONNX 모델 폴더")
    ap.add_argument(
        "--max-features",
        type=int,
        nargs="+",
        default=[30000],
        help="TF-IDF 낱말 수(평가 모드는 여러 개 비교)",
    )
    ap.add_argument("--save-eval", help="평가 모드에서 마지막 모델을 이 폴더에 저장한다")
    ap.add_argument(
        "--fixture-out", help="테스트용 작은 분류기와 sklearn 기준 출력을 이 폴더에 만든다"
    )
    args = ap.parse_args()
    if args.fixture_out:
        make_fixture(Path(args.fixture_out))
        return
    if not args.data:
        ap.error("--data 가 필요하다")
    old = load_json(args.data[0])
    big = load_json(args.data[1]) if len(args.data) > 1 else None
    extra = [load_json(p) for p in args.extra]
    if args.eval:
        if big is None:
            ap.error("--eval 에는 --data 두 개(ft_data.json, ft_data_big.json)가 필요하다")
        run_eval(args, old, big, extra)
    else:
        run_final(args, old, big, extra)


if __name__ == "__main__":
    main()
