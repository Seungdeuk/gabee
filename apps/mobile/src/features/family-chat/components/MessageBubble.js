import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { Platform, Pressable, StyleSheet, Text, View } from "react-native";

import AuthImage from "@/shared/components/AuthImage";
import UserAvatar from "@/shared/components/UserAvatar";
import { colors, font, radius, spacing } from "@/theme";

import { ALBUM_WIDTH, albumCells } from "../album";
import { playPathFromLink, splitPlayLink } from "@/features/playground/invite";
import { formatTime } from "../chatUtils";
import { unreadByA11yLabel } from "../listUtils";
import { fitSize } from "../photo";
import { bubbleSelectable, bubbleTextStyle } from "../pinUtils";
import { FILE_SAVE_LABEL, fileSaveHelp, isFileMessage } from "../fileUtils";
import { DELETED_TEXT, DOUBLE_TAP_MS, isDoubleTap } from "../messageActions";
import { openChatFile, saveChatFile } from "../openFile";
import { saveFileName } from "../mediaUtils";
import { savePhoto } from "../savePhoto";
import AlbumViewer from "./AlbumViewer";
import AssistantAvatar from "./AssistantAvatar";
import FileCard from "./FileCard";
import { highlightNodes, hitStyles } from "./Highlighted";
import PhotoViewer from "./PhotoViewer";
import ReactionRow from "./ReactionRow";
import ReplyQuote from "./ReplyQuote";

const AVATAR = 36;

/** 글자 속 놀이터 초대 링크(gabee://play…)를 눌러 그 게임 화면을 열 수 있게 한다. 링크가 없으면 글자 그대로. */
function playLinkNodes(text) {
  const parts = splitPlayLink(text);
  if (parts.length === 1 && !parts[0].link) return text;
  return parts.map((part, i) =>
    part.link ? (
      <Text key={i} style={styles.playLink} onPress={() => { const path = playPathFromLink(part.text); if (path) router.push(path); }} accessibilityRole="link">
        {part.text}
      </Text>
    ) : (
      part.text
    ),
  );
}

/**
 * 말풍선 한 줄. 내 말은 오른쪽(복숭아색, 시각은 왼쪽 아래), 상대는 왼쪽(아바타·이름·카드색, 시각은 오른쪽 아래).
 * 내 말풍선은 아직 읽지 않은 사람이 있을 때만 시각 위에 작은 숫자(unread)를 보여 준다(모두 읽으면 표시 없음).
 * 사진 메시지(attachment)는 글자 대신 썸네일을 말풍선 안에 보여 주고(원본 비율로 크기를 미리 정해 레이아웃이 점프하지 않는다), 누르면 전체 화면으로 본다.
 * 전송 중이면 "전송 중…", 실패하면 "전송 실패 · 다시 보내기"(누르면 재전송, 길게 누르거나 "삭제" 로 지움).
 * 가비(AI)가 @가비 호출에 답해 올린 메시지(is_assistant)는 반짝이 아바타와 꿀색 말풍선으로 사람과 구분한다.
 * 검색 결과로 이동했을 때 그 메시지는 highlighted 로 잠깐 배경색을 입힌다.
 * 채팅방 검색이 열려 있으면 searchTerms 로 글 안의 검색어를 꿀색으로 강조하고, 지금 가리키는 일치 메시지(searchCurrent)는 배경과 검색어를 더 진하게 보인다.
 * linkBadges 가 있으면(이 메시지에서 일정·할 일로 등록됨) 글 아래에 작은 표시를 붙인다(표시만, 눌러도 아무 일 없다).
 * onActions 가 있으면(서버에 저장된 지우지 않은 메시지) 말풍선을 길게 눌러 메뉴(반응·답장·공지·복사·삭제)를 열고, 누른 지점(anchor)을 함께 넘긴다. 네이티브에서는 길게 누르기가 글자 선택과 겹치지 않도록 이 경우 글자 선택을 끈다(복사는 메뉴에서 한다).
 * onHeart 가 있으면 말풍선(사진은 썸네일)을 두 번 눌러 하트 반응을 켜고 끈다(사진은 한 번 누르면 잠깐 기다렸다가 크게 보기).
 * 답장이면(reply_to) 글 위에 원본 인용(ReplyQuote)이 붙고 누르면 onReplyPress 로 원본으로 이동한다. 반응(reactions)은 말풍선 아래 칩으로 보이고 누르면 onReactionPress 가 내 반응을 켜거나 끈다.
 * 지운 메시지(deleted)는 말풍선 대신 가운데에 "삭제된 메시지입니다"만 보인다.
 * onSaveToRecord 가 있으면(가족 전체방의 사진) 전체 화면 사진 보기에 "가비 기록에 저장" 버튼이 붙고, 누르면 그 사진을 AI 비서의 가족 기록으로 올린다(결과 문구는 사진 보기에 보인다).
 * 파일 메시지(attachment.kind === "file")는 사진 대신 파일 카드를 보인다: 본문을 누르면 열기/공유, 다운로드 아이콘은 내 파일/드라이브에 저장. 사진 보기에는 "사진첩에 저장" 버튼이 붙는다.
 * onSaveToLibrary 가 있으면(가족 전체방의 사진) 사진 보기에 "문서로 저장" 버튼이 붙고, 누르면 그 사진을 가족 공유 문서함에 직접 넣는다(결과 문구는 사진 보기에 보인다).
 * @param {{ message: object, mine: boolean, showName: boolean, showTime?: boolean, unread?: number, photoUrl?: string | null, highlighted?: boolean, searchTerms?: string[], searchCurrent?: boolean, onRetry?: (clientId: string) => void, onDiscard?: (clientId: string) => void, onActions?: (message: object, anchor: { x: number, y: number } | null) => void, onHeart?: (message: object) => void, onReactionPress?: (message: object, emoji: string) => void, onReplyPress?: (messageId: number) => void, linkBadges?: { kind: "event" | "todo", label: string }[], onSaveToRecord?: (attachment: object) => Promise<{ ok: boolean, message: string }>, onSaveToLibrary?: (attachment: object) => Promise<{ ok: boolean, message: string }>, nameOf?: (userId: string) => string | undefined }} props
 */
export default function MessageBubble({ message, mine, showName, showTime = true, unread = 0, photoUrl, highlighted = false, searchTerms, searchCurrent = false, onRetry, onDiscard, onActions, onHeart, onReactionPress, onReplyPress, linkBadges, onSaveToRecord, onSaveToLibrary, nameOf, album }) {
  const senderName = nameOf?.(message.user_id) || message.user_name; // 내가 붙인 별명이 있으면 별명
  const failed = message.status === "failed";
  const sending = message.status === "sending";
  const attachment = message.attachment ?? null;
  const isAlbum = Boolean(album && album.length > 1); // 같은 묶음으로 올린 사진들(message 는 그 마지막 사진)
  const [viewing, setViewing] = useState(false);
  const [albumStart, setAlbumStart] = useState(null); // 앨범 뷰어를 연 사진 순서(닫혀 있으면 null)
  const [albumRecords, setAlbumRecords] = useState({}); // 앨범 사진별(첨부 id) 가비 기록 저장 상태
  const [record, setRecord] = useState({ saving: false, done: false, notice: "" }); // 가비 기록에 저장한 상태(이 사진 하나의 것)
  const [albumLibraries, setAlbumLibraries] = useState({}); // 앨범 사진별(첨부 id) 문서함 저장 상태
  const [library, setLibrary] = useState({ saving: false, done: false, notice: "" }); // 문서함에 저장한 상태(이 사진 하나의 것)
  const isFile = isFileMessage(message);
  const [fileState, setFileState] = useState({ busy: null, notice: "" }); // 파일 열기·저장 진행/결과
  const fileBusyRef = useRef(false);
  const [device, setDevice] = useState({ saving: false, notice: "" }); // 사진첩 저장 상태
  const size = attachment && !isFile ? fitSize(attachment.width, attachment.height) : null;
  const boxRef = useRef(null); // 메뉴를 말풍선 바로 아래에 붙이려고 위치를 잰다
  const lastTap = useRef(null); // 앞선 누름 시각(더블탭 판정)
  const photoTimer = useRef(null); // 사진 한 번 누름은 더블탭인지 기다렸다가 크게 본다
  useEffect(() => () => clearTimeout(photoTimer.current), []);

  /** 글 말풍선을 눌렀을 때: 두 번째 누름이면 하트. */
  const tapBubble = () => {
    const now = Date.now();
    if (isDoubleTap(lastTap.current, now)) {
      lastTap.current = null;
      onHeart?.(message);
    } else lastTap.current = now;
  };
  /** 사진 썸네일을 눌렀을 때: 두 번째 누름이면 하트, 아니면 더블탭을 기다린 뒤 크게 본다(하트를 못 켜는 메시지는 바로). */
  const tapPhoto = () => {
    const now = Date.now();
    clearTimeout(photoTimer.current);
    if (onHeart && isDoubleTap(lastTap.current, now)) {
      lastTap.current = null;
      onHeart(message);
      return;
    }
    lastTap.current = now;
    photoTimer.current = setTimeout(() => setViewing(true), onHeart ? DOUBLE_TAP_MS : 0);
  };

  /** 앨범 안의 사진을 길게 눌렀을 때: 그 사진의 메시지로 메뉴를 연다(삭제 등이 그 사진에만 적용된다). */
  const openAlbumMenu = (target, e) => {
    const n = e?.nativeEvent;
    onActions?.(target, typeof n?.pageX === "number" && typeof n?.pageY === "number" ? { x: n.pageX, y: n.pageY } : null);
  };
  /** 앨범 뷰어의 "가비 기록에 저장": 지금 보는 사진 한 장을 올린다(저장 중이거나 이미 저장했으면 다시 올리지 않는다). */
  const saveAlbumRecord = async (photo, index) => {
    const state = albumRecords[photo.id];
    if (!onSaveToRecord || state?.saving || state?.done) return;
    setAlbumRecords((prev) => ({ ...prev, [photo.id]: { saving: true, done: false, notice: "" } }));
    const result = await onSaveToRecord(album[index].attachment);
    setAlbumRecords((prev) => ({ ...prev, [photo.id]: { saving: false, done: result.ok, notice: result.message } }));
  };
  /** 앨범 뷰어의 "문서로 저장": 지금 보는 사진 한 장을 문서함에 넣는다(저장 중이거나 이미 저장했으면 다시 누르지 않는다). 실패하면 다시 누를 수 있다. */
  const saveAlbumLibrary = async (photo, index) => {
    const state = albumLibraries[photo.id];
    if (!onSaveToLibrary || state?.saving || state?.done) return;
    setAlbumLibraries((prev) => ({ ...prev, [photo.id]: { saving: true, done: false, notice: "" } }));
    const result = await onSaveToLibrary(album[index].attachment);
    setAlbumLibraries((prev) => ({ ...prev, [photo.id]: { saving: false, done: result.ok, notice: result.message } }));
  };
  /** 앨범 뷰어의 "메뉴": 뷰어를 닫고(모달이 겹치지 않게) 그 사진의 메시지로 메뉴를 연다. */
  const openAlbumViewerMenu = (index) => {
    setAlbumStart(null);
    onActions?.(album[index], null);
  };
  /** 앨범 뷰어의 "사진첩에 저장": 지금 보고 있는 사진 한 장을 저장한다. */
  const saveAlbumPhoto = async (photo) => {
    if (device.saving) return;
    setDevice({ saving: true, notice: "" });
    const target = album.find((m) => m.attachment?.id === photo.id);
    const result = await savePhoto({ url: photo.url }, saveFileName({ attachment_id: photo.id, created_at: target?.created_at ?? message.created_at }), Platform.OS);
    setDevice({ saving: false, notice: result.message });
  };

  /** "가비 기록에 저장"을 눌렀을 때: 저장 중이거나 이미 저장했으면 다시 올리지 않는다(같은 사진이 기록에 두 번 쌓이지 않게). */
  const saveRecord = async () => {
    if (!onSaveToRecord || record.saving || record.done) return;
    setRecord({ saving: true, done: false, notice: "" });
    const result = await onSaveToRecord(attachment);
    setRecord({ saving: false, done: result.ok, notice: result.message });
  };

  /** "문서로 저장"을 눌렀을 때: 저장 중이거나 이미 저장했으면 다시 누르지 않는다. 실패하면 문구를 보이고 다시 누를 수 있다. */
  const saveLibrary = async () => {
    if (!onSaveToLibrary || library.saving || library.done) return;
    setLibrary({ saving: true, done: false, notice: "" });
    const result = await onSaveToLibrary(attachment);
    setLibrary({ saving: false, done: result.ok, notice: result.message });
  };

  /** 파일 카드: 열기/공유(open) 또는 내 파일/드라이브에 저장(save). 진행 중에는 다시 누를 수 없다. */
  const runFile = async (kind) => {
    if (fileBusyRef.current) return; // 연속으로 눌러도 한 번만 실행(state 는 한 박자 늦다)
    fileBusyRef.current = true;
    setFileState({ busy: kind, notice: kind === "save" ? fileSaveHelp(Platform.OS) : "" });
    const result = await (kind === "save" ? saveChatFile(attachment, Platform.OS) : openChatFile(attachment, Platform.OS));
    fileBusyRef.current = false;
    setFileState({ busy: null, notice: result.message });
  };
  /** 사진 보기의 "사진첩에 저장": 기기 사진첩(갤러리)에 저장한다. */
  const saveToDevice = async () => {
    if (device.saving) return;
    setDevice({ saving: true, notice: "" });
    const result = await savePhoto({ url: attachment.url }, saveFileName({ attachment_id: attachment.id, created_at: message.created_at }), Platform.OS);
    setDevice({ saving: false, notice: result.message });
  };

  if (message.deleted) {
    return (
      <View style={[styles.deletedRow, (highlighted || searchCurrent) && styles.highlight]} accessible accessibilityLabel={DELETED_TEXT}>
        <Text style={styles.deletedText}>{DELETED_TEXT}</Text>
      </View>
    );
  }

  /** 길게 누른 지점(화면 기준)과 함께 메뉴를 연다. 안쪽 사진·원본 인용도 같은 메뉴를 열도록 함께 쓴다. */
  const openMenu = (e) => {
    const n = e?.nativeEvent;
    const point = typeof n?.pageX === "number" && typeof n?.pageY === "number" ? { x: n.pageX, y: n.pageY } : null;
    const node = boxRef.current;
    if (node?.measureInWindow) {
      // 말풍선 위치를 알면 그 바로 아래에 메뉴를 붙인다(내 말풍선은 오른쪽 끝에 맞춤). 못 재면 누른 지점 근처, 그것도 모르면 화면 가운데
      node.measureInWindow((x, y, width, height) => {
        if (width > 0 && height > 0) onActions?.(message, { x: x + width / 2, y: y + height, rect: { x, y, width, height }, side: mine ? "right" : "left" });
        else onActions?.(message, point);
      });
      return;
    }
    onActions?.(message, point);
  };
  const selectable = bubbleSelectable({ canAct: Boolean(onActions), os: Platform.OS });
  const Box = onActions ? Pressable : View;
  // 스크린리더: 바깥 말풍선이 하나로 묶여도 안쪽 동작(사진 크게 보기, 원본으로 이동)을 동작 목록으로 열어 둔다
  const a11yActions = [
    { name: "menu", label: "메뉴 열기" },
    ...(attachment && !isFile ? [{ name: "view", label: isAlbum ? `사진 ${album.length}장 크게 보기` : "사진 크게 보기" }] : []),
    ...(attachment && isFile ? [{ name: "open", label: "파일 열기" }, { name: "save", label: FILE_SAVE_LABEL }] : []),
    ...(message.reply_to && onReplyPress ? [{ name: "jump", label: "답장한 원본으로 이동" }] : []),
  ];
  const boxProps = onActions
    ? {
        ref: boxRef,
        onLongPress: openMenu,
        onPress: attachment || !onHeart ? undefined : tapBubble,
        accessibilityHint: "길게 누르면 메뉴가 열려요",
        accessibilityActions: a11yActions,
        onAccessibilityAction: (e) => {
          const name = e.nativeEvent.actionName;
          if (name === "menu") onActions(message, null);
          else if (name === "view" && !isFile) {
            if (isAlbum) setAlbumStart(0);
            else setViewing(true);
          }
          else if (name === "open" && isFile) runFile("open");
          else if (name === "save" && isFile) runFile("save");
          else if (name === "jump") onReplyPress?.(message.reply_to.id);
        },
      }
    : null;
  const bubble = (
    <Box {...boxProps} style={[styles.bubble, attachment && !isFile && styles.photoBubble, mine ? styles.mineBubble : styles.otherBubble, message.is_assistant && styles.assistantBubble, sending && styles.dim]}>
      {message.reply_to ? <ReplyQuote reply={message.reply_to} onPress={onReplyPress} onLongPress={onActions ? openMenu : undefined} /> : null}
      {attachment && isFile ? (
        <>
          <FileCard attachment={attachment} busy={fileState.busy} onOpen={() => runFile("open")} onSave={() => runFile("save")} onLongPress={onActions ? openMenu : undefined} />
          {fileState.notice ? (
            <Text style={styles.fileNotice} accessibilityLiveRegion="polite">
              {fileState.notice}
            </Text>
          ) : null}
        </>
      ) : null}
      {isAlbum ? (
        <>
          <AlbumGrid album={album} onOpen={setAlbumStart} onLongPress={onActions ? openAlbumMenu : undefined} />
          <AlbumViewer
            photos={album.map((m) => ({ id: m.attachment.id, url: m.attachment.url }))}
            startIndex={albumStart ?? 0}
            visible={albumStart != null}
            onClose={() => setAlbumStart(null)}
            onSaveToDevice={saveAlbumPhoto}
            saving={device.saving}
            notice={device.notice}
            onSaveToRecord={onSaveToRecord ? saveAlbumRecord : undefined}
            recordOf={(id) => albumRecords[id] ?? { saving: false, done: false, notice: "" }}
            onSaveToLibrary={onSaveToLibrary ? saveAlbumLibrary : undefined}
            libraryOf={(id) => albumLibraries[id] ?? { saving: false, done: false, notice: "" }}
            onMenu={onActions ? openAlbumViewerMenu : undefined}
          />
        </>
      ) : null}
      {attachment && !isFile && !isAlbum ? (
        <>
          <Pressable onPress={tapPhoto} onLongPress={onActions ? openMenu : undefined} accessibilityRole="imagebutton" accessibilityLabel="사진, 누르면 크게 봐요">
            <AuthImage path={attachment.thumb_url} style={[styles.photo, { width: size.width, aspectRatio: size.width / size.height }]} />
          </Pressable>
          <PhotoViewer
            path={attachment.url}
            visible={viewing}
            onClose={() => setViewing(false)}
            onSaveToRecord={onSaveToRecord ? saveRecord : undefined}
            recordSaving={record.saving}
            recordDone={record.done}
            recordNotice={record.notice}
            onSaveToLibrary={onSaveToLibrary ? saveLibrary : undefined}
            librarySaving={library.saving}
            libraryDone={library.done}
            libraryNotice={library.notice}
            onSaveToDevice={saveToDevice}
            deviceSaving={device.saving}
            deviceNotice={device.notice}
          />
        </>
      ) : null}
      {message.text ? (
        <Text style={bubbleTextStyle({ selectable, base: styles.text, photo: attachment ? styles.photoText : null, noSelect: styles.noSelect })} selectable={selectable}>
          {searchTerms?.length ? highlightNodes(message.text, searchTerms, searchCurrent ? hitStyles.current : message.is_assistant ? styles.hitOnAssistant : styles.hit) : playLinkNodes(message.text)}
        </Text>
      ) : null}
      {(linkBadges ?? []).map((b) => (
        <View key={b.kind} style={styles.linkChip} accessible accessibilityLabel={b.label}>
          <Ionicons name={b.kind === "event" ? "calendar-outline" : "checkbox-outline"} size={12} color={colors.accent} />
          <Text style={styles.linkChipText}>{b.label}</Text>
        </View>
      ))}
    </Box>
  );

  let meta = null;
  if (failed) {
    meta = (
      <View style={styles.failRow}>
        <Pressable
          onPress={() => onRetry?.(message.clientId)}
          onLongPress={() => onDiscard?.(message.clientId)}
          accessibilityRole="button"
          accessibilityLabel="전송 실패. 다시 보내기. 길게 누르면 지워요"
          style={styles.failBox}
        >
          <Text style={styles.fail}>전송 실패 · 다시 보내기</Text>
        </Pressable>
        <Pressable onPress={() => onDiscard?.(message.clientId)} accessibilityRole="button" accessibilityLabel="보내지 못한 메시지 삭제" style={styles.failBox}>
          <Text style={styles.discard}>삭제</Text>
        </Pressable>
      </View>
    );
  } else if (sending) {
    meta = <Text style={styles.time}>전송 중…</Text>;
  } else if (showTime) {
    meta = <Text style={styles.time}>{formatTime(message.created_at)}</Text>;
  }

  const unreadNode =
    mine && !failed && !sending && unread > 0 ? (
      <Text style={styles.unread} accessibilityLabel={unreadByA11yLabel(unread)}>
        {unread}
      </Text>
    ) : null;

  const reactions = <ReactionRow reactions={message.reactions} onPress={onReactionPress ? (emoji) => onReactionPress(message, emoji) : undefined} align={mine ? "end" : "start"} />;
  const hasReactions = (message.reactions?.length ?? 0) > 0;
  if (mine) {
    return (
      <View>
        <View style={[styles.row, styles.mineRow, (highlighted || searchCurrent) && styles.highlight]}>
          {meta || unreadNode ? (
            <View style={styles.metaMine}>
              {unreadNode}
              {meta}
            </View>
          ) : null}
          {bubble}
        </View>
        {hasReactions ? <View style={styles.reactionsMine}>{reactions}</View> : null}
      </View>
    );
  }
  return (
    <View>
      <View style={[styles.row, (highlighted || searchCurrent) && styles.highlight]}>
        {showName ? (
          message.is_assistant ? (
            <AssistantAvatar size={AVATAR} />
          ) : (
            <UserAvatar name={senderName || "?"} userId={message.user_id} photoUrl={photoUrl} size={AVATAR} />
          )
        ) : (
          <View style={styles.spacer} />
        )}
        <View style={[styles.column, message.is_assistant && styles.assistantColumn]}>
          {showName ? <Text style={styles.name}>{senderName}</Text> : null}
          <View style={styles.line}>
            {bubble}
            {meta ? <View style={styles.metaOther}>{meta}</View> : null}
          </View>
        </View>
      </View>
    {hasReactions ? <View style={styles.reactionsOther}>{reactions}</View> : null}
    </View>
    );
}

/**
 * 앨범 말풍선 안의 사진 칸들(2장 나란히 · 3장 위 한 장+아래 두 장 · 4장 이상 2×2 에 마지막 칸 "+N"). 누르면 그 사진부터 뷰어가 열린다.
 * @param {{ album: object[], onOpen: (index: number) => void, onLongPress?: (message: object, e: object) => void }} props
 */
function AlbumGrid({ album, onOpen, onLongPress }) {
  const { cells, more } = albumCells(album.length, ALBUM_WIDTH);
  return (
    <View style={styles.album} accessible={false}>
      {cells.map((cell, i) => (
        <Pressable
          key={album[i].id}
          onPress={() => onOpen(i)}
          onLongPress={onLongPress ? (e) => onLongPress(album[i], e) : undefined}
          accessibilityRole="imagebutton"
          accessibilityLabel={`사진 ${album.length}장 중 ${i + 1}번째, 누르면 크게 봐요`}
          style={{ width: cell.width, height: cell.height }}
        >
          <AuthImage path={album[i].attachment.thumb_url} style={{ width: cell.width, height: cell.height, borderRadius: radius.sm }} />
          {more > 0 && i === cells.length - 1 ? (
            <View style={[styles.albumMore, { borderRadius: radius.sm }]}>
              <Text style={styles.albumMoreText}>{`+${more}`}</Text>
            </View>
          ) : null}
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  playLink: { color: colors.accent, textDecorationLine: "underline", fontWeight: "700" },
  row: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: 1 },
  mineRow: { justifyContent: "flex-end" },
  deletedRow: { alignItems: "center", paddingVertical: spacing.sm, paddingHorizontal: spacing.md },
  deletedText: { ...font.caption, color: colors.textMuted, textAlign: "center" },
  reactionsMine: { paddingHorizontal: spacing.md, alignItems: "flex-end" },
  reactionsOther: { paddingLeft: AVATAR + spacing.sm + spacing.md, paddingRight: spacing.md },
  highlight: { backgroundColor: colors.honeySoft },
  hit: { fontFamily: font.bodyStrong.fontFamily, backgroundColor: colors.honeySoft },
  hitOnAssistant: { fontFamily: font.bodyStrong.fontFamily, backgroundColor: colors.peach }, // 가비 말풍선 바탕이 꿀색이라 다른 색으로
  spacer: { width: AVATAR },
  column: { flexShrink: 1, maxWidth: "80%", gap: spacing.xs, alignItems: "flex-start" }, // 폭 기준은 row(확정된 폭)의 %. 안쪽 말풍선은 이 폭 안에서만 줄어든다
  line: { flexDirection: "row", alignItems: "flex-end", gap: spacing.xs, maxWidth: "100%" },
  name: { ...font.tab, fontFamily: font.bodyStrong.fontFamily, color: colors.textSub },
  bubble: { flexShrink: 1, maxWidth: "70%", paddingHorizontal: spacing.md, paddingVertical: spacing.xs + 2, borderRadius: radius.bubble },
  mineBubble: { backgroundColor: colors.peach, borderBottomRightRadius: spacing.xs },
  otherBubble: { maxWidth: "100%", backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, borderTopLeftRadius: spacing.xs },
  assistantBubble: { backgroundColor: colors.honeySoft, borderColor: colors.accent },
  assistantColumn: { maxWidth: "92%" }, // 가비의 긴 답(목록)은 폭을 넓혀 읽기 쉽게
  photoBubble: { paddingHorizontal: spacing.xs, paddingVertical: spacing.xs }, // 위쪽 bubble 의 가로·세로 여백(longhand)이 padding 보다 우선해서 같은 방향으로 덮어쓴다
  photo: { maxWidth: "100%", borderRadius: radius.md }, // 좁은 화면에서는 말풍선 안으로 비율을 지키며 줄어든다
  fileNotice: { ...font.caption, color: colors.textSub, marginTop: spacing.xs },
  album: { flexDirection: "row", flexWrap: "wrap", gap: 2, width: ALBUM_WIDTH },
  albumMore: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(0,0,0,0.45)" },
  albumMoreText: { ...font.cardTitle, color: colors.onDark },
  photoText: { paddingHorizontal: spacing.sm, paddingVertical: spacing.xs },
  dim: { opacity: 0.6 },
  linkChip: { flexDirection: "row", alignItems: "center", gap: spacing.xs, alignSelf: "flex-start", marginTop: spacing.xs, paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.pill, backgroundColor: colors.honeySoft },
  linkChipText: { ...font.tab, color: colors.accent },
  noSelect: { userSelect: "none" }, // styles.text 의 userSelect 가 selectable prop 을 이기므로 스타일에서도 끈다
  text: { ...font.body, color: colors.text, userSelect: "text" },
  time: { ...font.tab, color: colors.textMuted },
  unread: { ...font.tab, fontFamily: font.bodyStrong.fontFamily, color: colors.accent },
  metaMine: { alignItems: "flex-end", justifyContent: "flex-end", flexShrink: 0 },
  metaOther: { justifyContent: "flex-end", flexShrink: 0 },
  failRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  failBox: { minHeight: 32, justifyContent: "center" },
  fail: { ...font.tab, color: colors.danger },
  discard: { ...font.tab, color: colors.textMuted },
});
