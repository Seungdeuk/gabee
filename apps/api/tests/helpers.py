def signup(client, name="지민", role="child") -> dict:
    """가입하고 이후 요청에 쓸 헤더를 돌려준다."""
    r = client.post("/family-group/users", json={"name": name, "role": role})
    assert r.status_code == 201, r.text
    return {"X-Gyeot-Token": r.json()["token"]}


def allow_ai(client, headers, monkeypatch) -> None:
    """가족 AI 동의를 켜고(소유자·관리자 헤더) 시험에서는 사용자 쿨다운을 없앤다."""
    from app.shared.config import settings

    monkeypatch.setattr(settings, "ai_request_cooldown_seconds", 0)
    r = client.put("/family-chat/ai/settings", json={"enabled": True}, headers=headers)
    assert r.status_code == 200, r.text


def join_family(client, owner: dict, code: str, joiner: dict):
    """초대 코드로 가입을 신청하고, 가족의 자동 승인이 꺼져 있어 승인 대기이면 가족 관리자(owner)가 승인한다.
    자동 승인(기본 켜짐)이면 가입 응답을, 아니면 승인 응답을 돌려준다. 구성원이 필요한 시험은 이 함수로 만든다."""
    r = client.post("/family-group/groups/join", json={"code": code}, headers=joiner)
    assert r.status_code == 200 and r.json()["status"] in ("pending", "approved"), r.text
    # 가족의 자동 승인(groups.auto_approve_invites, 기본 켜짐)이면 바로 구성원이라 승인할 요청이 없다
    if r.json()["status"] == "approved":
        return r
    approved = client.post(
        f"/family-group/groups/join-requests/{r.json()['id']}/approve", headers=owner
    )
    assert approved.status_code == 200, approved.text
    return approved


def chat_masking_like_service(monkeypatch) -> None:
    """운영 설정(`INGEST_LLM_MASK=true`)을 흉내 낸다: 가족 채팅 문서·사진은 실제 Claude 가리기를 거쳐야 등록된다(ADR 0023, MASK OFF 차단).
    루트 conftest 는 시험이 실제 Claude 를 부르지 않게 가리기를 꺼 두므로, 채팅 문서 등록을 확인하는 시험은 가리기 단계를 **로컬 규칙과 같은 결과를 내는 대역**으로 바꿔
    켠다(실제 API 호출 없음). 대역은 서비스의 로컬 가리기와 같은 코드를 쓰므로 이 시험들이 보던 가리기 결과는 달라지지 않는다."""
    from collections import Counter

    from app.features.ai_assistant.ingest import llm_ingest, masking
    from app.shared.config import settings

    def mask(text, family=None):
        if family is not None:
            text = family.protect(text)
        kind = masking.sensitive_kind(text)
        counts: Counter = Counter()
        masked = masking.mask_text(text, kind, counts=counts)
        if family is not None:
            masked = family.expand(masked)
        return masked, {k: v for k, v in counts.items() if v}, kind

    monkeypatch.setattr(settings, "ingest_llm_mask", True)
    monkeypatch.setattr(llm_ingest, "mask", mask)
