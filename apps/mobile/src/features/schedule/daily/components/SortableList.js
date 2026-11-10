import { useRef, useState } from "react";
import { PanResponder, StyleSheet, View } from "react-native";

import { colors } from "@/theme";

import { HOLD_CANCEL_PX, ROW_MENU_HOLD_MS, dragTargetIndex, holdDecision, shiftOffset } from "../logic";

/**
 * 끌어서 순서를 바꾸는 세로 목록(가족 순서 바꾸기 화면, 내 항목 편집 화면). 줄 높이(rowHeight)와 간격(gap)은 고정이다.
 * 구현: React Native 기본 PanResponder(gesture-handler 를 쓰지 않는다). 줄마다 responder 하나.
 * 호출 순서와 상태 전이:
 *   1) onPanResponderGrant(손가락이 줄에 닿음): 꾹 누름 타이머(ROW_MENU_HOLD_MS)를 건다. 아직 armed 아님.
 *   2) onPanResponderMove, armed 전: holdDecision 이 "fail"(취소 거리 HOLD_CANCEL_PX 넘게 움직임)이면 타이머를 지우고
 *      responder 를 놓는다. 이때 onPanResponderTerminationRequest 가 true 라서 ScrollView 가 스크롤을 받는다.
 *   3) 타이머 발사(armed): setDrag 로 줄을 들어 올리고, onDragActive(true) 로 바깥 ScrollView 를 scrollEnabled=false 로 잠근다.
 *      잠금은 화면 상태 반영이므로 손가락이 실제로 움직이기 전에 끝난다(타이머 450ms 뒤).
 *   4) onPanResponderMove, armed 후: g.dy(시작점부터 이동량)로 dragTargetIndex 를 계산해 줄을 따라 translateY 로 옮긴다.
 *      armed 후에는 onPanResponderTerminationRequest 가 false 라서 responder 를 빼앗기지 않는다.
 *   5) onPanResponderRelease / onPanResponderTerminate: 타이머를 지우고, armed 였다면 onDragActive(false) 로 스크롤을 풀고
 *      처음 자리와 놓은 자리가 다르면 onReorder(from, to) 한 번 호출(저장은 부모가 한다).
 * 줄의 왼쪽 화살표·연필·휴지통·눈 버튼은 자식 Pressable 이 responder 를 먼저 잡으므로 드래그 시작이 되지 않는다.
 * @param {{ data: { id: string }[], rowHeight: number, gap: number,
 *   renderRow: (item: object, index: number) => import("react").ReactNode,
 *   onReorder: (from: number, to: number) => void, onDragActive?: (active: boolean) => void }} props
 */
export default function SortableList({ data, rowHeight, gap, renderRow, onReorder, onDragActive }) {
  const stride = rowHeight + gap;
  const [drag, setDrag] = useState(null); // { index, dy, to }
  const dragRef = useRef(null);
  // responder 콜백은 한 번 만들어지므로 최신 값은 ref 로 읽는다.
  const latest = useRef({});
  latest.current = { count: data.length, stride, onReorder, onDragActive };

  const commit = (next) => {
    dragRef.current = next;
    setDrag(next);
  };

  // 줄마다 responder 를 한 번만 만든다(자리 index 별). 매 렌더마다 새로 만들면 잡은 터치가 끊긴다.
  const respondersRef = useRef(new Map());
  const responderFor = (index) => {
    let r = respondersRef.current.get(index);
    if (!r) {
      let armed = false;
      let timer = null;
      const clearTimer = () => {
        if (timer) clearTimeout(timer);
        timer = null;
      };
      const finish = () => {
        clearTimer();
        const wasArmed = armed;
        armed = false;
        const current = dragRef.current;
        if (!wasArmed) return;
        commit(null);
        latest.current.onDragActive?.(false);
        if (current && current.to !== current.index) latest.current.onReorder(current.index, current.to);
      };
      r = PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        // 꾹 누르기 전에는 움직임이 생기면 responder 를 내줘서 스크롤이 받게 한다. 꾹 누른 뒤에는 내주지 않는다.
        onPanResponderTerminationRequest: () => !armed,
        onPanResponderGrant: () => {
          armed = false;
          clearTimer();
          timer = setTimeout(() => {
            timer = null;
            armed = true;
            commit({ index, dy: 0, to: index });
            latest.current.onDragActive?.(true);
          }, ROW_MENU_HOLD_MS);
        },
        onPanResponderMove: (_e, g) => {
          const decision = holdDecision({ armed, moved: Math.hypot(g.dx, g.dy), cancelPx: HOLD_CANCEL_PX });
          if (!armed) {
            // 꾹 누르기 전에 움직였으면 취소: 타이머를 지우고 스크롤에 양보한다
            if (decision === "fail") clearTimer();
            return;
          }
          const to = dragTargetIndex(index, g.dy, latest.current.stride, latest.current.count);
          commit({ index, dy: g.dy, to });
        },
        onPanResponderRelease: finish,
        onPanResponderTerminate: finish,
      });
      respondersRef.current.set(index, r);
    }
    return r;
  };

  return (
    <View>
      {data.map((item, index) => {
        const dragging = drag?.index === index;
        const offset = dragging ? drag.dy : drag ? shiftOffset(index, drag.index, drag.to, stride) : 0;
        return (
          <View
            key={item.id}
            style={[
              styles.slot,
              { height: rowHeight, marginBottom: gap, transform: [{ translateY: offset }, { scale: dragging ? 1.02 : 1 }] },
              dragging && styles.lifted,
            ]}
          >
            <View style={styles.fill} {...responderFor(index).panHandlers}>
              {renderRow(item, index)}
            </View>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  slot: { zIndex: 0 },
  lifted: {
    zIndex: 10,
    elevation: 6,
    shadowColor: colors.text,
    shadowOpacity: 0.15,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 6 },
  },
  fill: { flex: 1 },
});
