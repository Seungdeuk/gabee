import Svg, { Path } from "react-native-svg";

import { colors } from "@/theme";

/**
 * 메모 아이콘(시안 2-3): 종이 한 장과 줄 두 개. 습관 이름 옆에 쓴다.
 * @param {{ size?: number, color?: string }} props
 */
export default function MemoIcon({ size = 16, color = colors.textMuted }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <Path d="M6 4h12a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z" />
      <Path d="M9 9h6M9 13h4" />
    </Svg>
  );
}
