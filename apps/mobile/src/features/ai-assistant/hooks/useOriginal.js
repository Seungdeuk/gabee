import { useCallback, useRef, useState } from "react";

import { openOriginal } from "../api";

/**
 * 원본 보기 창의 상태. open 을 부르면 바로 창을 띄우고(불러오는 중), 준비되면 사진이나 PDF 쪽을 채운다.
 * @returns {{ state: null | object, open: (id: string, sourcePath: string | null | undefined, title?: string) => Promise<void>, close: () => void }}
 */
export default function useOriginal() {
  const [state, setState] = useState(null);
  const token = useRef(0); // 닫은 뒤에 늦게 도착한 결과가 창을 다시 열지 않게

  const open = useCallback(async (id, sourcePath, title = "") => {
    const mine = ++token.current;
    setState({ title, loading: true });
    const result = await openOriginal(id, sourcePath);
    if (token.current === mine) setState({ title, ...result });
  }, []);

  const close = useCallback(() => {
    token.current += 1;
    setState(null);
  }, []);

  return { state, open, close };
}
