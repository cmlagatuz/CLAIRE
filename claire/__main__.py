import sys

if "--link" in sys.argv[1:]:
    from .companion import setup_link as main
elif "--window" in sys.argv[1:] or "window" in sys.argv[1:]:
    from .web import main
else:
    from .cli import main

main()
