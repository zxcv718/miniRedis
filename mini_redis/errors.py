"""Redis 스타일 에러 정의.

``RedisError`` 의 메시지는 출력 시 ``(error) `` 뒤에 그대로 붙는다.
"""

NOT_INTEGER = "ERR value is not an integer or out of range"
OOM = "OOM command not allowed when used_memory > 'maxmemory'"
UNBALANCED_QUOTES = "ERR Protocol error: unbalanced quotes in request"


class RedisError(Exception):
    """명령 실행 실패. ``str(err)`` 가 사용자에게 보여줄 메시지다."""


class OutOfMemoryError(RedisError):
    """단일 엔트리가 maxmemory 를 초과해 저장할 수 없을 때."""

    def __init__(self):
        super().__init__(OOM)


def unknown_command(name):
    return RedisError("ERR unknown command '{}'".format(name))


def wrong_arity(name):
    return RedisError("ERR wrong number of arguments for '{}' command".format(name))


def not_integer():
    return RedisError(NOT_INTEGER)
