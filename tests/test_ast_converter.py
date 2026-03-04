"""Tests for src.core.ast_converter."""

from src.core.ast_converter import to_zss_tree, count_nodes


def test_empty_dict():
    tree = to_zss_tree({})
    assert tree.label == "root"
    assert tree.children == []


def test_simple_dict():
    """For a leaf value, the key label is passed as param but the node becomes VAL:..."""
    tree = to_zss_tree({"ami": "ami-123"})
    assert tree.label == "root"
    assert len(tree.children) == 1
    # Leaf: key "ami" is consumed as label param, but overridden by VAL: prefix
    assert tree.children[0].label == "VAL:ami-123"


def test_nested_dict():
    """When value is a dict, the key IS used as the node label."""
    data = {"tags": {"Name": "web", "Env": "dev"}}
    tree = to_zss_tree(data)
    tags_node = tree.children[0]
    assert tags_node.label == "tags"
    # Children are leaf values (sorted keys: Env, Name → VAL:dev, VAL:web)
    assert len(tags_node.children) == 2
    assert tags_node.children[0].label == "VAL:dev"
    assert tags_node.children[1].label == "VAL:web"


def test_list_conversion():
    """Lists with dict items produce labeled _item nodes; primitive items become VAL:."""
    data = {"items": [{"nested": "val"}, {"other": "val2"}]}
    tree = to_zss_tree(data)
    items_node = tree.children[0]
    assert items_node.label == "items"
    assert len(items_node.children) == 2
    assert items_node.children[0].label == "items_item"
    assert items_node.children[1].label == "items_item"


def test_leaf_values():
    data = {"count": 3}
    tree = to_zss_tree(data)
    # Leaf directly under root
    assert tree.children[0].label == "VAL:3"


def test_count_nodes_single():
    tree = to_zss_tree("hello")
    assert count_nodes(tree) == 1


def test_count_nodes_tree():
    # root -> VAL:ami-123 = 2 nodes (leaf value replaces key node)
    data = {"ami": "ami-123"}
    tree = to_zss_tree(data)
    assert count_nodes(tree) == 2


def test_sorted_keys():
    """Keys are sorted alphabetically; dict values preserve key as label."""
    data = {"z_key": {"a": 1}, "a_key": {"b": 2}, "m_key": {"c": 3}}
    tree = to_zss_tree(data)
    labels = [child.label for child in tree.children]
    assert labels == ["a_key", "m_key", "z_key"]
