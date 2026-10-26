import { useRouter } from "expo-router";
import { useState } from "react";

import Button from "@/shared/components/Button";
import Field from "@/shared/components/Field";

import { createGroup } from "../api";
import FamilyFrame from "../components/FamilyFrame";
import Notice from "../components/Notice";
import { familyErrorMessage } from "../messages";

/** 새 가족 만들기: 이름을 정하면 내가 소유자가 되고 초대 코드를 만들 수 있다. */
export default function CreateFamilyScreen() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim()) {
      setError("가족 이름을 입력해 주세요");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await createGroup(name.trim());
      router.replace("/family");
    } catch (e) {
      setError(familyErrorMessage(e));
      setBusy(false);
    }
  };

  return (
    <FamilyFrame title="가족 만들기" subtitle="가족 이름을 정하면 내가 소유자가 돼요">
      <Field label="가족 이름" value={name} onChangeText={setName} maxLength={60} placeholder="예: 우리 가족" onSubmitEditing={submit} testID="family-name" />
      <Notice tone="error" text={error} />
      <Button label={busy ? "만드는 중..." : "가족 만들기"} onPress={submit} disabled={busy} testID="family-create" />
    </FamilyFrame>
  );
}
