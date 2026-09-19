"""체이닝 방식 해시맵 (HashMap).

내장 ``dict`` 를 대체하는 Key-Value 저장소.

설계 포인트
-----------
* 해시 함수: 키를 UTF-8 바이트열로 바꾼 뒤 **FNV-1a (32bit)** 로 해시한다.
* 인덱스: 버킷 수(capacity)를 항상 2의 거듭제곱으로 유지하므로
  ``hash % capacity`` 대신 ``hash & (capacity - 1)`` 비트 마스크를 쓴다.
* 충돌 해결: 각 버킷은 ``DoublyLinkedList`` (체이닝). 같은 인덱스로 모인
  엔트리는 한 리스트에 이어 붙이고, 조회 시 체인을 따라가며 키를 비교한다.
* 확장: ``size / capacity > 0.75`` 가 되면 버킷 배열을 2배로 늘리고
  모든 엔트리를 새 capacity 기준으로 재해시(rehash)한다.
"""

from typing import List, Optional

from mini_redis.doubly_linked_list import DoublyLinkedList

_FNV_OFFSET_BASIS = 0x811C9DC5  # 2166136261
_FNV_PRIME = 0x01000193  # 16777619
_UINT32_MASK = 0xFFFFFFFF


def fnv1a_32(key):
    """문자열 ``key`` 의 FNV-1a 32bit 해시값(0 ~ 2^32-1)을 반환한다.

    과정: UTF-8 바이트열로 인코딩 → 오프셋 기저값에서 시작 →
    각 바이트마다 (1) XOR 로 섞고 (2) FNV 소수를 곱한 뒤 32bit 로 자른다.
    """
    h = _FNV_OFFSET_BASIS
    for byte in key.encode("utf-8"):
        h ^= byte
        h = (h * _FNV_PRIME) & _UINT32_MASK
    return h


class _Entry:
    """버킷(체인) 안에 저장되는 키-값 쌍."""

    __slots__ = ("key", "value")

    def __init__(self, key, value):
        self.key = key
        self.value = value


class HashMap:
    """체이닝 방식 해시맵. 키는 ``str`` 이어야 한다.

    평균 시간 복잡도: put / get / remove / contains → O(1), keys → O(n).
    """

    DEFAULT_CAPACITY = 16
    MAX_LOAD_FACTOR = 0.75

    def __init__(self, capacity=DEFAULT_CAPACITY):
        # capacity 를 2의 거듭제곱으로 올림 (비트 마스크 인덱싱 전제 조건)
        cap = 1
        while cap < capacity:
            cap <<= 1
        self._capacity = cap
        # 고정 길이 배열: 각 칸은 None(빈 버킷) 또는 DoublyLinkedList(체인)
        self._buckets: List[Optional[DoublyLinkedList]] = [None] * cap
        self._size = 0

    # ------------------------------------------------------------------ #
    # 해시 / 탐색 헬퍼
    # ------------------------------------------------------------------ #
    def _index(self, key):
        """키 → 버킷 인덱스. FNV-1a 해시의 하위 비트를 사용한다."""
        if not isinstance(key, str):
            raise TypeError("HashMap keys must be str, got {}".format(type(key).__name__))
        return fnv1a_32(key) & (self._capacity - 1)

    def _find_node(self, bucket, key):
        """체인에서 ``key`` 를 가진 노드를 찾는다. 없으면 None."""
        if bucket is None:
            return None
        for node in bucket.nodes():
            if node.data.key == key:
                return node
        return None

    # ------------------------------------------------------------------ #
    # 공개 API
    # ------------------------------------------------------------------ #
    def put(self, key, value):
        """``key`` 에 ``value`` 를 저장한다. 이미 있으면 값을 덮어쓴다."""
        index = self._index(key)
        bucket = self._buckets[index]
        node = self._find_node(bucket, key)
        if node is not None:
            node.data.value = value
            return
        if bucket is None:
            bucket = DoublyLinkedList()  # 버킷은 첫 삽입 때 생성 (lazy)
            self._buckets[index] = bucket
        bucket.insert_back(_Entry(key, value))
        self._size += 1
        if self._size / self._capacity > self.MAX_LOAD_FACTOR:
            self._resize(self._capacity * 2)

    def get(self, key, default=None):
        """``key`` 의 값을 반환한다. 없으면 ``default``."""
        node = self._find_node(self._buckets[self._index(key)], key)
        return node.data.value if node is not None else default

    def remove(self, key):
        """``key`` 를 삭제하고 성공 여부(bool)를 반환한다."""
        index = self._index(key)
        bucket = self._buckets[index]
        if bucket is None:
            return False
        node = self._find_node(bucket, key)
        if node is None:
            return False
        bucket.remove_node(node)
        if bucket.is_empty():
            self._buckets[index] = None  # 빈 체인은 해제
        self._size -= 1
        return True

    def contains(self, key):
        """``key`` 존재 여부를 반환한다."""
        return self._find_node(self._buckets[self._index(key)], key) is not None

    def keys(self):
        """모든 키를 리스트로 반환한다 (순서 보장 없음). O(capacity + n)."""
        result = []
        for bucket in self._buckets:
            if bucket is not None:
                for entry in bucket:
                    result.append(entry.key)
        return result

    def items(self):
        """모든 ``(key, value)`` 쌍을 순회한다 (순서 보장 없음)."""
        for bucket in self._buckets:
            if bucket is not None:
                for entry in bucket:
                    yield entry.key, entry.value

    def size(self):
        """저장된 키 개수. O(1)."""
        return self._size

    def capacity(self):
        """현재 버킷 수 (확장 동작 확인용)."""
        return self._capacity

    def load_factor(self):
        return self._size / self._capacity

    # ------------------------------------------------------------------ #
    # 확장 (rehash)
    # ------------------------------------------------------------------ #
    def _resize(self, new_capacity):
        """버킷 배열을 ``new_capacity`` 로 교체하고 모든 엔트리를 재배치한다.

        절차:
          1. 새 크기의 빈 버킷 배열을 만든다.
          2. 기존 모든 체인의 엔트리를 꺼내 **새 capacity 기준**으로 인덱스를 다시 계산한다.
             (capacity 가 바뀌면 ``hash & (capacity-1)`` 결과가 달라지므로 필수)
          3. 해당 새 버킷 체인의 뒤에 붙인다. 엔트리 객체는 재사용한다.
        """
        old_buckets = self._buckets
        new_buckets: List[Optional[DoublyLinkedList]] = [None] * new_capacity
        self._capacity = new_capacity
        self._buckets = new_buckets
        mask = new_capacity - 1
        for bucket in old_buckets:
            if bucket is None:
                continue
            for entry in bucket:
                index = fnv1a_32(entry.key) & mask
                new_bucket = new_buckets[index]
                if new_bucket is None:
                    new_bucket = DoublyLinkedList()
                    new_buckets[index] = new_bucket
                new_bucket.insert_back(entry)

    # ------------------------------------------------------------------ #
    # 파이썬 프로토콜 (편의)
    # ------------------------------------------------------------------ #
    def __len__(self):
        return self._size

    def __contains__(self, key):
        return self.contains(key)

    def __repr__(self):
        return "HashMap(size={}, capacity={})".format(self._size, self._capacity)
