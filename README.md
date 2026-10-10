# Lang

An experimental language with preposition-labelled arguments and
test-defined types. See [DESIGN.md](DESIGN.md) for the design notes.

The bootstrap compiler is written in Python and emits C for gcc:

```
python3 -m langc examples/hello.lang --run      # build and run
python3 -m langc examples/hello.lang --emit-c   # show generated C
python3 -m unittest discover -s tests -t .      # run the test suite
```
