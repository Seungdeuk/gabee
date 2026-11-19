import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { useRouter } from "expo-router";
import { useMemo, useRef, useState } from "react";
import { Modal, PanResponder, Pressable, StyleSheet, Switch, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import AuthImage from "@/shared/components/AuthImage";
import Button from "@/shared/components/Button";
import { colors, font, fonts, radius } from "@/theme";

import { photoRecView } from "../adapt";
import { createPhoto } from "../api";
import PhotoRecommend from "../components/photo/PhotoRecommend";
import PlayScreen from "../components/PlayScreen";
import { AudiencePicker, Chip, RevealNote, MakeQuotaNote, Toggle } from "../components/quiz/QuizParts";
import { playLive, usePhotoRecs } from "../hooks";
import { recordMade } from "../mock";
import { activeDraft, EMPTY_REC_PHOTO, isRecUnavailable, photoSendPartFor, recDraftFromItem, REC_UNAVAILABLE_NOTE } from "../photoRec";

const ZOOMS = [4, 6, 8, 16, 32];
const ASKS = { "직접 쓰기": "", 어디서: "이 사진, 어디서 찍었을까?", 언제: "이 사진, 언제 찍었을까?", 누가: "이 사진에 누가 있을까?" }; // 보여 주는 순서도 이 순서
const INSET_W = 120; // 원본 사진 위에 겹쳐 보이는 확대 미리보기 너비
const INSET_GAP = 8;
const STAGE_H = 260;
const NOTE_MAX = 100;
const Q_MAX = 20; // 질문 글자 수: 맞히는 화면에서 질문이 한 줄에 들어가는 길이
// 가족 앨범 시안(실제로는 가족이 공유한 사진 목록)
const ALBUM = [
  { id: "a1", name: "제주도 여행", color: "#CDB9A3" },
  { id: "a2", name: "생일 파티", color: "#E7C9B6" },
  { id: "a3", name: "캠핑", color: "#B9CDB5" },
  { id: "a4", name: "돌잔치", color: "#C9D3E3" },
  { id: "a5", name: "할머니 댁", color: "#E3D5B0" },
  { id: "a6", name: "강릉 바다", color: "#B5D2DC" },
];

/** 찰칵! 탐정단 문제 내기: 사진(가족 앨범 또는 내 폰), 보여 줄 부분(네모 끌기), 확대 배율, 질문·정답·보기, 한마디. */
export default function PhotoCreateScreen() {
  const router = useRouter();
  const live = playLive(); // 서버에 연결되면 내 폰의 사진을 올린다(가족 앨범은 시안뿐)
  const [mode, setMode] = useState("rec"); // "rec" 가비 추천 | "manual" 직접 내기
  const recs = usePhotoRecs();
  const [recIndex, setRecIndex] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [pickedId, setPickedId] = useState(null); // 마지막으로 "이 문제로 쓰기"를 누른 추천
  const recPlace = useRef(null); // 추천 사진이 뜨면 네모를 놓을 자리(사진 전체에서의 0~1). 사진 크기를 알아야 정할 수 있다
  // 고치는 칸(사진·질문·보기·배율·네모)은 탭마다 따로 둔다: 직접 내기는 추천과 상관없이 늘 자기 초안에서 시작한다.
  // 사진 상태 하나가 출처(recId·내 폰 파일)의 전부다: 추천 초안의 사진만 recId 를 가진다
  const recDraft = useDraft({ kind: "none" });
  const manualDraft = useDraft(live ? { kind: "none" } : { kind: "album", ...ALBUM[0] });
  const draft = activeDraft(mode, recDraft, manualDraft);
  const { photo, setPhoto, ratio, setRatio, zoom, setZoom, ask, setAsk, question, setQuestion, count, setCount, opts, setOpts, ansIdx, setAnsIdx, withNote, setWithNote, note, setNote, box, setBox, stageW, setStageW } = draft;
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState("");
  const [albumOpen, setAlbumOpen] = useState(false);
  const shown = opts.slice(0, count);
  const changeCount = (n) => {
    const c = Math.max(2, Math.min(4, n));
    setCount(c);
    setAnsIdx((a) => (a != null && a >= c ? null : a)); // 정답 보기가 사라지면 다시 고르게
  };
  const [target, setTarget] = useState([]);
  const stageH = live && ratio ? Math.round(stageW / ratio) : STAGE_H; // 사진 비율대로(잘리지 않게)
  const [dragging, setDragging] = useState(false);

  // 문제로 낼 부분(네모)은 배율이 클수록 작아진다: 사진 전체의 1/배율
  const bw = stageW / zoom;
  const bh = stageH / zoom;
  const drag0 = useRef({ box, stageW, stageH, start: box, bw, bh, setBox });
  drag0.current.setBox = setBox; // 끌기 처리기는 한 번만 만들므로, 지금 탭의 초안에 쓰도록 매번 갱신한다
  drag0.current.box = box;
  drag0.current.stageW = stageW;
  drag0.current.stageH = stageH;
  drag0.current.bw = bw;
  drag0.current.bh = bh;
  const drag = useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onPanResponderTerminationRequest: () => false,
        onPanResponderGrant: () => {
          drag0.current.start = drag0.current.box;
          setDragging(true);
        },
        onPanResponderMove: (_, g) => {
          const s = drag0.current.start;
          drag0.current.setBox({
            x: Math.max(0, Math.min(drag0.current.stageW - drag0.current.bw, s.x + g.dx)),
            y: Math.max(0, Math.min(drag0.current.stageH - drag0.current.bh, s.y + g.dy)),
          });
        },
        onPanResponderRelease: () => setDragging(false),
        onPanResponderTerminate: () => setDragging(false),
      }),
    [],
  );

  const pickZoom = (z) => {
    setZoom(z);
    // 네모가 작아지면 사진 밖으로 나가지 않게 위치를 다시 맞춘다
    setBox((b) => ({ x: Math.max(0, Math.min(stageW - stageW / z, b.x)), y: Math.max(0, Math.min(stageH - stageH / z, b.y)) }));
  };
  const k = INSET_W / bw; // 네모 한 변이 미리보기 한 변으로 커지는 비율
  const insetH = bh * k;
  // 미리보기는 네모와 겹치지 않는 모서리에 둔다(오른쪽 아래 → 왼쪽 아래 → 오른쪽 위 → 왼쪽 위)
  const insetPos = (() => {
    const corners = [
      { right: INSET_GAP, bottom: INSET_GAP },
      { left: INSET_GAP, bottom: INSET_GAP },
      { right: INSET_GAP, top: INSET_GAP },
      { left: INSET_GAP, top: INSET_GAP },
    ];
    const rect = (c) => {
      const x = c.left ?? stageW - INSET_W - c.right;
      const y = c.top ?? stageH - insetH - c.bottom;
      return { x, y };
    };
    const free = corners.find((c) => {
      const { x, y } = rect(c);
      return box.x + bw < x - 4 || box.x > x + INSET_W + 4 || box.y + bh < y - 4 || box.y > y + insetH + 4;
    });
    return free ?? corners[0];
  })();
  const refreshRecs = async () => {
    setRefreshing(true);
    await recs.reload();
    setRefreshing(false);
  };
  // 추천을 고르면 추천 초안의 질문·보기·정답·배율·확대 위치를 채우고, 탭은 그대로 둔 채 그 자리에서 고칠 수 있게 한다(다른 추천을 고르면 고치던 내용을 덮어쓴다). 직접 내기 초안은 건드리지 않는다
  const pickRec = (item) => {
    const d = recDraftFromItem(item);
    recDraft.setPhoto(d.photo);
    recDraft.setRatio(null);
    recDraft.setZoom(d.zoom);
    recDraft.setAsk(d.ask);
    recDraft.setQuestion(d.question);
    recDraft.setCount(d.count);
    recDraft.setOpts(d.opts);
    recDraft.setAnsIdx(d.ansIdx);
    recDraft.setWithNote(d.withNote);
    recDraft.setNote(d.note);
    recPlace.current = { x: d.photo.boxX, y: d.photo.boxY };
    const w = recDraft.stageW;
    const bwNew = w / d.zoom;
    recDraft.setBox({ x: Math.max(0, Math.min(w - bwNew, d.photo.boxX * w - bwNew / 2)), y: Math.max(0, Math.min(STAGE_H - STAGE_H / d.zoom, d.photo.boxY * STAGE_H - STAGE_H / d.zoom / 2)) }); // 사진 크기를 알기 전의 임시 자리
    setDragging(false);
    setSendError("");
    setPickedId(d.pickedId);
  };
  // 서버 사진이 뜨면 비율에 맞춰 추천이 알려 준 자리에 네모를 놓는다
  const onRecLoad = (event) => {
    const { width, height } = event?.source ?? {};
    if (!width || !height) return;
    setRatio(width / height);
    const place = recPlace.current;
    if (!place) return;
    recPlace.current = null;
    const h = stageW / (width / height);
    const w2 = stageW / zoom;
    const h2 = h / zoom;
    setBox({ x: Math.max(0, Math.min(stageW - w2, place.x * stageW - w2 / 2)), y: Math.max(0, Math.min(h - h2, place.y * h - h2 / 2)) });
  };
  const pickFromPhone = async () => {
    try {
      const res = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.8 });
      const asset = res.assets?.[0];
      if (!res.canceled && asset?.uri) {
        setPhoto({ kind: "phone", uri: asset.uri, asset });
        setRatio(asset.width && asset.height ? asset.width / asset.height : null);
        setBox({ x: 0, y: 0 });
      }
    } catch {
      // 사진을 못 불러와도 화면은 그대로 둔다
    }
  };
  const pickAsk = (k2) => {
    setAsk(k2);
    setQuestion(ASKS[k2]);
  };
  const [tried, setTried] = useState(false);
  const problem = mode === "rec" && pickedId == null
    ? "가비 추천에서 '이 문제로 쓰기'를 눌러 주세요"
    : live && !photoSendPartFor(mode, photo)
    ? "사진을 골라 주세요"
    : !question.trim()
    ? "질문을 써 주세요"
    : shown.some((o) => !o.trim())
      ? "보기를 모두 채워 주세요"
      : ansIdx == null
        ? "정답 보기를 골라 주세요"
        : null;

  const pickBlock = (
    <>
      <View style={styles.block}>
        {photo.kind === "album" ? <Text style={styles.label}>{`가족 앨범에서 고른 사진 · ${photo.name}`}</Text> : null}
        <View style={styles.row}>
          {live ? null : (
            <View style={styles.flex}>
              <Button label="가족 앨범에서 고르기" small variant="secondary" onPress={() => setAlbumOpen(true)} />
            </View>
          )}
          <View style={styles.flex}>
            <Button label="내 폰에서 올리기" small variant="secondary" onPress={pickFromPhone} />
          </View>
        </View>
      </View>
    </>
  );
  const stageBlock = (
    <>
      <View style={[styles.stage, { height: stageH }, photo.kind === "album" && { backgroundColor: photo.color }]} onLayout={(e) => setStageW(e.nativeEvent.layout.width)}>
        {photo.kind === "phone" ? <Image source={{ uri: photo.uri }} style={StyleSheet.absoluteFill} contentFit="cover" accessibilityLabel="올린 사진" /> : null}
        {photo.kind === "rec" ? <AuthImage path={photo.imageUrl} contentFit="cover" style={StyleSheet.absoluteFill} accessibilityLabel="추천 사진" onLoad={onRecLoad} /> : null}
        <View {...drag.panHandlers} style={[styles.box, { left: box.x, top: box.y, width: bw, height: bh }]} accessibilityLabel="보여 줄 부분. 끌어서 옮겨요" />
        <Text style={styles.stageNote}>네모를 끌어 보여줄 부분을 옮겨요</Text>
        <View pointerEvents="none" style={[styles.inset, insetPos, { width: INSET_W + 4, height: insetH + 4 }, photo.kind === "album" && { backgroundColor: photo.color }]} accessibilityLabel={`사진의 일부를 ${zoom}배 확대한 미리보기`}>
          <View style={{ width: INSET_W, height: insetH, overflow: "hidden", borderRadius: 8, backgroundColor: photo.kind === "album" ? photo.color : "#CDB9A3" }}>
            {photo.kind === "phone" ? <Image source={{ uri: photo.uri }} style={{ position: "absolute", width: stageW * k, height: stageH * k, left: -box.x * k, top: -box.y * k }} contentFit="cover" /> : null}
            {photo.kind === "rec" ? <AuthImage path={photo.imageUrl} contentFit="cover" style={{ position: "absolute", width: stageW * k, height: stageH * k, left: -box.x * k, top: -box.y * k }} /> : null}
            <Text style={styles.insetBadge}>{zoom}배 확대</Text>
          </View>
        </View>
      </View>
    </>
  );
  const zoomBlock = (
    <>
      <View style={styles.block}>
        <View style={styles.labelRow}>
          <Text style={styles.label}>확대 정도</Text>
          <Text style={[styles.sub, styles.flex]}>배율이 높을수록 사진이 흐려 보일 수 있어요</Text>
        </View>
        <View style={styles.row}>
          {ZOOMS.map((z) => (
            <Chip key={z} label={`${z}배`} on={zoom === z} onPress={() => pickZoom(z)} />
          ))}
        </View>
      </View>
    </>
  );
  const askBlock = (
    <>
      <View style={styles.block}>
        <Text style={styles.label}>무엇을 물어볼까요</Text>
        <View style={styles.row}>
          {Object.keys(ASKS).map((k) => (
            <Chip key={k} label={k} on={ask === k} onPress={() => pickAsk(k)} />
          ))}
        </View>
        <View style={styles.labelRow}>
          <Text style={styles.label}>질문</Text>
          <Text style={styles.sub}>
            ({question.length}/{Q_MAX})
          </Text>
        </View>
        <TextInput value={question} onChangeText={(v) => setQuestion(v.slice(0, Q_MAX))} maxLength={Q_MAX} style={styles.input} accessibilityLabel="질문" />
      </View>
    </>
  );
  const optsBlock = (
    <>
      <View style={styles.block}>
        <View style={styles.optHead}>
          <View style={styles.labelRow}>
            <Text style={styles.label}>보기</Text>
            <Text style={styles.sub}>눌러서 고칠 수 있어요</Text>
          </View>
          <View style={styles.stepper}>
            <Pressable onPress={() => changeCount(count - 1)} disabled={count <= 2} accessibilityRole="button" accessibilityLabel="보기 줄이기" style={[styles.stepBtn, count <= 2 && styles.stepOff]}>
              <Text style={styles.stepText}>−</Text>
            </Pressable>
            <Text style={styles.stepNum}>{count}</Text>
            <Pressable onPress={() => changeCount(count + 1)} disabled={count >= 4} accessibilityRole="button" accessibilityLabel="보기 늘리기" style={[styles.stepBtn, count >= 4 && styles.stepOff]}>
              <Text style={styles.stepText}>+</Text>
            </Pressable>
          </View>
        </View>
        {shown.map((o, i) => {
          const isAns = ansIdx === i;
          return (
            <View key={i} style={[styles.opt, isAns && styles.optAns2]}>
              <Pressable onPress={() => setAnsIdx(i)} accessibilityRole="button" accessibilityState={{ selected: isAns }} accessibilityLabel={isAns ? `보기 ${i + 1} 정답으로 표시됨` : `보기 ${i + 1} 정답으로 표시`} hitSlop={6} style={[styles.radio, isAns && styles.radioOn]}>
                {isAns ? <Text style={styles.radioMark}>✓</Text> : null}
              </Pressable>
              <TextInput value={o} onChangeText={(v) => setOpts((arr) => arr.map((x, j) => (j === i ? v.slice(0, 20) : x)))} placeholder={`보기 ${i + 1}`} placeholderTextColor={colors.placeholder} accessibilityLabel={`보기 ${i + 1}`} style={styles.optInput} />
            </View>
          );
        })}
      </View>
    </>
  );
  const noteBlock = (
    <>
      <View style={styles.block}>
        <View style={styles.noteRow}>
          <Text style={styles.noteLabel}>한마디 남기기 (선택)</Text>
          <Switch value={withNote} onValueChange={setWithNote} trackColor={{ false: "#E0D6CB", true: colors.success }} thumbColor="#FFFFFF" />
        </View>
        {withNote ? (
          <>
            <Text style={styles.sub}>{`그날 이야기나 언제·어디서·무엇을 했는지 적어요\n정답 공개될 때 같이 보여요 (${note.length}/${NOTE_MAX}자)`}</Text>
            <TextInput value={note} onChangeText={(v) => setNote(v.slice(0, NOTE_MAX))} multiline numberOfLines={3} placeholder="남기고 싶은 말을 써보세요" placeholderTextColor={colors.placeholder} style={[styles.input, styles.area]} accessibilityLabel="한마디" />
          </>
        ) : null}
      </View>
    </>
  );

  // 고른 카드가 아닌 다른 카드를 보는 동안에도 고치던 내용은 초안에 그대로 있다(수정 화면은 고른 카드에서만 보인다)
  const recItems = photoRecView(recs.error && !recs.data ? { state: "failed" } : recs.data).items;
  const recAt = Math.min(recIndex, Math.max(recItems.length - 1, 0));
  const pickedAt = pickedId == null ? -1 : recItems.findIndex((r) => r.id === pickedId);
  const viewingPicked = recItems[recAt]?.id === pickedId;
  const hiddenEditing = pickedId != null && !viewingPicked;
  const goPicked = () => {
    if (pickedAt < 0) return;
    setDragging(false);
    setRecIndex(pickedAt);
  };

  return (
    <PlayScreen
      title="찰칵! 탐정단 문제 내기"
      footerInScroll
      close
      scrollEnabled={!dragging}
      footer={
        <>
          {sendError || (tried && problem) ? (
            <Text style={styles.error} accessibilityRole="alert">
              {sendError || problem}
            </Text>
          ) : (
            <RevealNote>내일 오후 2:10에 정답이 공개돼요, 모두 답하면 바로 열려요</RevealNote>
          )}
          <MakeQuotaNote />
          <Button
            label="사진 문제 보내기"
            disabled={sending}
            onPress={async () => {
              if (problem) {
                setTried(true);
                return;
              }
              if (live) {
                setSending(true);
                setSendError("");
                try {
                  const item = await createPhoto({
                    ...photoSendPartFor(mode, photo), // 추천 탭의 추천 카드면 recId 만, 직접 내기 탭의 내 폰 사진이면 파일과 source 2 만
                    zoom,
                    boxX: (box.x + bw / 2) / stageW, // 네모의 가운데를 사진 전체에서의 위치(0~1)로
                    boxY: (box.y + bh / 2) / stageH,
                    question: question.trim(),
                    options: shown.map((o) => o.trim()),
                    answerIndex: ansIdx,
                    comment: withNote ? note.trim() : "",
                    playerIds: target,
                  });
                  router.replace(`/play/sent-detail?id=${item.id}&kind=photo`);
                } catch (e) {
                  if (isRecUnavailable(e)) {
                    setSendError(REC_UNAVAILABLE_NOTE);
                    recPlace.current = null;
                    recDraft.setPhoto(EMPTY_REC_PHOTO);
                    setPickedId(null);
                    setMode("rec");
                    refreshRecs();
                  } else {
                    setSendError(e.message || "보내지 못했어요. 잠시 뒤 다시 해 주세요");
                  }
                } finally {
                  setSending(false);
                }
                return;
              }
              recordMade();
              // 맞히는 화면에 방식과 보기를 넘긴다(정답 위치는 출제자가 고른 그대로)
              const options = shown.map((o) => o.trim());
              router.replace({ pathname: "/play/photo-guess", params: { question: question.trim(), options: JSON.stringify(options) } });
            }}
          />
        </>
      }
    >
      <Toggle
        value={mode}
        onChange={(m) => {
          setDragging(false); // 네모를 끌던 중 탭을 옮겨도 화면 스크롤 잠금이 남지 않게
          setMode(m);
        }}
        options={[
          { key: "rec", label: "가비 추천" },
          { key: "manual", label: "직접 내기" },
        ]}
      />
      {mode === "rec" ? (
        <>
          <PhotoRecommend
            recs={recs}
            index={recIndex}
            onIndex={(i) => {
              setDragging(false); // 네모를 끌던 중 카드를 넘겨도 화면 스크롤 잠금이 남지 않게
              setRecIndex(i);
            }}
            pickedId={pickedId}
            onPick={pickRec}
            refreshing={refreshing}
            onRefresh={refreshRecs}
            editor={
              <>
                {stageBlock}
                {zoomBlock}
              </>
            }
          />
          {hiddenEditing ? (
            <Pressable onPress={goPicked} disabled={pickedAt < 0} accessibilityRole="button" accessibilityLabel="고치던 문제로 돌아가기" style={styles.editingBar}>
              <Text style={styles.editingText}>고치던 문제로 돌아가기</Text>
            </Pressable>
          ) : null}
          {pickedId != null ? (
            <>
              {askBlock}
              {optsBlock}
              {noteBlock}
            </>
          ) : null}
        </>
      ) : (
        <>
          {pickBlock}
          {stageBlock}
          {zoomBlock}
          {askBlock}
          {optsBlock}
          {noteBlock}
        </>
      )}
      <AudiencePicker value={target} onChange={setTarget} />

      <BottomSheet visible={albumOpen} title="가족 앨범" onClose={() => setAlbumOpen(false)}>
        <View style={styles.grid}>
          {ALBUM.map((a) => (
            <Pressable
              key={a.id}
              onPress={() => {
                setPhoto({ kind: "album", ...a });
                setAlbumOpen(false);
              }}
              accessibilityRole="button"
              accessibilityLabel={`${a.name} 사진 고르기`}
              style={[styles.tile, { backgroundColor: a.color }, photo.id === a.id && styles.tileOn]}
            >
              <Text style={styles.tileName}>{a.name}</Text>
            </Pressable>
          ))}
        </View>
      </BottomSheet>
    </PlayScreen>
  );
}

/** 고치는 칸 한 벌의 상태: 사진, 사진 비율, 배율, 질문 종류·질문, 보기, 정답, 한마디, 네모 위치, 사진 칸 너비 */
function useDraft(initialPhoto) {
  const [photo, setPhoto] = useState(initialPhoto);
  const [ratio, setRatio] = useState(null); // 고른 사진의 가로÷세로(서버 사진과 같은 비율로 네모 위치를 잡는다)
  const [zoom, setZoom] = useState(4);
  const [ask, setAsk] = useState("어디서");
  const [question, setQuestion] = useState(ASKS["어디서"]);
  const [count, setCount] = useState(4); // 선택식 보기 수(2~4개)
  const [opts, setOpts] = useState(["제주도 여행", "할머니 댁", "강릉 바다", "우리 집 거실"]);
  const [ansIdx, setAnsIdx] = useState(0); // 몇 번째 보기가 정답인지
  const [withNote, setWithNote] = useState(true);
  const [note, setNote] = useState("");
  const [box, setBox] = useState({ x: 130, y: 80 });
  const [stageW, setStageW] = useState(350); // 탭마다 사진 칸 너비가 달라(추천은 카드 안) 네모 위치(픽셀)와 함께 따로 둔다
  return { photo, setPhoto, ratio, setRatio, zoom, setZoom, ask, setAsk, question, setQuestion, count, setCount, opts, setOpts, ansIdx, setAnsIdx, withNote, setWithNote, note, setNote, box, setBox, stageW, setStageW };
}

/** 아래에서 올라오는 시트. 바깥 어두운 부분을 누르면 닫힌다. */
function BottomSheet({ visible, title, onClose, children }) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.sheetWrap}>
        <Pressable style={styles.backdrop} onPress={onClose} accessibilityRole="button" accessibilityLabel={`${title} 닫기`} />
        <SafeAreaView edges={["bottom"]} style={styles.sheet}>
          <View style={styles.modalHead}>
            <Text style={styles.modalTitle}>{title}</Text>
            <Pressable onPress={onClose} accessibilityRole="button" accessibilityLabel="닫기" style={styles.modalClose}>
              <Text style={styles.modalCloseText}>닫기</Text>
            </Pressable>
          </View>
          {children}
        </SafeAreaView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  editingBar: { alignSelf: "stretch", paddingVertical: 10, paddingHorizontal: 14, borderRadius: 12, backgroundColor: colors.surfaceStrong, alignItems: "center" },
  editingText: { fontSize: 14, fontFamily: fonts.bold, color: colors.text },
  error: { ...font.caption, color: colors.danger, textAlign: "center", fontFamily: fonts.bold },
  block: { gap: 8 },
  row: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  label: { ...font.bodyStrong, color: colors.text },
  sub: { fontSize: 13, lineHeight: 20, fontFamily: fonts.regular, color: colors.textSub },
  stage: { minHeight: STAGE_H, borderRadius: radius.card, backgroundColor: "#CDB9A3", overflow: "hidden" },
  labelRow: { flexDirection: "row", alignItems: "baseline", gap: 8 },
  inset: { position: "absolute", padding: 2, borderRadius: 10, backgroundColor: colors.background },
  insetBadge: { position: "absolute", left: 6, top: 6, paddingVertical: 2, paddingHorizontal: 7, borderRadius: 999, overflow: "hidden", backgroundColor: colors.background, fontSize: 11, fontFamily: fonts.bold, color: colors.text },
  box: { position: "absolute", borderWidth: 3, borderColor: colors.background, borderRadius: 10, backgroundColor: "rgba(255,252,247,0.25)" },
  stageNote: { position: "absolute", left: 0, right: 0, top: 12, textAlign: "center", fontSize: 13, color: "#3A2719" },
  input: { height: 44, paddingVertical: 0, paddingHorizontal: 14, borderRadius: 12, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, color: colors.text, fontSize: 15, lineHeight: 20, includeFontPadding: false, fontFamily: fonts.regular },
  optHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  stepper: { flexDirection: "row", alignItems: "center", gap: 6 },
  stepBtn: { width: 32, height: 32, borderRadius: 16, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, alignItems: "center", justifyContent: "center" },
  stepOff: { opacity: 0.35 },
  stepText: { fontSize: 18, lineHeight: 22, fontFamily: fonts.bold, color: colors.text },
  stepNum: { minWidth: 20, textAlign: "center", fontSize: 16, fontFamily: fonts.bold, color: colors.text },
  opt: { height: 48, paddingLeft: 10, paddingRight: 10, borderRadius: 12, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, flexDirection: "row", alignItems: "center", gap: 8 },
  optAns2: { backgroundColor: "#F2F8F4", borderColor: colors.success },
  radio: { width: 26, height: 26, borderRadius: 13, borderWidth: 1.5, borderColor: "#D9C7B4", alignItems: "center", justifyContent: "center" },
  radioOn: { backgroundColor: colors.success, borderColor: colors.success },
  radioMark: { fontSize: 14, lineHeight: 18, color: "#FFFFFF", fontFamily: fonts.bold },
  optInput: { flex: 1, height: 44, paddingVertical: 0, fontSize: 15, lineHeight: 20, includeFontPadding: false, fontFamily: fonts.regular, color: colors.text },
  area: { height: 88, paddingTop: 10, textAlignVertical: "top" },
  noteRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 44 },
  noteLabel: { ...font.body, color: colors.text },
  sheetWrap: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(58,39,25,0.4)" }, // 바깥을 누르면 닫힌다
  sheet: { padding: 20, gap: 16, borderTopLeftRadius: 24, borderTopRightRadius: 24, backgroundColor: colors.background },
  modalHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  modalTitle: { ...font.title, color: colors.text },
  modalClose: { minHeight: 44, justifyContent: "center", paddingHorizontal: 8 },
  modalCloseText: { fontSize: 15, fontFamily: fonts.bold, color: colors.text },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  tile: { width: "31%", flexGrow: 1, height: 110, borderRadius: radius.lg, justifyContent: "flex-end", padding: 10, borderWidth: 2, borderColor: "transparent" },
  tileOn: { borderColor: colors.dark },
  tileName: { fontSize: 13, fontFamily: fonts.bold, color: "#3A2719" },
});
