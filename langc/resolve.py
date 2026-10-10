"""Name resolution, call splitting, and type checking.

Each flat call is resolved by enumerating every interpretation (which word is
the verb, which words are labels, mention vs call, overloads, literals) and
narrowing by shape and type. Exactly one interpretation must survive.
"""

import itertools
import re
from dataclasses import dataclass, field

from . import syntax as S
from .errors import CompileError
from .types import CLASSES, INT, NOTHING, TEXT, Class, FnType

MAX_INTERPRETATIONS = 256


# ---------------------------------------------------------------- bindings


@dataclass(eq=False)
class Var:
    name: str
    type: object
    cname: str


@dataclass(eq=False)
class FnDecl:
    name: str
    params: list  # [(label, name, type)] in declaration order
    type: FnType
    cname: str
    line: int = 0
    builtin: bool = False


class Scope:
    def __init__(self, parent=None):
        self.parent = parent
        self.names = {}
        self.literal_parsers = []

    def add(self, name, binding):
        self.names.setdefault(name, []).append(binding)

    def lookup(self, name):
        found = []
        scope = self
        while scope:
            found.extend(scope.names.get(name, []))
            scope = scope.parent
        return found

    def all_bindings(self):
        scope = self
        while scope:
            for bindings in scope.names.values():
                yield from bindings
            scope = scope.parent

    def all_literal_parsers(self):
        scope = self
        while scope:
            yield from scope.literal_parsers
            scope = scope.parent


# ---------------------------------------------------------- typed program


@dataclass(eq=False)
class Lit:
    type: Class
    value: object


@dataclass(eq=False)
class VarRef:
    var: Var

    @property
    def type(self):
        return self.var.type


@dataclass(eq=False)
class FnRef:
    decl: FnDecl

    @property
    def type(self):
        return self.decl.type


@dataclass(eq=False)
class Call:
    callee: object  # FnDecl, or a typed expression of function type
    args: dict  # label -> typed expression
    type: object


@dataclass(eq=False)
class TReturn:
    value: object  # typed expression or None


@dataclass(eq=False)
class TBind:
    var: Var
    value: object
    new: bool  # first binding of this name (declares the C variable)


@dataclass(eq=False)
class TExprStmt:
    expr: object


@dataclass(eq=False)
class TFunction:
    decl: FnDecl
    body: list


@dataclass
class TProgram:
    functions: list = field(default_factory=list)
    main: list = field(default_factory=list)
    builtins: list = field(default_factory=list)


def show(expr):
    """Render an interpretation for error messages."""
    if isinstance(expr, Lit):
        return repr(expr.value) if expr.type == TEXT else f"{expr.value} (literal)"
    if isinstance(expr, VarRef):
        return expr.var.name
    if isinstance(expr, FnRef):
        return f"{expr.decl.name} (mentioned, not called)"
    callee = expr.callee.name if isinstance(expr.callee, FnDecl) else show(expr.callee)
    args = ", ".join(f"{l}: {show(a)}" for l, a in expr.args.items())
    return f"{callee}[{args}]"


# --------------------------------------------------------------- literals


def parse_int(text):
    if re.fullmatch(r"-?[0-9]+", text):
        value = int(text)
        if -(2**63) <= value < 2**63:
            return Lit(INT, value)
    return None


# ----------------------------------------------------------------- mangling


def mangle(name):
    out = []
    for c in name:
        if c.isascii() and c.isalnum():
            out.append(c)
        elif c == "_":
            out.append("__")
        else:
            out.append(f"_{ord(c):02x}")
    return "".join(out)


# ----------------------------------------------------------------- resolver


class Resolver:
    def __init__(self, builtins):
        self.globals = Scope()
        self.globals.literal_parsers.append(parse_int)
        self.program = TProgram(builtins=builtins)
        self.fn_counter = 0
        for decl in builtins:
            self.globals.add(decl.name, decl)

    def run(self, prog):
        # Top-level bindings belong to the program's entry point and are not
        # visible inside functions.
        main_scope = Scope(self.globals)
        for decl in prog.decls:
            if isinstance(decl, S.FnDef):
                self.fn_def(decl)
            elif isinstance(decl, S.Return):
                raise CompileError("return outside a function", decl.line)
            else:
                self.program.main.append(self.statement(decl, main_scope, None))
        return self.program

    # -- types

    def type_expr(self, texpr):
        if isinstance(texpr, S.TypeName):
            if texpr.name not in CLASSES:
                raise CompileError(f"unknown type '{texpr.name}'", texpr.line)
            return CLASSES[texpr.name]
        params = [(p.label, self.param_type(p)) for p in texpr.params]
        return FnType.make(params, self.return_type(texpr.ret))

    def param_type(self, param):
        if param.context:
            raise CompileError("context arguments are not supported yet", param.line)
        if not param.types:
            raise CompileError(
                f"parameter '{param.name}' needs a type ('{param.label} {param.name} is ...')",
                param.line,
            )
        if len(param.types) > 1:
            raise CompileError("multiple types per parameter are not supported yet", param.line)
        t = self.type_expr(param.types[0])
        if t == NOTHING:
            raise CompileError("a parameter cannot be Nothing", param.line)
        return t

    def return_type(self, texpr):
        return NOTHING if texpr is None else self.type_expr(texpr)

    # -- definitions

    def fn_def(self, fn):
        params = [(p.label, p.name, self.param_type(p)) for p in fn.params]
        ftype = FnType.make([(l, t) for l, _, t in params], self.return_type(fn.ret))
        self.fn_counter += 1
        decl = FnDecl(fn.name, params, ftype, f"f_{mangle(fn.name)}_{self.fn_counter}", fn.line)
        for other in self.globals.names.get(fn.name, []):
            if isinstance(other, FnDecl) and other.type.params == ftype.params:
                raise CompileError(
                    f"'{fn.name}' is already defined with the same parameters", fn.line
                )
        # Declared before its body so it can call itself.
        self.globals.add(fn.name, decl)

        scope = Scope(self.globals)
        names = [n for _, n, _ in params]
        for label, name, t in params:
            if names.count(name) > 1:
                raise CompileError(f"duplicate parameter name '{name}'", fn.line)
            scope.add(name, Var(name, t, f"v_{mangle(name)}"))
        body = [self.statement(stmt, scope, ftype.ret) for stmt in fn.body]
        if ftype.ret != NOTHING and not (body and isinstance(body[-1], TReturn)):
            raise CompileError(f"'{fn.name}' must end with a return", fn.line)
        self.program.functions.append(TFunction(decl, body))

    # -- statements

    def statement(self, stmt, scope, ret):
        if isinstance(stmt, S.Return):
            if ret is None:
                raise CompileError("return outside a function", stmt.line)
            if not stmt.items:
                if ret != NOTHING:
                    raise CompileError(f"return needs a value of type {ret}", stmt.line)
                return TReturn(None)
            if ret == NOTHING:
                raise CompileError("this function returns nothing", stmt.line)
            return TReturn(self.expect_one(stmt.items, scope, ret, stmt.line))
        if isinstance(stmt, S.Bind):
            return self.bind(stmt, scope)
        # An expression statement must do something: a bare value is dropped.
        cands = [c for c in self.resolve_seq(stmt.items, scope, {}) if isinstance(c, Call)]
        return TExprStmt(self.pick(cands, stmt.items, scope, stmt.line, None))

    def bind(self, stmt, scope):
        value = self.pick(
            self.resolve_seq(stmt.items, scope, {}), stmt.items, scope, stmt.line, None
        )
        if value.type == NOTHING:
            raise CompileError(f"'{S.describe(stmt.items)}' has no value to bind", stmt.line)
        existing = [b for b in scope.names.get(stmt.name, []) if isinstance(b, Var)]
        if existing:
            var = existing[0]
            if var.type != value.type:
                raise CompileError(
                    f"'{stmt.name}' is {var.type}; cannot assign {value.type}", stmt.line
                )
            return TBind(var, value, new=False)
        var = Var(stmt.name, value.type, f"v_{mangle(stmt.name)}")
        scope.add(stmt.name, var)
        return TBind(var, value, new=True)

    def expect_one(self, items, scope, expected, line):
        cands = self.resolve_seq(items, scope, {})
        matching = [c for c in cands if c.type == expected]
        if not matching and cands:
            found = ", ".join(sorted({str(c.type) for c in cands}))
            raise CompileError(
                f"'{S.describe(items)}' is {found}, but {expected} is expected", line
            )
        return self.pick(matching, items, scope, line, expected)

    def pick(self, cands, items, scope, line, expected):
        if len(cands) == 1:
            return cands[0]
        text = S.describe(items)
        if not cands:
            unknown = self.unknown_word(items, scope)
            if unknown:
                raise CompileError(f"unknown name '{unknown}'", line)
            raise CompileError(f"no interpretation of '{text}' fits", line)
        listing = "".join(f"\n    {show(c)}" for c in cands[:10])
        raise CompileError(
            f"'{text}' is ambiguous ({len(cands)} interpretations); "
            f"add parentheses or a type{listing}",
            line,
        )

    def unknown_word(self, items, scope):
        labels = set()
        for b in scope.all_bindings():
            if isinstance(b.type, FnType):
                labels.update(b.type.labels)
        for item in items:
            if isinstance(item, S.Group):
                found = self.unknown_word(item.items, scope)
                if found:
                    return found
            elif isinstance(item, S.Word):
                if item.text in labels or scope.lookup(item.text):
                    continue
                if any(p(item.text) for p in scope.all_literal_parsers()):
                    continue
                return item.text
        return None

    # -- expressions

    def resolve_seq(self, items, scope, memo):
        """All interpretations of a flat sequence of items."""
        if len(items) == 1:
            return self.resolve_item(items[0], scope, memo)
        cands = []
        for v in (0, 1):
            if v >= len(items) or not isinstance(items[v], S.Word):
                continue
            for callee, shape in self.callees(items[v].text, scope):
                cands.extend(self.calls(callee, shape, items[:v], items[v + 1 :], scope, memo))
                if len(cands) > MAX_INTERPRETATIONS:
                    raise CompileError(
                        f"too many interpretations of '{S.describe(items)}'; add parentheses",
                        items[0].line,
                    )
        return cands

    def resolve_item(self, item, scope, memo):
        key = id(item)
        if key in memo:
            return memo[key]
        if isinstance(item, S.Str):
            result = [Lit(TEXT, item.value)]
        elif isinstance(item, S.Group):
            result = self.resolve_seq(item.items, scope, memo)
        else:
            result = []
            for b in scope.lookup(item.text):
                ref = FnRef(b) if isinstance(b, FnDecl) else VarRef(b)
                result.append(ref)
                # A function taking no arguments may also be called.
                if isinstance(b.type, FnType) and not b.type.params:
                    callee = b if isinstance(b, FnDecl) else ref
                    result.append(Call(callee, {}, b.type.ret))
            for parser in scope.all_literal_parsers():
                lit = parser(item.text)
                if lit is not None:
                    result.append(lit)
        memo[key] = result
        return result

    def callees(self, name, scope):
        for b in scope.lookup(name):
            if isinstance(b.type, FnType):
                yield (b if isinstance(b, FnDecl) else VarRef(b)), b.type

    def calls(self, callee, shape, before, after, scope, memo):
        """Interpretations of `before verb after` as a call with this shape.

        The subject, if any, must come before the verb.
        """
        if bool(before) != ("subject" in shape.labels):
            return []
        slots = ["object"] if "object" in shape.labels else []
        named = [l for l in shape.labels if l not in ("subject", "object")]
        results = []
        for assignment in _assign(after, slots, named):
            if before:
                assignment["subject"] = before[0]
            if set(assignment) != set(shape.labels):
                continue
            options = []
            for label in shape.labels:
                want = shape.param_type(label)
                options.append(
                    [a for a in self.resolve_item(assignment[label], scope, memo) if a.type == want]
                )
            for combo in itertools.product(*options):
                results.append(Call(callee, dict(zip(shape.labels, combo)), shape.ret))
        return results


def _assign(items, slots, labels):
    """Ways to split the items after a verb into arguments.

    The positional argument (the object) comes first, then
    `label item` pairs in any order.
    """
    out = []

    def walk(i, slots_left, positional_open, acc):
        if i == len(items):
            out.append(dict(acc))
            return
        item = items[i]
        if (
            isinstance(item, S.Word)
            and item.text in labels
            and item.text not in acc
            and i + 1 < len(items)
        ):
            acc[item.text] = items[i + 1]
            walk(i + 2, slots_left, False, acc)
            del acc[item.text]
        if positional_open and slots_left:
            acc[slots_left[0]] = item
            walk(i + 1, slots_left[1:], True, acc)
            del acc[slots_left[0]]

    walk(0, list(slots), True, {})
    return out
