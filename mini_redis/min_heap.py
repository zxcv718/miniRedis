"""최소 힙 (Min Heap).

TTL 관리에서 ``(expire_at, key)`` 원소를 저장해 "가장 빨리 만료되는 키"를
O(1)로 확인(peek)하고 O(log n)으로 꺼내기(pop) 위해 사용한다.

설계 포인트
-----------
* 완전 이진 트리를 배열 하나로 표현한다 (포인터 불필요).
    - 부모: ``(i - 1) // 2``, 왼쪽 자식: ``2i + 1``, 오른쪽 자식: ``2i + 2``
* 힙 속성: 모든 부모 ≤ 자식 → 루트(인덱스 0)가 항상 최솟값.
* 원소 비교는 ``<`` 연산자를 사용한다. 튜플 ``(expire_at, key)`` 는
  사전식으로 비교되므로 만료 시각이 같으면 키 순서로 정렬된다.
"""


class MinHeap:
    """배열 기반 최소 힙."""

    def __init__(self):
        self._items = []

    # ------------------------------------------------------------------ #
    # 공개 API
    # ------------------------------------------------------------------ #
    def push(self, item):
        """원소를 추가한다. 맨 끝에 넣고 위로 올리며 힙 속성을 복구한다. O(log n)."""
        self._items.append(item)
        self._heapify_up(len(self._items) - 1)

    def pop(self):
        """최솟값(루트)을 제거하고 반환한다. 비어 있으면 IndexError. O(log n).

        마지막 원소를 루트 자리로 옮긴 뒤 아래로 내리며 힙 속성을 복구한다.
        """
        if not self._items:
            raise IndexError("pop from empty heap")
        root = self._items[0]
        last = self._items.pop()
        if self._items:
            self._items[0] = last
            self._heapify_down(0)
        return root

    def peek(self):
        """최솟값을 제거하지 않고 반환한다. 비어 있으면 IndexError. O(1)."""
        if not self._items:
            raise IndexError("peek from empty heap")
        return self._items[0]

    def size(self):
        """원소 개수. O(1)."""
        return len(self._items)

    def is_empty(self):
        return not self._items

    # ------------------------------------------------------------------ #
    # 힙 속성 복구
    # ------------------------------------------------------------------ #
    def _heapify_up(self, index):
        """``index`` 의 원소가 부모보다 작으면 부모와 교환하며 위로 올린다."""
        items = self._items
        while index > 0:
            parent = (index - 1) // 2
            if items[index] < items[parent]:
                items[index], items[parent] = items[parent], items[index]
                index = parent
            else:
                break

    def _heapify_down(self, index):
        """``index`` 의 원소를 더 작은 자식과 교환하며 아래로 내린다."""
        items = self._items
        n = len(items)
        while True:
            left = 2 * index + 1
            right = left + 1
            smallest = index
            if left < n and items[left] < items[smallest]:
                smallest = left
            if right < n and items[right] < items[smallest]:
                smallest = right
            if smallest == index:
                break
            items[index], items[smallest] = items[smallest], items[index]
            index = smallest

    def __len__(self):
        return len(self._items)

    def __repr__(self):
        return "MinHeap(size={})".format(len(self._items))
