from __future__ import annotations

from model_audit.output import table_cell


def test_final_table_colors_status_without_changing_its_text():
    assert (table_cell("✓ supported").plain, table_cell("✓ supported").style) == ("✓ supported", "bold green")
    assert (table_cell("○ unsupported").plain, table_cell("○ unsupported").style) == ("○ unsupported", "yellow")
    assert (table_cell("? unknown").plain, table_cell("? unknown").style) == ("? unknown", "yellow")
    assert (table_cell("✗ mismatch").plain, table_cell("✗ mismatch").style) == ("✗ mismatch", "bold red")
    assert (table_cell("~ flaky").plain, table_cell("~ flaky").style) == ("~ flaky", "yellow")
    assert table_cell("anthropic/claude-fable-5").style == ""
