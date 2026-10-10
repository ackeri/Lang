"""C code generation from the typed program."""

from .builtins import RUNTIME
from .resolve import Call, FnDecl, FnRef, Lit, TBind, TExprStmt, TReturn, VarRef, mangle
from .types import TEXT, FnType


class CGen:
    def __init__(self):
        self.typedefs = {}  # FnType -> C typedef name
        self.typedef_lines = []

    def ctype(self, t):
        if not isinstance(t, FnType):
            return t.ctype
        if t not in self.typedefs:
            args = ", ".join(self.ctype(pt) for _, pt in t.params) or "void"
            name = f"fn_t{len(self.typedefs) + 1}"
            ret = self.ctype(t.ret)
            self.typedefs[t] = name
            self.typedef_lines.append(f"typedef {ret} (*{name})({args});")
        return self.typedefs[t]

    def signature(self, decl):
        cparams = {label: f"{self.ctype(t)} v_{mangle(name)}" for label, name, t in decl.params}
        args = ", ".join(cparams[label] for label in decl.type.labels) or "void"
        return f"static {self.ctype(decl.type.ret)} {decl.cname}({args})"

    def generate(self, program):
        protos = [self.signature(f.decl) + ";" for f in program.functions]
        bodies = []
        for f in program.functions:
            bodies.append(self.signature(f.decl) + " {")
            bodies.extend(self.stmt(s) for s in f.body)
            bodies.append("}\n")
        main = ["int main(void) {"]
        main.extend(self.stmt(s) for s in program.main)
        main.append("    return 0;\n}")
        parts = [
            RUNTIME.strip(),
            "\n".join(self.typedef_lines),
            "\n".join(protos),
            "\n".join(bodies),
            "\n".join(main),
        ]
        return "\n\n".join(p for p in parts if p) + "\n"

    def stmt(self, s):
        if isinstance(s, TReturn):
            return "    return;" if s.value is None else f"    return {self.expr(s.value)};"
        if isinstance(s, TBind):
            decl = f"{self.ctype(s.var.type)} " if s.new else ""
            return f"    {decl}{s.var.cname} = {self.expr(s.value)};"
        assert isinstance(s, TExprStmt)
        return f"    {self.expr(s.expr)};"

    def expr(self, e):
        if isinstance(e, Lit):
            if e.type == TEXT:
                return _c_string(e.value)
            return f"INT64_C({e.value})" if e.value != -(2**63) else "INT64_MIN"
        if isinstance(e, VarRef):
            return e.var.cname
        if isinstance(e, FnRef):
            return e.decl.cname
        assert isinstance(e, Call)
        if isinstance(e.callee, FnDecl):
            fn = e.callee.cname
        else:
            fn = f"({self.expr(e.callee)})"
        args = ", ".join(self.expr(e.args[label]) for label in e.callee.type.labels)
        return f"{fn}({args})"


def _c_string(value):
    out = ['"']
    for ch in value.encode("utf-8"):
        c = chr(ch)
        if c == '"' or c == "\\":
            out.append("\\" + c)
        elif 32 <= ch < 127:
            out.append(c)
        else:
            out.append(f"\\{ch:03o}")
    out.append('"')
    return "".join(out)


def generate(program):
    return CGen().generate(program)
