import { useMemo, useRef, useState } from "react";
import { PanResponder, StyleSheet, View } from "react-native";
import Svg, { Path, Rect } from "react-native-svg";

import { colors, radius } from "@/theme";

const toPath = (pts) => pts.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");

/**
 * 손가락으로 그리는 그림판. strokes 는 부모가 들고 있다(취소/지우개 버튼이 부모에 있어서).
 * @param {{ strokes: {color:string,pts:{x:number,y:number}[]}[], onChange: (s:any[])=>void, color: string, eraser?: boolean, height?: number }} props
 */
export default function DrawingCanvas({ strokes, onChange, color, eraser = false, height = 280, onTouching, svgRef }) {
  const ref = useRef({ strokes, color, eraser });
  ref.current = { strokes, color, eraser, onTouching };
  const [live, setLive] = useState(null);
  const cur = useRef(null); // 지금 긋는 선(손을 뗄 때 부모에 넘기려고 상태와 따로 들고 있는다)
  const origin = useRef({ x: 0, y: 0 }); // 터치를 시작한 점. 이후 좌표는 여기에 손가락이 움직인 거리(dx, dy)를 더해 구한다

  const responder = useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onMoveShouldSetPanResponder: () => true,
        onPanResponderTerminationRequest: () => false, // 그리는 중에는 스크롤이 제스처를 가져가지 못하게
        onPanResponderGrant: (e) => {
          ref.current.onTouching?.(true);
          const { locationX: x, locationY: y } = e.nativeEvent;
          origin.current = { x, y };
          const c = ref.current.eraser ? colors.card : ref.current.color; // 지우개는 바탕색으로 덮는다
          cur.current = { color: c, width: ref.current.eraser ? 18 : 4, pts: [{ x, y }] };
          setLive(cur.current);
        },
        onPanResponderMove: (_, g) => {
          // locationX/Y 는 손가락 밑의 가장 안쪽 요소 기준이라 가장자리·선 위를 지나면 기준이 바뀌어 튄다 → 시작점 + 이동 거리로 구한다
          if (!cur.current) return;
          const p = { x: origin.current.x + g.dx, y: origin.current.y + g.dy };
          cur.current = { ...cur.current, pts: [...cur.current.pts, p] };
          setLive(cur.current);
        },
        onPanResponderTerminate: () => {
          ref.current.onTouching?.(false);
          cur.current = null;
          setLive(null);
        },
        onPanResponderRelease: () => {
          ref.current.onTouching?.(false);
          const done = cur.current;
          cur.current = null;
          setLive(null);
          if (done) onChange([...ref.current.strokes, done]); // 상태 갱신 함수 안에서 부모를 바꾸면 React 경고가 난다 → 밖에서 부른다
        },
      }),
    [onChange],
  );

  const all = live ? [...strokes, live] : strokes;
  return (
    <View style={[styles.box, { height }]} {...responder.panHandlers} accessibilityLabel="그림판. 손가락으로 그려요">
      <Svg ref={svgRef} width="100%" height="100%" pointerEvents="none">
        <Rect width="100%" height="100%" fill={colors.card} />
        {all.map((s, i) => (
          <Path key={i} d={toPath(s.pts)} stroke={s.color} strokeWidth={s.width ?? 4} strokeLinecap="round" strokeLinejoin="round" fill="none" />
        ))}
      </Svg>
    </View>
  );
}

const styles = StyleSheet.create({
  box: { borderRadius: radius.card, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, overflow: "hidden" },
});
