"""CLI REPL: ``mini-redis>`` 프롬프트에서 명령을 읽고(Read) 실행하고(Eval) 출력(Print)하기를 반복(Loop)한다."""

import sys

from mini_redis import formatter
from mini_redis.commands import CommandExecutor
from mini_redis.store import MiniRedisStore

PROMPT = "mini-redis> "
EXIT_COMMANDS = ("exit", "quit")


def run_repl(executor, read_line=input, write=print):
    """REPL 루프. ``exit``/``quit`` 또는 EOF(Ctrl-D)/Ctrl-C 로 종료한다.

    ``read_line`` 과 ``write`` 를 주입할 수 있어 테스트에서 표준 입출력 없이 검증 가능하다.
    """
    while True:
        try:
            line = read_line(PROMPT)
        except (EOFError, KeyboardInterrupt):
            write("")  # 프롬프트 뒤 줄바꿈
            return

        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower() in EXIT_COMMANDS:
            return

        try:
            output = executor.execute_line(line)
        except Exception as exc:  # 예상치 못한 버그가 있어도 REPL 세션은 유지하고 원인을 보여준다
            output = formatter.error("ERR internal error: {}: {}".format(type(exc).__name__, exc))
        if output:
            write(output)


def main():
    """``python3 main.py`` 진입점."""
    try:
        import readline  # noqa: F401  (방향키 편집/히스토리 지원, 없으면 생략)
    except ImportError:
        pass
    reconfigure = getattr(sys.stdin, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="replace")  # 잘못된 UTF-8 입력으로 REPL 이 죽지 않도록

    if sys.stdin.isatty():
        print("Mini Redis CLI. Type 'exit' or 'quit' to leave.")
    run_repl(CommandExecutor(MiniRedisStore()))
    return 0
