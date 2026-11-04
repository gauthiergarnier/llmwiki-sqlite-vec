import ast
from pathlib import Path


def _load_guide_text() -> str:
    guide_path = Path(__file__).resolve().parents[2] / "mcp" / "tools" / "guide.py"
    module = ast.parse(guide_path.read_text())
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "GUIDE_TEXT" for target in node.targets):
            value = ast.literal_eval(node.value)
            assert isinstance(value, str)
            return value
    raise AssertionError("GUIDE_TEXT assignment not found")


GUIDE_TEXT = _load_guide_text()


def _course_guide() -> str:
    return GUIDE_TEXT.split("## Courses\n", 1)[1].split("## Available Knowledge Bases", 1)[0]


def test_course_guide_prioritizes_teaching_over_vocabulary_hygiene():
    guide = _course_guide()

    assert "teach a model, not a list" in guide
    assert "If the lesson merely defines terms" in guide
    assert "One sustained anchor case" in guide
    assert "One contrasting case" in guide
    assert "One transfer case or question" in guide
    assert "There is no required number of new terms" in guide
    assert "Cap: roughly 5–7 new terms" not in guide


def test_course_guide_retains_product_authoring_contracts():
    guide = _course_guide()

    assert 'create_knowledge_base(name="...", kind="course")' in guide
    assert "/wiki/01-foundations/01-why-rl.md" in guide
    assert "[!SUMMARY]" in guide
    assert "`answer` as the **0-based** correct-option index" in guide
    assert "Never author completion state" in guide
    assert "`reply_to_comment`" in guide
    assert "Do not publish a lesson with any zero" in guide


def test_private_design_brief_is_not_published_as_course_content():
    guide = _course_guide()

    assert "Do not include this brief in the lesson or save it as a course page" in guide
