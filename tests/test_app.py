from progression_heatmap.app import _aggregation_filter_values


def test_aggregation_filter_values_normalize_all_selected_to_no_filter() -> None:
    all_options = ("android", "ios", "uwp")

    assert _aggregation_filter_values(all_options, all_options) == ()
    assert _aggregation_filter_values((), all_options) == ()
    assert _aggregation_filter_values(("ios", "android"), all_options) == ("android", "ios")
