// 시험용 alias 훅이 디렉터리 index 를 찾지 못해 index 까지 적는다
import { avatarPalette } from "@/theme/index";

/**
 * 사용자 id(없으면 이름)로 항상 같은 아바타 색을 고른다.
 * @param {string | number | null | undefined} key 사용자 id 또는 이름
 * @returns {{ backgroundColor: string, color: string }} 팔레트의 한 칸. 키가 비면 첫 칸
 */
export default function avatarTone(key) {
  const text = String(key ?? "").trim();
  if (!text) return avatarPalette[0];
  let h = 5381;
  for (const ch of text) h = (Math.imul(h, 33) + ch.codePointAt(0)) >>> 0;
  return avatarPalette[h % avatarPalette.length];
}
