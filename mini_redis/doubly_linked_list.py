"""이중 연결 리스트 (Doubly Linked List).

LRU 추적과 HashMap 버킷(체이닝)에서 재사용한다.

설계 포인트
-----------
* head/tail 에 **센티널(dummy) 노드**를 둔다. 실제 노드는 항상 두 센티널
  사이에 존재하므로 "비어 있는가 / 맨 앞인가" 같은 경계 분기가 사라지고,
  모든 삽입/삭제가 동일한 포인터 연산 몇 개로 끝난다 → O(1).
* 삽입 메서드는 생성한 ``Node`` 를 반환한다. 호출자가 이 노드를 핸들로
  보관하면 ``remove_node`` / ``move_to_front`` 를 탐색 없이 O(1)로 수행할 수 있다.
"""

from typing import Any


class Node:
    """리스트의 노드. 명세가 요구하는 ``prev``, ``next``, ``data`` 필드를 가진다.

    리스트에 연결되지 않은 노드는 ``prev``/``next`` 가 자기 자신을 가리킨다
    (Linux 커널 ``list_head`` 관용구). None 이 등장하지 않아 None 검사가 필요 없다.
    """

    __slots__ = ("prev", "next", "data")

    def __init__(self, data: Any = None):
        self.prev = self
        self.next = self
        self.data = data

    def __repr__(self):
        return "Node({!r})".format(self.data)


class DoublyLinkedList:
    """센티널 노드 기반 이중 연결 리스트. 모든 삽입/삭제/이동 연산은 O(1)."""

    def __init__(self):
        self._head = Node()  # 센티널: 첫 실제 노드의 prev
        self._tail = Node()  # 센티널: 마지막 실제 노드의 next
        self._head.next = self._tail
        self._tail.prev = self._head
        self._size = 0

    # ------------------------------------------------------------------ #
    # 내부 헬퍼: 모든 공개 연산은 이 두 함수로 귀결된다.
    # ------------------------------------------------------------------ #
    def _link_after(self, anchor, node):
        """``anchor`` 바로 뒤에 ``node`` 를 연결한다. O(1)."""
        node.prev = anchor
        node.next = anchor.next
        anchor.next.prev = node
        anchor.next = node
        self._size += 1

    def _unlink(self, node):
        """``node`` 를 리스트에서 떼어낸다. O(1).

        이미 분리된 노드(자기 자신을 가리킴)를 다시 떼어내면 크기가 어긋나므로 거부한다.
        """
        if node.next is node:
            raise ValueError("node is not linked to a list")
        node.prev.next = node.next
        node.next.prev = node.prev
        node.prev = node  # 분리된 노드는 자기 자신을 가리키는 상태로 되돌린다
        node.next = node
        self._size -= 1

    def _check_not_empty(self, op):
        if self._size == 0:
            raise IndexError("{} from empty list".format(op))

    # ------------------------------------------------------------------ #
    # 삽입
    # ------------------------------------------------------------------ #
    def insert_front(self, data):
        """맨 앞에 ``data`` 를 삽입하고 생성된 노드를 반환한다. O(1)."""
        node = Node(data)
        self._link_after(self._head, node)
        return node

    def insert_back(self, data):
        """맨 뒤에 ``data`` 를 삽입하고 생성된 노드를 반환한다. O(1)."""
        node = Node(data)
        self._link_after(self._tail.prev, node)
        return node

    # ------------------------------------------------------------------ #
    # 삭제
    # ------------------------------------------------------------------ #
    def remove_front(self):
        """맨 앞 노드를 제거하고 그 ``data`` 를 반환한다. 비어 있으면 IndexError. O(1)."""
        self._check_not_empty("remove_front")
        node = self._head.next
        self._unlink(node)
        return node.data

    def remove_back(self):
        """맨 뒤 노드를 제거하고 그 ``data`` 를 반환한다. 비어 있으면 IndexError. O(1)."""
        self._check_not_empty("remove_back")
        node = self._tail.prev
        self._unlink(node)
        return node.data

    def remove_node(self, node):
        """이 리스트에 속한 ``node`` 를 제거하고 그 ``data`` 를 반환한다. O(1)."""
        self._unlink(node)
        return node.data

    # ------------------------------------------------------------------ #
    # 이동 / 조회
    # ------------------------------------------------------------------ #
    def move_to_front(self, node):
        """이미 리스트에 있는 ``node`` 를 맨 앞으로 옮긴다. O(1)."""
        if self._head.next is node:
            return
        self._unlink(node)
        self._link_after(self._head, node)

    def peek_front(self):
        """맨 앞 노드의 ``data`` 를 제거하지 않고 반환한다. 비어 있으면 IndexError."""
        self._check_not_empty("peek_front")
        return self._head.next.data

    def peek_back(self):
        """맨 뒤 노드의 ``data`` 를 제거하지 않고 반환한다. 비어 있으면 IndexError."""
        self._check_not_empty("peek_back")
        return self._tail.prev.data

    def size(self):
        """노드 개수를 반환한다. O(1)."""
        return self._size

    def is_empty(self):
        return self._size == 0

    def nodes(self):
        """앞에서 뒤로 노드를 순회하는 제너레이터 (HashMap 버킷 탐색용)."""
        node = self._head.next
        while node is not self._tail:
            next_node = node.next  # 순회 중 현재 노드가 제거되어도 안전하도록 미리 저장
            yield node
            node = next_node

    def __iter__(self):
        """앞에서 뒤로 ``data`` 를 순회한다."""
        for node in self.nodes():
            yield node.data

    def __len__(self):
        return self._size

    def __repr__(self):
        return "DoublyLinkedList([{}])".format(", ".join(repr(d) for d in self))
