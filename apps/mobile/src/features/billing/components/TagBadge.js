import Tag from "@/shared/components/Tag";

import { TAG_LABEL } from "../format";

/**
 * 지출의 정산 상태 표시. 정산하기를 누르기 전에는 "미정산", 누른 뒤에는 대상 태그를 보여 준다.
 * 정산하는 사람이 직접 고른(custom) 지출은 색과 연필 표시로 고정 태그와 구분한다.
 * @param {{ tag: "parents" | "children" | "all" | "custom", settled: boolean }} props
 */
export default function TagBadge({ tag, settled }) {
  if (!settled) return <Tag label="미정산" tone="gray" />;
  if (tag === "custom") return <Tag label={`✎ ${TAG_LABEL.custom}`} tone="orange" />;
  return <Tag label={TAG_LABEL[tag] ?? tag} tone="blue" />;
}
