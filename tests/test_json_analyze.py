from __future__ import annotations

import json

from msprof_mcp.tools.json_analyze import (
    CommunicationMatrixAnalyzer,
    ProfilerInfoAnalyzer,
)


def test_profiler_info_analyzer_extracts_structured_config(tmp_path):
    json_path = tmp_path / "profiler_info.json"
    json_path.write_text(
        json.dumps(
            {
                "rank_id": 7,
                "config": {
                    "common_config": {
                        "activities": ["CPU", "NPU"],
                        "record_shapes": True,
                        "profile_memory": False,
                        "with_stack": True,
                        "with_flops": False,
                        "with_modules": True,
                        "schedule": {"wait": 1, "warmup": 1, "active": 2},
                    },
                    "experimental_config": {
                        "_profiler_level": "Level1",
                        "_aic_metrics": "PipeUtilization",
                        "_l2_cache": True,
                        "_data_simplification": False,
                        "_export_type": "json",
                    },
                },
                "start_info": {
                    "freq": 1000,
                    "start_cnt": 12345,
                    "start_monotonic": 100,
                },
                "end_info": {
                    "collectionTimeEnd": 200,
                    "MonotonicTimeEnd": 300,
                },
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(ProfilerInfoAnalyzer().get_profiler_config(str(json_path)))

    assert payload["rank_id"] == 7
    assert payload["general_config"]["activities"] == ["CPU", "NPU"]
    assert payload["general_config"]["with_stack"] is True
    assert payload["scheduling"]["active"] == 2
    assert payload["experimental_config"]["export_type"] == "json"
    assert payload["runtime_info"]["freq"] == 1000


def test_communication_matrix_analyzer_reports_bottlenecks(tmp_path):
    json_path = tmp_path / "communication_matrix.json"
    json_path.write_text(
        json.dumps(
            {
                "step1": {
                    "p2p": {
                        "send-top1": {
                            "0->1": {
                                "Transit Time(ms)": 1,
                                "Transit Size(MB)": 4,
                                "Bandwidth(GB/s)": 20,
                                "Transport Type": "LOCAL",
                            }
                        }
                    },
                    "collective": {
                        "allreduce-top1": {
                            "0->1": {
                                "Transit Time(ms)": 2,
                                "Transit Size(MB)": 32,
                                "Bandwidth(GB/s)": 8,
                                "Transport Type": "HCCS",
                            },
                            "1->2": {
                                "Transit Time(ms)": 1,
                                "Transit Size(MB)": 16,
                                "Bandwidth(GB/s)": 12,
                                "Transport Type": "HCCS",
                            },
                        }
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        CommunicationMatrixAnalyzer().analyze_communication(str(json_path))
    )

    assert payload["summary"]["total_collective_ops_types"] == 1
    assert payload["summary"]["total_p2p_ops"] == 1
    assert payload["collective_stats"]["allreduce"]["count"] == 1
    assert payload["bottlenecks"]["slow_hccs_links_count"] == 1
    assert payload["bottlenecks"]["top_5_slowest_links"][0]["bandwidth_gb_s"] == 8
