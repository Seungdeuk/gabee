"""가족 이름 메타데이터화: 올린 문서의 가족 이름 -> `[가족:<user_id>]` 저장, 읽을 때 현재 이름으로 되돌리기, 사람으로 검색.

시험 데이터는 모두 가짜(가상의 이름·번호)다. 외부 서비스는 부르지 않는다.
"""

import pytest
from sqlalchemy import select

from app.features.ai_assistant import family_names as fn
from app.features.ai_assistant import files
from app.features.ai_assistant.family_names import FamilyTagger, Member
from app.features.ai_assistant.ingest.service import preprocess
from app.features.ai_assistant.knowledge import tools
from app.features.ai_assistant.knowledge.models import KnowledgeItem
from app.features.family_group.models import GroupMember
from app.shared.db import SessionLocal
from tests.helpers import join_family, signup

# ---------- 이름 찾기(DB 없이) ----------

A = Member("aaaa1111", "강민훈")
B = Member("bbbb2222", "강민수")
C = Member("cccc3333", "이수진", "수진")


def tag(text: str, *members: Member) -> str:
    return FamilyTagger(list(members)).tag(text)


def test_full_name_alias_and_particle_become_the_member_tag():
    assert tag("성명: 강민훈", A, B) == "성명: [가족:aaaa1111]"
    assert tag("민수야 밥 먹자", A, B) == "[가족:bbbb2222]야 밥 먹자"  # 성 뗀 이름 + 조사
    assert tag("수진이가 갔다", C) == "[가족:cccc3333]이가 갔다"  # 표시 이름 + 조사
    assert tag("이수진에게 전달", C) == "[가족:cccc3333]에게 전달"  # 실제 이름 + 조사


def test_display_name_is_a_spelling_of_the_same_person():
    hun = Member("aaaa1111", "강민훈", "훈이")
    assert (
        tag("훈이는 병원에 갔다. 강민훈 확인", hun)
        == "[가족:aaaa1111]는 병원에 갔다. [가족:aaaa1111] 확인"
    )


def test_names_inside_words_are_not_replaced():
    하나 = Member("hhhh1111", "하나")
    assert tag("하나은행 계좌", 하나) == "하나은행 계좌"  # 낱말 속 오탐 방지
    assert tag("하나가 왔다", 하나) == "[가족:hhhh1111]가 왔다"
    김하나 = Member("kkkk2222", "김하나")
    assert (
        tag("하나은행 하나로마트", 김하나) == "하나은행 하나로마트"
    )  # 일반어 별칭('하나')은 만들지 않는다
    assert tag("김하나 학생", 김하나) == "[가족:kkkk2222] 학생"
    assert tag("김민훈씨가", A) == "김민훈씨가"  # 다른 사람 이름 속 글자는 건드리지 않는다


def test_same_name_for_two_members_is_left_alone():
    same_1, same_2 = Member("s1", "강민훈"), Member("s2", "강민훈")
    assert tag("성명: 강민훈", same_1, same_2) == "성명: 강민훈"  # 동명이인: 임의로 고르지 않는다
    # 이름이 다른 두 사람이 같은 이름자를 가진 경우: 전체 이름은 구분되고 이름자만 부르는 말은 구분 못 한다
    kang, lee = Member("k1", "강민훈"), Member("l1", "이민훈")
    assert tag("강민훈, 이민훈", kang, lee) == "[가족:k1], [가족:l1]"
    assert tag("민훈이가", kang, lee) == "민훈이가"


def test_kinship_terms_are_not_names():
    엄마 = Member("mom1", "박영희", "엄마")
    assert tag("엄마가 말했다. 박영희", 엄마) == "엄마가 말했다. [가족:mom1]"


def test_existing_tags_survive_and_no_members_means_no_change():
    assert tag("[가족:aaaa1111] 확인", A) == "[가족:aaaa1111] 확인"
    assert (
        tag(
            "강민훈",
        )
        == "강민훈"
    )


def test_clip_never_cuts_a_tag_in_half():
    text = "[가족:aaaa1111] 진료"
    assert fn.clip(text, 8) == ""
    assert fn.clip(text, len("[가족:aaaa1111]")) == "[가족:aaaa1111]"
    assert fn.clip("가나다라", 2) == "가나"


def test_restore_unknown_and_departed_ids_get_a_neutral_word():
    names = {"aaaa1111": "민훈"}
    assert fn.restore("[가족:aaaa1111]과 [가족:gone9999]", names) == f"민훈과 {fn.NEUTRAL_NAME}"
    assert fn.family_of(["aaaa1111", "gone9999"], names) == ["민훈"]


def test_match_member_by_name_alias_or_given_name():
    assert fn.match_member([A, B, C], "강민훈") == ["aaaa1111"]
    assert fn.match_member([A, B, C], "민수") == ["bbbb2222"]
    assert fn.match_member([A, B, C], "수진") == ["cccc3333"]
    assert fn.match_member([A, B, C], "없는사람") == []
    assert fn.match_member([A, Member("x", "이민훈")], "민훈") == ["aaaa1111", "x"]


def test_suggest_members_offers_names_one_character_off_but_never_picks_one():
    # 질문의 오타('민혼')는 필터로 쓰지 않고(match_member 는 []), 안내에 비슷한 가족만 알려 준다
    assert fn.match_member([A, B, C], "민혼") == []
    assert fn.suggest_members([A, B, C], "민혼") == [
        "강민훈",
        "강민수",
    ]  # 민훈·민수 둘 다 한 글자 차이
    assert fn.suggest_members([A, B, C], "강민혼") == [
        "강민훈",
        "강민수",
    ]  # 강민수와도 한 글자 차이
    assert fn.suggest_members([A, B, C], "강만훈") == ["강민훈"]
    assert fn.suggest_members([A, B, C], "수짐") == ["수진"]  # 표시 이름(C 는 '수진')으로 보여 준다
    assert fn.suggest_members([A, B, C], "박없음") == []
    assert fn.suggest_members([A, B, C], "") == [] and fn.suggest_members([A, B, C], "훈") == []


# ---------- 가리기보다 먼저 ----------


def test_names_are_tagged_before_masking_so_they_never_become_stars():
    text = "진료확인서\n성명: 강민훈\n환자 강민수\n주민등록번호 900101-1234567\n"
    plain = preprocess(text.encode(), "a.txt")
    assert "강**" in plain.content.text  # 예전 동작: 둘 다 같은 `강**`
    result = preprocess(text.encode(), "a.txt", family=FamilyTagger([A, B]))
    out = result.content.text
    assert "성명: [가족:aaaa1111]" in out and "환자 [가족:bbbb2222]" in out
    assert (
        "강**" not in out and "강민훈" not in out and "900101" not in out
    )  # 번호는 그대로 가려진다


def test_tag_survives_masking_even_if_the_id_looks_like_a_number():
    digits = Member("9001011234567", "강민훈")  # 가리기 규칙에 걸릴 모양의 숫자 id
    result = preprocess(
        "성명: 강민훈\n연락처 010-1234-5678".encode(), "a.txt", family=FamilyTagger([digits])
    )
    assert "[가족:9001011234567]" in result.content.text
    assert "010-****-****" in result.content.text


# ---------- 저장·되돌리기·검색(DB) ----------


@pytest.fixture
def clan(client):
    """강민훈(소유자)·강민수가 있는 가족. (헤더, 그룹, {이름: user_id})."""
    a = signup(client, "강민훈", "parent")
    group = client.post("/family-group/groups", json={"name": "강씨네"}, headers=a).json()
    b = signup(client, "강민수")
    join_family(client, a, group["invite_code"], b)
    with SessionLocal() as db:
        ids = {m.name: m.user_id for m in fn.load_members(db, group["id"])}
    return a, b, group, ids


@pytest.fixture
def pipeline():
    old = files.processors
    files.processors = files.Processors()
    yield files.processors
    files.processors = old


def _upload(client, headers, text, name="a.txt"):
    r = client.post(
        "/ai-assistant/files", files={"file": (name, text.encode(), "text/plain")}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


DOC1 = "강민훈 진료확인서\n성명: 강민훈\n진단: 감기\n진료일 2026-10-15\n"
DOC2 = "강민수 예방접종 확인서\n성명: 강민수\n접종: 독감\n접종일 2026-10-20\n"


def test_upload_stores_tags_and_metadata_and_reads_back_current_names(client, clan, pipeline):
    a, _, group, ids = clan
    d1, d2 = _upload(client, a, DOC1), _upload(client, a, DOC2, "b.txt")
    with SessionLocal() as db:
        i1, i2 = db.get(KnowledgeItem, d1), db.get(KnowledgeItem, d2)
        assert i1.family_user_ids == [ids["강민훈"]] and i2.family_user_ids == [ids["강민수"]]
        for item in (i1, i2):
            stored = item.title + item.body_md
            assert "강민훈" not in stored and "강민수" not in stored and "강**" not in stored
            assert "[가족:" in item.title  # 제목에도 자리표시(반으로 잘리지 않았다)
    # 읽을 때: 상세·목록·파일 상태가 현재 이름으로
    detail = client.get(f"/ai-assistant/knowledge/items/{d1}", headers=a).json()
    assert "성명: 강민훈" in detail["body_md"] and "[가족:" not in detail["body_md"]
    assert detail["title"].startswith("강민훈")
    listed = client.get("/ai-assistant/knowledge/items", headers=a).json()
    assert {i["title"] for i in listed} >= {"강민훈 진료확인서", "강민수 예방접종 확인서"}
    st = client.get(f"/ai-assistant/files/{d1}", headers=a).json()
    assert st["title"] == "강민훈 진료확인서" and "[가족:" not in str(st)
    hits = client.post("/ai-assistant/knowledge/search", json={"query": "진료"}, headers=a).json()
    assert all("[가족:" not in h["title"] + h["snippet"] for h in hits["hits"])


def test_renamed_and_departed_members_show_current_names(client, clan, pipeline):
    a, b, group, ids = clan
    d1 = _upload(client, a, DOC1)
    with SessionLocal() as db:
        gm = db.scalar(
            select(GroupMember).where(
                GroupMember.group_id == group["id"], GroupMember.user_id == ids["강민훈"]
            )
        )
        gm.display_name = "민훈 아빠"
        db.commit()
    body = client.get(f"/ai-assistant/knowledge/items/{d1}", headers=b).json()["body_md"]
    assert "성명: 민훈 아빠" in body
    with SessionLocal() as db:  # 나간 구성원(그룹 멤버십이 없는 id)은 중립 문구
        db.delete(
            db.scalar(
                select(GroupMember).where(
                    GroupMember.group_id == group["id"], GroupMember.user_id == ids["강민훈"]
                )
            )
        )
        db.commit()
    body = client.get(f"/ai-assistant/knowledge/items/{d1}", headers=b).json()["body_md"]
    assert f"성명: {fn.NEUTRAL_NAME}" in body and "강민훈" not in body


def test_tools_restore_names_and_filter_by_member(client, clan, pipeline):
    a, _, group, ids = clan
    d1, d2 = _upload(client, a, DOC1), _upload(client, a, DOC2, "b.txt")
    with SessionLocal() as db:
        gid = group["id"]
        every = tools.search_knowledge(db, gid, "확인서", top_k=10)
        assert {r["item_id"] for r in every["results"]} == {d1, d2}
        assert all("[가족:" not in str(r) for r in every["results"])
        by_name = {r["item_id"]: r for r in every["results"]}
        assert by_name[d1]["family"] == ["강민훈"] and "성명: 강민훈" in by_name[d1]["text"]

        only_hun = tools.search_knowledge(db, gid, "확인서", top_k=10, member="민훈")
        assert [r["item_id"] for r in only_hun["results"]] == [d1]
        only_su = tools.search_knowledge(db, gid, "확인서", top_k=10, member="강민수")
        assert [r["item_id"] for r in only_su["results"]] == [d2]

        nobody = tools.search_knowledge(
            db, gid, "확인서", member="박없음"
        )  # 조용히 무시하지 않는다
        assert nobody["results"] == [] and "찾지 못했어요" in nobody["note"]
        assert "비슷한 이름" not in nobody["note"] and "이름이나 별칭" in nobody["note"]

        typo = tools.search_knowledge(db, gid, "확인서", member="민혼")  # OCR·오타 후보를 알려 준다
        assert typo["results"] == [] and "찾지 못했어요" in typo["note"]
        assert "비슷한 이름의 가족" in typo["note"] and "강민훈" in typo["note"]

        full = tools.get_item(db, gid, d1)
        assert "[가족:" not in full["title"] + full["text"] and full["family"] == ["강민훈"]
        listed = tools.list_items(db, gid)["items"]
        assert {i["title"] for i in listed} == {"강민훈 진료확인서", "강민수 예방접종 확인서"}
        assert all("[가족:" not in i["title"] for i in listed)
    assert "member" in tools.TOOL_SPECS[0]["input_schema"]["properties"]


def test_unknown_ids_in_a_record_are_shown_neutrally(client, clan, pipeline):
    a, _, group, ids = clan
    d1 = _upload(client, a, DOC1)
    with SessionLocal() as db:
        item = db.get(KnowledgeItem, d1)
        item.body_md = item.body_md + "\n- 보호자: [가족:zzzz0000]"
        db.commit()
        full = tools.get_item(db, group["id"], d1)
    assert f"보호자: {fn.NEUTRAL_NAME}" in full["text"]


def test_editing_a_record_retags_names_and_refreshes_metadata(client, clan, pipeline):
    a, _, group, ids = clan
    d1 = _upload(client, a, DOC1)
    detail = client.get(f"/ai-assistant/knowledge/items/{d1}", headers=a).json()
    edited = detail["body_md"] + "\n- 보호자 강민수"  # 앱은 이름이 되돌려진 글을 보내온다
    r = client.patch(f"/ai-assistant/knowledge/items/{d1}", json={"body_md": edited}, headers=a)
    assert r.status_code == 200, r.text
    assert "보호자 강민수" in r.json()["body_md"]
    with SessionLocal() as db:
        item = db.get(KnowledgeItem, d1)
        assert "강민수" not in item.body_md and "강민훈" not in item.body_md
        assert set(item.family_user_ids) == {ids["강민훈"], ids["강민수"]}


def test_description_with_a_family_name_is_stored_as_a_tag(client, clan, pipeline):
    a, _, group, ids = clan
    from app.features.ai_assistant.knowledge import from_ingest, service

    with SessionLocal() as db:
        item = service.ingest(
            db,
            group["id"],
            ids["강민훈"],
            kind_label=from_ingest.PHOTO_KIND,
            title="사진",
            body_md="# 사진\n분류: 사진",
            item_id="p" * 32,
        )
        from app.features.ai_assistant.models import Photo

        db.add(
            Photo(
                id=item.id,
                group_id=group["id"],
                uploaded_by=ids["강민훈"],
                filename="x.png",
                content_type="image/png",
                size=1,
                status="analyzed",
            )
        )
        db.commit()
        out = files.set_description(db, group["id"], item.id, "강민수와 놀이터에서")
        stored = db.get(KnowledgeItem, item.id)
        assert "강민수" not in stored.body_md + stored.title
        assert stored.family_user_ids == [ids["강민수"]]
    assert out.title == "강민수와 놀이터에서" and "[가족:" not in str(out)


# ---------- 이름 오타 확인(OCR 이 가족 이름을 한 글자 틀리게 읽은 경우) ----------


def test_near_member_finds_one_off_names_only_when_unique():
    t = FamilyTagger([A, C])
    assert t.near_member("민혼") == A.user_id  # '민훈' 의 성 뗀 이름자와 한 글자 차이
    assert t.near_member("강민혼") == A.user_id
    assert t.near_member("민훈") is None  # 정확히 같은 글자는 후보 판단이 맡는다
    assert t.near_member("엄마") is None and t.near_member("박") is None
    assert FamilyTagger([A, B]).near_member("강민호") is None  # 두 사람과 가까우면 고르지 않는다


def test_check_marker_is_shown_neutrally_and_resolved_by_the_answer():
    text = f"성명: [확인필요:{A.user_id}], 보호자 [가족:{C.user_id}]"
    shown = fn.restore(text, {C.user_id: "수진"})
    assert shown == "성명: [이름 확인 필요], 보호자 수진"
    assert fn.check_ids(text) == [A.user_id]
    assert (
        fn.resolve_check(text, A.user_id, True)
        == f"성명: [가족:{A.user_id}], 보호자 [가족:{C.user_id}]"
    )
    assert fn.resolve_check(text, A.user_id, False).startswith("성명: [이름],")


def _checked_record(db, group, uid, body=None):
    from app.features.ai_assistant.knowledge import service

    body = body or (f"# 진료확인서\n분류: 병원 서류\n성명: [확인필요:{uid}]\n진단: 감기\n")
    return service.ingest(
        db, group["id"], uid, kind_label="병원 서류", title="진료확인서", body_md=body
    ).id


def test_name_checks_list_resolve_and_reindex(client, clan, pipeline):
    a, _, group, ids = clan
    uid = ids["강민훈"]
    with SessionLocal() as db:
        item_id = _checked_record(db, group, uid)
        found = tools.list_name_checks(db, group["id"])["checks"]
        assert len(found) == 1 and found[0]["item_id"] == item_id
        assert found[0]["candidate"] == "강민훈" and "[?]" in found[0]["context"]
        assert "확인필요" not in str(found)  # 표시 문자열이 그대로 새지 않는다
        # 확인 대기 중에는 검색 결과에 '[이름 확인 필요]' 로 보인다
        got = tools.get_item(db, group["id"], item_id)
        assert "[이름 확인 필요]" in got["text"] and got["family"] == []

        # 같은 사람 -> 가족 이름표가 붙고 사람 필터로 찾아진다
        assert tools.resolve_name_check(db, group["id"], item_id, uid, True) == {
            "done": True,
            "same_person": True,
        }
        after = tools.get_item(db, group["id"], item_id)
        assert "성명: 강민훈" in after["text"] and after["family"] == ["강민훈"]
        assert tools.list_name_checks(db, group["id"])["checks"] == []
        hits = tools.search_knowledge(db, group["id"], "진료확인서", member="민훈")
        assert [r["item_id"] for r in hits["results"]] == [item_id]


def test_name_check_answered_no_becomes_a_plain_masked_name(client, clan, pipeline):
    _, _, group, ids = clan
    uid = ids["강민훈"]
    with SessionLocal() as db:
        item_id = _checked_record(db, group, uid)
        tools.resolve_name_check(db, group["id"], item_id, uid, False)
        item = db.get(KnowledgeItem, item_id)
        assert "성명: [이름]" in item.body_md and item.family_user_ids is None


def test_resolve_rejects_unknown_candidates_and_other_groups(client, clan, pipeline):
    from app.shared.errors import ApiError

    _, _, group, ids = clan
    uid = ids["강민훈"]
    with SessionLocal() as db:
        item_id = _checked_record(db, group, uid)
        with pytest.raises(ApiError):  # 이 기록에 없는 후보 id 는 모델이 만들 수 없다
            tools.resolve_name_check(db, group["id"], item_id, ids["강민수"], True)
        with pytest.raises(ApiError):  # 다른 그룹의 기록은 보이지 않는다
            tools.resolve_name_check(db, "other-group", item_id, uid, True)


def test_chat_prompt_mentions_pending_checks_only_when_there_are_some(client, clan, pipeline):
    from app.features.ai_assistant.knowledge import rag_chat

    _, _, group, ids = clan
    with SessionLocal() as db:
        assert "list_name_checks" not in rag_chat.system_prompt(name_checks=0)
        _checked_record(db, group, ids["강민훈"])
        from app.features.ai_assistant.knowledge import service

        assert service.count_name_checks(db, group["id"]) == 1
    assert "list_name_checks" in rag_chat.system_prompt(name_checks=1)


def test_resolve_tool_refuses_an_unclear_answer(client, clan, pipeline):
    from app.features.ai_assistant.knowledge import rag_chat

    _, _, group, ids = clan
    uid = ids["강민훈"]
    with SessionLocal() as db:
        item_id = _checked_record(db, group, uid)
        args = {"item_id": item_id, "candidate_id": uid, "same_person": "maybe"}
        with pytest.raises(ValueError):  # 모르는 값을 '다른 사람'으로 저장하지 않는다
            rag_chat._run_tool(db, group["id"], "resolve_name_check", args)
        assert fn.check_ids(db.get(KnowledgeItem, item_id).body_md) == [uid]
        done = rag_chat._run_tool(
            db, group["id"], "resolve_name_check", {**args, "same_person": "true"}
        )
        assert done["same_person"] is True
