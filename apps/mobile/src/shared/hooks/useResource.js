import { useFocusEffect } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";

/**
 * 서버에서 데이터를 한 번 불러오고, 다시 불러오는 함수(reload)를 돌려준다.
 * loader 가 바뀌면(예: 월 변경) 다시 불러온다. 오래 걸린 이전 요청의 응답은 버린다.
 * 다른 탭에 갔다가 이 화면으로 돌아오면(포커스) 한 번 더 불러온다. 화면의 값은 그대로 두고 응답이 오면 바꾸므로 깜빡이지 않는다
 * (예: AI 채팅에서 확인한 지출이 가계 탭에 바로 보인다). 처음 열 때는 이미 불러오므로 다시 부르지 않는다.
 *
 * @template T
 * @param {() => Promise<T>} loader 데이터를 돌려주는 함수. useCallback 으로 감싸서 넘긴다.
 * @param {unknown} [refreshKey] 바뀌면 다시 불러온다(다른 곳에서 값이 바뀐 걸 알릴 때).
 * @returns {{ data: T | null, error: string, loading: boolean, reload: () => Promise<void> }}
 */
export default function useResource(loader, refreshKey) {
  const [state, setState] = useState({ data: null, error: "", loading: true });
  const latest = useRef(0);

  const reload = useCallback(async () => {
    const id = ++latest.current;
    try {
      const data = await loader();
      if (id === latest.current) setState({ data, error: "", loading: false });
    } catch (e) {
      if (id === latest.current) setState((prev) => ({ ...prev, error: e.message, loading: false }));
    }
  }, [loader]);

  useEffect(() => {
    reload();
  }, [reload, refreshKey]);

  // 콜백이 바뀌면 포커스 효과가 다시 도므로(월을 바꿀 때 중복 요청) reload 는 ref 로 읽고 콜백은 고정한다
  const reloadRef = useRef(reload);
  reloadRef.current = reload;
  const focusedOnce = useRef(false);
  useFocusEffect(
    useCallback(() => {
      if (focusedOnce.current) reloadRef.current();
      focusedOnce.current = true;
    }, []),
  );

  return { ...state, reload };
}
