import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as Clipboard from "expo-clipboard";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { ActivityIndicator, Alert, FlatList, KeyboardAvoidingView, Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import Button from "@/shared/components/Button";
import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import { buildItems, canSend, itemHasMessage, lastId, photoSendErrorMessage, trimDraft, unreadCount, unreadDividerId } from "../chatUtils";
import { mergeNotes, parseMention, restoreThread } from "../mention";
import AiPanel from "../components/AiPanel";
import AssistantNote from "../components/AssistantNote";
import ChatSearchBar from "../components/ChatSearchBar";
import Composer from "../components/Composer";
import LiveReturnButton from "../components/LiveReturnButton";
import MessageBubble from "../components/MessageBubble";
import MessageMenu from "../components/MessageMenu";
import PinnedBar from "../components/PinnedBar";
import RoomDrawer from "../components/RoomDrawer";
import { HEART, canOpenMenu, messageActionError, reactionAction, replyPreview } from "../messageActions";
import { COPIED_NOTICE, COPY_FAILED_NOTICE, pinTapAction } from "../pinUtils";
import { parseFocusParam, roomSearchOptions, shouldLoadNewer } from "../searchUtils";
import { canSaveToLibrary, saveToLibrary } from "../saveToLibrary";
import { canSaveToRecord, saveToRecord } from "../saveToRecord";
import useChatLinks from "../useChatLinks";
import useChatMessages, { useRoomInfo } from "../useChatMessages";
import useChatPins from "../useChatPins";
import useMention from "../useMention";
import useRoomMute from "../useRoomMute";
import useChatSearch, { useFamilyRoomId } from "../useChatSearch";
import { memberName } from "../listUtils";
import { fileSendErrorMessage } from "../fileUtils";
import { pickChatDocument } from "../pickChatDocument";
import { makeBatchId } from "../album";
import { LIBRARY_NOTICE_BODY, LIBRARY_NOTICE_TITLE, markLibraryNoticeSeen, shouldShowLibraryNotice } from "../libraryNotice";
import { pickChatPhotos } from "../pickPhoto";
import useReadBaseline from "../useReadBaseline";
import useReadMarker from "../useReadMarker";

const NEAR = 120; // 바닥/맨 위에서 이 정도 안이면 "근처"로 본다
const FAR = 400; // 바닥에서 이 이상 올라와 있으면 "맨 아래로" 버튼을 보여 준다
const HIGHLIGHT_MS = 2000; // 검색 결과로 이동한 메시지를 강조해 두는 시간
const SETTLE_MS = 600; // 이동 직후 이 시간 동안은 위로 자동 불러오기를 막아 이동 위치가 밀리지 않게 한다
const NO_MESSAGES = []; // 과거 창을 보는 동안 읽음 처리에 넘기는 빈 목록
const LIST_READY_MAX_MS = 1500; // 처음 맨 아래로 자리 잡는 동안 목록을 숨기는 최대 시간(그 뒤에는 무조건 보인다)
const DIVIDER_VIEW_POSITION = 0.05; // 입장 때 "여기까지 읽었습니다" 줄이 화면 위쪽에 오도록(0 이 맨 위)
const DIVIDER_READY_MS = 350; // 구분선으로 이동한 뒤 목록을 보이기까지 기다리는 시간(첫 시도가 실패해도 재시도가 끝나도록)
const END_SETTLE_MS = 150; // 맨 아래로 간 뒤 마지막 항목 높이가 확정되길 기다리는 시간

/** 가족 전체방의 사진을 AI 비서의 가족 기록으로 올린다(사진 보기의 "가비 기록에 저장"). */
const savePhotoToRecord = (attachment) => saveToRecord(attachment, Platform.OS);

/** 가족 전체방의 사진을 가족 공유 문서함에 직접 넣는다(사진 보기의 "문서로 저장"). */
const savePhotoToLibraryDoc = (attachment) => saveToLibrary(attachment);

/**
 * 가족 문서함 자동 등록 안내를 보이고 닫힐 때까지 기다린다. 웹의 Alert 는 아무 동작도 하지 않아(끝나지 않아 문서 버튼이 잠긴다) 브라우저 알림 창을 쓴다.
 * 안드로이드에서는 뒤로 가기로도 닫힌다(cancelable).
 * @returns {Promise<void>}
 */
function showLibraryNotice() {
  if (Platform.OS === "web") {
    globalThis.alert?.(`${LIBRARY_NOTICE_TITLE}\n\n${LIBRARY_NOTICE_BODY}`);
    return Promise.resolve();
  }
  return new Promise((resolve) => Alert.alert(LIBRARY_NOTICE_TITLE, LIBRARY_NOTICE_BODY, [{ text: "확인", onPress: () => resolve() }], { cancelable: true, onDismiss: () => resolve() }));
}

/**
 * 앨범에 속한 사진들의 일정·할 일 연결 표시를 모은다(같은 표시는 한 번만).
 * @param {{ id: number }[]} album
 * @param {(id: number) => { kind: string, label: string }[]} badgesOf
 * @returns {{ kind: string, label: string }[]}
 */
function albumBadges(album, badgesOf) {
  const seen = new Set();
  return album.flatMap((m) => badgesOf(m.id) ?? []).filter((b) => (seen.has(`${b.kind}:${b.label}`) ? false : seen.add(`${b.kind}:${b.label}`)));
}

/** 가운데 안내(로딩·오류·그룹 없음). */
function Center({ children }) {
  return <View style={styles.center}>{children}</View>;
}

/**
 * 실제 채팅방: 메시지 목록, 입력창, AI 도우미(✨) 시트.
 * 경로 인자 roomId 가 없으면 가족 전체방이고, 있으면 그 방(1:1)이다. peer 는 1:1 상대의 id 로 방 이름을 정하는 데만 쓴다.
 * 1:1 대화는 AI 로 보내지 않아서 1:1 방에는 AI 도우미 버튼이 없다.
 * 상단 돋보기(대화 검색)는 이 방 안에서 글자 일치로 찾고, 결과를 누르면 그 메시지 위치(과거 창)로 이동한다. 경로 인자 focus 가 있으면 처음부터 그 위치로 열린다.
 * 과거 창을 보는 동안은 "최신 대화로 이동" 버튼이 뜨고, 새 메시지 확인과 읽음 처리는 멈춘다.
 */
export default function ChatRoomScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const roomId = typeof params.roomId === "string" && params.roomId ? params.roomId : null;
  const peerId = typeof params.peer === "string" ? params.peer : null;
  const direct = roomId != null;
  const initialFocus = parseFocusParam(params.focus);
  const info = useRoomInfo();
  const chat = useChatMessages({ me: info.me, enabled: info.status === "ready", roomId, initialFocus });
  const base = useReadBaseline({ roomId, enabled: info.status === "ready" }); // 입장 시점의 읽음 위치(읽음이 올라가도 바뀌지 않는다)
  const dividerId = useMemo(
    () => (chat.focusing || initialFocus != null ? null : unreadDividerId(chat.messages, base.baseline, info.me?.id)),
    [chat.focusing, chat.messages, initialFocus, base.baseline, info.me?.id],
  );
  // 과거 창을 보는 동안은 읽음 위치를 올리지 않는다(보고 있지 않은 최신 메시지를 읽음 처리하면 안 된다)
  useReadMarker({ messages: chat.focusing ? NO_MESSAGES : chat.messages, myId: info.me?.id, enabled: info.status === "ready", roomId });
  const pins = useChatPins({ roomId, enabled: info.status === "ready", me: info.me }); // 고정 바는 과거(포커스) 모드에서도 유지된다
  const links = useChatLinks({ roomId, enabled: info.status === "ready", me: info.me, poll: !direct, findMessage: (id) => chat.messages.find((m) => !m.clientId && Number(m.id) === id) }); // 일정·할 일로 등록한 메시지 연결(말풍선 표시)
  const familyRoom = useFamilyRoomId(!direct); // 가족 전체방은 경로에 방 id 가 없어 방 목록에서 알아낸다
  const search = useChatSearch(roomSearchOptions(roomId, familyRoom.id)); // 방 id 를 알기 전에는 검색하지 않는다(모든 방 검색으로 떨어지지 않게)
  const [searchOpen, setSearchOpen] = useState(false);
  const [highlightId, setHighlightId] = useState(null);
  const pickPinRef = useRef(null); // 검색 이동 효과가 항상 최신 pickPin 을 부르도록
  const [goingLive, setGoingLive] = useState(false);
  const [listReady, setListReady] = useState(false); // 방에 처음 들어갈 때 맨 아래로 자리 잡기 전까지 목록을 숨겨, 위에서부터 훑으며 내려가는 모습이 보이지 않게 한다
  const [draft, setDraft] = useState("");
  const [aiOpen, setAiOpen] = useState(false);
  const mention = useMention(roomId ?? undefined); // @가비 로 부른 뒤 나에게만 보이는 답·안내
  const listRef = useRef(null);
  const nearBottom = useRef(initialFocus == null);
  const lastScrollY = useRef(0); // 직전 스크롤 위치(위로 올렸는지 알아보려고)
  const endTimer = useRef(null); // 마지막 항목의 높이가 확정된 뒤 한 번 더 맨 아래로 맞추는 타이머
  const itemsRef = useRef([]);
  const pinHighlightTimer = useRef(null); // 강조 해제 타이머(고정 바 이동·포커스 이동이 함께 쓴다 — 새 이동이 시작되면 앞의 것을 지운다)
  const pinSettleTimer = useRef(null); // 위로 불러오기 잠금 해제 타이머(같은 이유로 공유)
  const settling = useRef(initialFocus != null);
  const focusRetry = useRef(0);
  const positioned = useRef(false); // 방에 처음 들어갈 때의 자리 잡기(구분선 또는 맨 아래)를 마쳤는지
  const sentEarly = useRef(false); // 자리 잡기 전에 내가 보냈으면 구분선으로 가지 않고 맨 아래에 둔다(보낸 메시지가 가려지지 않게)
  const dividerRetries = useRef(0); // 예약된 구분선 이동 재시도 수
  const dividerJump = useRef(false); // 구분선으로 이동하는 중(스크롤 재시도의 위치 값을 정한다)
  const scrollPos = useRef({ y: 0, height: 0 }); // 웹은 maintainVisibleContentPosition 이 없어 이전 대화가 위에 붙을 때 위치를 직접 지킨다
  const olderRequested = useRef(false);
  const picking = useRef(false); // 사진 고르는 중 중복 누름 방지(ref)
  const [pickingUi, setPicking] = useState(false);
  const pickingFile = useRef(false); // 문서 고르는 중 중복 누름 방지(ref)
  const [pickingFileUi, setPickingFile] = useState(false);
  const [far, setFar] = useState(false); // 바닥에서 멀리 올라와 있는지
  const [hasNew, setHasNew] = useState(false); // 올라와 있는 동안 새 메시지가 왔는지
  const [drawerOpen, setDrawerOpen] = useState(false);
  const roomMute = useRoomMute({ roomId, enabled: drawerOpen }); // 서랍을 열 때마다 이 방의 알림 설정을 다시 읽는다
  const [menu, setMenu] = useState(null); // 길게 눌러 메뉴를 연 메시지 { message, anchor }
  const [replyTo, setReplyTo] = useState(null); // 답장하려고 고른 원본 미리보기(입력창 위 바)
  const newestId = useRef(0);
  // 채팅 메시지 응답에는 사진 주소가 없어서 구성원 목록에서 user_id 로 찾는다
  const photoById = useMemo(() => Object.fromEntries((info.room?.members ?? []).map((m) => [m.id, m.photo_url ?? null])), [info.room]);


  const back = () => (router.canGoBack() ? router.back() : router.replace("/family-chat"));

  const scrollToEnd = useCallback((animated) => listRef.current?.scrollToEnd({ animated }), []);

  // 서랍에서 다른 화면(게시판·가족 할 일·사진 모음 등)을 열었다가 뒤로 돌아오면 가장 최근 메시지가 보이게 한다(검색 결과로 이동한 과거 창을 보는 중이면 그대로 둔다).
  const leftRoom = useRef(false);
  const focusingRef = useRef(false);
  focusingRef.current = chat.focusing;
  useFocusEffect(
    useCallback(() => {
      const timers = [];
      if (leftRoom.current) {
        leftRoom.current = false;
        const toLatest = () => {
          if (focusingRef.current) return;
          nearBottom.current = true;
          scrollToEnd(false);
        };
        timers.push(setTimeout(toLatest, 80), setTimeout(toLatest, 400)); // 목록이 다시 그려지며 높이가 바뀌므로 한 번 더 맞춘다
      }
      return () => {
        timers.forEach(clearTimeout);
        leftRoom.current = true;
      };
    }, [scrollToEnd]),
  );

  const onScroll = useCallback(
    ({ nativeEvent: { contentOffset, contentSize, layoutMeasurement } }) => {
      const fromBottom = contentSize.height - (contentOffset.y + layoutMeasurement.height);
      // 바닥을 따라가는 중(nearBottom)인지는 "바닥 근처에 닿았다"와 "사용자가 위로 올렸다"로만 바꾼다.
      // 아직 그려지지 않은 아래 항목 때문에 내용이 길어져 바닥에서 멀어 보이는 것만으로는 따라가기를 멈추지 않는다(그러면 처음 열 때·보낸 직후 마지막 메시지가 입력창에 가려졌다).
      const scrolledUp = contentOffset.y < lastScrollY.current - 2;
      lastScrollY.current = contentOffset.y;
      if (fromBottom < NEAR) nearBottom.current = true;
      else if (scrolledUp) nearBottom.current = false;
      setFar(!nearBottom.current && fromBottom > FAR);
      if (nearBottom.current || fromBottom <= FAR) setHasNew(false);
      scrollPos.current.y = contentOffset.y;
      if (contentOffset.y < NEAR && !settling.current) {
        olderRequested.current = true;
        chat.loadOlder();
      }
      if (shouldLoadNewer({ focusing: chat.focusing, fromBottom, near: NEAR, busy: false })) chat.loadNewer(); // 아래 끝에 닿으면 이후 대화를 이어 받고, 라이브 끝이면 자동으로 라이브로 돌아간다
    },
    [chat],
  );

  const onSend = () => {
    if (!canSend(draft)) return;
    const text = trimDraft(draft);
    const reply = replyTo;
    setDraft("");
    setReplyTo(null);
    nearBottom.current = true;
    sentEarly.current = true;
    const called = parseMention(text); // 1:1 방에서도 부를 수 있다(답은 그 1:1 방에 저장된다)
    chat.send(text, reply).then((started) => {
      if (!started) {
        setDraft((prev) => prev || text); // 보내지 못했으면(최신 대화로 돌아가지 못함 등) 쓴 글과 답장 대상을 되돌려 놓는다
        setReplyTo((prev) => prev ?? reply);
        return;
      }
      if (called.mentioned) mention.ask(called.question);
    });
  };

  /** 공유 선택 카드에서 고른 줄을 내 이름의 일반 메시지로 보낸다(입력창 전송과 같은 chat.send). 보내기를 시작하지 못하면 던져서 카드가 오류를 보여 준다. */
  const shareToRoom = async (text) => {
    nearBottom.current = true;
    sentEarly.current = true;
    if (!(await chat.send(text, null))) throw new Error("방에 보내지 못했어요. 잠시 후 다시 시도해 주세요.");
  };

  /** 가족 전체방에서만(1:1 방 제외) 문서함 자동 등록 안내를 처음 한 번 보이고 확인을 기억한다. 사진을 고를 때와 문서를 고를 때가 같은 저장 키를 쓴다. */
  const noticeLibraryOnce = async () => {
    if (!direct && (await shouldShowLibraryNotice(AsyncStorage))) {
      await showLibraryNotice();
      await markLibraryNoticeSeen(AsyncStorage);
    }
  };

  /** 갤러리에서 사진을 한 장 또는 여러 장(최대 10장) 골라 보낸다. 2장 이상이면 같은 묶음 번호를 붙여 앨범으로 보이게 하고, 한 장이 실패하면 거기서 멈춘다. 고르는 동안·보내는 동안은 다시 누를 수 없다. */
  const onPickPhoto = async () => {
    if (picking.current || chat.photoBusy) return;
    picking.current = true;
    setPicking(true);
    chat.setPhotoError("");
    try {
      await noticeLibraryOnce(); // 문서를 찍은 사진도 자동 등록되므로 사진을 처음 보낼 때도(문서와 같은 키로 한 번만) 안내한다
      const { assets, skipped } = await pickChatPhotos();
      if (!assets.length) {
        if (skipped) chat.setPhotoError(photoSendErrorMessage({ code: "photo_too_large" }));
        return;
      }
      nearBottom.current = true;
      sentEarly.current = true;
      const batchId = assets.length > 1 ? makeBatchId() : undefined;
      let count = 0;
      for (const asset of assets) {
        if (!(await chat.sendImage(asset, batchId))) break;
        count += 1;
      }
      if (count) scrollToEnd(true);
      if (count < assets.length && count > 0) chat.setPhotoError(`${assets.length}장 중 ${count}장만 보냈어요. 나머지는 다시 골라 보내 주세요`);
      else if (skipped) chat.setPhotoError(`용량이 커서 ${skipped}장은 빼고 보냈어요`);
    } catch (e) {
      chat.setPhotoError(photoSendErrorMessage(e));
    } finally {
      picking.current = false;
      setPicking(false);
    }
  };

  /** 기기에서 문서 파일 한 개를 골라 보낸다(pdf·워드·엑셀·파워포인트·한글·txt·csv, 20MB까지). 고르는 동안·보내는 동안은 다시 누를 수 없다. */
  const onPickFile = async () => {
    if (pickingFile.current || chat.fileBusy) return;
    pickingFile.current = true;
    setPickingFile(true);
    chat.setPhotoError("");
    try {
      await noticeLibraryOnce(); // 가족 전체방이면 문서함 자동 등록 안내를 처음 한 번만 보이고, 확인한 뒤 파일을 고른다
      const asset = await pickChatDocument();
      if (!asset) return;
      nearBottom.current = true;
      sentEarly.current = true;
      if (await chat.sendDocument(asset)) scrollToEnd(true);
    } catch (e) {
      chat.setPhotoError(fileSendErrorMessage(e));
    } finally {
      pickingFile.current = false;
      setPickingFile(false);
    }
  };

  const pickReply = (text) => {
    setDraft((prev) => (prev.trim() ? `${prev} ${text}` : text));
    setAiOpen(false);
  };

  // 방을 나갔다 들어와도 가비와 나눈 이야기를 이어 가도록, 처음 불러온 메시지에서 내 @가비 질문과 가비의 답을 되살린다(15분 이내만 쓰인다)
  const seedThread = mention.seed;
  useEffect(() => {
    if (info.status !== "ready" || !info.me?.id || chat.status !== "ready" || chat.focusing) return; // 최근 구간이 준비됐을 때만(검색 이동으로 과거를 보는 중이면 기다린다)
    seedThread(restoreThread(chat.messages, info.me.id)); // 이미 이 화면에서 나눈 대화가 있으면 seed 가 건드리지 않는다
  }, [info.status, info.me?.id, chat.status, chat.focusing, chat.messages, seedThread]);

  useEffect(
    () => () => {
      clearTimeout(pinHighlightTimer.current);
      clearTimeout(pinSettleTimer.current);
      clearTimeout(endTimer.current);
    },
    [],
  );

  useEffect(() => {
    if (replyTo && chat.messages.some((m) => !m.clientId && Number(m.id) === replyTo.id && m.deleted)) {
      setReplyTo(null); // 원본이 지워지면 답장할 수 없다
      pins.say("답장하려던 메시지가 삭제됐어요");
    }
  }, [chat.messages, replyTo, pins]);

  useEffect(() => {
    const newest = lastId(chat.messages);
    if (newest > newestId.current && newestId.current > 0 && !nearBottom.current) setHasNew(true);
    newestId.current = Math.max(newestId.current, newest);
  }, [chat.messages]);

  // 방에 처음 들어갈 때: 읽음 위치(baseline)와 첫 메시지가 모두 준비되면 구분선으로, 구분선이 없으면 맨 아래로 자리 잡은 뒤 목록을 보인다
  useEffect(() => {
    if (positioned.current || initialFocus != null) return;
    if (chat.status === "loading" || base.status === "pending") return;
    positioned.current = true;
    const index = dividerId != null && !chat.focusing && !sentEarly.current ? itemsRef.current.findIndex((it) => it.type === "unread") : -1;
    if (index < 0) {
      if (!nearBottom.current || chat.focusing) return;
      scrollToEnd(false);
      clearTimeout(endTimer.current);
      endTimer.current = setTimeout(() => {
        if (nearBottom.current && !chat.focusing) scrollToEnd(false);
        setListReady(true);
      }, END_SETTLE_MS);
      return;
    }
    nearBottom.current = false; // 맨 아래로 따라가는 스크롤이 구분선 위치를 덮어쓰지 않게(바닥 근처로 오면 onScroll 이 되돌린다)
    settling.current = true;
    dividerJump.current = true;
    focusRetry.current = 0;
    setTimeout(() => listRef.current?.scrollToIndex({ index, viewPosition: DIVIDER_VIEW_POSITION, animated: false }), 0);
    // 이동이 끝나면(재시도가 모두 끝난 뒤) 목록을 보이고 위로 불러오기 잠금과 구분선 모드를 푼다
    const finish = () => {
      if (dividerRetries.current > 0) {
        setTimeout(finish, 60);
        return;
      }
      dividerJump.current = false;
      setListReady(true);
      clearTimeout(pinSettleTimer.current);
      pinSettleTimer.current = setTimeout(() => {
        settling.current = false;
      }, SETTLE_MS);
    };
    setTimeout(finish, DIVIDER_READY_MS);
  }, [chat.status, chat.focusing, base.status, dividerId, initialFocus, scrollToEnd]);

  useEffect(() => {
    if (chat.status === "loading" || listReady) return undefined;
    if (chat.focusing || initialFocus != null || chat.messages.length === 0) {
      setListReady(true); // 과거 위치로 열거나 내용이 없으면 숨길 이유가 없다
      return undefined;
    }
    const t = setTimeout(() => setListReady(true), LIST_READY_MAX_MS);
    return () => clearTimeout(t);
  }, [chat.status, chat.focusing, chat.messages.length, initialFocus, listReady]);

  // 검색 결과(또는 focus 인자)로 이동: 목록이 그 창으로 바뀌면 해당 메시지로 스크롤하고 잠깐 강조한다
  useEffect(() => {
    const target = chat.focusTarget;
    if (!target) return undefined;
    clearTimeout(pinHighlightTimer.current); // 고정 바 이동의 타이머가 이번 이동의 잠금·강조를 일찍 끄지 않게
    clearTimeout(pinSettleTimer.current);
    nearBottom.current = false;
    settling.current = true;
    focusRetry.current = 0;
    setHasNew(false);
    setHighlightId(target.id);
    const scroll = setTimeout(() => {
      const index = itemsRef.current.findIndex((it) => itemHasMessage(it, target.id));
      if (index >= 0) listRef.current?.scrollToIndex({ index, viewPosition: 0.35, animated: false });
    }, 0);
    const settle = setTimeout(() => {
      settling.current = false;
    }, SETTLE_MS);
    const clear = setTimeout(() => setHighlightId(null), HIGHLIGHT_MS);
    pinSettleTimer.current = settle;
    pinHighlightTimer.current = clear;
    return () => {
      clearTimeout(scroll);
      clearTimeout(settle);
      clearTimeout(clear);
    };
  }, [chat.focusTarget]);

  // 포커스 실패로 최근 대화로 복구됐을 때: 위로 불러오기 잠금을 풀고 맨 아래로 간다
  useEffect(() => {
    if (chat.recovered === 0) return undefined;
    settling.current = false;
    nearBottom.current = true;
    const t = setTimeout(() => scrollToEnd(false), 50);
    return () => clearTimeout(t);
  }, [chat.recovered, scrollToEnd]);

  /** 아직 그려지지 않은 줄로 바로 갈 수 없을 때: 대략 위치로 먼저 간 뒤 다시 시도한다(최대 4번). */
  const onScrollToIndexFailed = useCallback(({ index, averageItemLength }) => {
    focusRetry.current += 1;
    if (focusRetry.current > 4) return;
    listRef.current?.scrollToOffset({ offset: Math.max(0, averageItemLength * index), animated: false });
    const viewPosition = dividerJump.current ? DIVIDER_VIEW_POSITION : 0.35;
    if (dividerJump.current) dividerRetries.current += 1;
    setTimeout(() => {
      if (dividerJump.current) dividerRetries.current = Math.max(0, dividerRetries.current - 1);
      listRef.current?.scrollToIndex({ index, viewPosition, animated: false });
    }, 120);
  }, []);

  const closeSearch = () => {
    setSearchOpen(false);
    search.reset();
  };

  const goLive = async () => {
    if (goingLive) return;
    setGoingLive(true);
    setHighlightId(null);
    nearBottom.current = true;
    const ok = await chat.returnToLive();
    setGoingLive(false);
    if (ok) setTimeout(() => scrollToEnd(false), 50);
    else nearBottom.current = false;
  };

  const closeMenu = () => setMenu(null);
  const openMenu = (message, anchor, reactTo) => setMenu({ message, anchor, reactTo }); // reactTo: 앨범 사진의 메뉴일 때 반응을 거는 대표 사진(마지막 사진)
  /** 내 반응을 켜거나(다른 이모지면 바꾸고) 같은 이모지를 다시 누르면 끈다. 실패하면 이유를 안내 줄에 보인다. */
  const runReaction = async (message, emoji) => {
    const action = reactionAction(message, emoji);
    const res = await chat.reactTo(message.id, action.type === "remove" ? null : emoji);
    if (!res.ok && !res.busy) pins.say(messageActionError(res.error, "react"));
  };
  const heart = (message) => runReaction(message, HEART);
  const reactFromMenu = (emoji) => {
    const opened = menu?.reactTo ?? menu?.message;
    closeMenu();
    if (!opened) return;
    const latest = chat.messages.find((m) => !m.clientId && Number(m.id) === Number(opened.id)) ?? opened; // 메뉴를 연 뒤 내 반응이 바뀌었을 수 있어 최신 상태로 켜고 끈다
    runReaction(latest, emoji);
  };
  const replyFromMenu = () => {
    const message = menu?.message;
    closeMenu();
    if (message) setReplyTo(replyPreview(message, nameOf));
  };
  const deleteFromMenu = async () => {
    const message = menu?.message;
    closeMenu();
    if (!message) return;
    const res = await chat.deleteMine(message.id);
    if (res.ok) pins.say("메시지를 삭제했어요");
    else if (!res.busy) pins.say(messageActionError(res.error, "delete"));
  };
  const copyMessage = () => {
    const text = menu?.message?.text;
    closeMenu();
    if (text) Clipboard.setStringAsync(text).then(() => pins.say(COPIED_NOTICE), () => pins.say(COPY_FAILED_NOTICE));
  };
  /** 고정 바 항목: 이미 목록에 있는 라이브 메시지면 스크롤+강조만, 아니면 그 위치 창을 불러온다. */
  const pickPin = (messageId, reuseWindow = false) => {
    if (pinTapAction({ messages: chat.messages, messageId, focusing: chat.focusing, reuseWindow }) === "focus") {
      clearTimeout(pinHighlightTimer.current);
      clearTimeout(pinSettleTimer.current);
      chat.focusOn(messageId);
      return;
    }
    const index = itemsRef.current.findIndex((it) => itemHasMessage(it, messageId));
    if (index < 0) {
      clearTimeout(pinHighlightTimer.current);
      clearTimeout(pinSettleTimer.current);
      chat.focusOn(messageId);
      return;
    }
    nearBottom.current = false;
    settling.current = true;
    focusRetry.current = 0;
    clearTimeout(pinHighlightTimer.current);
    clearTimeout(pinSettleTimer.current);
    setHighlightId(messageId);
    listRef.current?.scrollToIndex({ index, viewPosition: 0.35, animated: true });
    pinSettleTimer.current = setTimeout(() => {
      settling.current = false;
    }, SETTLE_MS);
    pinHighlightTimer.current = setTimeout(() => setHighlightId(null), HIGHLIGHT_MS);
  };
  pickPinRef.current = pickPin;
  const currentMatchId = searchOpen ? (search.current?.id ?? null) : null;
  // 검색 줄이 가리키는 일치(처음엔 가장 최근 것, ▲▼ 로 바뀜)가 달라지면 그 메시지로 이동한다
  useEffect(() => {
    if (currentMatchId != null) pickPinRef.current?.(currentMatchId, true);
  }, [currentMatchId]);
  const pinMessageFromMenu = () => {
    const message = menu?.message;
    closeMenu();
    pins.pin(message);
  };
  const unpinMessageFromMenu = () => {
    const id = menu?.message?.id;
    closeMenu();
    pins.unpin(id);
  };
  const nameOf = (userId) => {
    const m = info.room?.members?.find((x) => x.id === userId);
    return m ? memberName(m) : undefined;
  };

  const jumpToEnd = () => {
    nearBottom.current = true;
    setHasNew(false);
    setFar(false);
    scrollToEnd(true);
  };

  const items = buildItems(mergeNotes(chat.messages, mention.notes), { dividerBeforeId: dividerId }); // 개인용 가비 답은 내 화면에만 시간순으로 끼운다(읽음·새 메시지 계산은 chat.messages 그대로)
  itemsRef.current = items;
  const members = info.room?.members?.length ?? 0;
  const peer = direct ? info.room?.members?.find((m) => m.id === peerId) : null;
  const title = direct ? (info.room ? memberName(peer) : "1:1 대화") : (info.room?.name ?? "가족 채팅");

  const header = searchOpen ? (
    <ChatSearchBar search={search} scope={familyRoom} onClose={closeSearch} onJumpCurrent={() => currentMatchId != null && pickPin(currentMatchId, true)} />
  ) : (
    <>
      <View style={styles.bar}>
        <IconButton name="chevron-back" label="뒤로" onPress={back} />
        <View style={styles.titleBox}>
          <Text style={styles.title} numberOfLines={1}>
            {title}
          </Text>
          {info.room && !direct ? (
            <Text style={styles.count} accessibilityLabel={`구성원 ${members}명`}>
              {members}
            </Text>
          ) : null}
        </View>
        <IconButton name="search-outline" label="대화 검색" onPress={() => setSearchOpen(true)} disabled={info.status !== "ready"} />
        <IconButton name="sparkles-outline" label="AI 도우미 열기" onPress={() => setAiOpen(true)} disabled={info.status !== "ready"} />
        <IconButton name="ellipsis-vertical" label="채팅방 메뉴" onPress={() => setDrawerOpen(true)} />
      </View>
    </>
  );

  let body;
  if (info.status === "loading") {
    body = (
      <Center>
        <ActivityIndicator color={colors.accent} accessibilityLabel="불러오는 중" />
      </Center>
    );
  } else if (info.status === "none") {
    body = (
      <Center>
        <Text style={styles.emptyTitle}>가족을 먼저 만들어 주세요</Text>
        <Text style={styles.emptyText}>가족을 만들거나 초대 코드로 참여하면 함께 대화할 수 있어요.</Text>
        <Button label="가족 만들기 · 참여하기" onPress={() => router.push("/family")} />
      </Center>
    );
  } else if (info.status === "error") {
    body = (
      <Center>
        <Text style={styles.emptyText}>{info.error}</Text>
        <Button label="다시 시도" onPress={info.reload} />
      </Center>
    );
  } else if (chat.status === "loading") {
    body = (
      <Center>
        <ActivityIndicator color={colors.accent} accessibilityLabel="대화를 불러오는 중" />
      </Center>
    );
  } else if (chat.status === "error" && chat.messages.length === 0) {
    body = (
      <Center>
        <Text style={styles.emptyText}>{chat.error}</Text>
        <Button label="다시 시도" onPress={chat.retry} />
      </Center>
    );
  } else {
    body = (
      <>
        {chat.error ? (
          <View style={styles.banner} accessibilityLiveRegion="polite">
            <Ionicons name="alert-circle-outline" size={18} color={colors.danger} />
            <Text style={styles.bannerText} numberOfLines={2}>
              {chat.error}
            </Text>
            <Pressable onPress={chat.retry} accessibilityRole="button" accessibilityLabel="다시 시도" style={styles.bannerBtn}>
              <Text style={styles.bannerAction}>다시 시도</Text>
            </Pressable>
          </View>
        ) : null}
        <View style={styles.listArea}>
        <FlatList
          ref={listRef}
          style={[styles.list, !listReady && styles.listHidden]}
          data={items}
          keyExtractor={(it) => it.key}
          renderItem={({ item }) =>
            item.type === "unread" ? (
              <View style={styles.unreadWrap} accessible accessibilityRole="header" accessibilityLabel="여기까지 읽었습니다">
                <View style={styles.unreadLine} />
                <Text style={styles.unreadText}>여기까지 읽었습니다</Text>
                <View style={styles.unreadLine} />
              </View>
            ) : item.type === "day" ? (
              <View style={styles.dayWrap}>
                <Text style={styles.day} accessibilityRole="header">
                  {item.label}
                </Text>
              </View>
            ) : item.message.localNote ? (
              <AssistantNote note={item.message} onRetry={mention.ask} onDismiss={mention.dismiss} onResolveCard={mention.resolveCard} onShareToRoom={shareToRoom} />
            ) : (
              <MessageBubble
                nameOf={nameOf}
                message={item.message}
                mine={item.message.user_id === info.me?.id}
                showName={item.showName}
                showTime={item.showTime}
                unread={unreadCount(item.message, info.me, chat.readStates)}
                photoUrl={photoById[item.message.user_id]}
                album={item.album}
                highlighted={highlightId != null && itemHasMessage(item, highlightId)}
                searchTerms={searchOpen ? search.terms : undefined}
                searchCurrent={currentMatchId != null && itemHasMessage(item, currentMatchId)}
                onRetry={chat.resend}
                onDiscard={chat.discard}
                onActions={canOpenMenu(item.message) ? (m, anchor) => openMenu(m, anchor, item.album ? item.message : undefined) : undefined}
                onHeart={canOpenMenu(item.message) ? heart : undefined}
                onReactionPress={canOpenMenu(item.message) ? runReaction : undefined}
                onReplyPress={pickPin}
                linkBadges={item.album ? albumBadges(item.album, links.badgesOf) : links.badgesOf(item.message.id)}
                onSaveToRecord={canSaveToRecord({ direct, attachment: item.message.attachment }) ? savePhotoToRecord : undefined}
                onSaveToLibrary={canSaveToLibrary({ direct, attachment: item.message.attachment }) ? savePhotoToLibraryDoc : undefined}
              />
            )
          }
          ListHeaderComponent={chat.loadingOlder ? <ActivityIndicator style={styles.older} color={colors.accent} accessibilityLabel="이전 대화를 불러오는 중" /> : null}
          ListEmptyComponent={
            <View style={styles.emptyList}>
              <Text style={styles.emptyTitle}>아직 대화가 없어요</Text>
              <Text style={styles.emptyText}>첫 메시지를 보내 보세요.</Text>
            </View>
          }
          onScroll={onScroll}
          onScrollToIndexFailed={onScrollToIndexFailed}
          scrollEventThrottle={100}
          onContentSizeChange={(_, height) => {
            const grew = height - scrollPos.current.height;
            if (Platform.OS === "web" && olderRequested.current && grew > 0 && scrollPos.current.height > 0 && !nearBottom.current) {
              olderRequested.current = false;
              listRef.current?.scrollToOffset({ offset: scrollPos.current.y + grew, animated: false });
            } else if (nearBottom.current && !chat.focusing && (positioned.current || initialFocus != null)) {
              scrollToEnd(false);
              // 목록은 아직 그려지지 않았거나 높이가 바뀌는 마지막 항목(전송 중 → 보낸 시각·읽음 수) 때문에 한 번에 끝까지 못 갈 수 있어, 잠시 뒤 한 번 더 맞춘다
              clearTimeout(endTimer.current);
              endTimer.current = setTimeout(() => {
                if (nearBottom.current && !chat.focusing) scrollToEnd(false);
                setListReady(true);
              }, END_SETTLE_MS);
            }
            scrollPos.current.height = height;
          }}
          maintainVisibleContentPosition={{ minIndexForVisible: 0 }}
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={styles.listContent}
        />
        {!listReady ? (
          <View style={styles.listLoading} pointerEvents="none">
            <ActivityIndicator color={colors.accent} accessibilityLabel="대화를 불러오는 중" />
          </View>
        ) : null}
        {chat.focusing ? <LiveReturnButton onPress={goLive} busy={goingLive || chat.loadingNewer} /> : null}
        {far && !chat.focusing ? (
          <Pressable
            onPress={jumpToEnd}
            accessibilityRole="button"
            accessibilityLabel={hasNew ? "새 메시지, 맨 아래로" : "맨 아래로"}
            style={[styles.jump, hasNew && styles.jumpNew]}
          >
            <Ionicons name="arrow-down" size={20} color={colors.text} />
          </Pressable>
        ) : null}
        </View>
        <Composer
          value={draft}
          onChangeText={setDraft}
          onSend={onSend}
          onPickPhoto={onPickPhoto}
          onPickFile={onPickFile}
          fileBusy={pickingFileUi || chat.fileBusy}
          photoBusy={pickingUi || chat.photoBusy}
          photoError={chat.photoError}
          onDismissPhotoError={() => chat.setPhotoError("")}
          replyTo={replyTo}
          onCancelReply={() => setReplyTo(null)}
          direct={direct}
        />
      </>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      {header}
      {!searchOpen && info.status === "ready" ? (
        <PinnedBar pins={pins.pins} expanded={pins.expanded} onToggle={() => pins.setExpanded(!pins.expanded)} onPick={pickPin} onHide={pins.hide} onShowHidden={pins.showHidden} notice={pins.notice} nameOf={nameOf} />
      ) : null}
      <KeyboardAvoidingView style={styles.flex} behavior="padding">
        {body}
      </KeyboardAvoidingView>
      <RoomDrawer visible={drawerOpen} onClose={() => setDrawerOpen(false)} room={info.room} roomId={roomId} peerId={peerId} myId={info.me?.id} muted={roomMute.muted} onToggleMute={roomMute.toggle} />
      <MessageMenu target={menu} myId={info.me?.id} pinned={pins.isPinned(menu?.message?.id)} onClose={closeMenu} onReact={reactFromMenu} onReply={replyFromMenu} onPin={pinMessageFromMenu} onUnpin={unpinMessageFromMenu} onCopy={copyMessage} onDelete={deleteFromMenu} />
      <AiPanel visible={aiOpen} onClose={() => setAiOpen(false)} onPickReply={pickReply} onLinked={links.registerCandidate} roomId={roomId ?? undefined} peerId={peerId ?? undefined} />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
  bar: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  titleBox: { flex: 1, minWidth: 0, flexDirection: "row", alignItems: "center", gap: spacing.xs },
  title: { ...font.cardTitle, color: colors.text, flexShrink: 1 },
  count: { ...font.caption, color: colors.textMuted },
  listArea: { flex: 1 },
  jump: {
    position: "absolute",
    right: spacing.lg,
    bottom: spacing.lg,
    width: 40,
    height: 40,
    borderRadius: radius.pill,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  jumpNew: { backgroundColor: colors.peach, borderColor: colors.peach },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md, padding: spacing.xxl },
  emptyTitle: { ...font.cardTitle, color: colors.text, textAlign: "center" },
  emptyText: { ...font.body, color: colors.textSub, textAlign: "center" },
  emptyList: { alignItems: "center", gap: spacing.sm, paddingVertical: spacing.xxl * 2 },
  list: { flex: 1, backgroundColor: colors.background },
  listHidden: { opacity: 0 },
  listLoading: { ...StyleSheet.absoluteFillObject, alignItems: "center", justifyContent: "center" },
  listContent: { paddingVertical: spacing.md },
  older: { paddingVertical: spacing.md },
  dayWrap: { alignItems: "center", paddingVertical: spacing.md },
  unreadWrap: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  unreadLine: { flex: 1, height: StyleSheet.hairlineWidth, backgroundColor: colors.divider },
  unreadText: { ...font.caption, color: colors.textSub },
  day: { ...font.tab, color: colors.textMuted, backgroundColor: colors.surface, paddingHorizontal: spacing.md, paddingVertical: spacing.xs, borderRadius: radius.pill, overflow: "hidden" },
  banner: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, backgroundColor: colors.dangerSoft },
  bannerText: { flex: 1, ...font.caption, color: colors.danger },
  bannerBtn: { minHeight: 36, justifyContent: "center" },
  bannerAction: { ...font.caption, fontFamily: font.bodyStrong.fontFamily, color: colors.text },
});
