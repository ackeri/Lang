# Language design notes

Working notes from early design discussions. Nothing here is final; entries
marked **(open)** are undecided and entries marked **(provisional)** are a
placeholder we expect to revisit.

## Goals and implementation strategy

- A small compiled language whose call syntax reads like English sentences:
  arguments are named by prepositions (or other labels) declared by each
  function.
- Types are defined by tests: a class belongs to a type if it passes every
  test of that type. Type membership is checked at compile time.
- Memory is managed manually.
- Bootstrap compiler written in Python, emitting C, compiled with gcc.
  Python is chosen for ease of development and wide availability.
- The compiler keeps its own small lowered IR between the typed AST and C so
  another backend (for example LLVM IR) can be added later as a second
  printer rather than a rewrite.

## Source layout

- Blocks are delimited by indentation. The lexer emits `INDENT`/`DEDENT`
  tokens so the parser never sees whitespace; switching to explicit
  delimiters later would only change the lexer.
- Declaration order matters: a name must be declared above its use. This lets
  the compiler work in a single pass and is what makes compile-time execution
  (tests, literal parsers) possible.
- The lexer is thin: indentation, string literals, a small set of reserved
  punctuation (`(`, `)`, `:`, `,`, quotes), and whitespace-separated words.
  Every other word is either a name in scope or is offered to the registered
  literal parsers (see below).

## Calls

General shape of a call:

```
[subject] verb [object] (label argument)*
```

- The subject may appear before the verb; no other argument may.
- The subject, when present, always comes before the object.
- Labels are not a fixed keyword list. Each function declares its own labels
  (usually prepositions: `to`, `from`, `into`, `by`, ...). Labels are ordinary
  identifiers, so `to` can still be a variable name elsewhere.

```
write "hello" to "out.txt"
3 add 4
push 1 onto list
```

- Nested calls must be parenthesized (for now). Stronger inference may relax
  this later, but parens-required is the starting point:

```
write (3 add 4) to "out.txt"
```

### Shapes

A function's *shape* is the set of argument slots it takes: whether it takes a
subject, whether it takes an object, and its labels. Shapes are structural and
built in; they are the one part of the type system that is not test-defined,
because parsing depends on them.

Every name's shape must be known (from earlier code) before the name is
called. A name whose shape is not yet known can be *mentioned* but not
*called*.

### Parsing by enumeration and narrowing

For each flat (paren-free) call, the compiler enumerates every candidate
interpretation, then narrows using shapes and types already known:

- zero candidates survive: "no matching call" error;
- exactly one survives: that is the parse;
- more than one survives: **ambiguity compile error**; the user clarifies with
  parens or a type hint.

This single rule covers:

| Situation | Handling |
|---|---|
| Which word is the verb (`f g`: `f` with object `g`, or `g` with subject `f`) | both enumerated, narrowed by types |
| Mentioning a function vs calling it | both enumerated; no special syntax |
| Overloads | each overload is another candidate |
| A name and a literal both match a word | both enumerated; ambiguity if both type-check |
| Two literal parsers accept the same word | ambiguity if both type-check |

Parenthesized sub-expressions are resolved inside-out, so narrowing at each
level only uses facts already established. How often ambiguity arises depends
on how permissive types are: stricter test-defined types narrow more.

### Overloading

Functions may be overloaded by argument shape and by argument types. Further
argument variation (optional, variadic, ...) comes later; context arguments
are described below.

## Function definitions

```
fn add subject a is Number, object b is Number -> Number:
    return a plus b

fn write object msg is Text, to path is Text:
    ...
```

- Each parameter is `label name [is Type]`. The label is the external name; the
  name is the internal name used in the body.
- Parameter types use the same `is` syntax as everywhere else, written inline
  in the header. `is` statements in a body remain available for locals.
- A parameter with no `is` is unconstrained. **(open)** Whether that means
  "generic, checked per use when monomorphized" or is an error.
- Return type follows `->`.
- Functions are first-class values.

### Function shapes as types

A shape type is a function header without a body:

```
fn apply object f is (fn object n is Number -> Number), to x is Number -> Number:
    return f x
```

Because definitions and shape types share one syntax, "same shape as an
existing function" (`f is like write`) is easy to add later. A named shape is
just a name bound to such an expression. Internal names inside a shape type
are required (so `object n` is never confused with a type) but carry no
meaning beyond documentation.

### Combining types **(open)**

Since a type is a set of tests, the intersection of two types is just the
union of their tests. Something like `n is Number and Printable` would fall
out naturally and avoids needing a comma (which already separates
parameters).

## Types

A type is a set of tests. A class belongs to a type if it passes all of the
type's tests. Membership is decided at compile time by compiling and running
the tests.

```
type Number:
    test identity:
        check (zero add one) equals one
    test commutative for a, b in examples:
        check (a add b) equals (b add a)
```

- If a class lacks a function a test uses, the test fails to compile for that
  class, which counts as failing. So interface requirements come for free.
- Test values come from the class. The standard name for a class's sample
  instances is `examples`: a function taking no arguments that returns some
  instances. Types may also reference other constructors by name (for example
  `zero`, `one`); there are no C++-style constructors.
- Compile-time test runs allocate from an arena that is discarded afterwards,
  so tests do not free memory.
- Membership is based on samples, not proof. This is an accepted part of the
  design.

### `is`

`is` is an ordinary built-in function, called with normal call syntax.

- `x is Number` where `x` is a value tests the class of `x`;
  `NewClass is Number` where the subject is a class tests the class directly.
- It does nothing at runtime; at compile time it asserts membership and narrows
  candidate interpretations.
- `is` returns its subject, so it also works as an inline type ascription:

```
write ((parse s) is Number) to f
```

- Parameters in function headers use the same syntax: `object n is Number`.

- Types are therefore compile-time values that can be passed as arguments.

## Literal parsers

A built-in lets code register a function from token to value-or-`Nothing`.
Registration lasts for the rest of the enclosing scope. Later words not
resolved as names in scope are offered to the registered parsers.

- At compile time the compiler calls the parser only to learn whether the
  token matches and what class it produces.
- The emitted C calls the parser again at runtime (for example
  `mass_parse("12kg", heap)`). The value is built at runtime, which fits manual
  memory: allocation comes from the context heap like any other. The C
  compiler's constant folding handles the simple cases.
- Integers and other built-in literals may themselves be registered parsers
  rather than special cases in the lexer.

## Context arguments

A call site may omit an argument if a matching value is found in the
enclosing lexical scope. Typical use: functions that allocate take a heap, and
callers pass their own heap implicitly.

```
fn push object x, onto list, in heap is Heap context
    ...

fn build in heap is Heap context
    push 1 onto l        -- heap supplied from build's own heap
```

- The parameter must be tagged as a context argument in the definition, to
  avoid matching too much. (Tag spelling is **provisional**.)
- Matching is by internal name **and** type. Two matching candidates are an
  ambiguity error.
- Resolution is lexical and at compile time; at runtime it is just an ordinary
  argument.
- Mentioning a function does **not** capture context arguments. The context
  parameter stays part of the function's shape, so a call through a function
  value can still elide it. (Implicit closures are too heavy for an invisible
  operation, and the compiler has no closure machinery.)
- `main` creates the root heap, probably via an import.

## Compile-time execution

Tests and literal parsers both require running user code while compiling.
Bootstrap plan: compile the declarations so far to C, build a shared library,
load it with `ctypes`, and call into it. This keeps one semantics (the C
output) rather than a separate Python interpreter for compile-time code.

## Open questions

- Spelling of the context-argument tag.
- Optional and variadic arguments.
- Memory management details beyond heaps passed as context arguments.
- How a class is declared (fields, layout).
- Whether paren-free nesting is ever allowed, and under what rules.

## Milestones

1. Indentation lexer; parser for `fn` definitions and flat calls using
   enumerate-and-narrow; integers and text; `return`; built-in `print`; C
   output compiled with gcc.
2. Context arguments and a heap built-in.
3. Classes and `examples`; `type`/`test`; compile-time test execution; `is`.
4. Literal parser registration.
