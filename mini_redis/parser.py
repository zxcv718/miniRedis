"""입력 라인 파서: ``SET user:1 "Alice"`` → ``["SET", "user:1", "Alice"]``.

redis-cli 의 인자 분리 규칙을 단순화해 따른다.

* 공백으로 토큰을 나눈다.
* ``"..."``: 큰따옴표 안의 공백을 값으로 포함한다. 이스케이프 ``\\"``, ``\\\\``, ``\\n``, ``\\r``, ``\\t`` 지원.
* ``'...'``: 작은따옴표 안은 그대로 취급하고 ``\\'`` 만 이스케이프로 인정한다.
* ``""`` 는 빈 문자열 값이다.
* 닫는 따옴표 바로 뒤에는 공백이나 줄 끝이 와야 한다. 따옴표가 닫히지 않은 경우와
  함께 ``ERR Protocol error: unbalanced quotes in request`` 에러로 처리한다.
"""

from mini_redis.errors import UNBALANCED_QUOTES, RedisError

# 이스케이프 문자 매핑 (dict 대신 같은 위치의 문자끼리 대응)
_ESCAPE_CODES = "nrtab"
_ESCAPE_CHARS = "\n\r\t\a\b"


def _unescape(ch):
    index = _ESCAPE_CODES.find(ch)
    return _ESCAPE_CHARS[index] if index >= 0 else ch


def tokenize(line):
    """한 줄을 토큰 리스트로 분리한다. 따옴표 오류 시 ``RedisError``."""
    tokens = []
    i = 0
    n = len(line)
    while True:
        while i < n and line[i].isspace():
            i += 1
        if i >= n:
            return tokens

        chars = []
        quote = None  # 현재 열려 있는 따옴표 문자 (없으면 None)
        while True:
            if quote is None:
                if i >= n or line[i].isspace():
                    break  # 토큰 끝
                ch = line[i]
                if ch == '"' or ch == "'":
                    quote = ch
                else:
                    chars.append(ch)
                i += 1
                continue

            # 따옴표 내부
            if i >= n:
                raise RedisError(UNBALANCED_QUOTES)  # 닫히지 않은 따옴표
            ch = line[i]
            if ch == "\\" and i + 1 < n:
                nxt = line[i + 1]
                if quote == '"':
                    chars.append(_unescape(nxt))
                    i += 2
                    continue
                if nxt == "'":
                    chars.append("'")
                    i += 2
                    continue
                chars.append(ch)
                i += 1
            elif ch == quote:
                i += 1
                if i < n and not line[i].isspace():
                    raise RedisError(UNBALANCED_QUOTES)  # 닫는 따옴표 뒤에 문자가 붙음
                break
            else:
                chars.append(ch)
                i += 1

        tokens.append("".join(chars))
