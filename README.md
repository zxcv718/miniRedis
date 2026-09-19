# Mini Redis

해시맵 · 이중 연결 리스트 · 최소 힙을 밑바닥부터 구현해 만든 CLI 기반 In-Memory Key-Value 저장소.
메모리 한도(maxmemory)를 넘으면 LRU 방식으로 키를 자동 제거하고, 힙으로 TTL 만료를 관리한다.

---

## 1. 과제 개요

Redis 의 핵심 기능을 CLI 프로그램으로 구현하면서, 내장 컬렉션 없이 해시맵 · 이중 연결 리스트 · 힙을 직접 만들어
LRU 추적과 TTL 만료가 내부에서 어떻게 동작하는지 구현 수준에서 다룬다.

### 구현 범위

| 분류 | 명령 / 기능 |
|---|---|
| String 명령 | `SET` · `GET` · `DEL` · `EXISTS` · `DBSIZE` · `KEYS` |
| 메모리 관리 | `CONFIG SET maxmemory` · `INFO memory`, 한도 초과 시 LRU 자동 제거 |
| TTL 관리 | `EXPIRE` · `TTL`, 힙 기반 만료 |
| CLI | `mini-redis>` 프롬프트 REPL, `exit` / `quit` 종료 |

### 제약 사항

- Python 3.8 이상, 외부 의존성 없음
- `dict` / `set` / `collections` 사용 금지 — 명령어 라우팅 테이블까지 직접 구현한 `HashMap` 을 쓴다.
  Python `list` 는 고정 길이 배열(버킷 테이블)과 힙 저장소 용도로만 사용한다.
- 해시맵 · 이중 연결 리스트 · 힙은 각각 독립된 모듈로 분리
- 네트워크 통신, 데이터 영속성, 복합 자료형(List/Set/Sorted Set), 동시성은 범위에서 제외

---

## 2. 실행 방법

```bash
python3 main.py          # 또는 python3 -m mini_redis
```

```
mini-redis> CONFIG SET maxmemory 30
OK
mini-redis> SET user:1 "Alice"
OK
mini-redis> SET user:2 "Bob"
OK
mini-redis> SET user:3 "Charlie"
OK
mini-redis> GET user:1
(nil)
mini-redis> INFO memory
used_memory:22
maxmemory:30
evicted_keys:1
mini-redis> KEYS
1) "user:3"
2) "user:2"
mini-redis> EXPIRE user:2 3
(integer) 1
mini-redis> TTL user:2
(integer) 2
mini-redis> exit
```

종료: `exit`, `quit`, Ctrl-D, Ctrl-C

---

## 3. 명령어 명세

| 명령 | 출력 |
|---|---|
| `SET key value` | `OK` / 단일 엔트리 > maxmemory 이면 `(error) OOM ...` |
| `GET key` | `"value"` / `(nil)` |
| `DEL key` | `(integer) 1` / `(integer) 0` |
| `EXISTS key` | `(integer) 1` / `(integer) 0` |
| `DBSIZE` | `(integer) N` |
| `KEYS` (또는 `KEYS *`) | `1) "key"` … / `(empty array)` |
| `CONFIG SET maxmemory <bytes>` | `OK` (0 = 무제한) |
| `INFO [memory]` | `used_memory:N` · `maxmemory:N` · `evicted_keys:N` |
| `EXPIRE key seconds` | `(integer) 1` / 키 없으면 `(integer) 0` / seconds ≤ 0 이면 즉시 삭제 후 `1` |
| `TTL key` | 남은 초 / 만료 없음 `-1` / 키 없음 `-2` |

값 입력은 공백 없는 값, `"큰따옴표 값"` (공백 · `\"` · `\\` · `\n` 이스케이프), `'작은따옴표 값'` 을 모두 지원한다.

에러 형식:

```
(error) ERR unknown command '<cmd>'
(error) ERR wrong number of arguments for '<cmd>' command
(error) ERR value is not an integer or out of range
(error) OOM command not allowed when used_memory > 'maxmemory'
```

---

## 4. 전체 구조

```
main.py                       진입점 (python3 main.py)
mini_redis/
  __main__.py                 진입점 (python3 -m mini_redis)
  doubly_linked_list.py       Node(prev, next, data) + DoublyLinkedList
  hash_map.py                 FNV-1a 해시 + 체이닝 + 로드 팩터 0.75 초과 시 2배 확장
  min_heap.py                 배열 기반 최소 힙
  store.py                    MiniRedisStore: 데이터 · LRU · TTL · 메모리 관리
  commands.py                 명령어 테이블 · 인자 검증 · 정수 파싱 · 실행
  parser.py                   입력 라인 → 토큰
  formatter.py                Redis 스타일 출력
  errors.py                   표준 에러 메시지
  cli.py                      REPL
```

한 줄의 입력은 다음 계층을 차례로 통과한다.

```
입력 라인 ─► parser ─► commands ─► store ─► 자료구조 (HashMap · DoublyLinkedList · MinHeap)
                          │
                          └─► formatter ─► 출력 문자열 ─► cli
```

- `cli` 는 입출력과 종료 처리만 담당한다.
- `commands` 는 명령어 문법(인자 개수, 정수 형식)과 출력 형식을 담당하고, LRU/TTL 규칙은 모른다.
- `store` 는 저장 규칙(LRU, TTL, 메모리)을 담당하고, 출력 문자열 형식은 모른다.

---

## 5. 자료구조 구현

### 5.1 이중 연결 리스트 — `doubly_linked_list.py`

노드는 명세의 `prev` · `next` · `data` 필드를 가진다. 리스트의 양 끝에는 `head` / `tail` **센티널(dummy) 노드**를 두어,
실제 노드가 항상 두 센티널 사이에 있도록 한다. 그 결과 "리스트가 비었는가", "맨 앞 노드인가" 같은 경계 분기 없이
모든 삽입 · 삭제가 이웃 포인터 교체만으로 끝난다.

| 메서드 | 동작 | 복잡도 |
|---|---|---|
| `insert_front(data)` / `insert_back(data)` | 양 끝에 삽입하고 **생성한 노드를 반환** | O(1) |
| `remove_front()` / `remove_back()` | 양 끝 노드를 제거하고 data 반환 | O(1) |
| `remove_node(node)` | 주어진 노드를 제거 | O(1) |
| `move_to_front(node)` | 주어진 노드를 맨 앞으로 이동 | O(1) |
| `peek_front()` / `peek_back()` | 양 끝 data 조회 | O(1) |

- 삽입 메서드가 노드를 반환하므로, 호출자가 이 노드를 핸들로 보관하면 `remove_node` · `move_to_front` 에서
  리스트를 탐색할 필요가 없다. LRU 추적이 O(1)이 되는 근거다.
- 리스트에서 분리된 노드는 `prev` / `next` 가 자기 자신을 가리키도록 한다(Linux 커널 `list_head` 관용구).
  `None` 이 등장하지 않아 None 검사가 필요 없고, `node.next is node` 한 번으로 연결 여부를 판별해
  이미 떼어낸 노드를 다시 제거하는 오용을 거부한다.

### 5.2 해시맵 — `hash_map.py`

**해시 함수 (FNV-1a 32bit)** — `fnv1a_32(key)`

1. 키 문자열을 UTF-8 바이트열로 변환한다.
2. 오프셋 기저값 `h = 2166136261` 에서 시작한다.
3. 바이트마다 `h ^= byte` 후 `h = (h × 16777619) mod 2³²` 를 적용한다.
4. 버킷 인덱스는 `h & (capacity − 1)` 이다. capacity 를 항상 2의 거듭제곱으로 유지하므로 `h % capacity` 와 같다.

XOR 뒤에 곱셈을 하므로 마지막 바이트까지 곱셈으로 확산되어, `user:1` / `user:2` 처럼 끝만 다른 키도 흩어진다.
FNV 공식 참조값과 같은 결과를 낸다 (`"foobar"` → `0xBF9CF968`).

**충돌 해결 (체이닝)** — 각 버킷은 `DoublyLinkedList` 이고, 노드의 data 는 `(key, value)` 엔트리다.
같은 인덱스로 모인 키는 체인 뒤에 붙고, 조회 시 체인을 따라가며 키를 비교한다.
빈 버킷은 `None` 으로 두고 첫 삽입 때 리스트를 만들며, 체인이 비면 다시 `None` 으로 되돌린다.

**확장** — `put` 후 `size / capacity > 0.75` 이면 `_resize(capacity × 2)` 를 수행한다.

1. 2배 크기의 빈 버킷 배열을 만든다.
2. 기존 모든 엔트리를 꺼내 **새 capacity 기준으로 인덱스를 다시 계산**한다. (마스크가 한 비트 늘어나 인덱스가 바뀐다)
3. 새 버킷 체인에 삽입한다. 엔트리 객체는 재사용한다.

확장 한 번은 O(n)이지만 capacity 가 2배씩 늘어나므로 `put` 한 번당 분할상환 O(1)이다.

| 메서드 | 동작 | 평균 복잡도 |
|---|---|---|
| `put(key, value)` | 저장 (있으면 덮어쓰기) | O(1) |
| `get(key, default)` | 조회 | O(1) |
| `remove(key)` | 삭제, 성공 여부 반환 | O(1) |
| `contains(key)` | 존재 여부 | O(1) |
| `keys()` | 전체 키 목록 | O(capacity + n) |
| `size()` | 키 개수 | O(1) |

### 5.3 최소 힙 — `min_heap.py`

완전 이진 트리를 배열 하나로 표현한다. 인덱스 `i` 의 부모는 `(i − 1) // 2`, 자식은 `2i + 1` · `2i + 2` 이고,
모든 부모가 자식보다 작거나 같으므로 루트(인덱스 0)가 항상 최솟값이다.

| 메서드 | 동작 | 복잡도 |
|---|---|---|
| `push(item)` | 배열 끝에 추가 후 `_heapify_up` 으로 부모와 교환하며 올림 | O(log n) |
| `pop()` | 루트를 꺼내고, 마지막 원소를 루트로 옮긴 뒤 `_heapify_down` 으로 더 작은 자식과 교환하며 내림 | O(log n) |
| `peek()` | 루트 조회 | O(1) |
| `size()` | 원소 개수 | O(1) |

TTL 관리에서는 `(expire_at, key)` 튜플을 원소로 쓴다. 튜플은 사전식으로 비교되므로 만료 시각 순으로 정렬되고,
시각이 같으면 키 순으로 정렬된다.

---

## 6. 저장소 설계 — `store.py`

### 6.1 상태 구성

| 필드 | 자료구조 | 역할 |
|---|---|---|
| `_data` | `HashMap[key → Entry(value, lru_node, size)]` | 값 저장. Entry 가 LRU 노드 핸들과 메모리 산정 크기를 함께 보관 |
| `_expires` | `HashMap[key → expire_at]` | 만료 시각의 기준 데이터 |
| `_ttl_heap` | `MinHeap[(expire_at, key)]` | 가장 빨리 만료되는 키를 찾기 위한 색인 |
| `_lru` | `DoublyLinkedList[key]` | 사용 순서. 앞 = 가장 최근 사용(MRU), 뒤 = 가장 오래 전 사용(LRU) |
| `_used_memory` · `_maxmemory` · `_evicted_keys` | 정수 | 메모리 사용량, 한도(0 = 무제한), 누적 제거 수 |

시각은 주입 가능한 `clock` 함수로 얻는다. 기본값은 시스템 시각 변경의 영향을 받지 않는 `time.monotonic` 이다.

### 6.2 단일 삭제 경로

키 삭제는 모두 `_delete_key(key)` 하나를 거친다. 이 함수가 `_data` · `_expires` · LRU 노드를 한 번에 제거하고
`used_memory` 를 차감하므로, `DEL` · TTL 만료 · LRU 제거 · `EXPIRE ≤ 0` 어느 경로로 지워도 네 구조가 서로 어긋나지 않는다.

### 6.3 LRU 추적

HashMap 이 키 → Entry 조회를 O(1)로 처리하고, Entry 가 보관한 노드 핸들로 이중 연결 리스트의 노드를 O(1)에 옮긴다.
HashMap 만으로는 사용 순서를 알 수 없고 리스트만으로는 특정 키의 노드를 찾는 데 O(n)이 들기 때문에, 두 구조를 결합한다.

- **갱신**: `SET`(신규 · 덮어쓰기)과 **성공한** `GET` 만 노드를 맨 앞으로 옮긴다. `EXISTS` · `TTL` 과 만료된 키의 `GET` 은 갱신하지 않는다.
- **제거 대상**: 가장 오래 전에 사용된 키는 항상 리스트 맨 뒤에 있으므로 `peek_back()` 으로 O(1)에 찾는다.

### 6.4 TTL 관리

- `_expires` 가 만료 시각의 기준 데이터이고, 힙은 가장 빠른 만료를 찾기 위한 색인이다.
- **Lazy deletion**: 힙은 임의 원소 삭제가 O(n)이므로 `DEL` · 덮어쓰기 · `EXPIRE` 재설정 때 힙은 건드리지 않는다.
  힙에서 꺼낸 `(expire_at, key)` 가 `_expires[key]` 와 다르면 지난(stale) 항목으로 보고 버린다.
- **힙 재구성**: stale 항목이 쌓여 힙 크기가 `2 × (TTL 이 있는 키 수) + 64` 를 넘으면 `_expires` 기준으로 힙을 다시 만들어 메모리 상한을 둔다.
- **만료 확인 시점**
  - Lazy 만료 — 키 기반 명령(`GET` · `DEL` · `EXISTS` · `EXPIRE` · `TTL`)은 실행 전 `_expire_if_needed(key)` 로 해당 키의 만료를 확인하고, 만료됐으면 삭제 후 없는 키로 처리한다.
  - Active 만료 — 전체를 보는 명령(`DBSIZE` · `KEYS` · `INFO`)과 메모리를 판단하는 명령(`SET` · `CONFIG SET`)은 `_purge_expired()` 로 힙 루트부터 만료 시각이 지난 키를 모두 정리한다. 만료된 키가 없으면 `peek` 한 번으로 끝난다.
- `TTL` 의 남은 초는 소수점 이하를 버린다.

### 6.5 메모리 관리와 LRU 제거

`used_memory` 는 명세 공식대로 `Σ( len(utf8(key)) + len(utf8(value)) )` 이며, 자료구조 오버헤드는 포함하지 않는다.
각 Entry 가 자신의 크기를 보관하므로 삭제 · 덮어쓰기 때 재계산 없이 차감한다.

`SET key value` 처리 순서:

```
1. Active 만료로 이미 만료된 키부터 정리한다 (만료된 키 대신 살아 있는 키가 제거되지 않도록)
2. size = len(utf8(key)) + len(utf8(value))
3. maxmemory > 0 이고 size > maxmemory 이면 OOM 에러 — 아무 상태도 바꾸지 않는다
4. 기존 키: used_memory 에서 기존 size 차감, 값 교체, TTL 삭제, LRU 맨 앞으로 이동
   신규 키: LRU 맨 앞에 노드 삽입, HashMap 에 Entry 저장
5. used_memory += size
6. maxmemory > 0 이고 used_memory > maxmemory 인 동안
       LRU 맨 뒤 키를 _delete_key 로 제거하고 evicted_keys += 1
```

- 3단계의 OOM 검사는 상태를 바꾸기 전에 수행한다. 단일 엔트리가 한도보다 크면 다른 키를 모두 지워도 저장할 수 없으므로,
  기존 데이터를 지우지 않고 요청만 거부한다. 기존 키를 너무 큰 값으로 덮어쓰려는 경우에도 기존 값이 유지된다.
- 6단계에서 방금 쓴 키는 LRU 맨 앞에 있고 `size ≤ maxmemory` 이므로 스스로 제거되지 않는다.
- `CONFIG SET maxmemory` 로 한도를 현재 사용량보다 낮추면 같은 제거 루프를 즉시 실행해, 명령이 끝난 뒤 항상 `used_memory ≤ maxmemory` 가 성립한다.

### 6.6 GET 처리 순서

```
1. _expires[key] 가 있고 now ≥ expire_at 인지 확인한다
2. 만료됐다면 _delete_key 로 모든 구조에서 삭제하고 (nil) 을 반환한다 — LRU 갱신 없음
3. HashMap 에 키가 없으면 (nil) 을 반환한다
4. 키가 있으면 LRU 노드를 맨 앞으로 옮기고 "value" 를 반환한다
```

---

## 7. 명령 처리와 CLI

### 7.1 파서 — `parser.py`

입력 라인을 공백 기준으로 토큰으로 나눈다. 큰따옴표 안에서는 공백을 값에 포함하고 `\"` · `\\` · `\n` · `\r` · `\t`
이스케이프를 해석하며, 작은따옴표 안에서는 `\'` 만 해석한다. `""` 는 빈 문자열 값이다.
따옴표가 닫히지 않았거나 닫는 따옴표 바로 뒤에 문자가 붙으면 `(error) ERR Protocol error: unbalanced quotes in request` 를 출력한다.

### 7.2 명령 실행 — `commands.py`

- 명령어 이름(대문자) → `(핸들러, 최소 인자 수, 최대 인자 수)` 를 직접 구현한 `HashMap` 에 등록하고 조회한다.
- 명령어는 대소문자를 구분하지 않으며, 에러 메시지에는 사용자가 입력한 이름을 그대로 표시한다.
- 인자 개수가 범위를 벗어나면 `wrong number of arguments` 에러를 출력한다.
- 정수 인자(`EXPIRE` 의 seconds, `CONFIG SET maxmemory` 의 bytes)는 `-?[0-9]+` 형식과 64bit 부호 있는 정수 범위를 직접 검사한다.
  Python `int()` 는 `" 5"` · `"5_0"` · 유니코드 숫자까지 받아들이므로 사용 전에 형식을 먼저 확인한다.
  수천 자리 입력은 변환 전에 자릿수로 걸러낸다.
- 핸들러가 던진 `RedisError` 는 `(error) <메시지>` 문자열로 변환되어 반환된다.

### 7.3 출력 — `formatter.py`

`OK` · `(nil)` · `(integer) N` · `"value"` · `(error) ...` 형식으로 변환한다. 배열은 `1) "key"` 형식으로 출력하고
번호를 오른쪽 정렬하며, 비어 있으면 `(empty array)` 를 출력한다. 값 안의 따옴표와 제어 문자는 이스케이프한다.

### 7.4 REPL — `cli.py`

`mini-redis>` 프롬프트로 한 줄씩 읽어 실행하고 결과를 출력한다.

- 빈 줄은 무시하고, `exit` / `quit`(대소문자 무관) · Ctrl-D · Ctrl-C 로 종료한다.
- 예상하지 못한 예외가 발생해도 `(error) ERR internal error: ...` 로 표시하고 세션을 유지한다.
- 잘못된 UTF-8 입력으로 종료되지 않도록 표준 입력을 `errors="replace"` 로 설정하고,
  `readline` 이 있으면 방향키 편집과 입력 기록을 지원한다.

---

## 8. 명세 해석 및 설계 결정

| 항목 | 결정 | 근거 |
|---|---|---|
| TTL 남은 초 | 소수점 버림 | 명세 예시(`EXPIRE 3` 직후 `TTL` → 2)와 일치. `EXPIRE k 1` 직후 `TTL` 은 `0` 이며 키는 아직 존재한다(만료 시 `-2`) |
| KEYS 출력 형식 | redis-cli 형식 `1) "key"`, 순서는 해시 순서 | 명세는 순서를 요구하지 않는다 |
| `KEYS` 패턴 | `KEYS` · `KEYS *` 만 허용 | 패턴 매칭은 범위 밖 |
| `DEL` · `EXISTS` 인자 | 키 1개 | 명세의 명령 형식 |
| `CONFIG SET maxmemory` 로 한도 축소 | 즉시 LRU 제거 | 명령 후 `used_memory ≤ maxmemory` 유지 |
| 지원하지 않는 INFO 섹션 | 빈 문자열 `""` | 실제 Redis 동작과 동일 |
| 매우 큰 EXPIRE 초 | `(error) ERR invalid expire time in 'EXPIRE' command` | 밀리초 환산 시 int64 를 넘는 값 (실제 Redis 와 같은 상한) |
| 시계 | `time.monotonic` | 시스템 시각 변경의 영향을 받지 않음 |
| 명령어 대소문자 | 구분하지 않음, 에러에는 입력 그대로 표시 | `GET` → `'GET'`, `get` → `'get'` |
| 정수 파싱 | `-?[0-9]+` + int64 범위 | Redis 의 정수 규칙과 일치 |
