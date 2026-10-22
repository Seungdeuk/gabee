import { useCallback, useEffect, useRef, useState } from "react";

/**
 * 서버에서 데이터를 한 번 불러오고, 다시 불러오는 함수(reload)를 돌려준다.
 * loader 가 바뀌면(예: 월 변경) 다시 불러온다. 오래 걸린 이전 요청의 응답은 버린다.
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

  return { ...state, reload };
}
