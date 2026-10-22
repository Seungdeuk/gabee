import Tag from "@/shared/components/Tag";

import { TAG_LABEL } from "../format";

/**
 * 지출에 걸린 정산 대상 태그 표시. 정산하는 사람이 직접 고른(custom) 지출은 색과 연필 표시로 고정 태그와 구분한다.
 * @param {{ tag: "parents" | "children" | "all" | "custom" }} props
 */
export default function TagBadge({ tag }) {
  if (tag === "custom") return <Tag label={`✎ ${TAG_LABEL.custom}`} tone="orange" />;
  return <Tag label={TAG_LABEL[tag] ?? tag} tone="gray" />;
}
