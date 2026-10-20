import sys

if "--window" in sys.argv[1:] or "window" in sys.argv[1:]:
    from .web import main
else:
    from .cli import main

main()
