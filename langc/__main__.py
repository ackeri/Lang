import argparse
import os
import subprocess
import sys

from . import CompileError, build, compile_to_c


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m langc", description=__doc__)
    ap.add_argument("source")
    ap.add_argument("-o", "--output", help="executable path (default: source name)")
    ap.add_argument("--emit-c", action="store_true", help="print the generated C and stop")
    ap.add_argument("--run", action="store_true", help="run the program after building")
    args = ap.parse_args(argv)

    with open(args.source) as f:
        source = f.read()
    try:
        if args.emit_c:
            sys.stdout.write(compile_to_c(source))
            return 0
        output = args.output or os.path.splitext(args.source)[0]
        build(source, output)
    except CompileError as e:
        print(f"{args.source}: {e}", file=sys.stderr)
        return 1
    if args.run:
        return subprocess.run([os.path.abspath(output)]).returncode
    return 0


sys.exit(main())
