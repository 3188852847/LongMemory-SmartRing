"""允许使用 python -m longmemory 启动 CLI。"""

from longmemory.entrypoints.cli.app import main


raise SystemExit(main())