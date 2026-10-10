import os
import subprocess
import tempfile
import textwrap
import unittest

from langc import CompileError, build, compile_to_c

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, "examples")


def run(source):
    with tempfile.TemporaryDirectory() as tmp:
        exe = build(textwrap.dedent(source), os.path.join(tmp, "prog"))
        return subprocess.run([exe], capture_output=True, text=True, check=True).stdout


class Examples(unittest.TestCase):
    def test_examples(self):
        for name in sorted(os.listdir(EXAMPLES)):
            if not name.endswith(".lang"):
                continue
            with self.subTest(name):
                with open(os.path.join(EXAMPLES, name)) as f:
                    source = f.read()
                with open(os.path.join(EXAMPLES, name[:-5] + ".out")) as f:
                    expected = f.read()
                self.assertEqual(run(source), expected)


class Programs(unittest.TestCase):
    def test_subject_before_verb(self):
        self.assertEqual(run("print (2 add 3)\n"), "5\n")

    def test_local_binding(self):
        src = """
        fn cube object n is Int -> Int:
            sq = multiply n by n
            return multiply sq by n
        x = 2 add 1
        print (cube x)
        x = x add 1
        print x
        """
        self.assertEqual(run(src), "27\n4\n")

    def test_bind_function_value(self):
        src = """
        fn square object n is Int -> Int:
            return multiply n by n
        f = square
        print (f 6)
        """
        self.assertEqual(run(src), "36\n")

    def test_subject_or_object_overload(self):
        src = """
        fn show object x is Int:
            print x
        fn show subject x is Int:
            print (x add 100)
        show 3
        3 show
        """
        self.assertEqual(run(src), "3\n103\n")

    def test_labels_in_any_order(self):
        src = """
        fn area of w is Int; by h is Int -> Int:
            return multiply w by h
        print (area by 2 of 5)
        """
        self.assertEqual(run(src), "10\n")

    def test_overload_by_type(self):
        self.assertEqual(run('print 1\nprint "one"\n'), "1\none\n")

    def test_overload_by_labels(self):
        src = """
        fn move object x is Int; to y is Int -> Int:
            return y
        fn move object x is Int; by d is Int -> Int:
            return x add d
        print (move 1 to 5)
        print (move 1 by 5)
        """
        self.assertEqual(run(src), "5\n6\n")

    def test_zero_argument_call_vs_mention_narrowed_by_type(self):
        src = """
        fn seven -> Int:
            return 7
        print seven
        """
        self.assertEqual(run(src), "7\n")

    def test_overloaded_function_value_narrowed_by_shape(self):
        src = """
        fn flip object n is Int -> Int:
            return subtract n from 0
        fn flip object t is Text -> Text:
            return t
        fn twice object f is (fn object n is Int -> Int); to x is Int -> Int:
            return f (f x)
        print (twice flip to 3)
        """
        self.assertEqual(run(src), "3\n")

    def test_label_word_can_also_be_a_variable(self):
        src = """
        fn pick object to is Int; to x is Int -> Int:
            return to
        print (pick 1 to 2)
        """
        self.assertEqual(run(src), "1\n")

    def test_text_escapes(self):
        self.assertEqual(run('print "a\\tb \\"q\\" -- not a comment"\n'), 'a\tb "q" -- not a comment\n')

    def test_recursion_reference_compiles(self):
        # No conditionals yet, so just check a self-reference resolves.
        compile_to_c("fn loop object n is Int -> Int:\n    return loop n\n")


class Errors(unittest.TestCase):
    def assertError(self, source, fragment):
        with self.assertRaises(CompileError) as cm:
            compile_to_c(textwrap.dedent(source))
        self.assertIn(fragment, str(cm.exception))

    def test_name_and_literal_both_fit(self):
        self.assertError(
            """
            fn 3 -> Int:
                return 4
            print 3
            """,
            "ambiguous",
        )

    def test_verb_position_ambiguity(self):
        # `f g`: f with object g, or g with subject f.
        self.assertError(
            """
            fn g -> Int:
                return 1
            fn f object x is (fn -> Int):
                print x
            fn g subject s is (fn object x is (fn -> Int)):
                print 2
            f g
            """,
            "ambiguous",
        )

    def test_subject_after_verb(self):
        self.assertError("print (add 2 3)\n", "no interpretation")

    def test_rebind_with_other_type(self):
        self.assertError('x = 1\nx = "a"\n', "cannot assign Text")

    def test_bind_nothing(self):
        self.assertError("x = print 1\n", "no value")

    def test_top_level_bindings_not_visible_in_functions(self):
        self.assertError("y = 1\nfn f -> Int:\n    return y\n", "unknown name 'y'")

    def test_unknown_name(self):
        self.assertError("print nope\n", "unknown name 'nope'")

    def test_declaration_order(self):
        self.assertError(
            """
            fn a -> Int:
                return b
            fn b -> Int:
                return 1
            """,
            "unknown name 'b'",
        )

    def test_type_mismatch(self):
        self.assertError(
            """
            fn square object n is Int -> Int:
                return multiply n by n
            print (square "x")
            """,
            "no interpretation",
        )

    def test_wrong_return_type(self):
        self.assertError(
            """
            fn f -> Int:
                return "x"
            """,
            "Text, but Int is expected",
        )

    def test_missing_return(self):
        self.assertError("fn f -> Int:\n    print 1\n", "must end with a return")

    def test_untyped_parameter(self):
        self.assertError("fn f object x:\n    return\n", "needs a type")

    def test_duplicate_definition(self):
        self.assertError(
            "fn f object x is Int:\n    return\nfn f object y is Int:\n    return\n",
            "already defined",
        )


if __name__ == "__main__":
    unittest.main()
