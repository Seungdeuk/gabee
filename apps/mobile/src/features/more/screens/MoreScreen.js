import { useRouter } from "expo-router";
import { useState } from "react";
import { StyleSheet, Switch, Text, View } from "react-native";

import FamilyGroupCard from "@/features/family-group/components/FamilyGroupCard";
import AccountCard from "@/shared/auth/AccountCard";
import Card from "@/shared/components/Card";
import IconButton from "@/shared/components/IconButton";
import ListItem from "@/shared/components/ListItem";
import Screen from "@/shared/components/Screen";
import SectionTitle from "@/shared/components/SectionTitle";
import Tag from "@/shared/components/Tag";
import { colors, font } from "@/theme";

import { today } from "../mock";

function SettingRow({ title, subtitle, value, onValueChange }) {
  return (
    <View style={styles.setting}>
      <View style={styles.settingText}>
        <Text style={styles.settingTitle}>{title}</Text>
        <Text style={styles.settingSub}>{subtitle}</Text>
      </View>
      <Switch
        value={value}
        onValueChange={onValueChange}
        trackColor={{ true: colors.primary }}
        accessibilityLabel={title}
      />
    </View>
  );
}

/** 기타 탭: 가족의 오늘 요약(원본 홈 화면), 가족 그룹, 설정. */
export default function MoreScreen() {
  const router = useRouter();
  // TODO: 동의 상태를 서버(자동 전송·위치 저장 설정)와 연결한다. 켤 때는 동의 확인이 필요하다.
  const [autoUpload, setAutoUpload] = useState(false);
  const [saveLocation, setSaveLocation] = useState(false);

  return (
    <Screen
      title="기타"
      subtitle="가족 그룹과 설정"
      left={<IconButton name="chevron-back" label="뒤로" onPress={() => router.back()} />}
    >
      <SectionTitle title="계정" />
      <AccountCard />

      <Card tone="blue">
        <Text style={styles.label}>{today.date}</Text>
        <Text style={styles.heading}>우리 가족의 오늘</Text>
        <Text style={styles.sub}>{today.family}</Text>
      </Card>

      <SectionTitle title="오늘 체크" />
      <Card tone="white">
        {today.checks.map((item) => (
          <ListItem
            key={item.id}
            icon={item.icon}
            tone={item.tone}
            title={item.title}
            right={<Tag label={item.status} tone={item.tone} />}
          />
        ))}
      </Card>
      <Card tone="orange">
        <Text style={styles.notice}>{today.notice}</Text>
      </Card>

      <SectionTitle title="가족 그룹" />
      <FamilyGroupCard />

      <SectionTitle title="설정" />
      <Card tone="white">
        <SettingRow
          title="사진 자동 전송"
          subtitle="찍는 사진을 가족 기록으로 보내요. 켠 뒤에 찍은 사진부터 받아요."
          value={autoUpload}
          onValueChange={setAutoUpload}
        />
        <SettingRow
          title="촬영 위치 저장"
          subtitle="자동 전송과 별도로 켜고 끌 수 있어요."
          value={saveLocation}
          onValueChange={setSaveLocation}
        />
      </Card>
    </Screen>
  );
}

const styles = StyleSheet.create({
  label: { ...font.caption, color: colors.primaryDark, fontWeight: "600" },
  heading: { ...font.h1, color: colors.text },
  sub: { ...font.body, color: colors.textSub },
  notice: { ...font.body, color: colors.textSub },
  setting: { flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 8 },
  settingText: { flex: 1, gap: 2 },
  settingTitle: { ...font.bodyStrong, color: colors.text },
  settingSub: { ...font.caption, color: colors.textMuted },
});
