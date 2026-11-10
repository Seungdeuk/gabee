import { Image } from "expo-image";
import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import Animated, { cancelAnimation, useAnimatedStyle, useSharedValue, withDecay, withTiming } from "react-native-reanimated";

import { clampPan, clampPinchScale, clampScale, doubleTapScale, fittedSize, maxPan, MIN_SCALE, zoomAround } from "../zoomMath";

/**
 * 폰 갤러리처럼 손가락으로 확대해서 보는 사진 한 장.
 * - 두 손가락: 손가락 사이 지점을 기준으로 확대·축소(1배~5배)하고, 벌린 채로 움직이면 사진도 따라온다.
 * - 한 손가락: 확대한 사진을 끌어 옮기고, 튕기듯 놓으면 관성으로 더 움직인다. 사진 가장자리가 화면 안으로 들어오지는 않는다.
 * - 두 번 누르기: 누른 곳을 중심으로 2.5배, 다시 누르면 원래 크기.
 *
 * 안드로이드의 ScrollView 는 핀치 확대가 없어서(iOS 만 된다) 제스처 핸들러로 직접 만들었다.
 * 제스처는 움직이지 않는 바깥 뷰에 붙인다(움직이는 사진에 붙이면 손가락 좌표가 변형돼 어긋난다).
 * 부모가 GestureHandlerRootView 안에 있어야 한다(Modal 안에서는 Modal 안쪽에 둔다).
 * @param {{ source: { uri: string, headers?: Record<string, string> }, label?: string }} props source 는 expo-image 의 source, label 은 접근성 이름·실패 안내에 쓴다
 */
export default function ZoomableImage({ source, label = "사진" }) {
  const [failed, setFailed] = useState(false);
  const viewWidth = useSharedValue(0);
  const viewHeight = useSharedValue(0);
  const ratio = useSharedValue(0); // 사진의 가로÷세로(불러오면 채운다)
  const scale = useSharedValue(1);
  const x = useSharedValue(0);
  const y = useSharedValue(0);
  const lastPinch = useSharedValue(1);
  const lastPanX = useSharedValue(0);
  const lastPanY = useSharedValue(0);
  const pinched = useSharedValue(false); // 이번 터치에 핀치를 했는지(했으면 놓을 때 관성을 주지 않는다)

  /** 지금 이동 값을 주어진 배율의 범위 안으로 맞춘 [x, y]. */
  const clamped = (nextX, nextY, atScale) => {
    "worklet";
    const fit = fittedSize(viewWidth.value, viewHeight.value, ratio.value);
    return [clampPan(nextX, fit.width, viewWidth.value, atScale), clampPan(nextY, fit.height, viewHeight.value, atScale)];
  };

  const pinch = Gesture.Pinch()
    .onStart(() => {
      lastPinch.value = 1;
      pinched.value = true;
      cancelAnimation(scale);
    })
    .onUpdate((e) => {
      if (!(e.scale > 0)) return;
      const next = clampPinchScale(scale.value * (e.scale / lastPinch.value));
      lastPinch.value = e.scale;
      // 손가락 사이 지점이 그 자리에 머물게 옮긴다. 손가락이 움직인 거리는 아래 드래그가 더한다.
      const [nextX, nextY] = clamped(
        zoomAround(x.value, e.focalX - viewWidth.value / 2, scale.value, next),
        zoomAround(y.value, e.focalY - viewHeight.value / 2, scale.value, next),
        next,
      );
      x.value = nextX;
      y.value = nextY;
      scale.value = next;
    })
    .onEnd(() => {
      const target = clampScale(scale.value);
      const [nextX, nextY] = clamped(x.value, y.value, target);
      if (target !== scale.value) scale.value = withTiming(target);
      if (nextX !== x.value) x.value = withTiming(nextX);
      if (nextY !== y.value) y.value = withTiming(nextY);
    });

  // 손가락 수가 바뀌어도(두 손가락 → 한 손가락) 끊기지 않게 지난번과의 차이만큼만 더한다
  const pan = Gesture.Pan()
    .averageTouches(true)
    .onBegin(() => {
      pinched.value = false;
      cancelAnimation(x);
      cancelAnimation(y);
    })
    .onStart((e) => {
      lastPanX.value = e.translationX;
      lastPanY.value = e.translationY;
    })
    .onUpdate((e) => {
      const [nextX, nextY] = clamped(x.value + e.translationX - lastPanX.value, y.value + e.translationY - lastPanY.value, scale.value);
      lastPanX.value = e.translationX;
      lastPanY.value = e.translationY;
      x.value = nextX;
      y.value = nextY;
    })
    .onEnd((e, success) => {
      if (!success || pinched.value) return;
      const fit = fittedSize(viewWidth.value, viewHeight.value, ratio.value);
      const limitX = maxPan(fit.width, viewWidth.value, scale.value);
      const limitY = maxPan(fit.height, viewHeight.value, scale.value);
      if (limitX > 0) x.value = withDecay({ velocity: e.velocityX, clamp: [-limitX, limitX] });
      if (limitY > 0) y.value = withDecay({ velocity: e.velocityY, clamp: [-limitY, limitY] });
    });

  const doubleTap = Gesture.Tap()
    .numberOfTaps(2)
    .maxDistance(24)
    .onEnd((e, success) => {
      if (!success) return;
      const next = doubleTapScale(scale.value);
      const [nextX, nextY] =
        next === MIN_SCALE
          ? [0, 0]
          : clamped(zoomAround(x.value, e.x - viewWidth.value / 2, scale.value, next), zoomAround(y.value, e.y - viewHeight.value / 2, scale.value, next), next);
      scale.value = withTiming(next);
      x.value = withTiming(nextX);
      y.value = withTiming(nextY);
    });

  // Race: 손가락이 움직이는 순간 드래그·핀치가 바로 시작되고 두 번 누르기는 취소된다.
  // (Exclusive 로 묶으면 두 번 누르기가 실패할 때까지 핀치·드래그가 시작되지 못해 빠른 동작이 씹힌다)
  const gesture = Gesture.Race(doubleTap, Gesture.Simultaneous(pinch, pan));

  const animated = useAnimatedStyle(() => ({
    transform: [{ translateX: x.value }, { translateY: y.value }, { scale: scale.value }],
  }));

  if (failed) {
    return (
      <View style={styles.box}>
        <Text style={styles.message}>{label}을(를) 불러오지 못했어요.</Text>
      </View>
    );
  }
  return (
    <GestureDetector gesture={gesture}>
      <View
        style={styles.box}
        collapsable={false}
        onLayout={(e) => {
          viewWidth.value = e.nativeEvent.layout.width;
          viewHeight.value = e.nativeEvent.layout.height;
        }}
      >
        <Animated.View style={[styles.fill, animated]}>
          <Image
            source={source}
            style={styles.fill}
            contentFit="contain"
            onLoad={(e) => {
              if (e?.source?.width && e?.source?.height) ratio.value = e.source.width / e.source.height;
            }}
            onError={() => setFailed(true)}
            accessibilityLabel={label}
          />
        </Animated.View>
      </View>
    </GestureDetector>
  );
}

const styles = StyleSheet.create({
  box: { flex: 1, overflow: "hidden", alignItems: "center", justifyContent: "center" },
  fill: { width: "100%", height: "100%" },
  message: { color: "#fff", fontSize: 15, textAlign: "center", lineHeight: 24, padding: 24 },
});
