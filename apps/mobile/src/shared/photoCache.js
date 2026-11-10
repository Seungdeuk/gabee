/**
 * 프로필 사진 주소·메모리 캐시의 순수 로직(React·네트워크와 무관). 웹에서 인증이 필요한 사진을 blob 주소로 들고 있을 때 쓴다.
 * 키는 서버가 준 photo_url 그대로(?v= 버전 포함)라서 사진이 바뀌면 키가 달라져 새로 받는다.
 */

// 서버가 만드는 형태만 받는다. 다른 주소(외부 사이트 등)로 인증 헤더가 나가지 않게 하려는 것이다.
const PHOTO_PATH = /^\/family-group\/users\/[\w-]+\/photo(\?v=\d+)?$/;
// 채팅 사진: attachment.url(/family-chat/photos/<id>)과 thumb_url(…?size=thumb). 사진은 바뀌지 않는다.
const CHAT_PHOTO_PATH = /^\/family-chat\/photos\/[\w-]+(\?size=(full|thumb))?$/;
// 가족 놀이터 그림·사진: /play/items/<id>/image 와 ?v=(줄여 보기 횟수, 결과 공개 때 f). 풀이 중 사진은 서버가 확대한 조각만 준다.
const PLAY_IMAGE_PATH = /^\/play\/items\/[\w-]+\/image(\?v=\d+f?)?$/;

/**
 * 서버가 준 사진 주소(프로필 photo_url, 채팅 attachment.url·thumb_url)가 우리 경로일 때만 돌려준다.
 * @param {unknown} photoUrl
 * @returns {string | null} 상대 경로(없거나 낯선 형태면 null)
 */
export function photoPath(photoUrl) {
  return typeof photoUrl === "string" && (PHOTO_PATH.test(photoUrl) || CHAT_PHOTO_PATH.test(photoUrl) || PLAY_IMAGE_PATH.test(photoUrl)) ? photoUrl : null;
}

/**
 * 같은 사람의 사진끼리 묶는 값(?v= 를 뗀 경로). 채팅 사진은 바뀌지 않으므로 원본·썸네일을 각각 따로 둔다(경로 그대로).
 * @param {string} path
 */
export const photoOwner = (path) => (CHAT_PHOTO_PATH.test(path) || PLAY_IMAGE_PATH.test(path) ? path : path.split("?")[0]);

/**
 * 같은 키를 여러 곳이 쓰면 한 번만 받고(진행 중인 요청도 공유), 아무도 안 쓰는 사진은 최근 maxIdle 개만 남긴다.
 * 같은 사람의 새 버전이 오면 안 쓰는 옛 버전은 바로 버린다.
 * @template T
 * @param {{ load: (key: string) => Promise<any>, create: (data: any) => string, revoke: (url: string) => void, maxIdle?: number }} deps
 *   load: 사진 데이터 받기, create: 데이터 → 화면에 쓸 주소(URL.createObjectURL), revoke: 주소 해제
 */
export function createPhotoCache({ load, create, revoke, maxIdle = 30 }) {
  const entries = new Map(); // key → { refs, url, promise }
  const idle = new Set(); // 쓰는 곳이 없는 key(오래된 것부터)

  const drop = (key) => {
    const entry = entries.get(key);
    if (!entry) return;
    entries.delete(key);
    idle.delete(key);
    if (entry.url) revoke(entry.url);
  };

  const trim = () => {
    for (const key of idle) {
      if (idle.size <= maxIdle) break;
      drop(key);
    }
  };

  return {
    /**
     * 사진 주소를 얻는다. 쓰는 동안 참조를 잡으므로 다 쓰면 release 를 부른다. 받기에 실패하면 거부되고 참조는 풀린다.
     * @param {string} key
     * @returns {Promise<string>}
     */
    acquire(key) {
      let entry = entries.get(key);
      if (!entry) {
        const fresh = { refs: 0, url: "", promise: null };
        fresh.promise = load(key).then(
          (data) => {
            const url = create(data);
            if (entries.get(key) === fresh) fresh.url = url;
            else revoke(url); // 받는 사이에 버려졌다
            return url;
          },
          (e) => {
            if (entries.get(key) === fresh) entries.delete(key); // 실패는 기억하지 않는다(다음에 다시 시도)
            throw e;
          },
        );
        entries.set(key, fresh);
        entry = fresh;
        const owner = photoOwner(key);
        for (const other of [...idle]) if (other !== key && photoOwner(other) === owner) drop(other);
      }
      entry.refs += 1;
      idle.delete(key);
      return entry.promise;
    },

    /** acquire 한 사진을 다 썼다고 알린다. @param {string} key */
    release(key) {
      const entry = entries.get(key);
      if (!entry) return;
      entry.refs = Math.max(0, entry.refs - 1);
      if (entry.refs === 0) {
        idle.add(key);
        trim();
      }
    },

    /** 전부 비운다(로그아웃 등). */
    clear() {
      for (const key of [...entries.keys()]) drop(key);
    },

    /** 시험용: 지금 들고 있는 키 수. */
    get size() {
      return entries.size;
    },
  };
}

/**
 * 캐시에서 사진을 받아 쓰고, 정리 함수를 돌려준다. 정리 함수는 이 호출이 참조를 실제로 쥐고 있을 때만 release 한다
 * (acquire 가 실패했다면 풀 참조가 없으니 부르지 않는다 - 실패 뒤 다른 곳이 만든 새 항목의 참조 수를 줄이지 않기 위해).
 * 받는 도중에 정리되면 받기가 끝나는 즉시 참조를 푼다.
 * @param {{ acquire: (key: string) => Promise<string>, release: (key: string) => void }} cache
 * @param {string} key
 * @param {{ onReady: (url: string) => void, onFail: () => void }} handlers 정리된 뒤에는 불리지 않는다
 * @returns {() => void} 정리 함수
 */
export function holdPhoto(cache, key, { onReady, onFail }) {
  let cancelled = false;
  let held = false;
  cache.acquire(key).then(
    (url) => {
      if (cancelled) {
        cache.release(key);
        return;
      }
      held = true;
      onReady(url);
    },
    () => {
      if (!cancelled) onFail();
    },
  );
  return () => {
    cancelled = true;
    if (held) {
      held = false;
      cache.release(key);
    }
  };
}
