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
import CalendarIcon from "../components/CalendarIcon";
import CallDoneSheet from "../components/CallDoneSheet";
import CallSheet from "../components/CallSheet";
import CheerSheet from "../components/CheerSheet";
import CheerStrip from "../components/CheerStrip";
import ConfirmSheet, { ConfirmBody } from "../components/ConfirmSheet";
import DailyRow from "../components/DailyRow";
import DayPickSheet from "../components/DayPickSheet";
import MemoFullPopup from "../components/MemoFullPopup";
import MemoSheet from "../components/MemoSheet";
import PencilIcon from "../components/PencilIcon";
import { useDayRecords } from "../dayRecords";
import { createEntrySync } from "../entrySync";
import { FAMILY_ITEMS_MOCK } from "../mock";
import {
  HOLD_CANCEL_PX,
  ROW_GAP,
  ROW_HEIGHT,
  ROW_MENU,
  ROW_MENU_HOLD_MS,
  canGoNextDay,
  canGoPrevDay,
  cheerSubtitle,
  dayCardTitle,
  dayHeaderLabel,
  familyRowsOf,
  findCallItem,
  formatClock,
  isDone,
  itemsOnDate,
  lastRecordOf,
  memoShareText,
  memoSheetSub,
  memoStampText,
  needsOnboarding,
  nowClock,
  normalizeTabs,
  progressOf,
  rowMenuAction,
  rowMenuTop,
  shouldHideDotsOnTouch,
  shouldShowCallDone,
  stepDay,
  tabLabel,
  shouldShowCallButton,
  talkingPoints,
  visibleTabIds,
} from "../logic";
import { useDailyMembers, useDailyScope } from "../scope";
import { failureNotice, loadErrorText, todayKeyKST } from "../serverMap";

/** 확인 팝업 내용을 안내형(확인 한 개)으로 만든다. */
const infoSheet = (notice) => ({ title: notice.title, body: notice.body, confirmLabel: "확인" });

/**
 * 데일리 체크 메인: 내 탭(체크·횟수, 줄을 길게 누르면 수정·삭제 메뉴, 받은 응원 카드)과 가족 탭(보기만, 응원 보내기·전화 버튼).
 * 습관·기록·메모·응원은 서버에서 읽는다. 기록과 메모는 누르는 즉시 화면에 반영하고 서버 저장은 뒤에서 한다(오늘 기록은 entrySync.js, 지난 날과 메모는 dayStore.js).
 * 지난 날을 보면 그 날짜의 목록을 서버에서 읽는다(날짜별로 한 번, 당겨서 새로고침하면 다시 읽는다).
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
  const [pastDays, setPastDays] = useState({}); // 지난 날 목록: 날짜 → { loading, error, items }(오늘은 items 를 쓴다)
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
  const [viewDate, setViewDate] = useState(null); // 내 탭에서 보고 있는 날짜(YYYY-MM-DD). null 이면 오늘
  const [dayPick, setDayPick] = useState(false); // 날짜 고르기 시트를 열었는가
  const [memoSheet, setMemoSheet] = useState(null); // 메모 쓰기 시트를 연 항목: { id }
  const [memoFull, setMemoFull] = useState(null); // 메모 전문 팝업: { id, family }
  const viewing = viewDate ?? today; // 보고 있는 날짜(가족 탭은 늘 오늘을 본다)
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
  // 날짜별 기록·메모 저장 자리(dayRecords.js). 오늘의 기록은 sync 를, 지난 날의 기록과 모든 메모는 서버를 쓴다.
  const records = useDayRecords({ today, entries, sync, onError: (error) => setSheet(infoSheet(failureNotice(error))) });
  const { seedEntries, seedMemos, flushAll } = records;

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
      seedMemos(today, its);
      setItems(its);
      setCheers(cs);
      setLoadFailed(null);
      setLoaded(true);
      readyRef.current = true;
    } catch (error) {
      if (readyRef.current) setSheet(infoSheet(failureNotice(error, "불러오지 못했어요")));
      else setLoadFailed(error);
    }
  }, [router, sync, seedMemos, today]);

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

  // 지난 날 목록을 읽는다(날짜별로 처음 볼 때 한 번, 실패하면 그 날의 다시 시도 줄). 기록·메모도 같이 맞춘다.
  const loadDay = useCallback(
    async (date) => {
      setPastDays((prev) => ({ ...prev, [date]: { loading: true, error: null, items: prev[date]?.items ?? [] } }));
      try {
        const list = await listItems(date);
        seedEntries(date, list);
        seedMemos(date, list);
        setPastDays((prev) => ({ ...prev, [date]: { loading: false, error: null, items: list } }));
      } catch (error) {
        setPastDays((prev) => ({ ...prev, [date]: { loading: false, error, items: prev[date]?.items ?? [] } }));
      }
    },
    [seedEntries, seedMemos],
  );

  // 화면에 올 때마다 읽는다. 나갈 때는 남은 저장(횟수·메모)을 바로 보내고 줄 메뉴를 닫는다.
  useFocusEffect(
    useCallback(() => {
      let alive = true;
      load();
      loadSummary();
      dropLocalCopy(scope); // 지난 버전이 폰에 남긴 습관·기록·응원 사본은 버린다(서버가 기준이다)
      setPastDays({}); // 지난 날 목록은 화면에 올 때마다 다시 읽는다(습관 수정·삭제 반영). 보고 있는 날만 바로 다시 읽힌다
      loadTabOrder(scope).then((tb) => alive && setTabState(tb));
      return () => {
        alive = false;
        flushAll();
        setMenuFor(null);
        setShowMenuDots(false);
      };
    }, [load, loadSummary, scope, flushAll]),
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

  const isViewingToday = viewing === today;
  const pastDay = isViewingToday ? null : pastDays[viewing]; // 지난 날 목록 상태(아직 안 읽었으면 undefined)
  // 목록은 서버가 그 날짜로 준 습관을 쓴다(applies 로 거른다). 오늘은 아래 load() 가 읽은 목록이다.
  const mine = itemsOnDate(isViewingToday ? items : (pastDay?.items ?? []), viewing);
  const myProgress = progressOf(mine, (item) => records.entryOf(item.id, viewing));
  const myReady = isViewingToday ? loaded : Boolean(pastDay && !pastDay.loading && !pastDay.error);
  const canPrev = canGoPrevDay(viewing, today);
  const canNext = canGoNextDay(viewing, today);
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
  // 지난 날을 보고 있고 아직 안 읽었으면 그 날의 목록을 읽는다(날짜별 한 번. 실패한 날은 다시 시도 줄로 다시 읽는다).
  useEffect(() => {
    if (!isMe || isViewingToday || pastDays[viewing]) return;
    loadDay(viewing);
  }, [isMe, isViewingToday, viewing, pastDays, loadDay]);
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
    if (id !== ME_ID) setViewDate(null); // 가족 탭은 오늘만 보므로 내 탭의 날짜 보기는 오늘로 되돌린다
    setTab(id);
  };

  // ── 기록 ──
  const onCheck = (item) => records.checkItem(item, viewing);
  const onStep = (item, delta) => records.stepItem(item, viewing, delta);

  // ── 메모 ──
  // 메모 아이콘은 쓰기 시트를, 메모 글자는 전문 팝업을 연다. 팝업의 [수정]은 쓰기 시트로 이어진다(내 화면만).
  const sheetItem = memoSheet ? (mine.find((x) => x.id === memoSheet.id) ?? null) : null;
  const sheetMemo = sheetItem ? records.memoOf(sheetItem.id, viewing) : undefined;
  const saveSheetMemo = (memo) => {
    if (sheetItem) records.saveMemo(sheetItem, viewing, memo);
    setMemoSheet(null);
  };
  // 전문 팝업: 내 화면은 내 목록에서, 가족 탭은 가족 목록(오늘)에서 찾는다.
  const fullFamily = Boolean(memoFull?.family);
  const fullItem = memoFull ? ((fullFamily ? activeRows : mine).find((x) => x.id === memoFull.id) ?? null) : null;
  const fullMemo = fullItem && !fullFamily ? records.memoOf(fullItem.id, viewing) : undefined;
  const fullEntry = fullItem ? (fullFamily ? fullItem.entry : records.entryOf(fullItem.id, viewing)) : undefined;

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
            setPastDays((prev) =>
              Object.fromEntries(Object.entries(prev).map(([date, day]) => [date, { ...day, items: day.items.filter((x) => x.id !== item.id) }])),
            );
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
        flushAll();
        return;
      }
      if (state !== "active" || !pendingCall.current) return;
      const memberId = pendingCall.current;
      pendingCall.current = null;
      openCallDoneRef.current?.(memberId);
    });
    return () => sub.remove();
  }, [flushAll]);

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
    await flushAll();
    await Promise.all([load(), loadSummary(), isMe ? null : loadFamily(activeMember), isMe && !isViewingToday ? loadDay(viewing) : null]);
    setRefreshing(false);
  };

  const meLoading = isMe && (isViewingToday ? !loaded && !loadFailed : !pastDay || pastDay.loading);
  const meFailed = isMe && (isViewingToday ? loadFailed : pastDay?.error);
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
          {isMe ? (
            // 날짜 줄: ‹ 날짜 › 화살표(8일 범위), 오른쪽 끝에 달력 아이콘(날짜 고르기 시트)
            <View style={styles.dateRow}>
              <DayArrow prev disabled={!canPrev} onPress={() => setViewDate(stepDay(viewing, -1, today))} />
              <Text style={[styles.date, styles.dateInRow]}>{dayHeaderLabel(viewing, today)}</Text>
              <DayArrow disabled={!canNext} onPress={() => setViewDate(stepDay(viewing, 1, today))} />
              <View style={styles.flexFill} />
              <Pressable
                onPress={() => setDayPick(true)}
                style={styles.calendarBtn}
                accessibilityRole="button"
                accessibilityLabel="다른 날짜 보기"
              >
                <CalendarIcon size={22} />
              </Pressable>
            </View>
          ) : (
            <Text style={styles.date}>{dayHeaderLabel(today, today)}</Text>
          )}
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
          myReady ? (
            <ProgressCard tone="me" title={dayCardTitle(viewing, today)} done={myProgress.done} total={myProgress.total} pct={myProgress.pct} />
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

        {isMe && loaded && isViewingToday ? (
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
              <LoadError text={loadErrorText(isViewingToday ? loadFailed : pastDay.error)} onRetry={isViewingToday ? load : () => loadDay(viewing)} />
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
                      entry={records.entryOf(item.id, viewing)}
                      memo={records.memoOf(item.id, viewing)?.note ?? ""}
                      onMemoIcon={() => setMemoSheet({ id: item.id })}
                      onMemoText={() => setMemoFull({ id: item.id, family: false })}
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
              <Text style={styles.empty}>{isViewingToday ? "오늘 해당하는 습관이 없어요, 아래에서 추가해 보세요" : "그날 해당하는 습관이 없어요"}</Text>
            )
          ) : familyLoading ? (
            <Text style={styles.empty}>불러오는 중이에요</Text>
          ) : familyFailed ? (
            <LoadError text={loadErrorText(activeView.error)} onRetry={() => loadFamily(activeMember)} />
          ) : activeRows.length ? (
            activeRows.map((row) => (
              <View key={row.id} style={styles.familyRow}>
                <DailyRow item={row} entry={row.entry} family memo={row.note ?? ""} onMemoText={() => setMemoFull({ id: row.id, family: true })} />
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
      <DayPickSheet
        visible={dayPick}
        onClose={() => setDayPick(false)}
        selected={viewing}
        onPick={(date) => {
          setViewDate(date);
          setDayPick(false);
        }}
      />
      <MemoSheet
        visible={sheetItem !== null}
        onClose={() => setMemoSheet(null)}
        itemName={sheetItem?.name ?? ""}
        subtitle={memoSheetSub(viewing, today)}
        note={sheetMemo?.note ?? ""}
        shared={sheetMemo?.noteShared ?? false}
        onSave={(memo) => saveSheetMemo(memo)}
        onClear={() => saveSheetMemo(null)}
      />
      <MemoFullPopup
        visible={fullItem !== null}
        title={fullItem?.name ?? ""}
        stamp={fullItem ? memoStampText(fullFamily ? today : viewing, fullItem, fullEntry) : ""}
        note={fullFamily ? (fullItem?.note ?? "") : (fullMemo?.note ?? "")}
        shareText={memoShareText({ shared: Boolean(fullMemo?.noteShared), mine: !fullFamily })}
        canEdit={!fullFamily}
        onClose={() => setMemoFull(null)}
        onEdit={() => {
          if (fullItem) setMemoSheet({ id: fullItem.id });
          setMemoFull(null);
        }}
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

/** 날짜 줄의 ‹ › 화살표. 터치 칸 36(시안) + 여백. 막힌 쪽은 흐리게 두고 누르지 않는다. */
function DayArrow({ prev = false, disabled, onPress }) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={styles.dayArrow}
      hitSlop={4}
      accessibilityRole="button"
      accessibilityLabel={prev ? "이전 날짜" : "다음 날짜"}
      accessibilityState={{ disabled }}
    >
      <Ionicons name={prev ? "chevron-back" : "chevron-forward"} size={20} color={disabled ? colors.disabled : colors.text} />
    </Pressable>
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
  // 날짜 줄(내 탭): ‹ 날짜 › 와 오른쪽 달력. 왼쪽 화살표 칸이 여백 안에 들어가게 -10 으로 당긴다.
  dateRow: { flexDirection: "row", alignItems: "center", marginLeft: -10 },
  dateInRow: { marginHorizontal: 2 },
  dayArrow: { width: 36, height: 36, alignItems: "center", justifyContent: "center" },
  flexFill: { flex: 1 },
  calendarBtn: { width: 44, height: 44, marginVertical: -4, marginRight: -10, alignItems: "center", justifyContent: "center" },
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
