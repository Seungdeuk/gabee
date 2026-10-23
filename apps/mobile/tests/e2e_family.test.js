// 실제 서버(격리된 임시 DB 로 띄운 FastAPI)에 대한 가족 초대·가입 승인 흐름 시험. 평소 npm test 에서는 건너뛴다.
// 서버는 임시 SQLite 로 띄우고 GABEE_E2E_API_URL 만 알려 준다(메일 설정이 없으면 이메일 인증 정책은 적용되지 않는다).
import assert from "node:assert/strict";
import { describe, test } from "node:test";

const URL_BASE = process.env.GABEE_E2E_API_URL;
const skip = !URL_BASE ? "GABEE_E2E_API_URL 이 필요해요" : false;

process.env.EXPO_PUBLIC_API_URL = URL_BASE ?? "";
process.env.EXPO_PUBLIC_DEV_TOKEN = "";

describe("가족 초대·승인 ↔ 실제 서버", { skip }, () => {
  test("초대 → 참여 요청 → 승인 대기 → 관리자 승인 → 구성원, 거절·취소·재사용", async () => {
    const client = await import("../src/shared/api/client.js");
    const auth = await import("../src/features/auth/api.js");
    const sessionApi = await import("../src/shared/auth/sessionApi.js");
    const family = await import("../src/features/family-group/api.js");
    const suffix = Date.now().toString(36);

    const as = async (id, name) => {
      const form = { loginId: `${id}_${suffix}`, password: "Sunny-day-2026", email: `${id}_${suffix}@example.com`, name };
      await auth.signupAccount(form);
      const login = await sessionApi.login(form.loginId, form.password);
      return () => client.setSession({ accessToken: login.access_token, refreshToken: login.refresh_token });
    };
    const owner = await as("mom", "엄마");
    const guest = await as("jimin", "지민");
    const other = await as("uncle", "삼촌");

    owner();
    const group = await family.createGroup("우리 가족");
    assert.equal(group.invite_code.length, 10);
    assert.equal(group.my_role, "owner");

    guest();
    const sent = await family.requestJoin(group.invite_code);
    assert.equal(sent.status, "pending"); // 정식 회원은 바로 들어가지 못한다
    await assert.rejects(family.getMyGroup(), { status: 404 }); // 승인 전에는 가족 정보가 없다
    assert.equal((await family.getMyJoinRequest()).status, "pending");
    await assert.rejects(family.listJoinRequests(), { code: "no_group" }); // 승인 대기자는 아직 가족이 없어 관리자 기능을 못 쓴다

    other();
    await assert.rejects(family.requestJoin(group.invite_code), { code: "invalid_invite" }); // 1회용 코드는 이미 사용됨

    owner();
    const pending = await family.listJoinRequests();
    assert.deepEqual(pending.map((r) => r.user_name), ["지민"]);
    const approved = await family.approveJoinRequest(pending[0].id);
    assert.deepEqual(approved.members.map((m) => [m.name, m.group_role]).sort(), [["엄마", "owner"], ["지민", "member"]]);
    await assert.rejects(family.approveJoinRequest(pending[0].id), { code: "join_request_already_decided" });

    guest();
    assert.equal((await family.getMyGroup()).my_role, "member");
    assert.equal((await family.getMyJoinRequest()).status, "approved");
    await assert.rejects(family.reissueInvite(), { code: "not_manager" });

    // 새 코드 → 거절, 그리고 취소
    owner();
    const second = await family.reissueInvite();
    other();
    const request = await family.requestJoin(second.invite_code);
    owner();
    await family.rejectJoinRequest(request.id);
    other();
    assert.equal((await family.getMyJoinRequest()).status, "rejected");
    owner();
    const third = await family.reissueInvite();
    other();
    const again = await family.requestJoin(third.invite_code);
    await family.cancelJoinRequest(again.id);
    assert.equal((await family.getMyJoinRequest()).status, "cancelled");
  });
});
