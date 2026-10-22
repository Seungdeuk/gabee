"""동시 요청에도 돌봄 기본 항목이 7개로 유지되는지 확인하는 스모크 테스트.

주의: TestClient 는 요청을 순서대로 처리해서 잠금을 빼도 이 테스트는 실패하지 않는다(구독 항목은 기본 목록을 미리
만들지 않게 바뀌어 이제 돌봄만 해당한다). 잠금 자체가 동시 실행을 막는지는 tests/test_seed_lock.py 가 검증한다."""

from concurrent.futures import ThreadPoolExecutor


def _parallel(client, headers, path, n=8):
    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(lambda _: client.get(path, headers=headers), range(n)))


def test_default_care_items_are_created_once_under_concurrent_requests(client, family):
    a, _, _ = family
    results = _parallel(client, a, "/care/daily")
    assert all(r.status_code == 200 for r in results)
    assert len(client.get("/care/daily", headers=a).json()["items"]) == 7
