"""Mini Redis 실행 진입점: ``python3 main.py``"""

import sys

from mini_redis.cli import main

if __name__ == "__main__":
    sys.exit(main())
