"""문서 검색 섞기: 임베딩 후보 안에서 글자 TF-IDF 로 다시 순위를 매겨 두 순위를 합친다(DB·모델 변경 없음).

임베딩은 뜻은 잘 잡지만 고유명사·숫자·낱말 그대로의 일치에 약하다. 글자 2·3개 묶음(한글은 조사가 붙어도 묶음이 겹쳐 걸린다)의
TF-IDF 코사인을 임베딩 순위와 RRF(순위 합치기)로 섞는다. TF-IDF 만 쓰면 오히려 나빠지므로(가족 문서 Hit@1 84.8%) 반드시 섞는다.
idf 는 후보 묶음 기준으로 계산한다(후보 묶음이 작아도 전체 조각 대상 섞기의 효과 대부분이 유지된다. 근거는
docs/features/ai_assistant-knowledge-hybrid.md).
"""

import math
import re
from collections import Counter
from functools import lru_cache

RRF_K = 60  # 순위 합치기 상수. 순위가 낮은 쪽의 영향이 너무 빨리 줄지 않게 하는 흔한 값
_TOKEN = re.compile(r"[가-힣]+|[a-z]+|\d+")


@lru_cache(maxsize=4096)
def _grams(text: str) -> Counter:
    """한글은 글자 2·3개 묶음, 영문·숫자는 낱말. 같은 조각을 질문마다 다시 쪼개지 않게 글 단위로 캐시한다."""
    out: list[str] = []
    for word in _TOKEN.findall(text.lower()):
        if "가" <= word[0] <= "힣":
            out += [word[i : i + 2] for i in range(max(1, len(word) - 1))]
            out += [word[i : i + 3] for i in range(len(word) - 2)]
        else:
            out.append(word)
    return Counter(out)


def tfidf_scores(query: str, texts: list[str]) -> list[float]:
    """질문과 각 글의 TF-IDF 코사인(sublinear tf, idf 는 texts 기준). 질문에 묶음이 없으면 모두 0."""
    docs = [_grams(t) for t in texts]
    q = Counter(_grams(query))
    if not docs or not q:
        return [0.0] * len(texts)
    df: Counter = Counter()
    for d in docs:
        df.update(d.keys())
    n = len(docs)
    idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}

    def weigh(tf: Counter, only: set | None = None) -> dict[str, float]:
        return {
            t: (1 + math.log(c)) * idf.get(t, 0.0)
            for t, c in tf.items()
            if only is None or t in only
        }

    qv = weigh(q)
    qnorm = math.sqrt(sum(x * x for x in qv.values())) or 1.0
    scores = []
    for d in docs:
        dv = weigh(d)
        dnorm = math.sqrt(sum(x * x for x in dv.values())) or 1.0
        dot = sum(w * dv[t] for t, w in qv.items() if t in dv)
        scores.append(dot / (qnorm * dnorm))
    return scores


def fuse_order(query: str, texts: list[str], weight: float = 1.0) -> list[int]:
    """texts 는 임베딩 점수 순(가까운 것이 앞). 임베딩 순위와 TF-IDF 순위를 RRF 로 섞은 새 순서(원래 위치 번호)를 돌려준다.
    글자 일치가 하나도 없으면 원래 순서 그대로다."""
    scores = tfidf_scores(query, texts)
    if not any(scores):
        return list(range(len(texts)))
    by_text = sorted(range(len(texts)), key=lambda i: -scores[i])
    text_rank = {i: r for r, i in enumerate(by_text, 1)}
    return sorted(
        range(len(texts)), key=lambda i: -(1 / (RRF_K + i + 1) + weight / (RRF_K + text_rank[i]))
    )
