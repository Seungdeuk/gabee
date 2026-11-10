import Svg, { Path, Rect } from "react-native-svg";

import { colors } from "@/theme";

/**
 * 달력 아이콘(시안 2-3 오른쪽 끝): 날짜 줄에서 다른 날짜를 고르는 시트를 연다.
 * @param {{ size?: number, color?: string }} props
 */
export default function CalendarIcon({ size = 22, color = colors.text }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round">
      <Rect x={4} y={5} width={16} height={15} rx={2.5} />
      <Path d="M4 10h16M8 3v4M16 3v4" />
    </Svg>
  );
}
