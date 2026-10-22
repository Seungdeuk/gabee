// 시험 전용: 앱 코드의 "@/..." 경로(jsconfig 의 별칭)와 확장자 없는 상대 경로를 Node 가 찾게 한다.
import { pathToFileURL } from "node:url";
import path from "node:path";

const SRC = path.resolve(import.meta.dirname, "../src");

export async function resolve(specifier, context, nextResolve) {
  if (specifier.startsWith("@/")) {
    let target = path.join(SRC, specifier.slice(2));
    if (!path.extname(target)) target += ".js";
    return nextResolve(pathToFileURL(target).href, context);
  }
  if (specifier.startsWith(".") && !path.extname(specifier)) {
    return nextResolve(`${specifier}.js`, context); // 앱 코드의 확장자 없는 상대 경로
  }
  return nextResolve(specifier, context);
}
