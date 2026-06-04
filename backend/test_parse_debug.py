"""Debug: test _parse_tool_calls with various inputs."""
import sys
sys.path.insert(0, '.')
from agent.loop import _parse_tool_calls
import re

def test(text, label):
    results = _parse_tool_calls(text)
    print(f"\n=== {label} ===")
    print(f"Results: {len(results)}")
    if results:
        for name, params in results:
            code = params.get("code", params.get("script", ""))
            print(f"  tool={name}, code_len={len(code)}")
    else:
        print("  NO MATCH - checking why...")
        tc = re.compile(r'<tool_call>\s*(.+?)\s*</tool_call>', re.DOTALL)
        ti = re.compile(r'<tool_input>\s*(.+?)\s*</tool_input>', re.DOTALL)
        names = tc.findall(text)
        inputs = ti.findall(text)
        print(f"  tool_call tags found: {names}")
        print(f"  tool_input tags found: {len(inputs)}")


# Test 1: simple case
test(
    """<tool_call>run</tool_call><tool_input>{"code": "print(1+1)"}</tool_output>""",
    "Simple adjacent tags"
)

# Test 2: with text before
test(
    """让我来执行这个代码。

<tool_call>run</tool_call><tool_input>{"code": "print(1+1)"}</tool_output>""",
    "Text before tags"
)

# Test 3: multi-line code in JSON
test(
    """<tool_call>run</tool_call><tool_input>{"code": "line1\\nline2\\nline3"}</tool_output>""",
    "Multi-line code with \\n"
)

# Test 4: long code
test(
    '<tool_call>run</tool_call><tool_input>{"code": "from PIL import Image, ImageDraw\\n\\nimg = Image.new(\'RGBA\', (500, 500), (0,0,0,0))\\ndraw = ImageDraw.Draw(img)\\ndraw.ellipse([50, 50, 450, 450], fill=\'black\', outline=None)\\nimg.save(\'circle.png\')\\nprint(\'done\')"}</tool_output>',
    "Long PIL code with escaped quotes"
)
