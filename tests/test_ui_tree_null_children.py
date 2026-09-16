from mobilerun.tools.filters import ConciseFilter, DetailedFilter
from mobilerun.tools.formatters import IndexedFormatter
from mobilerun.tools.helpers.element_search import Filters, flatten_tree
from mobilerun.tools.ui.state import UIState


def _node(text, *, children=None, index=None):
    node = {
        "text": text,
        "boundsInScreen": {"left": 0, "top": 0, "right": 100, "bottom": 100},
    }
    if children != "missing":
        node["children"] = children
    if index is not None:
        node["index"] = index
    return node


def test_filters_treat_root_and_nested_null_children_as_empty():
    tree = _node(
        "root",
        children=[_node("null", children=None), _node("nested", children=[_node("leaf")])],
    )
    context = {"screen_bounds": {"width": 100, "height": 100}}

    concise = ConciseFilter().filter(tree, context)
    detailed = DetailedFilter().filter(tree, context)

    assert concise["children"][0]["children"] == []
    assert detailed["children"][0]["children"] == []
    assert detailed["children"][1]["children"][0]["children"] == []


def test_root_null_children_is_safe_for_all_consumers():
    tree = _node("root", children=None, index=7)
    context = {"screen_bounds": {"width": 100, "height": 100}}

    assert ConciseFilter().filter(tree, context)["children"] == []
    assert DetailedFilter().filter(tree, context)["children"] == []
    assert flatten_tree(tree) == [tree]

    formatted_text, _, elements, _ = IndexedFormatter().format(tree, {})
    assert [element["text"] for element in elements] == ["root"]
    assert "1." in formatted_text

    state = UIState(
        elements=[tree],
        formatted_text=formatted_text,
        focused_text="",
        phone_state={},
        screen_width=100,
        screen_height=100,
    )
    assert state.get_element(7) is tree
    assert state.get_element_info(7)["text"] == "root"
    assert state._collect_indices([tree]) == [7]
    assert state._collect_all([tree]) == [tree]


def test_missing_and_empty_children_preserve_valid_tree_semantics():
    tree = _node("root", children=[_node("missing", children="missing"), _node("empty", children=[])])

    filtered = ConciseFilter().filter(
        tree, {"screen_bounds": {"width": 100, "height": 100}}
    )

    assert [child["text"] for child in filtered["children"]] == ["missing", "empty"]
    assert filtered["children"][0]["children"] == []
    assert filtered["children"][1]["children"] == []


def test_formatter_and_search_handle_null_children_without_changing_order_or_indices():
    tree = _node(
        "root",
        children=[
            _node("first", children=None, index=1),
            _node("second", children=[_node("nested", children=None, index=3)], index=2),
        ],
        index=0,
    )

    assert [node["text"] for node in flatten_tree(tree)] == [
        "root",
        "first",
        "second",
        "nested",
    ]
    assert Filters.contains_child(Filters.has_text())([tree]) == [tree, tree["children"][1]]

    formatted_text, _, elements, _ = IndexedFormatter().format(tree, {})
    assert all(f"{index}." in formatted_text for index in (1, 2, 3, 4))
    assert [element["text"] for element in elements] == ["root", "first", "second", "nested"]
    assert all(element["bounds"] == "0,0,100,100" for element in elements)

    state = UIState(
        elements=[tree],
        formatted_text=formatted_text,
        focused_text="",
        phone_state={},
        screen_width=100,
        screen_height=100,
    )
    assert state.get_element(3)["text"] == "nested"
