import ast
import pytest
from agent.agents.coder import extract_clean_code

def test_extract_clean_code_from_markdown_fences():
    """Verify that conversational prose before and after markdown code blocks is removed."""
    proposal = """To implement a bubble sort algorithm in the `sort.py` file, we need to define a function that sorts a list using the bubble sort method. Bubble sort is a simple sorting algorithm that repeatedly steps through the list, compares adjacent elements, and swaps them if they are in the wrong order.

Here's how you can implement this:

1. **Define the `bubble_sort` function**:
   - It will take a list as an argument.

Here's the complete code for `sort.py`:

```python
# sort.py

def bubble_sort(arr):
    n = len(arr)
    for i in range(n):
        swapped = False
        for j in range(0, n - i - 1):
            if arr[j] > arr[j + 1]:
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
                swapped = True
        if not swapped:
            break
    return arr
```

### Explanation:
- **Outer Loop**: Iterates over each element in the list.
- **Inner Loop**: Compares adjacent elements.
"""
    cleaned = extract_clean_code(proposal, "sort.py")
    assert "To implement a bubble sort algorithm" not in cleaned
    assert "### Explanation:" not in cleaned
    assert "```" not in cleaned
    assert "def bubble_sort(arr):" in cleaned
    
    # Must parse cleanly without syntax errors
    parsed = ast.parse(cleaned)
    assert parsed is not None

def test_extract_clean_code_already_clean():
    """Verify that already clean python code is preserved."""
    clean_code = """import math

def calculate_area(radius):
    return math.pi * radius * radius
"""
    result = extract_clean_code(clean_code, "math_utils.py")
    assert result == clean_code.strip()
    parsed = ast.parse(result)
    assert parsed is not None

def test_extract_clean_code_multiple_blocks():
    """Verify that the appropriate language block is selected when multiple blocks exist."""
    proposal = """Here is the bash command to run it:
```bash
python -m sort
```

And here is the python implementation:
```python
def bubble_sort(arr):
    return sorted(arr)
```
"""
    result = extract_clean_code(proposal, "sort.py")
    assert "python -m sort" not in result
    assert "def bubble_sort(arr):" in result
    parsed = ast.parse(result)
    assert parsed is not None
