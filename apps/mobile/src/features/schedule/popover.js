// 칩 곁에 딱 붙어 뜨는 말풍선·삭제 버튼의 위치 계산(순수 함수라 node 테스트로 시험한다).

export const POPOVER_MARGIN = 8; // 화면 가장자리에서 띄우는 최소 간격

const clamp = (value, min, max) => Math.min(Math.max(value, min), Math.max(min, max));

/**
 * 말풍선(left/top)을 윈도우 좌표로 계산한다. 칩 테두리에 틈 없이 붙는다.
 * - "above"/"below": 칩 위/아래에 붙고 가로는 칩 가운데에 맞춘다(화면 밖이면 안쪽으로 민다). 자리가 없으면 반대쪽으로 뒤집는다.
 * - "right": 칩 오른쪽 테두리에 붙고 위쪽을 칩과 맞춘다. 오른쪽에 자리가 없으면 왼쪽, 그것도 없으면 아래로 간다.
 * 키보드가 올라와 있으면 keyboardTop 위까지만 쓴다.
 * @param {{ anchor: { x: number, y: number, width: number, height: number }, width: number, height: number,
 *   screenWidth: number, screenHeight: number, placement?: "above" | "below" | "right", keyboardTop?: number | null }} args
 * @returns {{ left: number, top: number, placement: "above" | "below" | "right" | "left" }}
 */
export function popoverPosition({ anchor, width, height, screenWidth, screenHeight, placement = "below", keyboardTop = null }) {
  const limit = (keyboardTop ?? screenHeight) - POPOVER_MARGIN;
  const fitTop = (top) => clamp(top, POPOVER_MARGIN, limit - height);

  if (placement === "right") {
    const rightLeft = anchor.x + anchor.width;
    if (rightLeft + width <= screenWidth - POPOVER_MARGIN) return { left: rightLeft, top: fitTop(anchor.y), placement: "right" };
    const leftLeft = anchor.x - width;
    if (leftLeft >= POPOVER_MARGIN) return { left: leftLeft, top: fitTop(anchor.y), placement: "left" };
    return popoverPosition({ anchor, width, height, screenWidth, screenHeight, placement: "below", keyboardTop });
  }

  const left = clamp(anchor.x + anchor.width / 2 - width / 2, POPOVER_MARGIN, screenWidth - width - POPOVER_MARGIN);
  const belowTop = anchor.y + anchor.height;
  const aboveTop = anchor.y - height;
  const fitsBelow = belowTop + height <= limit;
  const fitsAbove = aboveTop >= POPOVER_MARGIN;

  let side = placement;
  if (placement === "below" && !fitsBelow && fitsAbove) side = "above";
  if (placement === "above" && !fitsAbove && fitsBelow) side = "below";
  return { left, top: fitTop(side === "above" ? aboveTop : belowTop), placement: side };
}
