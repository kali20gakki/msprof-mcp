from __future__ import annotations

import json
from textwrap import dedent

from msprof_mcp.tools.csv_analyze import (
    GenericCsvAnalyzer,
    KernelDetailsAnalyzer,
    OpStatisticAnalyzer,
)


def test_kernel_details_analyzer_summarizes_csv(tmp_path):
    csv_path = tmp_path / "kernel_details.csv"
    csv_path.write_text(
        dedent(
            """\
            Name,Type,Device ID,Duration(us),Wait Time(us),OP State
            MatMul,Compute,0,10,1,Dynamic
            MatMul,Compute,0,30,2,Dynamic
            AllReduce,Communication,1,5,0,Static
            """
        ),
        encoding="utf-8",
    )

    analyzer = KernelDetailsAnalyzer()
    payload = json.loads(analyzer.analyze_kernel_details(str(csv_path)))

    assert payload["total_rows"] == 3
    assert payload["summary"]["unique_operators"] == 2
    assert payload["summary"]["total_duration_us"] == 45.0
    assert payload["device_distribution"] == {"0": 2, "1": 1}
    assert payload["top_operators"][0]["operator"] == "MatMul"
    assert payload["dynamic_static_ratio"] == {
        "Dynamic": {"count": 2, "percentage": "66.67%"},
        "Static": {"count": 1, "percentage": "33.33%"},
    }


def test_get_operator_details_filters_and_limits_rows(tmp_path):
    csv_path = tmp_path / "kernel_details.csv"
    csv_path.write_text(
        dedent(
            """\
            Name,Type,Device ID,Duration(us),Wait Time(us),OP State
            MatMul,Compute,0,10,1,Dynamic
            MatMul,Compute,0,30,2,Dynamic
            AllReduce,Communication,1,5,0,Static
            """
        ),
        encoding="utf-8",
    )

    analyzer = KernelDetailsAnalyzer()
    payload = json.loads(
        analyzer.get_operator_details(
            str(csv_path),
            operator_name="MatMul",
            limit=1,
        )
    )

    assert payload["filter_criteria"] == {"operator_name": "MatMul"}
    assert payload["total_matches"] == 2
    assert payload["summary"]["returned_records"] == 1
    assert payload["summary"]["total_duration_us"] == 40.0
    assert len(payload["details"]) == 1
    assert payload["details"][0]["name"] == "MatMul"


def test_op_statistic_analyzer_covers_summary_and_detail_queries(tmp_path):
    csv_path = tmp_path / "op_statistic.csv"
    csv_path.write_text(
        dedent(
            """\
            OP Type,Core Type,Count,Total Time(us),Avg Time(us),Min Time(us),Max Time(us),Ratio(%)
            MatMul,AI_CORE,4,100,25,20,30,80
            Add,AI_CPU,2,20,10,8,12,20
            """
        ),
        encoding="utf-8",
    )

    analyzer = OpStatisticAnalyzer()
    summary_payload = json.loads(analyzer.analyze_op_statistic(str(csv_path)))
    detail_payload = json.loads(
        analyzer.get_op_type_details(
            str(csv_path),
            op_type="MatMul",
            core_type="AI_CORE",
        )
    )

    assert summary_payload["summary"]["total_time_us"] == 120.0
    assert summary_payload["summary"]["total_operator_calls"] == 6
    assert summary_payload["top_operators"][0]["op_type"] == "MatMul"
    assert summary_payload["core_type_distribution"]["AI_CORE"]["op_count"] == 1

    assert detail_payload["filter_criteria"] == {
        "op_type": "MatMul",
        "core_type": "AI_CORE",
    }
    assert detail_payload["total_matches"] == 1
    assert detail_payload["summary"]["total_calls"] == 4
    assert detail_payload["details"][0]["op_type"] == "MatMul"


def test_generic_csv_analyzer_reports_info_and_matches(tmp_path):
    csv_path = tmp_path / "generic.csv"
    csv_path.write_text(
        dedent(
            """\
            name,kind,score
            alpha,group-a,10
            beta,group-b,20
            alphonse,group-a,30
            """
        ),
        encoding="utf-8",
    )

    analyzer = GenericCsvAnalyzer()
    info_payload = json.loads(analyzer.get_csv_info(str(csv_path)))
    search_payload = json.loads(
        analyzer.search_csv_by_field(
            str(csv_path),
            field_name="name",
            field_value="alph",
            match_mode="contains",
            limit=5,
        )
    )

    assert info_payload["total_rows"] == 3
    assert info_payload["headers"] == ["name", "kind", "score"]
    assert info_payload["column_types"]["score"] == "integer"

    assert search_payload["total_matches"] == 2
    assert search_payload["returned_rows"] == 2
    assert [row["name"] for row in search_payload["matches"]] == [
        "alpha",
        "alphonse",
    ]
