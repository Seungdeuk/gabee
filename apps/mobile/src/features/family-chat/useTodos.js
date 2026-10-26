import { useFocusEffect } from "expo-router";
import { useCallback, useRef, useState } from "react";

import { createTodo, deleteTodo, getRoomInfo, listTodos, updateTodo } from "./api";
import { isNoGroup } from "./chatUtils";
import { memberName } from "./listUtils";
import { applyPatch, mergeDone, mergeFetched, removeTodo, replaceTodo, splitTodos, todoErrorMessage } from "./todoUtils";

const BUSY_MESSAGE = "아직 처리 중이에요. 잠시 뒤에 다시 해 주세요";
const GONE_MESSAGE = "이미 지워진 할 일이에요";

/**
 * 공동 할 일 화면의 상태. 화면이 보일 때(포커스)와 새로고침(reload)으로만 불러오고 폴링은 하지 않는다.
 * 안 끝난 일은 처음부터, 끝난 일은 펼칠 때(setDoneOpen(true)) 처음 불러온다. 완료·되돌리기는 낙관적으로 먼저 보여 주고 실패하면 되돌린다.
 * 불러오는 중에 바뀐 항목은 현재 화면의 값을 우선해 합친다(mergeFetched·mergeDone). 변경 함수는 오류 문구(성공이면 빈 문자열)를 돌려준다.
 * 할 일 제목 등은 로그에 남기지 않는다.
 * @returns {{ status: "loading" | "ready" | "none" | "error", error: string, info: string, members: { id: string, name: string }[], meId: string | null, open: object[], done: object[], doneOpen: boolean, doneLoaded: boolean, refreshing: boolean, reload: () => Promise<void>, refresh: () => Promise<void>, toggleDone: (todo: object) => Promise<string>, setDoneOpen: (open: boolean) => void, add: (body: object) => Promise<string>, edit: (id: string, patch: object) => Promise<string>, remove: (id: string) => Promise<string> }}
 */
export default function useTodos() {
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const [info, setInfo] = useState(""); // 이미 지워진 할 일 같은 짧은 안내
  const [members, setMembers] = useState([]);
  const [meId, setMeId] = useState(null);
  const [todos, setTodos] = useState([]);
  const [doneOpen, setDoneOpenState] = useState(false);
  const [doneLoaded, setDoneLoaded] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const doneOpenRef = useRef(false);
  const todosRef = useRef([]); // 가장 최근 목록(요청이 끝난 시점에 합칠 때 쓴다)
  const busy = useRef(new Set()); // 요청 중인 할 일 id: 같은 항목의 중복 누름을 막는다
  const watchers = useRef(new Set()); // 불러오는 중인 요청들이 지켜보는 "그 사이 바뀐 id" 집합

  const apply = useCallback((next) => {
    todosRef.current = typeof next === "function" ? next(todosRef.current) : next;
    setTodos(todosRef.current);
  }, []);

  /** 불러오는 동안 바뀐 id 를 모으는 집합을 만든다(끝나면 stop). 지금 요청 중인 id 도 처음부터 보호한다. */
  const watch = () => {
    const changed = new Set(busy.current);
    watchers.current.add(changed);
    return { changed, stop: () => watchers.current.delete(changed) };
  };
  const touch = (id) => watchers.current.forEach((set) => set.add(id));

  const fetchAll = useCallback(
    async (withDone) => {
      const w = watch();
      try {
        // 할 일 목록의 404 는 서버에 아직 이 기능이 없다는 뜻일 수 있어서 가족 없음과 구분한다(코드 no_group 만 가족 없음)
        const todoCall = (s) =>
          listTodos(s, 200).catch((e) => {
            throw Object.assign(e, { fromTodos: true });
          });
        const [group, open, done] = await Promise.all([getRoomInfo(), todoCall("open"), withDone ? todoCall("done") : Promise.resolve([])]);
        setMembers((Array.isArray(group.members) ? group.members : []).map((m) => ({ id: m.id, name: memberName(m) })));
        setMeId(group.my_id ?? null);
        apply((cur) => mergeFetched(cur, [...open, ...done], w.changed));
        setDoneLoaded(withDone);
        setStatus("ready");
        setError("");
      } finally {
        w.stop();
      }
    },
    [apply],
  );

  const reload = useCallback(async () => {
    setInfo("");
    try {
      await fetchAll(doneOpenRef.current);
    } catch (e) {
      const noGroup = e?.fromTodos ? e.code === "no_group" : isNoGroup(e);
      if (noGroup) setStatus("none");
      else {
        setStatus((s) => (s === "ready" ? s : "error"));
        setError(e?.fromTodos && e.status === 404 ? "할 일을 불러오지 못했어요. 잠시 뒤에 다시 시도해 주세요" : todoErrorMessage(e));
      }
    }
  }, [fetchAll]);

  useFocusEffect(
    useCallback(() => {
      reload();
    }, [reload]),
  );

  const refresh = useCallback(async () => {
    setRefreshing(true);
    await reload();
    setRefreshing(false);
  }, [reload]);

  const setDoneOpen = useCallback(
    (next) => {
      doneOpenRef.current = next;
      setDoneOpenState(next);
      if (!next) return;
      const w = watch();
      listTodos("done", 200)
        .then((done) => {
          apply((cur) => mergeDone(cur, done, w.changed));
          setDoneLoaded(true);
        })
        .catch((e) => setError(todoErrorMessage(e)))
        .finally(w.stop);
    },
    [apply],
  );

  /** 항목 하나를 먼저 바꿔 보이고 서버에 보낸다. 실패하면 그 사이 다른 값으로 바뀌지 않았을 때만 되돌리고 오류 문구를 돌려준다. */
  const mutate = useCallback(
    async (todo, patch) => {
      if (busy.current.has(todo.id)) return BUSY_MESSAGE;
      busy.current.add(todo.id);
      touch(todo.id);
      setInfo("");
      const optimistic = applyPatch(todo, patch, meId);
      apply((cur) => replaceTodo(cur, todo.id, optimistic));
      try {
        const saved = await updateTodo(todo.id, patch);
        apply((cur) => replaceTodo(cur, todo.id, saved));
        return "";
      } catch (e) {
        if (e?.status === 404) {
          apply((cur) => removeTodo(cur, todo.id));
          setInfo(GONE_MESSAGE);
          return "";
        }
        apply((cur) => (cur.find((t) => t.id === todo.id) === optimistic ? replaceTodo(cur, todo.id, todo) : cur));
        return todoErrorMessage(e);
      } finally {
        busy.current.delete(todo.id);
      }
    },
    [apply, meId],
  );

  const toggleDone = useCallback((todo) => mutate(todo, { done: !todo.done }), [mutate]);

  const edit = useCallback(
    (id, patch) => {
      const todo = todosRef.current.find((t) => t.id === id);
      return todo ? mutate(todo, patch) : Promise.resolve(GONE_MESSAGE);
    },
    [mutate],
  );

  const add = useCallback(
    async (body) => {
      try {
        const created = await createTodo(body);
        apply((cur) => [...cur.filter((t) => t.id !== created.id), created]);
        return "";
      } catch (e) {
        return todoErrorMessage(e);
      }
    },
    [apply],
  );

  const remove = useCallback(
    async (id) => {
      if (busy.current.has(id)) return BUSY_MESSAGE;
      busy.current.add(id);
      touch(id);
      setInfo("");
      try {
        await deleteTodo(id);
        apply((cur) => removeTodo(cur, id));
        return "";
      } catch (e) {
        if (e?.status === 404) {
          apply((cur) => removeTodo(cur, id));
          setInfo(GONE_MESSAGE);
          return "";
        }
        return todoErrorMessage(e);
      } finally {
        busy.current.delete(id);
      }
    },
    [apply],
  );

  const { open, done } = splitTodos(todos);
  return { status, error, info, members, meId, open, done, doneOpen, doneLoaded, refreshing, reload, refresh, toggleDone, setDoneOpen, add, edit, remove };
}
