import { useFocusEffect } from "expo-router";
import { useCallback, useRef, useState } from "react";

import { listLinks } from "./api";
import { todoOrigins } from "./linkUtils";

/**
 * 가족 할 일 중 대화에서 등록한 것의 원본 메시지 id 를 모은다(할 일 id → 메시지 id). 가족 전체방의 연결 목록에서 할 일 종류만 쓴다.
 * 화면이 보일 때마다 다시 불러오고, 실패하면 조용히 비워 둔다(원본 보기 버튼만 없어지고 할 일 목록은 그대로다). 대화 내용은 기록하지 않는다.
 * @returns {Record<string, number>}
 */
export default function useTodoOrigins() {
  const [origins, setOrigins] = useState({});
  const seq = useRef(0);
  useFocusEffect(
    useCallback(() => {
      seq.current += 1;
      const mine = seq.current;
      listLinks({ kind: "todo", limit: 100 }).then(
        (page) => {
          if (seq.current === mine) setOrigins(todoOrigins(page?.items));
        },
        () => {},
      );
      return () => {
        seq.current += 1;
      };
    }, []),
  );
  return origins;
}
