"""Tests for the MCP server tools."""

from __future__ import annotations

from delonghi_mcp.server import _resolve_recipe_id


def test_resolve_recipe_id_exact() -> None:
    assert _resolve_recipe_id("espresso") == 0x01
    assert _resolve_recipe_id("regular coffee") == 0x02
    assert _resolve_recipe_id("cappuccino") == 0x07


def test_resolve_recipe_id_case_insensitive() -> None:
    assert _resolve_recipe_id("Espresso") == 0x01
    assert _resolve_recipe_id("CAPPUCCINO") == 0x07
    assert _resolve_recipe_id("Flat White") == 0x0A


def test_resolve_recipe_id_fuzzy() -> None:
    assert _resolve_recipe_id("latte-macchiato") == 0x08
    assert _resolve_recipe_id("latte_macchiato") == 0x08
    assert _resolve_recipe_id("caffe latte") == 0x09


def test_resolve_recipe_id_partial() -> None:
    assert _resolve_recipe_id("espresso") == 0x01
    assert _resolve_recipe_id("americano") == 0x06


def test_resolve_recipe_id_not_found() -> None:
    assert _resolve_recipe_id("mocha") is None
    assert _resolve_recipe_id("xyz") is None
