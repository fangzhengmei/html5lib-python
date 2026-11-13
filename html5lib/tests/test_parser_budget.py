from __future__ import absolute_import, division, unicode_literals

import io

import pytest

from . import support  # noqa

from html5lib import (
    HTMLParser, ParseBudget, ParseBudgetExceeded, parse, parseFragment
)
from html5lib.serializer import serialize


class ChunkedStringIO(io.StringIO):
    """A stream that only returns a few characters per read call"""

    def __init__(self, value, chunk_size):
        io.StringIO.__init__(self, value)
        self._chunk_size = chunk_size

    def read(self, size=-1):
        if size is None or size < 0 or size > self._chunk_size:
            size = self._chunk_size
        return io.StringIO.read(self, size)


def nested_document(depth, text="x"):
    return "".join("<div>" for _ in range(depth)) + text


def test_no_budget_returns_full_tree_and_errors():
    parser = HTMLParser()
    doc = parser.parse("<div><span>hello</span><table><td></table>")
    assert serialize(doc) is not None
    # parse errors are still recorded, not raised
    assert len(parser.errors) > 0


def test_depth_budget_document():
    budget = ParseBudget(max_depth=5)
    with pytest.raises(ParseBudgetExceeded) as excinfo:
        parse(nested_document(10), budget=budget)
    assert excinfo.value.resource == "depth"
    assert excinfo.value.limit == 5
    assert excinfo.value.actual == 6


def test_depth_budget_fragment_shares_accounting():
    # document and fragment parsing enforce the same budget
    budget = ParseBudget(max_depth=5)
    with pytest.raises(ParseBudgetExceeded) as excinfo:
        parseFragment(nested_document(10), budget=budget)
    assert excinfo.value.resource == "depth"


def test_token_budget():
    # a document with more start tags than the budget allows
    budget = ParseBudget(max_tokens=5)
    with pytest.raises(ParseBudgetExceeded) as excinfo:
        parse(nested_document(20), budget=budget)
    assert excinfo.value.resource == "tokens"
    assert excinfo.value.limit == 5


def test_text_budget():
    budget = ParseBudget(max_text=10)
    with pytest.raises(ParseBudgetExceeded) as excinfo:
        parse("<p>" + "a" * 100 + "</p>", budget=budget)
    assert excinfo.value.resource == "text"
    assert excinfo.value.limit == 10
    assert excinfo.value.actual > 10


def test_budget_accepts_dict():
    with pytest.raises(ParseBudgetExceeded) as excinfo:
        parse(nested_document(10), budget={"max_depth": 4})
    assert excinfo.value.resource == "depth"


def test_budget_not_exceeded_returns_complete_tree():
    html = nested_document(3, "hello")
    budgeted = parse(html, budget=ParseBudget(max_depth=100,
                                              max_tokens=1000,
                                              max_text=1000))
    unbudgeted = parse(html)
    assert serialize(budgeted) == serialize(unbudgeted)


def test_table_foster_parenting_consumes_budget():
    # text inside a table is foster parented (table error correction);
    # those tokens still consume the budget
    html = "<table>" + "x" * 50 + "<tr><td>cell</td></tr></table>"
    with pytest.raises(ParseBudgetExceeded) as excinfo:
        parse(html, budget={"max_text": 10})
    assert excinfo.value.resource == "text"
    with pytest.raises(ParseBudgetExceeded) as excinfo:
        parse(html, budget={"max_tokens": 6})
    assert excinfo.value.resource == "tokens"


def test_foreign_content_consumes_budget():
    # elements in the SVG/MathML foreign namespaces count towards depth
    html = ("<svg><foreignObject><div><div><div>text</div></div></div>"
            "</foreignObject></svg>")
    with pytest.raises(ParseBudgetExceeded) as excinfo:
        parse(html, budget={"max_depth": 4})
    assert excinfo.value.resource == "depth"
    # and their tokens count towards the token total
    with pytest.raises(ParseBudgetExceeded) as excinfo:
        parse(html, budget={"max_tokens": 6})
    assert excinfo.value.resource == "tokens"


@pytest.mark.parametrize("budget", [
    None,
    {"max_depth": 100, "max_tokens": 10000, "max_text": 10000},
    {"max_depth": 6},
    {"max_tokens": 9},
    {"max_text": 5},
])
def test_chunked_input_matches_one_shot(budget):
    html = "<div><p>hello <b>world</b></p><table>x<td>y</td></table></div>"
    parser_one_shot = HTMLParser(budget=budget)
    parser_chunked = HTMLParser(budget=budget)
    error_one_shot = error_chunked = None
    try:
        result_one_shot = serialize(parser_one_shot.parse(html))
    except ParseBudgetExceeded as e:
        error_one_shot = (e.resource, e.limit)
        result_one_shot = None
    try:
        result_chunked = serialize(
            parser_chunked.parse(ChunkedStringIO(html, 3)))
    except ParseBudgetExceeded as e:
        error_chunked = (e.resource, e.limit)
        result_chunked = None
    assert error_one_shot == error_chunked
    assert result_one_shot == result_chunked
    assert parser_one_shot._budgetTokens == parser_chunked._budgetTokens
    assert parser_one_shot._budgetText == parser_chunked._budgetText


def test_parser_reuse_resets_budget():
    parser = HTMLParser(budget={"max_tokens": 20})
    with pytest.raises(ParseBudgetExceeded):
        parser.parse(nested_document(50))
    # reusing the parser starts the budget afresh
    doc = parser.parse("<p>hi</p>")
    assert serialize(doc) is not None
    with pytest.raises(ParseBudgetExceeded):
        parser.parse(nested_document(50))


def test_partial_tree_not_returned():
    parser = HTMLParser(budget={"max_depth": 3})
    try:
        parser.parse(nested_document(10, "partial"))
    except ParseBudgetExceeded:
        pass
    else:
        raise AssertionError("expected ParseBudgetExceeded")
    # a subsequent parse on the same parser is unaffected
    assert serialize(parser.parse("<p>ok</p>")) is not None


def test_invalid_budget_rejected():
    with pytest.raises(ValueError):
        ParseBudget(max_depth=-1)
    with pytest.raises(ValueError):
        ParseBudget(max_tokens="many")
    with pytest.raises(TypeError):
        HTMLParser(budget=42)


def test_module_level_parse_fragment_budget():
    with pytest.raises(ParseBudgetExceeded):
        parse(nested_document(10), budget={"max_depth": 4})
    with pytest.raises(ParseBudgetExceeded):
        parseFragment(nested_document(10), budget={"max_depth": 4})
