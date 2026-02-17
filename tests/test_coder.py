"""Tests for the _extract_code helper in src.agents.coder."""

from src.agents.coder import _extract_code


class TestExtractCode:
    def test_python_code_block(self):
        text = '''Here is code:
```python
print("hello")
x = 42
```
Done.'''
        assert _extract_code(text) == 'print("hello")\nx = 42'

    def test_generic_code_block(self):
        text = '''Code:
```
def foo():
    return 1
```'''
        assert _extract_code(text) == "def foo():\n    return 1"

    def test_no_code_block_returns_full_text(self):
        text = "just plain text, no blocks"
        assert _extract_code(text) == "just plain text, no blocks"

    def test_multiple_blocks_takes_first(self):
        text = '''First:
```python
x = 1
```
Second:
```python
x = 2
```'''
        assert _extract_code(text) == "x = 1"

    def test_python_block_preferred_over_generic(self):
        text = '''```python
specific = True
```

```
generic = True
```'''
        assert _extract_code(text) == "specific = True"

    def test_strips_whitespace(self):
        text = '''```python

  code_here = 1

```'''
        assert _extract_code(text) == "code_here = 1"

    def test_empty_python_block(self):
        text = '''```python
```'''
        # regex won't match with nothing between markers
        # falls through to generic or raw
        result = _extract_code(text)
        assert isinstance(result, str)

    def test_multiline_code(self):
        text = '''```python
import os
import sys

def main():
    print("hello")

if __name__ == "__main__":
    main()
```'''
        result = _extract_code(text)
        assert "import os" in result
        assert "def main():" in result
        assert 'if __name__' in result

    def test_raw_text_stripped(self):
        text = "   some code   "
        assert _extract_code(text) == "some code"
