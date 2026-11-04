import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppState, Linking, Platform, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import Svg, { Path } from "react-native-svg";

import { colors, font, radius, spacing } from "@/theme";

import { ME_ID } from "../../mock";
import {
  deleteItem,
  dropLocalCopy,
  listCheers,
  listFamilySummary,
  listFamilyToday,
  listItems,
  loadOnboarded,
  loadTabOrder,
  markCheerClosed,
  markCheerThanked,
  sendCheer,
  setEntry,
} from "../api";
import CallDoneSheet from "../components/CallDoneSheet";
import CallSheet from "../components/CallSheet";
import CheerSheet from "../components/CheerSheet";
import CheerStrip from "../components/CheerStrip";
import ConfirmSheet, { ConfirmBody } from "../components/ConfirmSheet";
import DailyRow from "../components/DailyRow";
import PencilIcon from "../components/PencilIcon";
import { createEntrySync } from "../entrySync";
import { FAMILY_ITEMS_MOCK } from "../mock";
import {
  HOLD_CANCEL_PX,
  ROW_GAP,
  ROW_HEIGHT,
  ROW_MENU,
  ROW_MENU_HOLD_MS,
  applyCheck,
  applyStep,
  cheerSubtitle,
  familyRowsOf,
  findCallItem,
  formatClock,
  formatDayLabel,
  isDone,
  lastRecordOf,
  needsOnboarding,
  nowClock,
  normalizeTabs,
  progressOf,
  rowMenuAction,
  rowMenuTop,
  shouldHideDotsOnTouch,
  shouldShowCallDone,
  tabLabel,
  shouldShowCallButton,
  talkingPoints,
  todayItemsOf,
  visibleTabIds,
} from "../logic";
import { useDailyMembers, useDailyScope } from "../scope";
import { failureNotice, loadErrorText, todayKeyKST } from "../serverMap";

/** 확인 팝업 내용을 안내형(확인 한 개)으로 만든다. */
const infoSheet = (notice) => ({ title: notice.title, body: notice.body, confirmLabel: "확인" });

/**
 * 데일리 체크 메인: 내 탭(체크·횟수, 줄을 길게 누르면 수정·삭제 메뉴, 받은 응원 카드)과 가족 탭(보기만, 응원 보내기·전화 버튼).
 * 습관·기록·응원은 서버에서 읽는다. 기록은 누르는 즉시 화면에 반영하고 서버 저장은 뒤에서 한다(entrySync.js).
 * 처음이고 서버에 습관이 없으면 온보딩으로 보낸다. 가족 탭 라벨은 가족 요약, 가족 탭 목록은 탭을 열 때와 당겨 새로고침 때만 읽는다.
 */
export default function DailyCheckScreen() {
  const router = useRouter();
  const scope = useDailyScope();
  const members = useDailyMembers();
  const today = todayKeyKST();

  const [loaded, setLoaded] = useState(false); // 서버에서 내 습관·온보딩 표시를 한 번 받았는가
  const [loadFailed, setLoadFailed] = useState(null); // 받지 못한 오류(있으면 오류 빈 상태)
  const [items, setItems] = useState([]);
  const [entries, setEntries] = useState({});
  const [tabState, setTabState] = useState({ order: [], hidden: [] });
  const [summary, setSummary] = useState({}); // 가족 앱 id → { done, total }
  const [familyView, setFamilyView] = useState({}); // 가족 앱 id → { loading, error, rows }
  const [cheers, setCheers] = useState([]); // 받은 응원
  const [tab, setTab] = useState(ME_ID);
  const [refreshing, setRefreshing] = useState(false);
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
  const [cheerFor, setCheerFor] = useState(null); // 응원 시트를 연 가족 id
  const [callFor, setCallFor] = useState(null); // 전화 확인 시트를 연 가족 id
  const [callDone, setCallDone] = useState(null); // 통화 뒤 시트: { memberId }
  const pendingCall = useRef(null); // 전화 앱을 연 가족 id(앱으로 돌아오면 통화 뒤 시트를 띄운다)
  // 전화는 번호 없이 전화 앱 키패드를 연다(가족 전화번호는 서버에 두지 않는다).
  // 전화 버튼 판정: 안드로이드는 항상 보이고(canOpenURL 을 믿지 않는다), iOS 만 화면이 열릴 때 canOpenURL("tel:") 을 한 번 확인해 거짓이면 숨긴다.
  const [canOpen, setCanOpen] = useState(null);
  useEffect(() => {
    if (Platform.OS !== "ios") return undefined;
    let alive = true;
    Linking.canOpenURL("tel:")
      .then((ok) => alive && setCanOpen(Boolean(ok)))
      .catch(() => alive && setCanOpen(false));
    return () => {
      alive = false;
    };
  }, []);
  const canCall = shouldShowCallButton(Platform.OS, canOpen);

  // 기록 저장 보조: 화면 값(낙관적 갱신)·서버 확인·롤백을 한 곳에서 한다.
  const [sync] = useState(() =>
    createEntrySync({
      send: setEntry,
      show: (id, entry) => setEntries((prev) => ({ ...prev, [id]: entry })),
      onError: (error) => setSheet(infoSheet(failureNotice(error))),
    }),
  );

  // 가족 구성원(나 제외).
  const familyIds = useMemo(() => members.filter((m) => m.id !== ME_ID).map((m) => m.id), [members]);
  const tabs = normalizeTabs(tabState, familyIds);
  const visibleIds = visibleTabIds(tabs);
  const memberOf = (id) => members.find((m) => m.id === id);
  const nameOf = (id) => memberOf(id)?.name ?? "";

  // 내 습관 · 온보딩 표시 · 받은 응원을 서버에서 읽는다. 처음 한 번 실패하면 오류 빈 상태, 그 뒤 실패는 안내만 한다.
  const readyRef = useRef(false);
  const load = useCallback(async () => {
    try {
      const [its, onboarded, cs] = await Promise.all([listItems(), loadOnboarded(), listCheers("received")]);
      if (needsOnboarding(its, onboarded)) {
        router.replace("/schedule/daily-onboarding");
        return;
      }
      setEntries(sync.seed(Object.fromEntries(its.map((item) => [item.id, item.entry]))));
      setItems(its);
      setCheers(cs);
      setLoadFailed(null);
      setLoaded(true);
      readyRef.current = true;
    } catch (error) {
      if (readyRef.current) setSheet(infoSheet(failureNotice(error, "불러오지 못했어요")));
      else setLoadFailed(error);
    }
  }, [router, sync]);

  // 가족 탭 라벨용 요약(실패해도 라벨만 이름으로 남는다).
  const loadSummary = useCallback(
    () =>
      listFamilySummary()
        .then((list) => setSummary(Object.fromEntries(list.map((s) => [s.id, s]))))
        .catch(() => {}),
    [],
  );

  // 가족 한 사람의 오늘 습관. 개발용 가상 가족은 서버 없이 읽기 전용 mock 을 쓴다.
  const loadFamily = useCallback(async (member) => {
    if (!member || member.id === ME_ID || member.hasAccount === false) return; // 가상 가족은 mock 을 바로 쓴다(서버 호출 없음)
    setFamilyView((prev) => ({ ...prev, [member.id]: { loading: true, error: null, rows: prev[member.id]?.rows ?? [] } }));
    try {
      const rows = await listFamilyToday(member.id);
      setFamilyView((prev) => ({ ...prev, [member.id]: { loading: false, error: null, rows } }));
    } catch (error) {
      setFamilyView((prev) => ({ ...prev, [member.id]: { loading: false, error, rows: prev[member.id]?.rows ?? [] } }));
    }
  }, []);

  // 화면에 올 때마다 읽는다. 나갈 때는 남은 횟수 저장을 바로 보내고 줄 메뉴를 닫는다.
  useFocusEffect(
    useCallback(() => {
      let alive = true;
      load();
      loadSummary();
      dropLocalCopy(scope); // 지난 버전이 폰에 남긴 습관·기록·응원 사본은 버린다(서버가 기준이다)
      loadTabOrder(scope).then((tb) => alive && setTabState(tb));
      return () => {
        alive = false;
        sync.flushAll();
        setMenuFor(null);
        setShowMenuDots(false);
      };
    }, [load, loadSummary, scope, sync]),
  );

  // ── 탭 줄 ──
  // 가족 오늘 줄: 개발용 가상 가족은 읽기 전용 mock 을 바로 쓰고, 실제 가족은 탭을 열어 받은 줄을 쓴다.
  const isVirtualId = (id) => memberOf(id)?.hasAccount === false;
  const familyRows = (id) => familyRowsOf(isVirtualId(id) ? (FAMILY_ITEMS_MOCK[id] ?? []) : (familyView[id]?.rows ?? []), today);
  // 탭 라벨 숫자: 가상 가족은 mock 으로, 실제 가족은 서버 요약으로 센다.
  const countsOf = (id) => {
    if (isVirtualId(id)) {
      const p = progressOf(familyRows(id), (row) => row.entry);
      return { done: p.done, total: p.total };
    }
    const s = summary[id];
    return s ? { done: s.done, total: s.total } : null;
  };

  const mine = todayItemsOf(items, today);
  const myProgress = progressOf(mine, (item) => entries[item.id]);
  const tabList = [
    { id: ME_ID, label: tabLabel("나", myProgress.done, myProgress.total) },
    ...visibleIds.map((id) => {
      const counts = countsOf(id);
      return { id, label: counts ? tabLabel(nameOf(id), counts.done, counts.total) : nameOf(id) };
    }),
  ];
  const activeTab = tabList.some((t) => t.id === tab) ? tab : ME_ID;
  const isMe = activeTab === ME_ID;
  const activeMember = memberOf(activeTab);
  const isVirtual = !isMe && activeMember?.hasAccount === false;
  // 가족 탭을 열면 그 사람의 오늘 습관을 한 번 읽는다(폴링 없음). 탭을 바꾸거나 새로고침할 때만 다시 읽는다.
  useEffect(() => {
    if (activeMember && activeMember.id !== ME_ID) loadFamily(activeMember);
  }, [activeMember, loadFamily]);
  const activeView = isMe ? null : familyView[activeTab];
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

  // ── 기록 ──
  const onCheck = (item) => sync.change(item, applyCheck(sync.valueOf(item.id), nowClock()));
  const onStep = (item, delta) => sync.change(item, applyStep(item, sync.valueOf(item.id), delta, nowClock()), { debounced: true });

  // ── 줄 메뉴 ──
  // 내 줄을 길게 누르면(ROW_MENU_HOLD_MS) 그 줄 아래에 수정·삭제 메뉴가 뜬다. 메뉴 바깥을 누르면 닫힌다.
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
          try {
            await deleteItem(item.id);
            setItems((prev) => prev.filter((x) => x.id !== item.id));
          } catch (error) {
            setSheet(infoSheet(failureNotice(error, "지우지 못했어요")));
          }
        },
      });
    }
  };

  // ── 응원 ──
  // 고마워·닫기는 화면에서 먼저 바꾸고 서버에 보낸다. 실패하면 되돌리고 안내한다.
  const patchCheer = (id, patch) => setCheers((prev) => prev.map((c) => (c.id === id ? { ...c, ...patch } : c)));
  const thankCheer = async (id) => {
    patchCheer(id, { thanked: true });
    try {
      const row = await markCheerThanked(id);
      setCheers((prev) => prev.map((c) => (c.id === id ? row : c)));
    } catch (error) {
      patchCheer(id, { thanked: false });
      setSheet(infoSheet(failureNotice(error)));
    }
  };
  const closeCheer = async (id) => {
    patchCheer(id, { closed: true });
    try {
      const row = await markCheerClosed(id);
      setCheers((prev) => prev.map((c) => (c.id === id ? row : c)));
    } catch (error) {
      patchCheer(id, { closed: false });
      setSheet(infoSheet(failureNotice(error)));
    }
  };
  const sendTo = async (memberId, cheer) => {
    try {
      await sendCheer({ toId: memberId, kind: cheer.kind, text: cheer.text, groupChat: cheer.groupChat });
      setCheerFor(null);
    } catch (error) {
      setSheet(infoSheet(failureNotice(error, "보내지 못했어요")));
    }
  };

  // ── 전화 ──
  const startCall = async (memberId) => {
    setCallFor(null);
    pendingCall.current = memberId;
    try {
      await Linking.openURL("tel:"); // 번호 없이 전화 앱 키패드를 연다
    } catch {
      pendingCall.current = null;
      setSheet({
        title: "전화 앱을 열 수 없어요",
        confirmLabel: "확인",
        onConfirm: () => setSheet(null),
      });
    }
  };

  // 전화 앱에서 돌아왔을 때: "안부 전화" 습관이 오늘 있고 아직 완료가 아닐 때만 시트를 띄운다(없거나 완료면 아무것도 안 한다)
  const openCallDoneRef = useRef(null);
  function openCallDone(memberId) {
    if (!shouldShowCallDone(items, entries, today)) return;
    setCallDone({ memberId });
  }
  openCallDoneRef.current = openCallDone;
  useEffect(() => {
    const sub = AppState.addEventListener("change", (state) => {
      if (state === "background" || state === "inactive") {
        sync.flushAll();
        return;
      }
      if (state !== "active" || !pendingCall.current) return;
      const memberId = pendingCall.current;
      pendingCall.current = null;
      openCallDoneRef.current?.(memberId);
    });
    return () => sub.remove();
  }, [sync]);

  // "완료로 체크하기": 오늘 목록의 "안부 전화" 습관을 완료로 바꾸고 시트를 닫는다(시트는 습관이 있을 때만 열렸다).
  const finishCall = () => {
    const target = findCallItem(items, today);
    if (target && !isDone(target, sync.valueOf(target.id))) {
      sync.change(target, { done: true, count: 0, doneAt: nowClock() });
    }
    setCallDone(null);
  };
  // "다음에 할게요": 아무것도 바꾸지 않고 닫는다.
  const laterCall = () => setCallDone(null);

  // 당겨서 새로고침: 남은 저장을 먼저 보내고 내 습관·응원·요약(과 열린 가족 탭)을 다시 읽는다.
  const onRefresh = async () => {
    setRefreshing(true);
    await sync.flushAll();
    await Promise.all([load(), loadSummary(), isMe ? null : loadFamily(activeMember)]);
    setRefreshing(false);
  };

  const meLoading = isMe && !loaded && !loadFailed;
  const meFailed = isMe && loadFailed;
  const familyLoading = !isMe && !isVirtual && (!activeView || activeView.loading) && !activeRows.length && !activeView?.error;
  const familyFailed = !isMe && !isVirtual && activeView?.error && !activeRows.length;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]} onTouchStart={onScreenTouch}>
      <ScrollView
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      >
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
          loaded ? (
            <ProgressCard tone="me" title="오늘 나의 체크" done={myProgress.done} total={myProgress.total} pct={myProgress.pct} />
          ) : null
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

        {isMe && loaded ? (
          <CheerStrip
            cheers={cheers}
            today={today}
            onReplyInfo={() =>
              setSheet({
                title: "답장은 곧 만들어져요",
                body: "가족 대화방으로 이어지는 답장은 아직 준비 중이에요",
                confirmLabel: "확인",
              })
            }
            onThank={thankCheer}
            onDismiss={closeCheer}
            onOpenHistory={() => router.push("/schedule/daily-cheer-history")}
          />
        ) : null}

        <View style={[styles.list, styles.listWrap]}>
          {/* 내 줄을 길게 누르면(ROW_MENU_HOLD_MS) 그 줄 아래에 수정·삭제 메뉴가 뜬다. 메뉴 바깥을 누르면 닫힌다. */}
          {isMe ? (
            meLoading ? (
              <Text style={styles.empty}>불러오는 중이에요</Text>
            ) : meFailed ? (
              <LoadError text={loadErrorText(loadFailed)} onRetry={load} />
            ) : mine.length ? (
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
          ) : familyLoading ? (
            <Text style={styles.empty}>불러오는 중이에요</Text>
          ) : familyFailed ? (
            <LoadError text={loadErrorText(activeView.error)} onRetry={() => loadFamily(activeMember)} />
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
          loaded ? (
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
          ) : null
        ) : isVirtual ? (
          <View style={styles.footer}>
            <Text style={styles.devNote}>개발용 가상 가족이에요(서버 데이터가 아니에요)</Text>
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
              {canCall ? (
                <Pressable
                  onPress={() => setCallFor(activeTab)}
                  style={[styles.actionBtn, styles.actionPeach]}
                  accessibilityRole="button"
                  accessibilityLabel={`${nameOf(activeTab)}에게 전화`}
                >
                  <Text style={styles.actionPeachText}>{`${nameOf(activeTab)}에게 전화`}</Text>
                </Pressable>
              ) : null}
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
        points={talkingPoints(callRows)}
        onCall={() => startCall(callFor)}
      />
      <CallDoneSheet
        visible={callDone !== null}
        memberName={nameOf(callDone?.memberId ?? "")}
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

/** 불러오기 실패 빈 상태: 한 줄 글자와 다시 시도 버튼. */
function LoadError({ text, onRetry }) {
  return (
    <View style={styles.loadError}>
      <Text style={styles.empty}>{text}</Text>
      <Pressable onPress={onRetry} style={styles.retry} accessibilityRole="button" accessibilityLabel="다시 시도">
        <Text style={styles.retryText}>다시 시도</Text>
      </Pressable>
    </View>
  );
}

/** 탭 줄의 사람 칩. 선택됨은 진한 갈색 알약(외곽선 없음), 아니면 옅은 외곽선. */
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
  loadError: { alignItems: "center", gap: 8 },
  retry: {
    minHeight: 44,
    paddingHorizontal: 18,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    alignItems: "center",
    justifyContent: "center",
  },
  retryText: { fontSize: 15, fontWeight: "700", color: colors.text },
  footer: { paddingHorizontal: spacing.xl, gap: 8, paddingTop: 4 },
  devNote: { ...font.caption, color: colors.textSub, textAlign: "center", paddingVertical: spacing.sm },
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
