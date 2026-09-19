"""Redis(redis-cli) 스타일 출력 포맷.

``OK`` / ``(nil)`` / ``(integer) N`` / ``"value"`` / ``1) "key"`` / ``(error) ...``
"""


def ok():
    return "OK"


def nil():
    return "(nil)"


def integer(n):
    return "(integer) {}".format(n)


def _escape(text):
    """따옴표로 감싸 출력할 때 깨지지 않도록 특수 문자를 이스케이프한다."""
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def bulk(text):
    """문자열 값: ``"value"``."""
    return '"{}"'.format(_escape(text))


def bulk_or_nil(text):
    return nil() if text is None else bulk(text)


def array(items):
    """문자열 배열: 번호를 오른쪽 정렬해 ``1) "a"`` 형식으로 출력. 비었으면 ``(empty array)``."""
    if not items:
        return "(empty array)"
    width = len(str(len(items)))
    lines = []
    for number, item in enumerate(items, start=1):
        lines.append("{}) {}".format(str(number).rjust(width), bulk(item)))
    return "\n".join(lines)


def fields(pairs):
    """INFO 형식: ``name:value`` 줄 목록."""
    return "\n".join("{}:{}".format(name, value) for name, value in pairs)


def error(message):
    return "(error) {}".format(message)
