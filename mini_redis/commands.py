"""명령어 테이블과 실행기.

입력 라인 → (parser) 토큰 → 명령어 조회(HashMap) → 인자 개수 검증 → 핸들러 실행 → Redis 스타일 문자열.
명령어 이름은 대소문자를 구분하지 않으며, 에러 메시지에는 사용자가 입력한 이름을 그대로 보여준다.
"""

from mini_redis import formatter
from mini_redis.errors import RedisError, not_integer, unknown_command, wrong_arity
from mini_redis.hash_map import HashMap
from mini_redis.parser import tokenize

_INT64_MIN = -(2 ** 63)
_INT64_MAX = 2 ** 63 - 1
_INT64_MAX_DIGITS = 19
_DIGITS = "0123456789"
# 만료 시각을 밀리초로 환산해도 int64 를 넘지 않는 최대 초 (실제 Redis 와 같은 상한)
_MAX_EXPIRE_SECONDS = _INT64_MAX // 1000


def parse_int(text):
    """Redis 규칙의 정수 파싱: ``-?[0-9]+`` 이면서 64bit 부호 있는 정수 범위.

    ``int()`` 는 ``" 5"``, ``"+5"``, ``"5_0"``, 유니코드 숫자까지 받아들이므로 직접 검사한다.
    수천 자리 입력은 ``int()`` 변환 전에 자릿수로 걸러낸다 (변환 비용 + 파이썬 자릿수 제한 회피).
    """
    digits = text[1:] if text.startswith("-") else text
    if not digits:
        raise not_integer()
    for ch in digits:
        if ch not in _DIGITS:
            raise not_integer()
    if len(digits.lstrip("0")) > _INT64_MAX_DIGITS:
        raise not_integer()
    value = int(text)
    if value < _INT64_MIN or value > _INT64_MAX:
        raise not_integer()
    return value


class _Command:
    """명령어 메타데이터: 핸들러와 허용 인자 개수(명령어 이름 제외)."""

    __slots__ = ("handler", "min_args", "max_args")

    def __init__(self, handler, min_args, max_args):
        self.handler = handler
        self.min_args = min_args
        self.max_args = max_args  # None = 상한 없음


class CommandExecutor:
    """토큰을 받아 ``MiniRedisStore`` 에 명령을 실행하고 출력 문자열을 반환한다."""

    def __init__(self, store):
        self._store = store
        self._commands = HashMap()  # 명령어 이름(대문자) → _Command
        self._register("SET", self._set, 2, 2)
        self._register("GET", self._get, 1, 1)
        self._register("DEL", self._del, 1, 1)
        self._register("EXISTS", self._exists, 1, 1)
        self._register("DBSIZE", self._dbsize, 0, 0)
        self._register("KEYS", self._keys, 0, 1)
        self._register("CONFIG", self._config, 1, None)
        self._register("INFO", self._info, 0, 1)
        self._register("EXPIRE", self._expire, 2, 2)
        self._register("TTL", self._ttl, 1, 1)

    def _register(self, name, handler, min_args, max_args):
        self._commands.put(name, _Command(handler, min_args, max_args))

    # ------------------------------------------------------------------ #
    # 실행 진입점
    # ------------------------------------------------------------------ #
    def execute_line(self, line):
        """입력 한 줄을 실행하고 출력 문자열을 반환한다. 빈 줄이면 빈 문자열."""
        try:
            tokens = tokenize(line)
        except RedisError as err:
            return formatter.error(str(err))
        return self.execute(tokens)

    def execute(self, tokens):
        """토큰 리스트를 실행하고 출력 문자열을 반환한다. 에러도 ``(error) ...`` 문자열로 반환."""
        if not tokens:
            return ""
        name, args = tokens[0], tokens[1:]
        try:
            command = self._commands.get(name.upper())
            if command is None:
                raise unknown_command(name)
            if len(args) < command.min_args or (
                command.max_args is not None and len(args) > command.max_args
            ):
                raise wrong_arity(name)
            return command.handler(name, args)
        except RedisError as err:
            return formatter.error(str(err))

    # ------------------------------------------------------------------ #
    # String 명령
    # ------------------------------------------------------------------ #
    def _set(self, name, args):
        self._store.set(args[0], args[1])  # OOM 이면 OutOfMemoryError(RedisError) 전파
        return formatter.ok()

    def _get(self, name, args):
        return formatter.bulk_or_nil(self._store.get(args[0]))

    def _del(self, name, args):
        return formatter.integer(1 if self._store.delete(args[0]) else 0)

    def _exists(self, name, args):
        return formatter.integer(1 if self._store.exists(args[0]) else 0)

    def _dbsize(self, name, args):
        return formatter.integer(self._store.dbsize())

    def _keys(self, name, args):
        # 패턴 매칭은 구현하지 않는다. 습관적으로 입력하는 'KEYS *' 만 허용.
        if args and args[0] != "*":
            raise RedisError("ERR pattern matching is not supported, use KEYS or KEYS *")
        return formatter.array(self._store.keys())

    # ------------------------------------------------------------------ #
    # 메모리 관리 명령
    # ------------------------------------------------------------------ #
    def _config(self, name, args):
        sub = args[0]
        if sub.upper() != "SET":
            raise RedisError("ERR unknown subcommand '{}'".format(sub))
        if len(args) != 3:
            raise wrong_arity("{}|{}".format(name, sub))
        param, raw_value = args[1], args[2]
        if param.lower() != "maxmemory":
            raise RedisError(
                "ERR Unknown option or number of arguments for CONFIG SET - '{}'".format(param)
            )
        limit = parse_int(raw_value)
        if limit < 0:
            raise not_integer()
        self._store.set_maxmemory(limit)
        return formatter.ok()

    def _info(self, name, args):
        if args and args[0].lower() != "memory":
            return formatter.bulk("")  # 지원하지 않는 섹션은 실제 Redis 처럼 빈 결과
        return formatter.fields(self._store.info_memory())

    # ------------------------------------------------------------------ #
    # TTL 명령
    # ------------------------------------------------------------------ #
    def _expire(self, name, args):
        seconds = parse_int(args[1])
        if seconds > _MAX_EXPIRE_SECONDS:
            raise RedisError("ERR invalid expire time in '{}' command".format(name))
        return formatter.integer(1 if self._store.expire(args[0], seconds) else 0)

    def _ttl(self, name, args):
        return formatter.integer(self._store.ttl(args[0]))
