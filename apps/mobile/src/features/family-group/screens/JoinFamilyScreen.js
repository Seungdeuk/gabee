import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";

import Button from "@/shared/components/Button";
import Field from "@/shared/components/Field";

import { requestJoin } from "../api";
import FamilyFrame from "../components/FamilyFrame";
import Notice from "../components/Notice";
import { familyErrorMessage } from "../messages";

const normalize = (value) => value.replace(/\s/g, "").toUpperCase();

/**
 * 초대 코드 입력. 가족이 자동 승인을 켜 두었으면 바로 가족 화면으로, 아니면 관리자의 승인을 기다리는 화면으로 간다.
 * 초대 링크(gabee://family-join?code=...)로 열리면 코드가 미리 채워진다.
 * 코드는 화면 상태에만 두고 로그로 남기지 않는다.
 */
export default function JoinFamilyScreen() {
  const router = useRouter();
  const { code: linkCode } = useLocalSearchParams();
  const [code, setCode] = useState(() => normalize(String(linkCode ?? "")));
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
      // 자동 승인이 켜진 가족이면 approved 로 바로 구성원이 되고, 아니면 pending 으로 승인을 기다린다
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
        hint="가족에 따라 바로 들어가거나, 가족 관리자가 승인하면 들어가요"
        onSubmitEditing={submit}
        testID="join-code"
      />
      <Notice tone="error" text={error} />
      <Button label={busy ? "요청 중..." : "참여 요청 보내기"} onPress={submit} disabled={busy || code.length < 4} testID="join-submit" />
    </FamilyFrame>
  );
}
