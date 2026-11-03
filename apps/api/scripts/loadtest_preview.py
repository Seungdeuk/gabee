"""가명화(규칙+NER) 경로 부하 측정: 실제 uvicorn 서버에 동시 요청을 보내 처리량·지연(P50/P95/P99)·메모리를 잰다.

- 대상: POST /family-chat/ai/preview. 가명화(규칙 + NER)를 거치지만 외부 AI 를 부르지 않고 한도도 쓰지 않는다.
- 서버는 이 스크립트가 임시 폴더·임시 SQLite 로 띄우고 끝나면 끈다. .env·공용/개인 DB·외부 API 를 쓰지 않는다. 모든 대화는 합성이다.
- 사용자당 분당 20회 제한(PREVIEW_LIMIT)이 있어서 단계마다 서로 다른 사용자를 쓰고, 단계 사이에 제한 창(60초)이 지나길 기다린다.
- 한계: 임시 SQLite·uvicorn 프로세스 1개·같은 PC 에서 부하를 만들기 때문에 운영(PostgreSQL, Docker/Caddy)의 절대 수치가 아니다.

실행(apps/api 에서)::

    PYTHONPATH=. python scripts/loadtest_preview.py --mode required --model-dir <NER 모델 폴더>
    PYTHONPATH=. python scripts/loadtest_preview.py --mode off

결과는 표로 출력하고 --out 이 있으면 JSON 으로도 저장한다.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

API_DIR = Path(__file__).resolve().parents[1]
PREVIEW_PER_MIN = 20  # ai_service.PREVIEW_LIMIT 과 같은 값(사용자당 분당)
WINDOW_WAIT = 62  # 제한 창이 지나길 기다리는 초

NAMES = ["김하준", "이서윤", "박민재", "최도현", "정서연", "강지후", "조예준", "윤하은"]
TEMPLATES = [
    "{n}이한테 전화해봐 010-{a}-{b} 이래",
    "내일 {n}이랑 점심 먹기로 했어",
    "택배 주소는 서울특별시 강남구 테헤란로 {c}길 {d} 로 보내줘",
    "메일은 {l}@example.com 으로 보내주세요",
    "계좌는 국민은행 {a}-{b}-{c}{d} 야 입금해줘",
    "오늘 저녁은 뭐 먹을까? 장 봐서 갈게",
    "{n}님 예약 확인됐습니다 몇 시까지 가면 돼?",
    "병원 {d}시에 예약해놨어 잊지 마",
]


def make_line(i: int) -> str:
    """i 번째 합성 대화 줄(이름·전화·주소·이메일·계좌가 섞인다)."""
    return TEMPLATES[i % len(TEMPLATES)].format(
        n=NAMES[i % len(NAMES)],
        a=1000 + (i * 37) % 9000,
        b=1000 + (i * 91) % 9000,
        c=10 + i % 80,
        d=1 + i % 9,
        l=f"user{i}",
    )


_TREE: dict[int, list[int]] = {}


def _tree(pid: int) -> list[int]:
    """pid 와 그 자식 프로세스(venv 의 python.exe 는 실제 인터프리터를 자식으로 띄운다). 처음 한 번만 조회한다."""
    if pid not in _TREE:
        pids = [pid]
        try:
            out = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"(Get-CimInstance Win32_Process -Filter 'ParentProcessId={pid}').ProcessId",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout
            pids += [int(x) for x in out.split() if x.isdigit()]
        except Exception:
            pass
        _TREE[pid] = pids
    return _TREE[pid]


def rss_mb(pid: int) -> float | None:
    """서버 프로세스(자식 포함)의 작업 집합 메모리 합(MB). tasklist 출력에서 읽는다(Windows 전용, 실패하면 None)."""
    total = 0.0
    try:
        for p in _tree(pid):
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {p}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
            row = next(csv.reader(io.StringIO(out.strip())))
            total += int("".join(ch for ch in row[4] if ch.isdigit())) / 1024
        return total
    except Exception:
        return None


def pct(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def start_server(
    mode: str, model_dir: str, port: int, tmp: Path, threads: int, conc: int, no_cache: bool = False
):
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": f"sqlite:///{(tmp / 'load.db').as_posix()}",
            "DATA_DIR": str(tmp),
            "ANTHROPIC_API_KEY": "",
            "JWT_SECRET": "load-test-only-secret-not-for-production-0123456789",
            "PRIVACY_NER_MODE": mode,
            "PRIVACY_NER_MODEL_DIR": model_dir,
            "PRIVACY_NER_THREADS": str(threads),
            "PRIVACY_NER_MAX_CONCURRENCY": str(conc),
            "PYTHONPATH": str(API_DIR),
            "PYTHONIOENCODING": "utf-8",
        }
    )
    for k in ("MAIL_BACKEND", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"):
        env[k] = ""
    log = open(tmp / "server.log", "wb")
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    if no_cache:
        # NER 결과 캐시(LRU)를 꺼서 매 줄을 새로 추론하는 최악 조건을 잰다(서비스 코드는 고치지 않고 시작할 때 변수만 바꾼다)
        cmd = [
            sys.executable,
            "-c",
            "import app.shared.privacy.ner as n, uvicorn; n.CACHE_SIZE = 0; "
            f"uvicorn.run('app.main:app', host='127.0.0.1', port={port}, log_level='warning')",
        ]
    proc = subprocess.Popen(
        cmd,
        cwd=API_DIR,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    return proc


def wait_ready(base: str, proc, timeout: float = 90.0) -> float:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        if proc.poll() is not None:
            raise SystemExit("서버가 시작 중 종료됐다(server.log 확인)")
        try:
            if httpx.get(f"{base}/health", timeout=2).status_code == 200:
                return time.perf_counter() - t0
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise SystemExit("서버 시작 시간 초과")


def setup_family(base: str, users: int, lines: int):
    """소유자 + (users-1)명이 한 가족이 되고, 합성 대화 lines 줄을 만든다. 각 사용자의 토큰 헤더 목록을 돌려준다."""
    c = httpx.Client(base_url=base, timeout=30)
    heads = []
    for i in range(users):
        r = c.post(
            "/family-group/users",
            json={"name": f"부하{i}", "role": "parent" if i == 0 else "child"},
        )
        r.raise_for_status()
        heads.append({"X-Gyeot-Token": r.json()["token"]})
    g = c.post("/family-group/groups", json={"name": "부하 가족"}, headers=heads[0])
    g.raise_for_status()
    code = g.json()["invite_code"]
    for h in heads[1:]:
        r = c.post("/family-group/groups/join", json={"code": code}, headers=h)
        r.raise_for_status()
        if r.json().get("status") == "pending":
            c.post(
                f"/family-group/groups/join-requests/{r.json()['id']}/approve", headers=heads[0]
            ).raise_for_status()
    for i in range(lines):
        r = c.post(
            "/family-chat/messages", json={"text": make_line(i)}, headers=heads[i % min(users, 4)]
        )
        r.raise_for_status()
    c.close()
    return heads


def run_level(base: str, proc_pid: int, heads: list[dict], conc: int, per_user: int, limit: int):
    """conc 명이 동시에 각자 per_user 번씩 연속 요청한다. 지연·상태·메모리 최고치를 모은다."""
    lat: list[float] = []
    codes: dict[str, int] = {}
    lock = threading.Lock()
    peak = [rss_mb(proc_pid) or 0.0]
    stop = threading.Event()

    def sampler():
        while not stop.is_set():
            v = rss_mb(proc_pid)
            if v:
                peak[0] = max(peak[0], v)
            stop.wait(0.5)

    def worker(h):
        cl = httpx.Client(base_url=base, timeout=60)
        for _ in range(per_user):
            t = time.perf_counter()
            try:
                r = cl.post("/family-chat/ai/preview", json={"limit": limit}, headers=h)
                code = str(r.status_code)
            except httpx.HTTPError as e:
                code = type(e).__name__
            dt = (time.perf_counter() - t) * 1000
            with lock:
                codes[code] = codes.get(code, 0) + 1
                if code == "200":
                    lat.append(dt)
        cl.close()

    th = threading.Thread(target=sampler, daemon=True)
    th.start()
    start = time.perf_counter()
    workers = [threading.Thread(target=worker, args=(heads[i],)) for i in range(conc)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    wall = time.perf_counter() - start
    stop.set()
    th.join()
    total = sum(codes.values())
    return {
        "concurrency": conc,
        "requests": total,
        "ok": codes.get("200", 0),
        "status": codes,
        "wall_s": round(wall, 2),
        "throughput_rps": round(codes.get("200", 0) / wall, 2) if wall else 0,
        "p50_ms": round(pct(lat, 0.50), 1),
        "p95_ms": round(pct(lat, 0.95), 1),
        "p99_ms": round(pct(lat, 0.99), 1),
        "mean_ms": round(statistics.fmean(lat), 1) if lat else None,
        "max_ms": round(max(lat), 1) if lat else None,
        "rss_peak_mb": round(peak[0], 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="required", choices=["required", "auto", "off"])
    ap.add_argument("--model-dir", default=str(API_DIR / "data" / "models" / "ner"))
    ap.add_argument("--port", type=int, default=8031)
    ap.add_argument("--levels", default="1,4,8,16,32")
    ap.add_argument("--per-user", type=int, default=10)
    ap.add_argument(
        "--lines", type=int, default=100, help="합성 대화 줄 수(미리보기가 처리하는 양)"
    )
    ap.add_argument("--limit", type=int, default=100, help="미리보기 요청의 limit")
    ap.add_argument("--ner-threads", type=int, default=2)
    ap.add_argument("--ner-concurrency", type=int, default=2)
    ap.add_argument("--no-cache", action="store_true", help="NER 결과 캐시를 꺼서 최악 조건을 잰다")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    levels = [int(x) for x in a.levels.split(",")]
    assert a.per_user <= PREVIEW_PER_MIN - 1

    tmp = Path(tempfile.mkdtemp(prefix="loadtest-"))
    base = f"http://127.0.0.1:{a.port}"
    proc = start_server(
        a.mode, a.model_dir, a.port, tmp, a.ner_threads, a.ner_concurrency, a.no_cache
    )
    try:
        boot = wait_ready(base, proc)
        mem_boot = rss_mb(proc.pid)
        heads = setup_family(base, max(levels), a.lines)
        # 워밍업: 첫 요청에 모델 로드가 섞이지 않게 소유자가 한 번 호출(제한 1회 사용)
        httpx.post(
            f"{base}/family-chat/ai/preview", json={"limit": a.limit}, headers=heads[0], timeout=120
        )
        mem_warm = rss_mb(proc.pid)
        results = []
        for n, conc in enumerate(levels):
            if n:
                time.sleep(WINDOW_WAIT)
            # 소유자(heads[0])는 워밍업에서 1회 썼으므로 per_user+1 <= 20 이면 괜찮다
            r = run_level(base, proc.pid, heads, conc, a.per_user, a.limit)
            results.append(r)
            print(json.dumps(r, ensure_ascii=False), flush=True)
        mem_end = rss_mb(proc.pid)
        summary = {
            "mode": a.mode,
            "ner_threads": a.ner_threads,
            "ner_concurrency": a.ner_concurrency,
            "ner_cache": "off" if a.no_cache else "on",
            "preview_lines": a.lines,
            "per_user_requests": a.per_user,
            "server_ready_s": round(boot, 1),
            "rss_boot_mb": round(mem_boot or 0, 1),
            "rss_after_warmup_mb": round(mem_warm or 0, 1),
            "rss_end_mb": round(mem_end or 0, 1),
            "levels": results,
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
    if a.out:
        Path(a.out).write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        "\n| 동시 | 요청 | 성공 | RPS | P50 ms | P95 ms | P99 ms | 최대 ms | 메모리 최고 MB | 상태 |"
    )
    print("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in summary["levels"]:
        print(
            f"| {r['concurrency']} | {r['requests']} | {r['ok']} | {r['throughput_rps']} | {r['p50_ms']} | "
            f"{r['p95_ms']} | {r['p99_ms']} | {r['max_ms']} | {r['rss_peak_mb']} | {r['status']} |"
        )
    print(
        f"\n시작 {summary['server_ready_s']}s, 메모리 시작 {summary['rss_boot_mb']}MB -> 워밍업 후 "
        f"{summary['rss_after_warmup_mb']}MB -> 종료 직전 {summary['rss_end_mb']}MB"
    )


if __name__ == "__main__":
    main()
