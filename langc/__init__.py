"""Bootstrap compiler: source -> C -> gcc."""

import os
import subprocess
import tempfile

from .builtins import builtins
from .cgen import generate
from .errors import CompileError
from .lexer import tokenize
from .resolve import Resolver
from .syntax import parse

__all__ = ["CompileError", "compile_to_c", "build"]

CFLAGS = ["-std=c11", "-O1", "-fwrapv", "-Wall", "-Wno-unused-function"]


def compile_to_c(source):
    program = Resolver(builtins()).run(parse(tokenize(source)))
    return generate(program)


def build(source, output, cc="gcc"):
    """Compile source to an executable at `output`."""
    c_source = compile_to_c(source)
    with tempfile.TemporaryDirectory() as tmp:
        c_path = os.path.join(tmp, "out.c")
        with open(c_path, "w") as f:
            f.write(c_source)
        result = subprocess.run(
            [cc, *CFLAGS, c_path, "-o", output], capture_output=True, text=True
        )
    if result.returncode != 0:
        raise RuntimeError("C compiler failed (compiler bug):\n" + result.stderr)
    return output
