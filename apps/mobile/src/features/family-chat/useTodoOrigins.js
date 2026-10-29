import { useFocusEffect } from "expo-router";
import { useCallback, useRef, useState } from "react";

import { listLinks } from "./api";
import { todoOrigins } from "./linkUtils";

/**
 * 가족 할 일 중 대화에서 등록한 것의 원본 메시지 id 를 모은다(할 일 id → 메시지 id). 가족 전체방의 연결 목록에서 할 일 종류만 쓴다.
 * 화면이 보일 때마다 다시 불러오고, 실패하면 조용히 넘어가고 이전에 받은 값을 그대로 둔다(처음부터 실패하면 비어 있어 원본 버튼만 없다). 최근 연결 100개만 쓴다. 대화 내용은 기록하지 않는다.
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
