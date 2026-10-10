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

- The subject, when the function takes one, always comes immediately before
  the verb, and is the only argument that may. (Allowing it after the verb as
  well was tried and dropped: it added interpretations without good uses.)
- Labels are not a fixed keyword list. Each function declares its own labels
  (usually prepositions: `to`, `from`, `into`, `by`, ...). Labels are ordinary
  identifiers, so `to` can still be a variable name elsewhere.

```
write "hello" to "out.txt"
3 add 4
push 1 onto list
```

- After the verb, the object (if any) comes first, followed by
  `label argument` pairs in any order.
- An expression statement must be a call: interpretations that are bare values
  (such as mentioning a function without calling it) are dropped there.
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

## Local bindings

```
x = 3 add 4
x = x add 1
```

- `name = expression` binds a local. `=` is recognised only as the second word
  of a statement, and needs spaces around it (`x=3` is a single word).
- The first binding of a name declares it with the value's type; later
  bindings of the same name in the same scope assign to it and must have the
  same type.
- Top-level bindings belong to the program's entry point and are not visible
  inside functions.

## Function definitions

```
fn add subject a is Number; object b is Number -> Number:
    return a plus b

fn write object msg is Text, Printable; to path is Text:
    ...
```

- Each parameter is `label [context] name [is Type, Type, ...]`. The label is
  the external name; the name is the internal name used in the body.
- Parameters are separated by `;`. Commas separate the types in an `is` list;
  a value must belong to every listed type (the union of their tests).
- Parameter types use the same `is` syntax as everywhere else, written inline
  in the header. `is` statements in a body remain available for locals.
- A parameter with no `is` has no requirements. That is legal but nearly
  useless: the body can do nothing with it except pass it to other
  unconstrained parameters or return it.
- Return type follows `->`.
- Functions are first-class values.

### Function shapes as types

A shape type is a function header without a body:

```
fn apply object f is (fn object n is Number -> Number); to x is Number -> Number:
    return f x
```

Because definitions and shape types share one syntax, "same shape as an
existing function" (`f is like write`) is easy to add later. A named shape is
just a name bound to such an expression. Internal names inside a shape type
are required (so `object n` is never confused with a type) but carry no
meaning beyond documentation.

### What a type guarantees

A function body is checked against its parameters' declared types, not the
concrete classes passed in. This keeps dispatch a compile-time question. A
type's guarantees come from its tests:

- Every call a test makes on `Self` values is a guaranteed operation, with the
  shape and argument types used in that call.
- The result of a guaranteed call is known only through `is` assertions in the
  tests. An unasserted result has no requirements, just like a parameter with
  no `is`.

A pure signature declaration is therefore just a test that only asserts types:

```
type Number:
    test signatures for a, b in examples:
        (a add b) is Self
        (a equals b) is Bool
    test commutative for a, b in examples:
        check (a add b) equals (b add a)
```

Inside a type, `Self` names the class being tested.

### Code generation for generic functions

Bodies are type-checked once, against declared types. Code is generated per
concrete class (monomorphization), so the C output knows every value's size
and every call target, and there is no runtime dispatch.

- A function value of a generic function must name a concrete instance; which
  one is chosen by narrowing, and an undecidable choice is an ambiguity error.
- Values whose class is only known at runtime (for example a list mixing
  classes) would need boxing and runtime dispatch. Not supported for now.

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

- `x is Number, Printable` asserts every listed type.
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
fn push object x; onto list; in context heap is Heap:
    ...

fn build in context heap is Heap:
    push 1 onto l        -- heap supplied from build's own heap
```

- The parameter must be tagged `context` in the definition, to avoid matching
  too much. The tag sits between the label and the name, since it is closely
  tied to how the label is supplied.
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

- Optional and variadic arguments.
- Memory management details beyond heaps passed as context arguments.
- How a class is declared (fields, layout).
- Whether paren-free nesting is ever allowed, and under what rules.

## Bootstrap compiler status

Milestone 1 is implemented in `langc/` (run with `python3 -m langc file.lang
--run`; tests with `python3 -m unittest discover -s tests -t .`).

- Classes: `Int` (64-bit, wrapping), `Text` (string literals only), `Nothing`.
- Built-ins: `print x` (Int or Text), `a add b`, `subtract a from b`,
  `multiply a by b`, `divide a by b`.
- Function values compile to C function pointers; generic code is not needed
  yet because all types are concrete.
- Not yet: conditionals and loops, classes, test-defined
  types, `is` in bodies, context arguments, literal parser registration.
  Integers are recognised by a built-in literal parser in the resolver, the
  same hook user-registered parsers will use.
- The `.lang` file extension is a placeholder.

## Milestones

1. Indentation lexer; parser for `fn` definitions and flat calls using
   enumerate-and-narrow; integers and text; `return`; built-in `print`; C
   output compiled with gcc.
2. Context arguments and a heap built-in.
3. Classes and `examples`; `type`/`test`; compile-time test execution; `is`.
4. Literal parser registration.
