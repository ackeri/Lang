"""Built-in functions, implemented in the C runtime prelude."""

from .resolve import FnDecl
from .types import INT, NOTHING, TEXT, FnType

RUNTIME = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

static void lang_print_int(int64_t v) { printf("%lld\n", (long long)v); }
static void lang_print_text(const char *v) { printf("%s\n", v); }
static int64_t lang_add(int64_t a, int64_t b) { return a + b; }
static int64_t lang_subtract(int64_t a, int64_t from) { return from - a; }
static int64_t lang_multiply(int64_t a, int64_t by) { return a * by; }
static int64_t lang_divide(int64_t a, int64_t by) {
    if (by == 0) { fprintf(stderr, "division by zero\n"); exit(1); }
    return a / by;
}
"""


def _builtin(name, params, ret, cname):
    ftype = FnType.make([(label, t) for label, _, t in params], ret)
    return FnDecl(name, params, ftype, cname, builtin=True)


def builtins():
    return [
        _builtin("print", [("object", "value", INT)], NOTHING, "lang_print_int"),
        _builtin("print", [("object", "value", TEXT)], NOTHING, "lang_print_text"),
        # a add b
        _builtin("add", [("subject", "a", INT), ("object", "b", INT)], INT, "lang_add"),
        # subtract a from b
        _builtin("subtract", [("object", "a", INT), ("from", "b", INT)], INT, "lang_subtract"),
        # multiply a by b
        _builtin("multiply", [("object", "a", INT), ("by", "b", INT)], INT, "lang_multiply"),
        # divide a by b
        _builtin("divide", [("object", "a", INT), ("by", "b", INT)], INT, "lang_divide"),
    ]
