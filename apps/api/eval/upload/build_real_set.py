"""실제 문서 양식 + 가상 개인정보 이미지 평가셋 만들기.

    python eval/upload/build_real_set.py fetch                  # 법제처 별지 서식 PDF 내려받기 + sources.json
    python eval/upload/build_real_set.py build [--seed 20261110] [--force]   # 값 채우기 + 사진판 + 정답 + 잠금

양식은 법령 별지 서식(저작권법 제7조, 자유 이용). 값은 전부 코드가 시드로 만든 가짜 값이다(mask_eval.make_value 와 같은 규칙:
전화 010-555x, 카드 9999 대역, 계좌 000-, 주민번호 검증 숫자 틀림, 이메일 example.com, 가상 주소, 가상 가족 4명).
외부 API 와 모델은 쓰지 않는다(칸 위치는 PDF 에 그려진 표 선으로 코드가 찾는다).
결과는 gabee_share/upload_eval_real/ : forms/ images/{clean,photo}/ truth.json sources.json data.lock.json
"""

import argparse
import hashlib
import json
import random
import re
import sys
from pathlib import Path

import mask_eval
import numpy as np
import real_fill
import real_forms
from PIL import Image, ImageChops, ImageDraw, ImageFilter
from real_specs import SPECS

DEFAULT_OUT = Path("C:/Users/403/Desktop/gabee_share/upload_eval_real")
VARIANTS = ("a", "b")
PII_KINDS = {"NAME", "RRN", "PHONE", "ADDR", "BIRTH", "EMAIL", "CARD", "ACCOUNT"}
KEEP_KINDS = {"AMOUNT", "DATE", "SHOP", "ORDERNO"}
IGNORE_KINDS = {"BIZNO", "BPHONE", "BADDR", "RECNO", "TEXT"}
TEXT_WORDS = [
    "내과",
    "소아청소년과",
    "정형외과",
    "일반",
    "상세 첨부",
    "수학·영어",
    "매매",
    "이전등록",
    "신분 확인용",
    "생명보험",
]


# ---------- 가짜 값 ----------
class Persons:
    """한 문서에 나오는 사람들. 0번이 주인공(가족일 수도), 1번은 상대방. 같은 사람의 값은 문서 안에서 같다."""

    def __init__(self, rng: random.Random, family_first: bool) -> None:
        self.rng = rng
        self.used: set[str] = set()
        self.values: dict[tuple[int, str, str], dict] = {}
        self.family_uid: dict[int, tuple[str, str]] = {}
        members = list(mask_eval.FAMILY)
        rng.shuffle(members)
        if family_first:
            self.family_uid[0] = members[0]
        if rng.random() < (0.2 if family_first else 0.45):
            self.family_uid[1] = members[1]

    def get(self, idx: int, kind: str, tag: str = "") -> dict:
        """tag 가 다르면 같은 사람·같은 종류라도 다른 값(카드 여러 장 등)."""
        key = (idx, kind, tag)
        if key in self.values:
            return self.values[key]
        if kind == "NAME" and idx in self.family_uid:
            uid, full = self.family_uid[idx]
            made = {"type": "FAMILY", "value": full, "family_uid": uid, "given": full[1:]}
        else:
            raw = mask_eval.make_value(self.rng, kind, False, self.used)
            if kind == "NAME":
                self.used.add(raw["value"])
            made = {"type": kind, **raw}
        self.values[key] = made
        return made


def make_keep(rng: random.Random, kind: str) -> dict:
    if kind == "AMOUNT":
        n = rng.randrange(120, 60000) * 10
        return {"type": "AMOUNT", "value": f"{n:,}", "norm": str(n)}
    if kind == "DATE":
        y, m, d = 2026, rng.randrange(1, 12), rng.randrange(1, 29)
        return {"type": "DATE", "value": f"{y}.{m:02d}.{d:02d}", "norm": f"{y}{m:02d}{d:02d}"}
    if kind == "SHOP":
        return {"type": "SHOP", "value": rng.choice(mask_eval.SHOPS)}
    raw = mask_eval.make_value(rng, "ORDERNO", False, set())
    return {"type": "ORDERNO", **raw}


def make_ignored(rng: random.Random, kind: str) -> dict:
    digits = lambda n: "".join(str(rng.randrange(10)) for _ in range(n))  # noqa: E731
    if kind == "BIZNO":
        value = f"{digits(3)}-{digits(2)}-{digits(5)}"
    elif kind == "BPHONE":
        value = f"031-555{rng.randrange(10)}-{digits(4)}"
    elif kind == "BADDR":
        value = mask_eval.make_value(rng, "ADDR", False, set())["value"]
    elif kind == "RECNO":
        value = digits(8)
    else:
        value = rng.choice(TEXT_WORDS)
    return {"type": kind, "value": value}


# ---------- 문서 만들기 ----------
def fill_form(slug: str, forms_dir: Path, rng: random.Random, family_first: bool) -> dict:
    """한 양식에 가상 값을 채운 그림과 정답 조각. {image, fields, skipped, template_text}"""
    form = real_fill.FormPage(str(forms_dir / f"{slug}.pdf"))
    img = form.render()
    persons = Persons(rng, family_first)
    fields: list[dict] = []
    skipped: list[dict] = []
    for label, kind, mode, nth in SPECS[slug]:
        base, _, pidx = kind.partition("@")
        base, _, tag = base.partition("#")
        cells, why = form.candidates(label, mode, nth)
        if not cells:
            skipped.append({"label": label, "kind": kind, "why": why})
            continue
        if base in PII_KINDS:
            item = dict(persons.get(int(pidx or 0), base, tag))
        elif base in KEEP_KINDS:
            item = make_keep(rng, base)
        elif base in IGNORE_KINDS:
            item = make_ignored(rng, base)
        else:
            raise ValueError(kind)
        align = "right" if item["type"] == "AMOUNT" else "left"
        box = None
        for cell in cells:  # 정한 칸에 안 들어가면 다음 후보 칸
            box = real_fill.draw_value(img, form.height, cell, item["value"], align)
            if box is not None:
                break
        if box is None:
            skipped.append({"label": label, "kind": kind, "why": "text_does_not_fit"})
            continue
        fields.append({**item, "label": label, "bbox_px": list(box)})
    template = re.sub(r"\s+", " ", form.text.get_text_range()).strip()
    return {"image": img, "fields": fields, "skipped": skipped, "template_text": template}


def classify(fields: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """써 넣은 칸 → (가릴 값, 지킬 값, 채점 제외). 같은 값은 한 번만."""
    pii: dict[tuple, dict] = {}
    keep: dict[tuple, dict] = {}
    ignored: list[dict] = []
    for f in fields:
        item = {k: v for k, v in f.items() if k not in ("label", "bbox_px")}
        if f["type"] in PII_KINDS or f["type"] == "FAMILY":
            pii.setdefault((f["type"], f["value"]), item)
        elif f["type"] in KEEP_KINDS:
            keep.setdefault((f["type"], f["value"]), item)
        else:
            ignored.append(item)
    return list(pii.values()), list(keep.values()), ignored


# ---------- 폰 사진처럼 ----------
def _smooth_noise(rng: np.random.Generator, h: int, w: int, cells: int) -> np.ndarray:
    small = rng.random((cells, max(2, int(cells * w / h)))).astype(np.float32)
    big = Image.fromarray((small * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
    return np.asarray(big, dtype=np.float32) / 255.0


def to_photo(page: Image.Image, seed: int) -> Image.Image:
    """종이를 책상 위에 놓고 비스듬히 찍은 것처럼: 회전·원근·그림자·밝기 불균일·흐림·노이즈·JPEG 전 단계."""
    rng = np.random.default_rng(seed)
    py = random.Random(seed)
    pw, ph = page.size
    margin_x, margin_y = int(pw * 0.14), int(ph * 0.09)
    cw, ch = pw + 2 * margin_x, ph + 2 * margin_y
    # 책상: 바탕색 + 부드러운 얼룩
    tone = np.array(
        py.choice([(150, 118, 88), (120, 125, 130), (178, 160, 130), (95, 80, 70)]), np.float32
    )
    desk = tone[None, None, :] * (0.8 + 0.4 * _smooth_noise(rng, ch, cw, 6))[:, :, None]
    canvas = Image.fromarray(np.clip(desk, 0, 255).astype(np.uint8))
    # 종이: 살짝 누런 흰색, 회전
    paper = ImageChops.multiply(page, Image.new("RGB", page.size, (250, 247, 240)))
    angle = py.uniform(-4.0, 4.0)
    rot = paper.convert("RGBA").rotate(angle, expand=True, resample=Image.BICUBIC)
    canvas.paste(
        rot,
        ((cw - rot.width) // 2 + py.randint(-20, 20), (ch - rot.height) // 2 + py.randint(-20, 20)),
        rot,
    )
    # 원근: 네 모서리를 조금씩 움직인다
    jitter = lambda: py.uniform(-0.035, 0.035)  # noqa: E731
    src = [(0, 0), (cw, 0), (cw, ch), (0, ch)]
    dst = [(x + jitter() * cw, y + jitter() * ch) for x, y in src]
    coeffs = _perspective_coeffs(dst, src)
    canvas = canvas.transform(
        (cw, ch), Image.PERSPECTIVE, coeffs, Image.BICUBIC, fillcolor=(90, 80, 70)
    )
    arr = np.asarray(canvas, dtype=np.float32)
    # 밝기 불균일(한쪽이 어두운 조명) + 그림자 띠
    yy, xx = np.mgrid[0:ch, 0:cw].astype(np.float32)
    gx, gy = py.uniform(-0.25, 0.25), py.uniform(-0.2, 0.2)
    light = 1.0 + gx * (xx / cw - 0.5) * 2 + gy * (yy / ch - 0.5) * 2
    light *= 0.9 + 0.15 * _smooth_noise(rng, ch, cw, 4)
    shadow = Image.new("L", (cw, ch), 255)
    sd = ImageDraw.Draw(shadow)
    x0 = py.randint(0, cw // 2)
    sd.polygon(
        [(x0, 0), (x0 + cw // 5, 0), (x0 + cw // 5 - cw // 4, ch), (x0 - cw // 4, ch)],
        fill=py.randint(150, 205),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(cw // 30))
    light *= np.asarray(shadow, dtype=np.float32) / 255.0
    arr = arr * light[:, :, None]
    # 색 번짐(따뜻한 조명), 대비 낮춤, 센서 노이즈
    arr = arr * np.array([1.0, 0.985, 0.94], np.float32)
    arr = (arr - 128) * py.uniform(0.82, 0.95) + 128 + py.uniform(-8, 8)
    arr += rng.normal(0, py.uniform(2.0, 4.5), arr.shape).astype(np.float32)
    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    out = out.filter(ImageFilter.GaussianBlur(py.uniform(0.9, 1.7)))
    scale = 1600 / max(out.size)
    return out.resize((int(out.width * scale), int(out.height * scale)), Image.LANCZOS)


def _perspective_coeffs(dst: list, src: list) -> list[float]:
    """PIL 원근 변환 계수(출력 좌표 → 입력 좌표)."""
    rows, vals = [], []
    for (x, y), (u, v) in zip(dst, src, strict=True):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        vals.extend([u, v])
    return np.linalg.solve(
        np.array(rows, dtype=np.float64), np.array(vals, dtype=np.float64)
    ).tolist()


# ---------- 명령 ----------
def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cmd_fetch(out: Path) -> None:
    rows = real_forms.fetch_all(out / "forms")
    (out / "sources.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"양식 {len(rows)}종 받음 → {out / 'forms'}, 출처 {out / 'sources.json'}")


def cmd_build(out: Path, seed: int, force: bool) -> None:
    lock = out / "data.lock.json"
    if lock.exists() and not force:
        raise SystemExit(
            "data.lock.json 이 이미 있어요. 점수를 본 뒤 정답을 바꾸지 마세요. 다시 만들려면 --force"
        )
    sources = json.loads((out / "sources.json").read_text(encoding="utf-8"))
    by_slug = {s["slug"]: s for s in sources}
    (out / "images" / "clean").mkdir(parents=True, exist_ok=True)
    (out / "images" / "photo").mkdir(parents=True, exist_ok=True)
    docs = []
    for slug, _law, _seq, kind, name in real_forms.FORMS:
        for variant in VARIANTS:
            doc_id = f"{slug}-{variant}"
            rng = random.Random(f"{seed}-{doc_id}")
            filled = fill_form(slug, out / "forms", rng, family_first=(variant == "a"))
            clean_path = out / "images" / "clean" / f"{doc_id}.png"
            photo_path = out / "images" / "photo" / f"{doc_id}.jpg"
            filled["image"].save(clean_path, optimize=True)
            photo = to_photo(
                filled["image"],
                int(hashlib.sha256(f"{seed}-{doc_id}".encode()).hexdigest()[:8], 16),
            )
            photo.save(
                photo_path, "JPEG", quality=random.Random(f"{seed}-q-{doc_id}").randint(42, 65)
            )
            pii, keep, ignored = classify(filled["fields"])
            docs.append(
                {
                    "id": doc_id,
                    "form": slug,
                    "kind": kind,
                    "name": name,
                    "source": by_slug[slug]["download_url"],
                    "clean": f"images/clean/{doc_id}.png",
                    "photo": f"images/photo/{doc_id}.jpg",
                    "pii": pii,
                    "keep": keep,
                    "ignored": ignored,
                    "fields": filled["fields"],
                    "skipped": filled["skipped"],
                    "template_text": filled["template_text"],
                    "values_text": [f["value"] for f in filled["fields"]],
                }
            )
            print(f"{doc_id:34s} 쓴 칸 {len(filled['fields']):2d}  건너뜀 {len(filled['skipped'])}")
    truth = {
        "meta": {
            "seed": seed,
            "note": "빈 서식(법령 별지 서식) 1쪽에 가상 값을 써 넣음. 모든 값은 가짜. pii=가려야 할 값, keep=지켜야 할 값, ignored=채점 제외",
            "family_arg": mask_eval.FAMILY,
        },
        "family": [{"user_id": uid, "name": n} for uid, n in mask_eval.FAMILY],
        "docs": docs,
    }
    (out / "truth.json").write_text(
        json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    files = {}
    for rel in ["truth.json", "sources.json"] + [d[k] for d in docs for k in ("clean", "photo")]:
        files[rel] = sha256_file(out / rel)
    for slug in by_slug:
        files[f"forms/{slug}.pdf"] = sha256_file(out / "forms" / f"{slug}.pdf")
    lock.write_text(
        json.dumps({"seed": seed, "sha256": files}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    skipped = sum(len(d["skipped"]) for d in docs)
    print(f"문서 {len(docs)}건, 이미지 {2 * len(docs)}장, 건너뛴 칸 {skipped}, 잠금 {lock}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("fetch", "build"):
        p = sub.add_parser(name)
        p.add_argument("--out", type=Path, default=DEFAULT_OUT)
        if name == "build":
            p.add_argument("--seed", type=int, default=20261110)
            p.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if args.cmd == "fetch":
        cmd_fetch(args.out)
    else:
        cmd_build(args.out, args.seed, args.force)


if __name__ == "__main__":
    sys.exit(main())
