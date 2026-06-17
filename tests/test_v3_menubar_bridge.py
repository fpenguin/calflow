"""
v1.4.0-dev — bridge args coercion.

`cli.menubar._ns_to_python` is the `json.dumps(default=...)` fallback
that recursively converts PyObjC NSDictionary / NSArray containers to
plain Python equivalents. WKScriptMessage.body() delivers nested NS
containers; the top-level `dict(raw_args)` only unwraps one level, so
nested payloads (Aliases editor, future Recipes saves) hit
`TypeError: Object of type INSDictionaryM is not JSON serializable`
without this helper.

This file locks the helper's behaviour and includes the literal
regression from v1.4.0-dev:
    "Save failed: bad apply-targets payload:
     Object of type INSDictionaryM is not JSON serializable"

The helper is pure-Python and has no PyObjC dependency at call time
(it duck-types on `keyEnumerator` / `objectAtIndex_`), so the tests
only need `cli.menubar` to *import* — they don't need a live PyObjC.
But importing `cli.menubar` itself requires pyobjc, so the suite
still skips when pyobjc is missing (sandbox CI).

Run:
    python -m unittest tests.test_v3_menubar_bridge -v
"""

from __future__ import annotations

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class _FakeNSDict:
    """Duck-types the bits of NSDictionary that `_ns_to_python` checks."""

    def __init__(self, d):
        self._d = d

    def keyEnumerator(self):       # noqa: N802 — matches the real selector
        return iter(self._d)

    def __iter__(self):
        return iter(self._d)

    def __getitem__(self, k):
        return self._d[k]


class _FakeNSArray(list):
    """Duck-types the bits of NSArray that `_ns_to_python` checks."""

    def objectAtIndex_(self, i):   # noqa: N802 — matches the real selector
        return self[i]


class NsToPythonHelper(unittest.TestCase):
    """`_ns_to_python` shape contract."""

    @classmethod
    def setUpClass(cls):
        try:
            import cli.menubar as menubar  # noqa: F401
        except ImportError as exc:
            raise unittest.SkipTest(f"pyobjc not installed: {exc}")
        cls.menubar = menubar

    def test_nsdict_is_unwrapped_one_level(self):
        nsd = _FakeNSDict({"a": 1, "b": "two"})
        self.assertEqual(
            self.menubar._ns_to_python(nsd),
            {"a": 1, "b": "two"},
        )

    def test_nsarray_is_unwrapped(self):
        nsa = _FakeNSArray(["x", "y", "z"])
        self.assertEqual(
            self.menubar._ns_to_python(nsa),
            ["x", "y", "z"],
        )

    def test_opaque_object_falls_back_to_str(self):
        class Opaque:
            def __str__(self):
                return "opaque"
        self.assertEqual(self.menubar._ns_to_python(Opaque()), "opaque")


class JsonDumpsWithDefault(unittest.TestCase):
    """End-to-end regression for the Aliases save / remove crash."""

    @classmethod
    def setUpClass(cls):
        try:
            import cli.menubar as menubar  # noqa: F401
        except ImportError as exc:
            raise unittest.SkipTest(f"pyobjc not installed: {exc}")
        cls.menubar = menubar

    def test_nested_nsdict_raises_without_default(self):
        # The literal pre-fix failure mode: json.dumps with no
        # default= raises TypeError on a nested NS container.
        args = {"targets": _FakeNSDict({"@chrome": "Google Chrome"})}
        with self.assertRaises(TypeError) as ctx:
            json.dumps(args)
        # The pre-fix error message the user saw.
        self.assertIn("not JSON serializable", str(ctx.exception))

    def test_nested_nsdict_serialises_with_default(self):
        # The Aliases-editor payload shape: {targets: {alias: app, ...}}.
        nested = _FakeNSDict({
            "@chrome": "Google Chrome",
            "@work":   _FakeNSArray(["Chrome", "Notion"]),
        })
        args = {"targets": nested}

        out = json.dumps(args, default=self.menubar._ns_to_python)
        self.assertEqual(json.loads(out), {
            "targets": {
                "@chrome": "Google Chrome",
                "@work":   ["Chrome", "Notion"],
            },
        })

    def test_deep_nesting_recurses(self):
        # json.dumps recurses through whatever default= returns, so
        # arbitrarily-deep NS-dict trees should serialise.
        innermost = _FakeNSDict({"leaf": 42})
        middle    = _FakeNSDict({"inner": innermost})
        outer     = _FakeNSDict({"middle": middle})
        wrapper   = {"deep": outer}

        out = json.dumps(wrapper, default=self.menubar._ns_to_python)
        self.assertEqual(json.loads(out), {
            "deep": {"middle": {"inner": {"leaf": 42}}},
        })

    def test_string_keys_are_coerced(self):
        # NSString → str via str(k); guard against an NSString-like
        # key sneaking through and causing json to emit a non-string
        # key (which would then fail json.loads round-trip).
        class _FakeNSString:
            def __init__(self, s): self._s = s
            def __str__(self):     return self._s

        nsd = _FakeNSDict({_FakeNSString("@chrome"): "Google Chrome"})
        out = json.dumps(nsd, default=self.menubar._ns_to_python)
        self.assertEqual(json.loads(out), {"@chrome": "Google Chrome"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
