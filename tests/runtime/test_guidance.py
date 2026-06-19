"""Tests for saga guidance placeholder pure functions."""

from __future__ import annotations

import pytest

from saga_agents.core.errors import ConfigError
from saga_agents.runtime.guidance import (
    GUIDANCE_KEYS,
    referenced_keys,
    substitute,
    validate_placeholders,
)


def test_referenced_keys_finds_namespaced_tokens() -> None:
    text = "Intro {{saga.store_description}} and {{ saga.folder_instructions }} end."
    assert referenced_keys(text) == {"store_description", "folder_instructions"}


def test_referenced_keys_empty_when_none() -> None:
    assert referenced_keys("no placeholders here") == set()


def test_validate_accepts_known_keys() -> None:
    validate_placeholders("{{saga.language}} {{saga.summary_instructions}}", source="a.md")


def test_validate_rejects_unknown_key() -> None:
    with pytest.raises(ConfigError):
        validate_placeholders("{{saga.does_not_exist}}", source="a.md")


def test_substitute_replaces_known_and_empties_missing() -> None:
    text = "Desc: {{saga.store_description}} | Folder: {{ saga.folder_instructions }}"
    out = substitute(text, {"store_description": "Family archive", "folder_instructions": ""})
    assert out == "Desc: Family archive | Folder: "


def test_substitute_leaves_non_saga_text_untouched() -> None:
    assert substitute("plain {{notsaga}} text", {}) == "plain {{notsaga}} text"


def test_guidance_keys_are_the_six() -> None:
    assert GUIDANCE_KEYS == {
        "store_description",
        "doctype_instructions",
        "metadata_instructions",
        "summary_instructions",
        "folder_instructions",
        "language",
    }
