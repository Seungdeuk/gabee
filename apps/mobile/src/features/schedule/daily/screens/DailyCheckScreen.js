import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppState, Linking, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import Svg, { Path } from "react-native-svg";

import { colors, font, radius, spacing } from "@/theme";

import { ME_ID } from "../../mock";
import {
  listCheers,
  toggleCheerThanked,
  listEntries,
  listFamilyPhone,
  listFamilyToday,
  listItems,
  loadCallMemo,
  loadOnboarded,
  loadTabOrder,
  deleteItem,
  saveCallMemo,
  sendCheer,
  setEntry,
} from "../api";
import CallDoneSheet from "../components/CallDoneSheet";
import ConfirmSheet, { ConfirmBody } from "../components/ConfirmSheet";
import CallSheet from "../components/CallSheet";
import CheerSheet from "../components/CheerSheet";
import CheerStrip from "../components/CheerStrip";
import PencilIcon from "../components/PencilIcon";
import DailyRow from "../components/DailyRow";
import {
  ROW_GAP,
  ROW_HEIGHT,
  ROW_MENU_HOLD_MS,
  HOLD_CANCEL_PX,
  applyCheck,
  applyStep,
  cheerSubtitle,
  familyRowsOf,
  findCallItem,
  formatClock,
  formatDayLabel,
  isDone,
  lastRecordOf,
  nowClock,
  normalizeTabs,
  progressOf,
  tabLabel,
  talkingPoints,
  todayItemsOf,
  visibleTabIds,
  ROW_MENU,
  rowMenuAction,
  rowMenuTop,
  shouldHideDotsOnTouch,
} from "../logic";
import { useDailyMembers, useDailyScope } from "../scope";
import { todayKey } from "../../utils/date";

/**
 * 데일리 체크 메인: 내 탭(체크·횟수, 줄을 길게 누르면 수정·삭제 메뉴, 받은 응원 칩)과 가족 탭(보기만, 응원 보내기·전화 버튼).
 * 순서 바꾸기는 가족 순서 바꾸기 화면과 내 항목 편집 화면에서만 한다(이 화면은 드래그하지 않는다).
 * 저장은 이 폰에만 하고(api.js), 가족 기록·전화번호는 mock 이다. 처음이고 항목이 없으면 온보딩으로 보낸다.
 * 전화는 Linking 으로 전화 앱을 열고, 앱으로 돌아오면(AppState active) 통화 뒤 시트를 띄운다.
 */
export default function DailyCheckScreen() {
  const router = useRouter();
  const scope = useDailyScope();
  const members = useDailyMembers();
  const today = todayKey();

  const [items, setItems] = useState([]);
  const [entries, setEntries] = useState({});
  const [tabState, setTabState] = useState({ order: [], hidden: [] });
  const [familyItems, setFamilyItems] = useState({});
  const [cheers, setCheers] = useState([]);
  const [tab, setTab] = useState(ME_ID);
  const [showMenuDots, setShowMenuDots] = useState(false); // 내 줄을 길게 누르면 켜지는 점 표시 모드: 모든 줄 왼쪽에 점 세 개
  const [menuFor, setMenuFor] = useState(null); // 점 세 개를 누르면 여는 줄 메뉴: { id, index }
  // 점 표시 모드의 바깥 터치 종료: 줄·점·메뉴 밖을 누르면 루트 onTouchStart 에서 점과 메뉴를 한 번에 닫는다.
  const insideRef = useRef(false);
  const markInside = () => {
    insideRef.current = true;
  };
  const onScreenTouch = () => {
    const action = shouldHideDotsOnTouch({ showDots: showMenuDots, insideRow: insideRef.current });
    insideRef.current = false;
    if (action === "hideAll") {
      setShowMenuDots(false);
      setMenuFor(null);
    }
  };
  const [sheet, setSheet] = useState(null); // 확인 팝업(ConfirmSheet) 내용. null 이면 닫힘
  // 화면을 떠나면 줄 메뉴를 닫는다. 다시 들어와도 닫힌 상태로 시작한다.
  useFocusEffect(
    useCallback(
      () => () => {
        setMenuFor(null);
        setShowMenuDots(false);
      },
      [],
    ),
  );
  const [cheerFor, setCheerFor] = useState(null); // 응원 시트를 연 가족 id
  const [dismissedCheers, setDismissedCheers] = useState([]); // 카드 X 로 닫은 응원 id(고마워 보냄과는 별개)
  const [callFor, setCallFor] = useState(null); // 전화 확인 시트를 연 가족 id
  const [callDone, setCallDone] = useState(null); // 통화 뒤 시트: { memberId, memo }
  const [phone, setPhone] = useState(null);
  const pendingCall = useRef(null); // 전화 앱을 연 가족 id(앱으로 돌아오면 통화 뒤 시트를 띄운다)

  // 가족 구성원(나 제외). 키 글자로 묶어 두면 목록이 같을 때 다시 읽지 않는다.
  const familyIds = useMemo(() => members.filter((m) => m.id !== ME_ID).map((m) => m.id), [members]);
  const familyKey = familyIds.join(",");
  const tabs = normalizeTabs(tabState, familyIds);
  const visibleIds = visibleTabIds(tabs);
  const nameOf = (id) => members.find((m) => m.id === id)?.name ?? "";

  useFocusEffect(
    useCallback(() => {
      let alive = true;
      Promise.all([listItems(scope), listEntries(scope, today), loadTabOrder(scope), loadOnboarded(scope), listCheers(scope)]).then(
        ([its, ens, tb, onboarded, cs]) => {
          if (!alive) return;
          // 처음 열었고 항목도 없으면 온보딩으로 보낸다(완료 표시가 남으면 다시 보내지 않는다)
          if (!onboarded && its.length === 0) {
            router.replace("/schedule/daily-onboarding");
            return;
          }
          setItems(its);
          setEntries(ens);
          setTabState(tb);
          setCheers(cs);
        },
      );
      return () => {
        alive = false;
      };
    }, [scope, today, router]),
  );

  // 가족 구성원마다 오늘 항목을 한 번 읽는다(탭 라벨의 완료 수에 쓴다).
  useEffect(() => {
    let alive = true;
    const ids = familyKey ? familyKey.split(",") : [];
    Promise.all(ids.map(async (id) => [id, await listFamilyToday(id)])).then((pairs) => {
      if (alive) setFamilyItems(Object.fromEntries(pairs));
    });
    return () => {
      alive = false;
    };
  }, [familyKey]);

  // 통화 뒤 시트: 전화 앱에 다녀와서 앱이 다시 활성이 되면 연 가족의 메모 시트를 띄운다.
  // 최신 openCallDone 을 ref 로 들고 있어 구독은 한 번만 붙인다.
  const openCallDoneRef = useRef(null);
  openCallDoneRef.current = openCallDone;
  useEffect(() => {
    const sub = AppState.addEventListener("change", (state) => {
      if (state !== "active" || !pendingCall.current) return;
      const memberId = pendingCall.current;
      pendingCall.current = null;
      openCallDoneRef.current?.(memberId);
    });
    return () => sub.remove();
  }, []);

  // 전화 번호: 전화 확인 시트를 열 때 한 번 읽는다.
  useEffect(() => {
    let alive = true;
    setPhone(null);
    if (callFor) listFamilyPhone(callFor).then((p) => alive && setPhone(p));
    return () => {
      alive = false;
    };
  }, [callFor]);

  // 탭 줄: 나(고정) + 보이는 가족. 라벨은 "이름 완료/전체".
  const mine = todayItemsOf(items, today);
  const myProgress = progressOf(mine, (item) => entries[item.id]);
  const familyRows = (id) => familyRowsOf(familyItems[id] ?? [], today);
  const tabList = [
    { id: ME_ID, label: tabLabel("나", myProgress.done, myProgress.total) },
    ...visibleIds.map((id) => {
      const p = progressOf(familyRows(id), (row) => row.entry);
      return { id, label: tabLabel(nameOf(id), p.done, p.total) };
    }),
  ];
  const activeTab = tabList.some((t) => t.id === tab) ? tab : ME_ID;
  const isMe = activeTab === ME_ID;
  const activeRows = isMe ? [] : familyRows(activeTab);
  const activeProgress = progressOf(activeRows, (row) => row.entry);
  const cheerRows = cheerFor ? familyRows(cheerFor) : [];
  const cheerProgress = progressOf(cheerRows, (row) => row.entry);
  const callRows = callFor ? familyRows(callFor) : [];

  const leave = () => (router.canGoBack() ? router.back() : router.replace("/(tabs)/schedule"));
  const pickTab = (id) => {
    setMenuFor(null);
    setShowMenuDots(false);
    setTab(id);
  };

  // 한 번 체크·횟수는 바로 화면에 반영하고 이 폰에 저장한다.
  const persistEntry = (itemId, next) => {
    setEntries((prev) => ({ ...prev, [itemId]: next }));
    setEntry(scope, today, itemId, next);
  };
  const onCheck = (item) => persistEntry(item.id, applyCheck(entries[item.id], nowClock()));
  const onStep = (item, delta) => persistEntry(item.id, applyStep(item, entries[item.id], delta, nowClock()));

  // ── 줄 메뉴 ──
  // 내 줄을 길게 누르면(ROW_MENU_HOLD_MS) 그 줄 아래에 수정·삭제 메뉴가 뜬다. 메뉴 바깥을 누르면 닫힌다.
  // 메뉴: 수정은 항목 수정 화면, 삭제는 확인 뒤 지운다.
  const runMenu = (key) => {
    const item = menuFor ? mine[menuFor.index] : null;
    setMenuFor(null);
    setShowMenuDots(false);
    if (!item) return;
    const action = rowMenuAction(key);
    if (action === "edit") {
      router.push({ pathname: "/schedule/daily-item", params: { id: item.id } });
    } else if (action === "delete") {
      setSheet({
        title: "이 습관을 삭제할까요?",
        body: <ConfirmBody name={item.name} note="삭제하면 되돌릴 수 없어요" />,
        cancelLabel: "취소",
        confirmLabel: "삭제",
        tone: "danger",
        onConfirm: async () => {
          setSheet(null);
          await deleteItem(scope, item.id);
          setItems((prev) => prev.filter((x) => x.id !== item.id));
        },
      });
    }
  };

  // ── 응원 ──
  // 고마워를 누르면 카드가 사라지고(전부 누르면 배너), 저장된 목록을 다시 읽는다.
  const thankCheer = async (id) => {
    await toggleCheerThanked(scope, id);
    setCheers(await listCheers(scope));
  };
  const sendTo = async (memberId, cheer) => {
    await sendCheer(scope, { ...cheer, toId: memberId, toName: nameOf(memberId), date: today, time: nowClock() });
    setCheers(await listCheers(scope));
    setCheerFor(null);
  };

  // ── 전화 ──
  const startCall = async (memberId) => {
    if (!phone) return;
    setCallFor(null);
    pendingCall.current = memberId;
    try {
      await Linking.openURL(`tel:${phone.dial}`);
    } catch {
      pendingCall.current = null;
      setSheet({
        title: "전화 앱을 열지 못했어요",
        body: "번호를 직접 눌러 전화해 주세요",
        confirmLabel: "확인",
        onConfirm: () => setSheet(null),
      });
    }
  };

  function openCallDone(memberId) {
    setCallDone({ memberId, memo: "" });
    loadCallMemo(scope, today, memberId).then((memo) =>
      setCallDone((prev) => (prev && prev.memberId === memberId ? { ...prev, memo } : prev)),
    );
  }

  // "완료로 체크하기": 메모를 저장하고 오늘 목록의 "안부 전화" 항목을 완료로 바꾼다. 없으면 안내 문구를 돌려준다.
  const finishCall = (memo) => {
    const memberId = callDone.memberId;
    saveCallMemo(scope, today, memberId, memo.trim());
    const target = findCallItem(items, today);
    if (!target) return "오늘 목록에 ‘안부 전화’ 습관이 없어요, 습관을 추가하면 여기서 체크할 수 있어요";
    if (!isDone(target, entries[target.id])) {
      persistEntry(target.id, { done: true, count: 0, doneAt: nowClock() });
    }
    setCallDone(null);
    return "";
  };
  const laterCall = (memo) => {
    if (callDone) saveCallMemo(scope, today, callDone.memberId, memo.trim());
    setCallDone(null);
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]} onTouchStart={onScreenTouch}>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        {/* 시안 순서: ① "‹ 일정" 줄 ② 제목 줄(오늘의 안녕 … 연필 편집) ③ 날짜 줄 */}
        <View style={styles.head}>
          <Pressable
            onPress={leave}
            style={styles.back}
            accessibilityRole="button"
            accessibilityLabel="일정으로 돌아가기"
            hitSlop={6}
          >
            <Ionicons name="chevron-back" size={20} color={colors.accent} />
            <Text style={styles.backText}>일정</Text>
          </Pressable>
          <View style={styles.titleRow}>
            <Text style={styles.title} accessibilityRole="header">
              오늘의 안녕
            </Text>
            <Pressable
              onPress={() => router.push("/schedule/daily-edit")}
              style={styles.editLink}
              accessibilityRole="button"
              accessibilityLabel="내 습관 편집"
            >
              <PencilIcon size={18} />
              <Text style={styles.editText}>편집</Text>
            </Pressable>
          </View>
          <Text style={styles.date}>{formatDayLabel(today)}</Text>
        </View>

        <View style={styles.tabBar}>
          {/* 탭 줄: 가로 스크롤. 칩은 눌러서 고르기만 한다(순서는 가족 순서 바꾸기 화면에서 바꾼다). 나는 맨 앞 고정. */}
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.tabScroll} contentContainerStyle={styles.tabRow}>
            {tabList.map((t) => (
              <TabChip key={t.id} t={t} on={t.id === activeTab} onPress={() => pickTab(t.id)} />
            ))}
          </ScrollView>
          <Pressable
            onPress={() => router.push("/schedule/daily-tabs")}
            style={styles.tabEdit}
            accessibilityRole="button"
            accessibilityLabel="가족 순서 편집"
          >
            <Svg width={18} height={18} viewBox="0 0 24 24" fill="none" stroke={colors.text} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <Path d="M4 8h14M15 5l3 3-3 3M20 16H6M9 13l-3 3 3 3" />
            </Svg>
            <Text style={styles.tabEditText}>편집</Text>
          </Pressable>
        </View>

        {isMe ? (
          <ProgressCard tone="me" title="오늘 나의 체크" done={myProgress.done} total={myProgress.total} pct={myProgress.pct} />
        ) : (
          <ProgressCard
            tone="family"
            title={`${nameOf(activeTab)}의 오늘`}
            done={activeProgress.done}
            total={activeProgress.total}
            pct={activeProgress.pct}
            last={lastRecordOf(activeRows)}
          />
        )}

        {isMe ? (
          <CheerStrip
            cheers={cheers}
            today={today}
            dismissed={dismissedCheers}
            onReplyInfo={() =>
              setSheet({
                title: "답장은 곧 만들어져요",
                body: "가족 대화방으로 이어지는 답장은 아직 준비 중이에요",
                confirmLabel: "확인",
              })
            }
            onThank={thankCheer}
            onDismiss={(id) => setDismissedCheers((prev) => (prev.includes(id) ? prev : [...prev, id]))}
            onOpenHistory={() => router.push("/schedule/daily-cheer-history")}
          />
        ) : null}

        <View style={[styles.list, styles.listWrap]}>
          {/* 내 줄을 길게 누르면(ROW_MENU_HOLD_MS) 그 줄 아래에 수정·삭제 메뉴가 뜬다. 메뉴 바깥을 누르면 닫힌다. */}
          {isMe ? (
            mine.length ? (
              mine.map((item, index) => (
                <View key={item.id} style={styles.rowWrap} onTouchStart={markInside}>
                  <Pressable
                    onLongPress={() => {
                      setMenuFor(null);
                      setShowMenuDots(true);
                    }}
                    delayLongPress={ROW_MENU_HOLD_MS}
                    pressRetentionOffset={HOLD_CANCEL_PX}
                    accessibilityHint="길게 누르면 줄 메뉴 점 세 개가 나타나요"
                  >
                    <DailyRow
                      item={item}
                      entry={entries[item.id]}
                      handle={
                        showMenuDots ? (
                          <Pressable
                            onPress={() => setMenuFor({ id: item.id, index })}
                            style={styles.dots}
                            accessibilityRole="button"
                            accessibilityLabel={`${item.name} 메뉴 열기`}
                          >
                            <Ionicons name="ellipsis-vertical" size={20} color={colors.textMuted} />
                          </Pressable>
                        ) : null
                      }
                      onCheck={() => onCheck(item)}
                      onStep={(delta) => onStep(item, delta)}
                    />
                  </Pressable>
                </View>
              ))
            ) : (
              <Text style={styles.empty}>오늘 해당하는 습관이 없어요, 아래에서 추가해 보세요</Text>
            )
          ) : activeRows.length ? (
            activeRows.map((row) => (
              <View key={row.id} style={styles.familyRow}>
                <DailyRow item={row} entry={row.entry} family />
              </View>
            ))
          ) : (
            <Text style={styles.empty}>가족에게 보이는 습관이 오늘 없어요</Text>
          )}
          {/* 점 표시 모드에서 점을 누르면 그 줄 아래에 메뉴 카드를 올린다. 바깥 터치는 루트에서 점과 메뉴를 모두 닫는다. */}
          {isMe && showMenuDots && menuFor && mine[menuFor.index] ? (
            <>
              <View onTouchStart={markInside} style={[styles.rowMenu, { top: rowMenuTop(menuFor.index, mine.length, ROW_HEIGHT + ROW_GAP, ROW_HEIGHT, 96) }]}>
                {ROW_MENU.map((m) => (
                  <Pressable
                    key={m.key}
                    onPress={() => runMenu(m.key)}
                    style={styles.menuItem}
                    accessibilityRole="button"
                    accessibilityLabel={m.label}
                  >
                    {m.icon === "pencil" ? <PencilIcon size={18} /> : null}
                    {m.icon === "trash" ? <Ionicons name="trash-outline" size={18} color={colors.danger} /> : null}
                    <Text style={[styles.menuText, m.danger && styles.menuDanger]}>{m.label}</Text>
                  </Pressable>
                ))}
              </View>
            </>
          ) : null}
        </View>

        {isMe ? (
          <View style={styles.footer}>
            <Pressable
              onPress={() => router.push("/schedule/daily-item")}
              style={styles.addButton}
              accessibilityRole="button"
              accessibilityLabel="습관 추가"
            >
              <Text style={styles.addText}>+ 습관 추가</Text>
            </Pressable>
          </View>
        ) : (
          <View style={styles.footer}>
            <View style={styles.familyActions}>
              <Pressable
                onPress={() => setCheerFor(activeTab)}
                style={[styles.actionBtn, styles.actionLine]}
                accessibilityRole="button"
                accessibilityLabel={`${nameOf(activeTab)}에게 응원 보내기`}
              >
                <Text style={styles.actionLineText}>응원 보내기</Text>
              </Pressable>
              <Pressable
                onPress={() => setCallFor(activeTab)}
                style={[styles.actionBtn, styles.actionPeach]}
                accessibilityRole="button"
                accessibilityLabel={`${nameOf(activeTab)}에게 전화`}
              >
                <Text style={styles.actionPeachText}>{`${nameOf(activeTab)}에게 전화`}</Text>
              </Pressable>
            </View>
          </View>
        )}
      </ScrollView>

      <CheerSheet
        visible={cheerFor !== null}
        onClose={() => setCheerFor(null)}
        title={`${nameOf(cheerFor ?? "")}에게 응원 보내기`}
        subtitle={cheerSubtitle(cheerProgress.done, cheerProgress.total)}
        onSend={(cheer) => sendTo(cheerFor, cheer)}
      />
      <CallSheet
        visible={callFor !== null}
        onClose={() => setCallFor(null)}
        memberId={callFor ?? ""}
        memberName={nameOf(callFor ?? "")}
        phone={phone}
        points={talkingPoints(callRows)}
        onCall={() => startCall(callFor)}
      />
      <CallDoneSheet
        visible={callDone !== null}
        memberName={nameOf(callDone?.memberId ?? "")}
        initialMemo={callDone?.memo ?? ""}
        onDone={finishCall}
        onLater={laterCall}
      />
      <ConfirmSheet
        visible={sheet !== null}
        title={sheet?.title ?? ""}
        body={sheet?.body}
        cancelLabel={sheet?.cancelLabel}
        confirmLabel={sheet?.confirmLabel ?? "확인"}
        tone={sheet?.tone}
        onCancel={() => setSheet(null)}
        onConfirm={() => (sheet?.onConfirm ? sheet.onConfirm() : setSheet(null))}
      />
    </SafeAreaView>
  );
}

/** 탭 줄의 사람 칩. 선택됨은 외곽선 없이 노란 채움(테두리는 바탕색과 같게 두어 크기를 맞춘다). */
function TabChip({ t, on, onPress }) {
  return (
    <Pressable
      onPress={onPress}
      style={[styles.tab, on ? styles.tabOn : styles.tabOff]}
      accessibilityRole="button"
      accessibilityState={{ selected: on }}
      accessibilityLabel={`${t.label} 탭`}
    >
      <Text style={[styles.tabText, on ? styles.tabTextOn : styles.tabTextOff]}>{t.label}</Text>
    </Pressable>
  );
}

/** 진행률 카드. 내 탭은 복숭아색 옅은 바탕, 가족 탭은 녹색 옅은 바탕이다. */
function ProgressCard({ tone, title, done, total, pct, last = null }) {
  const family = tone === "family";
  return (
    <View style={[styles.progress, family ? styles.progressFamily : styles.progressMe]}>
      <View style={styles.progressTop}>
        <Text style={[styles.progressTitle, family && styles.progressTitleFamily]}>{title}</Text>
        <Text style={[styles.progressCount, family && styles.progressTitleFamily]}>{`${done} / ${total} 완료`}</Text>
      </View>
      <View style={styles.bar}>
        <View style={[styles.barFill, { width: `${pct}%` }]} />
      </View>
      {family && last ? <Text style={styles.lastText}>{`마지막 기록 ${formatClock(last)}`}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { paddingBottom: spacing.xxl, paddingTop: spacing.xl, gap: spacing.md },
  // 위에서부터: "‹ 일정" 줄, 제목 줄(제목 | 편집), 날짜 줄(세로로 쌓는다)
  head: { flexDirection: "column", alignItems: "stretch", paddingHorizontal: spacing.xl, gap: 2 },
  titleRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.md },
  back: { flexDirection: "row", alignItems: "center", minHeight: 44, marginLeft: -8, paddingHorizontal: 8, gap: 2, alignSelf: "flex-start" },
  backText: { fontSize: 14, fontWeight: "500", color: colors.accent },
  title: { ...font.page, color: colors.text },
  date: { ...font.body, fontSize: 14, lineHeight: 20, color: colors.textSub },
  editLink: { minHeight: 44, flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 4 },
  editText: { fontSize: 15, fontWeight: "500", color: colors.text },
  tabBar: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: spacing.xl },
  tabScroll: { flex: 1, minWidth: 0 },
  tabRow: { gap: 6, alignItems: "center" },
  tab: { height: 44, paddingHorizontal: 13, borderRadius: 22, justifyContent: "center" },
  // 탭 줄 선택 칩: 진한 갈색 알약 + 흰 굵은 글자(외곽선 없음, 테두리는 배경과 같은 색으로 크기 유지)
  tabOn: { backgroundColor: colors.text, borderWidth: 1, borderColor: colors.text },
  tabOff: { borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card },
  tabText: { fontSize: 15 },
  tabTextOn: { fontWeight: "700", color: colors.onDark },
  tabTextOff: { fontWeight: "500", color: colors.text },
  tabEdit: {
    flexShrink: 0,
    height: 44,
    paddingHorizontal: 12,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.background,
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  tabEditText: { fontSize: 14, fontWeight: "500", color: colors.text },
  progress: { marginHorizontal: spacing.xl, paddingVertical: 16, paddingHorizontal: 18, borderRadius: radius.lg, gap: 10 },
  progressMe: { backgroundColor: colors.surfaceStrong },
  progressFamily: { backgroundColor: colors.successSoft },
  progressTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline" },
  progressTitle: { fontSize: 16, fontWeight: "700", color: colors.text },
  progressCount: { fontSize: 15, fontWeight: "500", color: colors.text },
  progressTitleFamily: { color: colors.success },
  bar: { height: 8, borderRadius: 4, backgroundColor: colors.background, overflow: "hidden" },
  barFill: { height: 8, borderRadius: 4, backgroundColor: colors.success },
  lastText: { fontSize: 13, color: colors.success },
  list: { paddingHorizontal: spacing.xl },
  listWrap: { position: "relative" },
  // 줄 메뉴: 점 세 개 줄 아래 오른쪽에 뜨는 작은 흰 카드(둥글기 16, 1px 테두리)
  rowMenu: {
    position: "absolute",
    left: spacing.xl + 4, // 점 세 개 버튼이 있는 쪽(줄 왼쪽)에 붙인다
    width: 148,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    paddingVertical: 4,
    zIndex: 50,
    elevation: 8,
  },
  menuItem: { height: 44, paddingHorizontal: 14, flexDirection: "row", alignItems: "center", gap: 8 },
  menuText: { fontSize: 15, color: colors.text },
  menuDanger: { color: colors.danger },
  familyRow: { marginBottom: ROW_GAP },
  // 내 줄 한 칸: 길게 누르는 대상. 줄 간격만 준다(줄 높이는 DailyRow 가 ROW_HEIGHT 로 그린다)
  rowWrap: { marginBottom: ROW_GAP },
  // 점 세 개 버튼: 줄 왼쪽, 44×44 터치 칸
  dots: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  empty: { ...font.caption, color: colors.textSub, textAlign: "center", paddingVertical: spacing.lg },
  footer: { paddingHorizontal: spacing.xl, gap: 8, paddingTop: 4 },
  addButton: {
    height: 56,
    borderRadius: radius.button,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    alignItems: "center",
    justifyContent: "center",
  },
  addText: { fontSize: 16, fontWeight: "500", color: colors.textSub },
  familyActions: { flexDirection: "row", gap: 10 },
  actionBtn: { flex: 1, height: 56, borderRadius: radius.button, alignItems: "center", justifyContent: "center" },
  actionLine: { borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card },
  actionLineText: { fontSize: 16, fontWeight: "700", color: colors.text },
  actionPeach: { backgroundColor: colors.peach },
  actionPeachText: { fontSize: 16, fontWeight: "700", color: colors.text },
});
