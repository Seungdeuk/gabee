"""동시 요청에도 기본 항목이 5개·7개로 유지되는지 확인하는 스모크 테스트.

주의: TestClient 는 요청을 순서대로 처리해서 잠금을 빼도 이 테스트는 실패하지 않는다(실제 서버에서 구독 탭이
목록과 월별 계획을 동시에 불러 기본 항목이 10개로 중복되는 것을 브라우저 검증에서 발견했다). 잠금 자체가 동시 실행을
막는지는 tests/test_seed_lock.py 가 검증한다."""

from concurrent.futures import ThreadPoolExecutor


def _parallel(client, headers, path, n=8):
    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(lambda _: client.get(path, headers=headers), range(n)))


def test_default_subscriptions_are_created_once_under_concurrent_requests(client, family):
    a, _, _ = family
    paths = ["/billing/subscriptions", "/billing/subscriptions/monthly?month=2026-10"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda i: client.get(paths[i % 2], headers=a), range(8)))
    assert all(r.status_code == 200 for r in results)
    items = client.get("/billing/subscriptions", headers=a).json()["items"]
    assert len(items) == 5 and len({i["name"] for i in items}) == 5


def test_default_care_items_are_created_once_under_concurrent_requests(client, family):
    a, _, _ = family
    results = _parallel(client, a, "/care/daily")
    assert all(r.status_code == 200 for r in results)
    assert len(client.get("/care/daily", headers=a).json()["items"]) == 7
