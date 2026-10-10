"""Tokenizer: indentation, strings, reserved punctuation, and words.

Everything that is not whitespace, a string, or reserved punctuation is a
word. Whether a word is a name, a label, or a literal is decided later by the
resolver, not here.
"""

from dataclasses import dataclass

from .errors import CompileError

PUNCTUATION = {"(": "LPAREN", ")": "RPAREN", ":": "COLON", ";": "SEMI", ",": "COMMA"}
ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}


@dataclass
class Token:
    kind: str  # WORD STRING LPAREN RPAREN COLON SEMI COMMA NEWLINE INDENT DEDENT EOF
    text: str
    line: int

    def __repr__(self):
        return f"{self.kind}({self.text!r})@{self.line}"


def tokenize(source):
    tokens = []
    indents = [0]
    depth = 0  # paren depth; newlines inside parens are ignored
    lines = source.split("\n")
    for lineno, raw in enumerate(lines, start=1):
        line = _strip_comment(raw, lineno)
        if depth == 0:
            if not line.strip():
                continue
            if "\t" in line[: len(line) - len(line.lstrip())]:
                raise CompileError("tabs are not allowed in indentation", lineno)
            width = len(line) - len(line.lstrip(" "))
            if width > indents[-1]:
                indents.append(width)
                tokens.append(Token("INDENT", "", lineno))
            else:
                while width < indents[-1]:
                    indents.pop()
                    tokens.append(Token("DEDENT", "", lineno))
                if width != indents[-1]:
                    raise CompileError("inconsistent dedent", lineno)
        depth = _scan_line(line, lineno, tokens, depth)
        if depth == 0:
            tokens.append(Token("NEWLINE", "", lineno))
    if depth != 0:
        raise CompileError("unclosed '('", len(lines))
    end = len(lines)
    for _ in indents[1:]:
        tokens.append(Token("DEDENT", "", end))
    tokens.append(Token("EOF", "", end))
    return tokens


def _strip_comment(line, lineno):
    """Remove a `--` comment, ignoring `--` inside strings."""
    in_string = False
    i = 0
    while i < len(line):
        c = line[i]
        if in_string:
            if c == "\\":
                i += 1
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif line.startswith("--", i) and (i == 0 or line[i - 1].isspace()):
            return line[:i].rstrip()
        i += 1
    return line.rstrip()


def _scan_line(line, lineno, tokens, depth):
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if c.isspace():
            i += 1
        elif c == '"':
            value, i = _scan_string(line, i, lineno)
            tokens.append(Token("STRING", value, lineno))
        elif c in PUNCTUATION:
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth < 0:
                    raise CompileError("unmatched ')'", lineno)
            tokens.append(Token(PUNCTUATION[c], c, lineno))
            i += 1
        else:
            start = i
            while i < n and not line[i].isspace() and line[i] not in PUNCTUATION and line[i] != '"':
                i += 1
            tokens.append(Token("WORD", line[start:i], lineno))
    return depth


def _scan_string(line, i, lineno):
    out = []
    i += 1
    while i < len(line):
        c = line[i]
        if c == '"':
            return "".join(out), i + 1
        if c == "\\":
            if i + 1 >= len(line) or line[i + 1] not in ESCAPES:
                raise CompileError("unknown escape in string", lineno)
            out.append(ESCAPES[line[i + 1]])
            i += 2
        else:
            out.append(c)
            i += 1
    raise CompileError("unterminated string", lineno)
