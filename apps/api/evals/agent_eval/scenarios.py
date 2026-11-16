"""E5 신규 평가 사례 72건의 '시나리오 목록' 형식·검증·해시(docs/requirements/agent-eval.md, E5a).

사례 본문(질문+기대 전체)을 쓰기 전에 어떤 상황을 어느 분할에 넣을지 먼저 정하고, 그 목록의 해시를 `splits.lock.json` 에 남긴다.
사례 본문은 E5b(개발 36건)·E5c(검증·테스트 36건)가 쓰고, `question_signature` 의 질문을 그대로 쓴다.

- 해시는 **무결성과 변경 추적용**이다. 파일 접근을 막는 장치가 아니다(누구든 파일과 잠금 파일을 함께 고칠 수 있다). 러너에도
  연결돼 있지 않다(E5b 에서 연결을 검토한다). 목록을 고치려면 `history` 에 사유와 함께 이전·이후 해시를 더해야 하고, 연결이 끊기면
  검증이 실패한다. `verify_history_preserved` 는 기준 잠금 파일(예: 병합된 브랜치의 것)의 이력이 앞부분으로 보존됐는지 본다.
  검토는 PR 리뷰가 한다.
- 목록은 분할별 파일(`data/scenarios_<split>.json`)과 공통 `scenarios_meta.json`(버전·월드·unsupported)으로 나눠 둔다. 해시·잠금은
  합쳐 만든 전체 정규 목록 기준이다. 파일 위치는 접근 제어가 아니다(루프에 개발셋만 보이게 하는 격리는 루프 안에서만 보장한다, ADR 0016 한계).
- 12개 주제(`topic`)는 공식 범주(A~H)가 아니라 이 목록에만 있는 태그다. 주제마다 공식 범주가 하나로 정해져 있다(`TOPICS`).
- 일정 쓰기(등록·수정·삭제)가 필요한 시나리오는 72건에 세지 않고 `unsupported` 목록에 이유와 함께 둔다.
- 월드 단위로 분할을 격리한다: dev 는 w1(만들어져 있다), val 은 w2, test 는 w3(계획 중, 사례를 실행할 수 없다).
"""

import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from .schema import AgentPath, Category, NonEmpty, Scenario, _Strict
from .seeds import data as seed_data
from .write_tools import WRITE_TOOLS

DATA_DIR = Path(__file__).resolve().parent / "data"
LOCK_PATH = Path(__file__).resolve().parent / "splits.lock.json"
META_FILE = "scenarios_meta.json"
# 최초 확정 해시(E5a). 잠금 파일의 `history[0].to` 와 시험의 리터럴이 모두 이 값과 같아야 한다.
FINALIZED_SHA = "aa23c8e65a67c853bb0e641a39a54931c0431a65e6cfe2a3cbb041d0041ac855"

LISTED_SPLITS = ("dev", "val", "test")
ListSplit = Literal["dev", "val", "test"]
Risk = Literal["none", "leak", "write", "injection", "tool_error"]
WORLD_OF_SPLIT = {"dev": "w1", "val": "w2", "test": "w3"}
SPLIT_TOTALS = {"dev": 36, "val": 18, "test": 18}
VARIANT_NOTE = "변형 월드에서 같은 구조의 데이터가 있다고 가정"
SEED_EXTENSION_TAG = "[시드 확장 필요]"


class ScenarioError(ValueError):
    """시나리오 목록·사례 검증 오류. 메시지에 항목 id 를 넣는다."""


class Topic(_Strict):
    category: Category
    agent_paths: frozenset[AgentPath]
    scenarios: frozenset[Scenario]
    per_split: dict[str, int]  # dev·val·test 개수


def _t(cat: str, paths: set[str], kinds: set[str], dev: int, val: int, test: int) -> Topic:
    return Topic(
        category=cat,  # type: ignore[arg-type]
        agent_paths=frozenset(paths),  # type: ignore[arg-type]
        scenarios=frozenset(kinds),  # type: ignore[arg-type]
        per_split={"dev": dev, "val": val, "test": test},
    )


_EARLY = (3, 2, 1)  # 주제 1~6
_LATE = (3, 1, 2)  # 주제 7~12
TOPICS: dict[str, Topic] = {
    "main_routing": _t("D", {"main"}, {"single_tool", "no_tool"}, *_EARLY),
    "schedule_query": _t("C", {"schedule", "main"}, {"single_tool", "multi_tool"}, *_EARLY),
    "billing": _t("D", {"billing"}, {"single_tool", "multi_tool"}, *_EARLY),
    "care": _t("D", {"main"}, {"no_tool"}, *_EARLY),
    "family_chat": _t("A", {"family_chat"}, {"single_tool", "multi_tool"}, *_EARLY),
    "doc_search": _t("D", {"main"}, {"single_tool"}, *_EARLY),
    "compound": _t("D", {"main"}, {"multi_tool"}, *_LATE),
    "ambiguous": _t("E", {"main"}, {"clarify", "no_tool"}, *_LATE),
    "private_1to1": _t("B", {"family_chat"}, {"cross_family"}, *_LATE),
    "group_isolation": _t("H", {"main", "family_chat"}, {"cross_family"}, *_LATE),
    "injection": _t("F", {"family_chat", "main", "billing"}, {"injection"}, *_LATE),
    "tool_failure": _t("G", {"main", "billing"}, {"tool_error"}, *_LATE),
}
# 요구사항 '상황 유형' 표의 "주로 나오는 범주"
SCENARIO_CATEGORIES: dict[str, frozenset[str]] = {
    "single_tool": frozenset("ACD"),
    "multi_tool": frozenset("ACD"),
    "no_tool": frozenset("DE"),
    "clarify": frozenset("CE"),
    "tool_error": frozenset("G"),
    "cross_family": frozenset("BH"),
    "injection": frozenset("F"),
}
RISKS_OF_SCENARIO: dict[str, frozenset[str]] = {
    "cross_family": frozenset({"leak"}),
    "injection": frozenset({"injection", "write"}),
    "tool_error": frozenset({"tool_error"}),
}
_DEFAULT_RISKS = frozenset({"none", "write"})


def normalize(text: str) -> str:
    """NFC 로 합치고 공백·문장부호·쉼표를 없애고 소문자로 맞춘다(중복 비교용)."""
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFC", text)).lower()


class SetupHint(_Strict):
    audience: Literal["me", "room"] = "me"
    room: NonEmpty | None = None
    as_user: NonEmpty | None = None
    seed: NonEmpty | None = None  # 사례 setup.seed 계획값(없음이 기본)
    history_turns: int = Field(default=0, ge=0)  # 사례 setup.history 길이 계획값

    @model_validator(mode="after")
    def _plan_is_possible(self) -> "SetupHint":
        if self.room is not None and self.room not in seed_data.ROOM_MEMBERS:
            raise ValueError(f"방 키가 월드에 없다: {self.room}")
        if self.as_user is not None and self.as_user not in seed_data.ALL_USERS:
            raise ValueError(f"사용자가 월드에 없다: {self.as_user}")
        if (
            self.room is not None
            and self.as_user is not None
            and self.as_user not in seed_data.ROOM_MEMBERS[self.room]
        ):
            raise ValueError(f"{self.as_user} 는 방 {self.room} 의 구성원이 아니다")
        return self


class World(_Strict):
    status: Literal["built", "planned"]
    splits: list[ListSplit]
    note: NonEmpty


class ScenarioItem(_Strict):
    id: NonEmpty
    topic: str
    category: Category
    scenario: Scenario
    split: ListSplit
    world_id: NonEmpty
    agent_path: AgentPath
    purpose: NonEmpty
    expected_behavior: NonEmpty
    setup_hint: SetupHint = Field(default_factory=SetupHint)
    question_signature: NonEmpty
    risk: Risk
    # 노리는 데이터·상황 키("<종류>:<대상>"). 분할 사이에서 같은 (주제, 키, 질문자, 방) 은 같은 상황의 변형이라 거부한다.
    target_key: NonEmpty
    # 그 시나리오가 노리는 비공개 표식(seeds.data 의 실제 값). 사례의 forbidden_strings 에 모두 들어 있어야 한다. 개발셋만 쓴다
    # (검증·테스트는 변형 월드의 값이라 E5c 에서 정한다. 원문은 목록에 두지 않는다).
    private_targets: list[NonEmpty] = Field(default_factory=list)
    # 실행 전에 E5b 가 월드에 더해야 하는 시드. 남아 있으면 `require_runnable` 이 거부한다(개발셋만, 비운 뒤 해시 이력을 갱신한다).
    needs: list[NonEmpty] = Field(default_factory=list)
    # 이 사례가 읽는 가족방에 일정 삭제 주입 문장(INJECTION_TEXT)이 있다. 모델이 따라 일정 쓰기를 부르면 실행기가 사례를
    # unsupported 로 빼 버릴 수 있다(runner.schedule_write_calls). 실행 중 unsupported 건수를 따로 세야 한다.
    schedule_write_exposure: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> "ScenarioItem":
        self._check_basics()
        self._check_security_fields()
        return self

    def _check_security_fields(self) -> None:
        if ":" not in self.target_key:
            raise ValueError(f"{self.id}: target_key 는 '<종류>:<대상>' 형식이다")
        tagged = SEED_EXTENSION_TAG in self.expected_behavior
        # needs 가 남아 있으면 태그가 있어야 한다. E5b 가 시드를 더해 needs 를 비운 뒤에도 서술(expected_behavior)은 확정본 그대로
        # 둬야 하므로 태그만 남은 것(needs 없음)은 **개발 항목에만** 허용한다(서술을 고치면 id·기대 동작 불변 원칙과 해시가 어긋난다).
        # 검증·테스트 항목은 needs 가 없으므로 태그도 있으면 안 된다(E5a 의 규칙 그대로).
        if (self.needs and not tagged) or (not self.needs and tagged and self.split != "dev"):
            raise ValueError(
                f"{self.id}: needs 와 expected_behavior 의 {SEED_EXTENSION_TAG} 태그가 맞지 않는다"
            )
        if self.split != "dev" and self.needs:
            raise ValueError(f"{self.id}: needs 는 개발셋만 쓴다(변형 월드는 월드 상태로 막는다)")
        wants_targets = self.split == "dev" and self.risk in {"leak", "injection"}
        if bool(self.private_targets) != wants_targets:
            raise ValueError(
                f"{self.id}: private_targets 는 개발셋의 leak·injection 시나리오만 비어 있지 않아야 한다"
            )
        user = self.setup_hint.as_user or seed_data.FAMILY_USERS[0]
        private = set(seed_data.forbidden_strings(user))
        for t in self.private_targets:
            if t not in private:
                raise ValueError(
                    f"{self.id}: private_targets {t!r} 는 {user} 에게 비공개인 표식이 아니다"
                )
            if normalize(t) in normalize(self.question_signature):
                raise ValueError(f"{self.id}: 질문에 private_targets {t!r} 가 들어 있다")
        if self.split != "dev":
            text = self.expected_behavior + self.purpose
            if any(ch.isdigit() for ch in text) or any(m.text in text for m in seed_data.TOKENS):
                raise ValueError(
                    f"{self.id}: val·test 의 기대 서술에는 정답 숫자·비밀 표식을 쓰지 않는다"
                )

    def _check_basics(self) -> None:
        topic = TOPICS.get(self.topic)
        if topic is None:
            raise ValueError(f"{self.id}: 알 수 없는 주제 {self.topic}")
        if self.category != topic.category:
            raise ValueError(f"{self.id}: 주제 {self.topic} 의 범주는 {topic.category}")
        if self.agent_path not in topic.agent_paths:
            raise ValueError(f"{self.id}: 주제 {self.topic} 에 {self.agent_path} 경로는 없다")
        if self.scenario not in topic.scenarios:
            raise ValueError(f"{self.id}: 주제 {self.topic} 에 {self.scenario} 유형은 없다")
        if self.category not in SCENARIO_CATEGORIES[self.scenario]:
            raise ValueError(
                f"{self.id}: {self.scenario} 유형은 범주 {self.category} 에 맞지 않는다"
            )
        if self.world_id != WORLD_OF_SPLIT[self.split]:
            raise ValueError(f"{self.id}: {self.split} 분할의 월드는 {WORLD_OF_SPLIT[self.split]}")
        if self.risk not in RISKS_OF_SCENARIO.get(self.scenario, _DEFAULT_RISKS):
            raise ValueError(f"{self.id}: {self.scenario} 유형에 위험 {self.risk} 는 맞지 않는다")
        if self.split != "dev" and VARIANT_NOTE not in self.expected_behavior:
            if not self.expected_behavior.endswith("(월드 데이터 불필요)"):
                raise ValueError(
                    f"{self.id}: val·test 는 변형 월드 가정 문구나 '(월드 데이터 불필요)' 가 필요하다"
                )
        if f"-{self.split}-" not in self.id:
            raise ValueError(f"{self.id}: id 에 분할({self.split})이 들어 있어야 한다")


class UnsupportedItem(_Strict):
    """72건에 세지 않는 시나리오: 이번 범위에서 평가할 수 없어 이유와 함께 둔다."""

    id: NonEmpty
    topic: str
    category: Category
    scenario: Scenario
    purpose: NonEmpty
    question_signature: NonEmpty
    blocked_tools: list[NonEmpty] = Field(min_length=1)
    reason: NonEmpty

    @model_validator(mode="after")
    def _topic_known(self) -> "UnsupportedItem":
        if self.topic not in TOPICS:
            raise ValueError(f"{self.id}: 알 수 없는 주제 {self.topic}")
        bad = [t for t in self.blocked_tools if t not in WRITE_TOOLS["schedule"]]
        if bad:
            raise ValueError(f"{self.id}: blocked_tools 는 일정 쓰기 도구여야 한다: {bad}")
        return self


class ScenarioList(_Strict):
    version: Literal[1]
    worlds: dict[str, World]
    scenarios: list[ScenarioItem]
    unsupported: list[UnsupportedItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _whole(self) -> "ScenarioList":
        ids = [s.id for s in self.scenarios] + [u.id for u in self.unsupported]
        dup = [i for i, n in Counter(ids).items() if n > 1]
        if dup:
            raise ValueError(f"id 가 겹친다: {dup}")
        for s in self.scenarios:
            if s.world_id not in self.worlds:
                raise ValueError(f"{s.id}: 월드 {s.world_id} 가 선언되지 않았다")
            if s.split not in self.worlds[s.world_id].splits:
                raise ValueError(f"{s.id}: 월드 {s.world_id} 는 {s.split} 분할용이 아니다")
        signatures: dict[tuple[str, str | None, str | None, str], str] = {}
        for s in self.scenarios:
            key = (
                normalize(s.question_signature),
                s.setup_hint.audience,
                s.setup_hint.room,
                s.setup_hint.as_user or "",
            )
            if key in signatures:
                raise ValueError(f"{s.id}: 질문이 {signatures[key]} 와 같다(표현만 바꾼 중복)")
            signatures[key] = s.id
        targets: dict[tuple[str, str, str, str], ScenarioItem] = {}
        for s in self.scenarios:
            tk = (s.topic, s.target_key, s.setup_hint.as_user or "", s.setup_hint.room or "")
            other = targets.get(tk)
            if other is not None and other.split != s.split:
                raise ValueError(
                    f"{s.id}: target_key {s.target_key} 가 {other.id} 와 같은 상황이다(분할 사이 변형)"
                )
            targets.setdefault(tk, s)
        return self


def parse_list(raw: object) -> ScenarioList:
    try:
        return ScenarioList.model_validate(raw)
    except ValidationError as e:
        raise ScenarioError(f"시나리오 목록 형식 오류: {e}") from e


def load_raw(directory: Path | None = None) -> dict:
    """분할별 파일과 공통 파일을 합친 원본 목록(dev→val→test 순). 항목이 자기 분할 파일에 있어야 한다."""
    d = directory or DATA_DIR
    names = [META_FILE, *(f"scenarios_{sp}.json" for sp in LISTED_SPLITS)]
    for name in names:
        if not (d / name).exists():
            raise ScenarioError(f"시나리오 목록 파일이 없다: {d / name}")
    raw = json.loads((d / META_FILE).read_text("utf-8"))
    scenarios: list[dict] = []
    for sp in LISTED_SPLITS:
        rows = json.loads((d / f"scenarios_{sp}.json").read_text("utf-8"))
        for row in rows:
            if row.get("split") != sp:
                raise ScenarioError(
                    f"{row.get('id')}: {sp} 분할 파일에 {row.get('split')} 분할 항목이 있다"
                )
        scenarios += rows
    return {**raw, "scenarios": scenarios}


def load_scenarios(directory: Path | None = None) -> ScenarioList:
    return parse_list(load_raw(directory))


# ---- 해시 -------------------------------------------------------------------------------------


def canonical(value: object) -> bytes:
    """정규 JSON: 키 정렬·공백 없음·UTF-8(한글을 이스케이프하지 않는다)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_of(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def list_hash(lst: ScenarioList) -> str:
    """목록 전체(월드·시나리오·unsupported) 해시. 항목 순서도 해시에 들어간다."""
    return sha256_of(lst.model_dump(mode="json"))


def split_hashes(lst: ScenarioList) -> dict[str, str]:
    """분할별 해시: 그 분할의 시나리오를 id 순으로 정렬한 목록의 해시."""
    return {
        sp: sha256_of(
            [
                s.model_dump(mode="json")
                for s in sorted(lst.scenarios, key=lambda s: s.id)
                if s.split == sp
            ]
        )
        for sp in LISTED_SPLITS
    }


def item_hashes(lst: ScenarioList) -> dict[str, str]:
    """항목별 해시(어느 시나리오가 바뀌었는지 찾는 데 쓴다)."""
    return {s.id: sha256_of(s.model_dump(mode="json")) for s in lst.scenarios}


def lock_section(lst: ScenarioList, *, at: str, reason: str) -> dict:
    """처음 확정할 때 `splits.lock.json` 의 `scenarios` 섹션에 쓸 내용."""
    digest = list_hash(lst)
    return {
        "version": lst.version,
        "sha256": digest,
        "per_split": split_hashes(lst),
        "items": item_hashes(lst),
        "count": len(lst.scenarios),
        "finalized_at": at,
        "history": [{"at": at, "reason": reason, "from": None, "to": digest}],
    }


def verify_lock(lst: ScenarioList, lock: dict) -> None:
    """계산한 해시가 잠금 파일과 같고 `history` 가 끊기지 않았는지 본다."""
    section = lock.get("scenarios")
    if not isinstance(section, dict):
        raise ScenarioError("잠금 파일에 scenarios 섹션이 없다")
    problems = []
    if section.get("version") != lst.version:
        problems.append("version")
    if section.get("sha256") != list_hash(lst):
        problems.append("전체 해시")
    if section.get("per_split") != split_hashes(lst):
        problems.append("분할별 해시")
    if section.get("items") != item_hashes(lst):
        problems.append("항목별 해시")
    if section.get("count") != len(lst.scenarios):
        problems.append("건수")
    if problems:
        raise ScenarioError(
            "목록이 잠금 파일과 다르다("
            + ", ".join(problems)
            + "). 고쳤다면 history 에 사유와 해시를 더하고 잠금 파일을 갱신한다"
        )
    history = section.get("history")
    if not isinstance(history, list) or not history:
        raise ScenarioError("history 가 비어 있다")
    prev: str | None = None
    for i, h in enumerate(history):
        if not (isinstance(h, dict) and {"at", "reason", "from", "to"} <= set(h) and h["reason"]):
            raise ScenarioError(f"history[{i}] 형식이 맞지 않는다(at·reason·from·to)")
        if h["from"] != prev:
            raise ScenarioError(f"history[{i}] 의 from 이 앞 항목의 to 와 이어지지 않는다")
        prev = h["to"]
    if prev != section["sha256"]:
        raise ScenarioError("history 의 마지막 to 가 현재 해시와 다르다")


def verify_history_preserved(current: dict, baseline: dict) -> None:
    """기준 잠금 파일(예: 병합된 브랜치)의 history 가 현재 것의 앞부분(접두사)으로 보존됐는지 본다.

    해시가 바뀌었다면 기준의 마지막 해시에서 이어지는 항목이 더해져 있어야 한다(조용히 해시만 바꾸지 못하게 한다).
    """
    cur, base = current["scenarios"], baseline["scenarios"]
    ch, bh = cur["history"], base["history"]
    if ch[: len(bh)] != bh:
        raise ScenarioError(
            "기준 잠금 파일의 history 가 현재 history 의 접두사가 아니다(앞 항목을 고치거나 지웠다)"
        )
    if cur["sha256"] != base["sha256"]:
        if len(ch) == len(bh) or ch[len(bh)]["from"] != base["sha256"]:
            raise ScenarioError(
                "해시가 바뀌었는데 기준 해시에서 이어지는 history 항목이 이어지지 않는다"
            )
