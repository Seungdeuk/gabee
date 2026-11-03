import Svg, { Path } from "react-native-svg";

import { colors } from "@/theme";

/**
 * 시안의 빈 연필(대각선 외곽선) 아이콘. 데일리 체크의 "편집"과 항목별 수정 버튼에 같이 쓴다.
 * @param {{ size?: number, color?: string }} props
 */
export default function PencilIcon({ size = 18, color = colors.text }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <Path d="M4 20h4L19 9l-4-4L4 16z" />
      {/* 뒤끝(오른쪽 위 지우개 띠)만 채운다. 앞 심은 외곽선만. */}
      <Path d="M15 5l4 4-2.5 2.5-4-4z" fill={color} stroke={color} strokeWidth={1.5} strokeLinejoin="round" />
    </Svg>
  );
}
