from colors import PALETTE, parse_overrides, resolve_color


class TestParseOverrides:
    def test_empty_or_blank_returns_empty_dict(self):
        assert parse_overrides("") == {}
        assert parse_overrides("   ") == {}
        assert parse_overrides(None) == {}

    def test_parses_json_mapping(self):
        assert parse_overrides('{"dev-1": "#ff0000"}') == {"dev-1": "#ff0000"}

    def test_invalid_json_returns_empty_dict(self):
        assert parse_overrides("not json") == {}

    def test_non_mapping_json_returns_empty_dict(self):
        assert parse_overrides('["#ff0000"]') == {}

    def test_accepts_hex_and_colour_keywords(self):
        got = parse_overrides('{"a": "#f00", "b": "#4e9bff", "c": "rebeccapurple"}')
        assert got == {"a": "#f00", "b": "#4e9bff", "c": "rebeccapurple"}

    def test_rejects_values_that_could_break_out_of_a_style_attribute(self):
        got = parse_overrides('{"a": "#123456", "b": "red; } * { display:none }", "c": "url(x)"}')
        assert got == {"a": "#123456"}


class TestResolveColor:
    def test_override_by_id_wins(self):
        color = resolve_color("canonic-abc", "Phone", {"canonic-abc": "#123456"})
        assert color == "#123456"

    def test_override_by_name_when_no_id_match(self):
        color = resolve_color("canonic-abc", "Phone", {"Phone": "#abcdef"})
        assert color == "#abcdef"

    def test_id_override_takes_precedence_over_name_override(self):
        overrides = {"canonic-abc": "#111111", "Phone": "#222222"}
        assert resolve_color("canonic-abc", "Phone", overrides) == "#111111"

    def test_fallback_color_is_from_palette(self):
        assert resolve_color("canonic-abc", "Phone", {}) in PALETTE

    def test_fallback_uses_the_given_palette_index(self):
        assert resolve_color("canonic-abc", "Phone", {}, 3) == PALETTE[3]

    def test_fallback_index_wraps_around_the_palette(self):
        assert resolve_color("canonic-abc", "Phone", {}, len(PALETTE)) == PALETTE[0]

    def test_two_different_indices_give_different_colors(self):
        a = resolve_color("dev-a", "A", {}, 0)
        b = resolve_color("dev-b", "B", {}, 1)
        assert a != b

    def test_override_still_wins_over_fallback_index(self):
        assert resolve_color("dev-a", "A", {"dev-a": "#000000"}, 4) == "#000000"

    def test_explicit_override_color_wins_over_everything(self):
        color = resolve_color(
            "dev-a", "A", {"dev-a": "#111111"}, 4, override_color="#abcabc"
        )
        assert color == "#abcabc"

    def test_blank_override_color_is_ignored(self):
        assert resolve_color("dev-a", "A", {}, 2, override_color="") == PALETTE[2]
        assert resolve_color("dev-a", "A", {}, 2, override_color=None) == PALETTE[2]
