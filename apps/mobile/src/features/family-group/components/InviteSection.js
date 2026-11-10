import { useState } from "react";
import { StyleSheet, Switch, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import SectionTitle from "@/shared/components/SectionTitle";
import { colors, font } from "@/theme";

import { reissueInvite, revokeInvite, setInviteAutoApprove } from "../api";
import { expiryText } from "../messages";
import InviteQrModal from "./InviteQrModal";

/**
 * 가족 관리자에게만 보이는 '가족 초대' 구역. 초대 코드 표시·공유·QR·재발급·폐기와 자동 승인 스위치.
 * busy/error/notice 처리는 부모의 run 이 맡는다.
 * @param {{
 *   group: object,
 *   busy: boolean,
 *   run: (job: () => Promise<unknown>, doneMessage: string) => Promise<void>,
 *   onShare: (code: string) => void,
 *   linkFor: (code: string) => string,
 * }} props group: 가족 그룹, busy: 요청 중 여부, run: 부모의 작업 실행 도우미, onShare: 코드 공유, linkFor: 초대 링크 만들기
 * @returns {JSX.Element} 초대 구역
 */
export default function InviteSection({ group, busy, run, onShare, linkFor }) {
  const [qrOpen, setQrOpen] = useState(false);
  const expiry = expiryText(group.invite_expires_at);
  const usesLeft = group.invite_uses_left == null ? "" : `${group.invite_uses_left}명 더 들어올 수 있어요`;
  const autoApprove = group.invite_auto_approve !== false;
  return (
    <>
      <SectionTitle title="가족 초대" />
      <Card tone="white">
        {group.invite_code ? (
          <>
            <Text style={styles.code} selectable accessibilityLabel="초대 코드" testID="invite-code">
              {group.invite_code}
            </Text>
            <Text style={styles.sub}>
              {[expiry, usesLeft].filter(Boolean).join(" · ")}
              {autoApprove ? "\n코드를 받은 사람은 바로 가족이 돼요." : "\n코드를 받은 사람은 관리자의 승인을 거쳐 들어와요."}
            </Text>
            <View style={styles.buttons}>
              <View style={styles.grow}>
                <Button label="초대 링크 보내기" onPress={() => onShare(group.invite_code)} disabled={busy} testID="invite-share" />
              </View>
              <View style={styles.grow}>
                <Button label="QR 보기" variant="secondary" onPress={() => setQrOpen(true)} disabled={busy} testID="invite-qr" />
              </View>
            </View>
            <InviteQrModal
              visible={qrOpen}
              link={linkFor(group.invite_code)}
              code={group.invite_code}
              caption={[expiry, usesLeft].filter(Boolean).join(" · ")}
              onClose={() => setQrOpen(false)}
            />
            <View style={styles.buttons}>
              <View style={styles.grow}>
                <Button label="새 코드 만들기" small variant="secondary" onPress={() => run(reissueInvite, "새 초대 코드를 만들었어요. 이전 코드는 쓸 수 없어요")} disabled={busy} testID="invite-reissue" />
              </View>
              <View style={styles.grow}>
                <Button label="코드 폐기" small variant="secondary" onPress={() => run(revokeInvite, "초대 코드를 폐기했어요")} disabled={busy} testID="invite-revoke" />
              </View>
            </View>
          </>
        ) : (
          <>
            <Text style={styles.sub}>지금 쓸 수 있는 초대 코드가 없어요. 새 코드를 만들어 가족에게 알려 주세요.</Text>
            <Button label="초대 코드 만들기" onPress={() => run(reissueInvite, "초대 코드를 만들었어요")} disabled={busy} testID="invite-reissue" />
          </>
        )}
        <View style={styles.switchRow}>
          <View style={styles.text}>
            <Text style={styles.name}>초대받은 사람 바로 들어오기</Text>
            <Text style={styles.sub}>끄면 내가 승인해야 가족이 돼요</Text>
          </View>
          <Switch
            value={autoApprove}
            onValueChange={(v) => run(() => setInviteAutoApprove(v), v ? "이제 초대받은 사람이 바로 들어와요" : "이제 내가 승인해야 들어와요")}
            disabled={busy}
            accessibilityLabel="초대받은 사람 바로 들어오기"
            testID="invite-auto-approve"
          />
        </View>
      </Card>
    </>
  );
}

const styles = StyleSheet.create({
  sub: { ...font.body, color: colors.textSub },
  text: { flex: 1 },
  name: { ...font.bodyStrong, color: colors.text },
  code: { ...font.h1, color: colors.text, letterSpacing: 2, textAlign: "center", paddingVertical: 8 },
  buttons: { flexDirection: "row", gap: 8 },
  grow: { flex: 1 },
  switchRow: { flexDirection: "row", alignItems: "center", gap: 12, marginTop: 12 },
});
