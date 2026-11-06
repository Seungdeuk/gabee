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

  const responder = useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onMoveShouldSetPanResponder: () => true,
        onPanResponderTerminationRequest: () => false, // 그리는 중에는 스크롤이 제스처를 가져가지 못하게
        onPanResponderGrant: (e) => {
          ref.current.onTouching?.(true);
          const { locationX: x, locationY: y } = e.nativeEvent;
          const c = ref.current.eraser ? colors.card : ref.current.color; // 지우개는 바탕색으로 덮는다
          setLive({ color: c, width: ref.current.eraser ? 18 : 4, pts: [{ x, y }] });
        },
        onPanResponderMove: (e) => {
          const { locationX: x, locationY: y } = e.nativeEvent;
          setLive((s) => (s ? { ...s, pts: [...s.pts, { x, y }] } : s));
        },
        onPanResponderTerminate: () => {
          ref.current.onTouching?.(false);
          setLive(null);
        },
        onPanResponderRelease: () => {
          ref.current.onTouching?.(false);
          setLive((s) => {
            if (s) onChange([...ref.current.strokes, s]);
            return null;
          });
        },
      }),
    [onChange],
  );

  const all = live ? [...strokes, live] : strokes;
  return (
    <View style={[styles.box, { height }]} {...responder.panHandlers} accessibilityLabel="그림판. 손가락으로 그려요">
      <Svg ref={svgRef} width="100%" height="100%">
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
