"""API-authored Markdown rejects malformed quiz blocks before persistence."""

import pytest
from pydantic import ValidationError
from services import types

VALID_QUIZ = """```quiz
questions:
  - prompt: What does koji contribute?
    options: [Enzymes, Alcohol]
    answer: 0
    explanation: Koji supplies enzymes.
```
"""

INVALID_SHORTHAND = """```quiz
Q: What does koji contribute?
- [x] Enzymes
- [ ] Alcohol
E: Koji supplies enzymes.
```
"""


@pytest.mark.parametrize(
    ("model", "extra"),
    [
        (types.CreateNote, {"filename": "lesson.md"}),
        (types.UpdateContent, {}),
    ],
)
def test_authored_content_accepts_structured_quiz(model, extra):
    body = model(content=VALID_QUIZ, **extra)

    assert body.content == VALID_QUIZ


@pytest.mark.parametrize(
    ("model", "extra"),
    [
        (types.CreateNote, {"filename": "lesson.md"}),
        (types.UpdateContent, {}),
    ],
)
def test_authored_content_rejects_quiz_shorthand(model, extra):
    with pytest.raises(ValidationError) as error:
        model(content=INVALID_SHORTHAND, **extra)

    message = str(error.value)
    assert "invalid ```quiz block" in message
    assert "required `questions:`" in message


def test_ordinary_task_list_is_not_treated_as_a_quiz():
    content = "Q: What does koji contribute?\n- [x] Enzymes\n- [ ] Alcohol\n"

    body = types.UpdateContent(content=content)

    assert body.content == content


def test_quiz_example_inside_outer_fence_is_not_validated():
    content = "````markdown\n```quiz\nquestions: []\n```\n````\n"

    body = types.UpdateContent(content=content)

    assert body.content == content
