import { useRouter } from "expo-router";
import { useState } from "react";

import Button from "@/shared/components/Button";
import Field from "@/shared/components/Field";

import { requestJoin } from "../api";
import FamilyFrame from "../components/FamilyFrame";
import Notice from "../components/Notice";
import { familyErrorMessage } from "../messages";

const normalize = (value) => value.replace(/\s/g, "").toUpperCase();

/**
 * 초대 코드 입력. 정식 회원은 가족 관리자의 승인을 기다리는 화면으로, 기존 익명 계정은 바로 가족 화면으로 간다.
 * 코드는 화면 상태에만 두고 로그로 남기지 않는다.
 */
export default function JoinFamilyScreen() {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (code.length < 4) {
      setError("초대 코드를 입력해 주세요");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const res = await requestJoin(code);
      router.replace(res.status === "pending" ? "/family-pending" : "/family");
    } catch (e) {
      setError(familyErrorMessage(e));
      if (e.code === "invalid_invite") setCode("");
      setBusy(false);
    }
  };

  return (
    <FamilyFrame title="초대 코드로 참여" subtitle="가족 관리자에게 받은 초대 코드를 입력해 주세요">
      <Field
        label="초대 코드"
        value={code}
        onChangeText={(v) => setCode(normalize(v))}
        autoCapitalize="characters"
        autoCorrect={false}
        maxLength={12}
        placeholder="예: K7M2Q9XW4P"
        hint="가족 관리자가 승인하면 가족 그룹에 들어가요. 새 초대 코드는 24시간 동안 한 번만 쓸 수 있어요"
        onSubmitEditing={submit}
        testID="join-code"
      />
      <Notice tone="error" text={error} />
      <Button label={busy ? "요청 중..." : "참여 요청 보내기"} onPress={submit} disabled={busy || code.length < 4} testID="join-submit" />
    </FamilyFrame>
  );
}
