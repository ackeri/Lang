"""Parser from tokens to a raw syntax tree.

Only definitions have a fixed grammar. A call is kept as a flat list of items
(words, strings, parenthesized groups); splitting it into verb and arguments
needs the shapes and types of names in scope, so it happens in the resolver.
"""

from dataclasses import dataclass, field

from .errors import CompileError

POSITIONAL = ("subject", "object")


@dataclass
class Word:
    text: str
    line: int


@dataclass
class Str:
    value: str
    line: int


@dataclass
class Group:
    items: list
    line: int


@dataclass
class TypeName:
    name: str
    line: int


@dataclass
class ShapeType:
    params: list
    ret: object  # type expression or None
    line: int


@dataclass
class Param:
    label: str
    name: str
    types: list  # type expressions
    context: bool
    line: int


@dataclass
class FnDef:
    name: str
    params: list
    ret: object  # type expression or None
    body: list
    line: int


@dataclass
class Return:
    items: list  # empty for a bare `return`
    line: int


@dataclass
class Bind:
    name: str
    items: list
    line: int


@dataclass
class ExprStmt:
    items: list
    line: int


@dataclass
class Program:
    decls: list = field(default_factory=list)  # FnDef or statements, in order


def parse(tokens):
    return _Parser(tokens).program()


def describe(items):
    """Render raw items back to source-like text for error messages."""
    out = []
    for item in items:
        if isinstance(item, Word):
            out.append(item.text)
        elif isinstance(item, Str):
            out.append('"' + item.value.encode("unicode_escape").decode() + '"')
        else:
            out.append("(" + describe(item.items) + ")")
    return " ".join(out)


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self, offset=0):
        return self.tokens[self.pos + offset]

    def next(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, kind, what=None):
        tok = self.next()
        if tok.kind != kind:
            raise CompileError(f"expected {what or kind}, found {tok.text or tok.kind}", tok.line)
        return tok

    def at_word(self, text):
        tok = self.peek()
        return tok.kind == "WORD" and tok.text == text

    def program(self):
        prog = Program()
        while self.peek().kind != "EOF":
            if self.peek().kind == "INDENT":
                raise CompileError("unexpected indent", self.peek().line)
            prog.decls.append(self.statement(top_level=True))
        return prog

    def statement(self, top_level=False):
        tok = self.peek()
        if self.at_word("fn"):
            if not top_level:
                raise CompileError("nested fn definitions are not supported yet", tok.line)
            return self.fn_def()
        if self.at_word("return"):
            self.next()
            items = self.items_until_newline()
            return Return(items, tok.line)
        items = self.items_until_newline()
        if len(items) >= 2 and isinstance(items[1], Word) and items[1].text == "=":
            if not isinstance(items[0], Word):
                raise CompileError("can only bind a name with '='", tok.line)
            if len(items) == 2:
                raise CompileError(f"nothing to bind to '{items[0].text}'", tok.line)
            return Bind(items[0].text, items[2:], tok.line)
        return ExprStmt(items, tok.line)

    def items_until_newline(self):
        items = []
        while self.peek().kind != "NEWLINE":
            items.append(self.item())
        self.next()
        return items

    def item(self):
        tok = self.next()
        if tok.kind == "WORD":
            return Word(tok.text, tok.line)
        if tok.kind == "STRING":
            return Str(tok.text, tok.line)
        if tok.kind == "LPAREN":
            items = []
            while self.peek().kind != "RPAREN":
                items.append(self.item())
            self.next()
            if not items:
                raise CompileError("empty parentheses", tok.line)
            return Group(items, tok.line)
        raise CompileError(f"unexpected {tok.text or tok.kind}", tok.line)

    def fn_def(self):
        line = self.next().line
        name = self.expect("WORD", "function name").text
        params, ret = self.signature(end="COLON")
        self.expect("COLON", "':'")
        self.expect("NEWLINE", "end of line after ':'")
        self.expect("INDENT", "indented body")
        body = []
        while self.peek().kind != "DEDENT":
            body.append(self.statement())
        self.next()
        return FnDef(name, params, ret, body, line)

    def signature(self, end):
        """Parse `param; param; ... [-> type]` up to (not including) `end`."""
        params = []
        ret = None
        while self.peek().kind != end:
            if self.at_word("->"):
                self.next()
                ret = self.type_expr()
                break
            if params:
                self.expect("SEMI", "';' between parameters")
            params.append(self.param())
        labels = [p.label for p in params]
        for label in labels:
            if labels.count(label) > 1:
                raise CompileError(f"duplicate label '{label}'", params[0].line)
        return params, ret

    def param(self):
        label = self.expect("WORD", "parameter label")
        context = False
        if self.at_word("context") and self.peek(1).kind == "WORD" and self.peek(1).text not in ("is", "->"):
            self.next()
            context = True
        name = self.expect("WORD", "parameter name")
        types = []
        if self.at_word("is"):
            self.next()
            types.append(self.type_expr())
            while self.peek().kind == "COMMA":
                self.next()
                types.append(self.type_expr())
        return Param(label.text, name.text, types, context, label.line)

    def type_expr(self):
        tok = self.next()
        if tok.kind == "WORD":
            return TypeName(tok.text, tok.line)
        if tok.kind == "LPAREN" and self.at_word("fn"):
            self.next()
            params, ret = self.signature(end="RPAREN")
            self.expect("RPAREN", "')'")
            return ShapeType(params, ret, tok.line)
        raise CompileError("expected a type", tok.line)
