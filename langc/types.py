"""Types known to the bootstrap compiler.

For now a type is either a built-in class or a function shape. Test-defined
types come in a later milestone.
"""

from dataclasses import dataclass

POSITIONAL = ("subject", "object")


@dataclass(frozen=True)
class Class:
    name: str
    ctype: str

    def __str__(self):
        return self.name


INT = Class("Int", "int64_t")
TEXT = Class("Text", "const char *")
NOTHING = Class("Nothing", "void")

CLASSES = {c.name: c for c in (INT, TEXT, NOTHING)}


def canonical_order(labels):
    """Subject, then object, then other labels alphabetically.

    Shapes compare by label set, so argument order in C must not depend on
    the order labels were written in.
    """
    head = [l for l in POSITIONAL if l in labels]
    return head + sorted(l for l in labels if l not in POSITIONAL)


@dataclass(frozen=True)
class FnType:
    params: tuple  # ((label, type), ...) in canonical order
    ret: object

    @staticmethod
    def make(params, ret):
        types = dict(params)
        return FnType(tuple((l, types[l]) for l in canonical_order(types)), ret)

    @property
    def labels(self):
        return [l for l, _ in self.params]

    def param_type(self, label):
        return dict(self.params)[label]

    def __str__(self):
        parts = "; ".join(f"{l} _ is {t}" for l, t in self.params)
        ret = "" if self.ret == NOTHING else f" -> {self.ret}"
        sep = " " if parts else ""
        return f"(fn{sep}{parts}{ret})"
