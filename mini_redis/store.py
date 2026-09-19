"""Mini Redis 저장소 핵심 로직: 데이터 + LRU + TTL + 메모리 관리.

자료구조 구성
-------------
``_data``     HashMap[key -> _Entry(value, lru_node, size)]
``_expires``  HashMap[key -> expire_at]       TTL 의 "진실의 원천" (실제 Redis 의 expires dict 와 같은 역할)
``_ttl_heap`` MinHeap[(expire_at, key)]       가장 빠른 만료를 O(1)로 찾기 위한 색인
``_lru``      DoublyLinkedList[key]           front = 가장 최근 사용(MRU), back = 가장 오래 전 사용(LRU)

O(1) LRU 의 원리
----------------
* 조회: HashMap 으로 key → Entry 를 O(1)에 찾는다. Entry 는 LRU 리스트의 노드를 들고 있다.
* 갱신: 그 노드를 ``move_to_front`` 로 O(1)에 맨 앞으로 옮긴다 (리스트 탐색 불필요).
* 제거: 제거 대상은 항상 리스트 맨 뒤(``peek_back``) → O(1).

TTL 과 힙 (lazy deletion)
-------------------------
힙은 임의 원소 삭제가 O(n)이므로, 키가 삭제되거나 TTL 이 바뀌어도 힙에서 즉시 빼지 않는다.
대신 힙에서 꺼낸 ``(expire_at, key)`` 가 ``_expires`` 의 현재 값과 다르면 "지난(stale) 항목"으로
보고 버린다. TTL 의 실제 상태는 항상 ``_expires`` 가 결정한다.

만료 처리 두 가지
-----------------
* Lazy: 키 기반 명령(GET/DEL/EXISTS/EXPIRE/TTL)은 실행 전에 그 키의 만료 여부를 먼저 확인한다.
* Active: 전체를 보는 명령(DBSIZE/KEYS/INFO)과 메모리를 판단하는 명령(SET/CONFIG SET)은
  힙 top 부터 만료된 키를 모두 정리한다. top 만 보면 되므로 만료된 키가 없으면 O(1)이다.
"""

import time

from mini_redis.doubly_linked_list import DoublyLinkedList
from mini_redis.errors import OutOfMemoryError
from mini_redis.hash_map import HashMap
from mini_redis.min_heap import MinHeap


def utf8_len(text):
    """문자열의 UTF-8 바이트 길이."""
    return len(text.encode("utf-8"))


class _Entry:
    """저장된 값과 LRU 노드 핸들, 메모리 산정 크기를 묶은 레코드."""

    __slots__ = ("value", "node", "size")

    def __init__(self, value, node, size):
        self.value = value
        self.node = node  # _lru 리스트 안의 이 키의 노드 (O(1) 이동/삭제용 핸들)
        self.size = size  # len(utf8(key)) + len(utf8(value))


class MiniRedisStore:
    """String 타입 Key-Value 저장소.

    현재 시각은 ``time.monotonic`` 으로 얻는다 (시스템 시계 변경의 영향을 받지 않음).
    """

    # stale 항목이 쌓여 힙이 살아 있는 TTL 수의 2배 + 여유분을 넘으면 재구성한다.
    _HEAP_COMPACT_SLACK = 64

    def __init__(self):
        self._data = HashMap()
        self._expires = HashMap()
        self._ttl_heap = MinHeap()
        self._lru = DoublyLinkedList()
        self._used_memory = 0
        self._maxmemory = 0  # 0 = 무제한
        self._evicted_keys = 0

    # ================================================================== #
    # 내부: 삭제 / 만료 / eviction
    # ================================================================== #
    def _delete_key(self, key):
        """키를 **모든 구조**에서 제거한다: data, expires(TTL), LRU 노드, used_memory.

        DEL / 만료 / eviction / EXPIRE(≤0) 가 모두 이 한 경로를 사용한다.
        힙에 남은 항목은 ``_expires`` 에서 빠졌으므로 이후 stale 로 무시된다.
        """
        entry = self._data.get(key)
        if entry is None:
            return False
        self._data.remove(key)
        self._expires.remove(key)
        self._lru.remove_node(entry.node)
        self._used_memory -= entry.size
        return True

    def _expire_if_needed(self, key):
        """Lazy 만료: ``key`` 가 만료됐으면 삭제하고 True 를 반환한다."""
        expire_at = self._expires.get(key)
        if expire_at is not None and time.monotonic() >= expire_at:
            self._delete_key(key)
            return True
        return False

    def _purge_expired(self):
        """Active 만료: 힙 top 부터 만료 시각이 지난 키를 모두 삭제한다.

        각 pop 은 O(log n), 만료된 키가 없으면 peek 한 번(O(1))으로 끝난다.
        """
        now = time.monotonic()
        heap = self._ttl_heap
        while not heap.is_empty() and heap.peek()[0] <= now:
            expire_at, key = heap.pop()
            if self._expires.get(key) == expire_at:  # 현재 유효한 TTL 인 경우에만 삭제
                self._delete_key(key)
            # 다르면 stale 항목(삭제됐거나 TTL 이 바뀐 키) → 그냥 버린다

    def _evict_until_fits(self):
        """maxmemory > 0 이고 used_memory 가 초과한 동안 LRU(리스트 맨 뒤) 키부터 제거한다."""
        while (
            self._maxmemory > 0
            and self._used_memory > self._maxmemory
            and not self._lru.is_empty()
        ):
            self._delete_key(self._lru.peek_back())
            self._evicted_keys += 1

    def _compact_ttl_heap_if_needed(self):
        """stale 항목이 너무 많아지면 ``_expires`` 기준으로 힙을 다시 만든다 (메모리 상한 유지)."""
        if self._ttl_heap.size() <= 2 * self._expires.size() + self._HEAP_COMPACT_SLACK:
            return
        heap = MinHeap()
        for key, expire_at in self._expires.items():
            heap.push((expire_at, key))
        self._ttl_heap = heap

    # ================================================================== #
    # String 명령
    # ================================================================== #
    def set(self, key, value):
        """키에 값을 저장한다.

        흐름: 만료 정리 → 크기 산정 → (단일 엔트리 > maxmemory 이면 OOM) →
              덮어쓰기(기존 크기 차감, TTL 초기화, LRU 갱신) 또는 신규 삽입(LRU 맨 앞) →
              used_memory 가산 → 초과분 LRU eviction.
        """
        self._purge_expired()
        size = utf8_len(key) + utf8_len(value)
        if self._maxmemory > 0 and size > self._maxmemory:
            raise OutOfMemoryError()

        entry = self._data.get(key)
        if entry is not None:
            self._used_memory -= entry.size
            entry.value = value
            entry.size = size
            self._expires.remove(key)  # 덮어쓰기 → 기존 TTL 초기화 (힙 항목은 stale 처리)
            self._lru.move_to_front(entry.node)
        else:
            node = self._lru.insert_front(key)
            self._data.put(key, _Entry(value, node, size))
        self._used_memory += size

        # 방금 쓴 키는 LRU 맨 앞이고 size <= maxmemory 이므로 절대 스스로 제거되지 않는다.
        self._evict_until_fits()

    def get(self, key):
        """값을 반환한다. 없거나 만료됐으면 None.

        흐름: TTL 확인 → (만료면 삭제 후 None, LRU 갱신 없음) → 없으면 None →
              있으면 LRU 맨 앞으로 이동(성공 시에만 갱신) → 값 반환.
        """
        if self._expire_if_needed(key):
            return None
        entry = self._data.get(key)
        if entry is None:
            return None
        self._lru.move_to_front(entry.node)
        return entry.value

    def delete(self, key):
        """키를 삭제하고 성공 여부를 반환한다 (데이터/TTL/LRU 모두에서 제거)."""
        if self._expire_if_needed(key):
            return False
        return self._delete_key(key)

    def exists(self, key):
        """키 존재 여부. LRU 는 갱신하지 않는다."""
        if self._expire_if_needed(key):
            return False
        return self._data.contains(key)

    def dbsize(self):
        """저장된 (만료되지 않은) 키 개수."""
        self._purge_expired()
        return self._data.size()

    def keys(self):
        """전체 키 목록 (순서 보장 없음)."""
        self._purge_expired()
        return self._data.keys()

    # ================================================================== #
    # TTL 명령
    # ================================================================== #
    def expire(self, key, seconds):
        """``seconds`` 초 뒤 만료되도록 설정한다. 키가 없으면 False.

        seconds <= 0 이면 즉시 만료(삭제)하고 True 를 반환한다.
        """
        if self._expire_if_needed(key) or not self._data.contains(key):
            return False
        if seconds <= 0:
            self._delete_key(key)
            return True
        expire_at = time.monotonic() + seconds
        self._expires.put(key, expire_at)
        self._ttl_heap.push((expire_at, key))
        self._compact_ttl_heap_if_needed()
        return True

    def ttl(self, key):
        """남은 만료 시간(초). 키 없음 -2, 만료 시간 없음 -1.

        남은 시간은 소수점 이하를 버린다 (예: 2.9초 → 2).
        """
        if self._expire_if_needed(key) or not self._data.contains(key):
            return -2
        expire_at = self._expires.get(key)
        if expire_at is None:
            return -1
        return max(0, int(expire_at - time.monotonic()))

    # ================================================================== #
    # 메모리 관리
    # ================================================================== #
    def set_maxmemory(self, limit):
        """최대 메모리(바이트)를 설정한다. 0 = 무제한.

        한도를 현재 사용량보다 낮추면 즉시 LRU eviction 으로 used_memory <= maxmemory 를 맞춘다.
        """
        if limit < 0:
            raise ValueError("maxmemory must be >= 0")
        self._maxmemory = limit
        self._purge_expired()
        self._evict_until_fits()

    def info_memory(self):
        """``[(항목명, 값), ...]`` 형태의 메모리 정보."""
        self._purge_expired()
        return [
            ("used_memory", self._used_memory),
            ("maxmemory", self._maxmemory),
            ("evicted_keys", self._evicted_keys),
        ]

    @property
    def used_memory(self):
        return self._used_memory

    @property
    def maxmemory(self):
        return self._maxmemory

    @property
    def evicted_keys(self):
        return self._evicted_keys
