"""
JSON analysis tool for profiler_info.json files from Ascend Profiler.
"""

import json
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class ProfilerInfoAnalyzer:
    """
    Analyzer for profiler_info_*.json files from Ascend Profiler.
    
    This tool extracts and analyzes the configuration and runtime information
    from the profiler run.
    """
    
    def get_profiler_config(self, json_path: str) -> str:
        """
        Extract configuration and runtime info from a profiler_info.json file.
        
        SCOPE:
        - Designed for `profiler_info_*.json` files.
        - Provides detailed view of profiler settings and execution timing.
        
        USE THIS WHEN:
        - You want to check what settings were used for a profiling run (e.g., with_stack, record_shapes).
        - You need to verify the scheduling parameters (wait/active/warmup loops).
        - You want runtime information like start/end times and rank ID.
        
        PARAMETERS:
        - json_path: Absolute path to profiler_info_*.json file
        
        OUTPUT:
        Returns JSON string with:
        - general_config: Common settings (activities, memory profile, stack trace, etc.)
        - scheduling: Schedule parameters (wait, active, warmup, etc.)
        - experimental_config: Advanced settings (AIC metrics, L2 cache, export type)
        - runtime_info: Start/End times, frequency, and rank ID
        - raw_content: The full content of the JSON file (optional if requested, but method returns structured summary by default)
        """
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
            
            # Navigate the JSON structure safely
            config = data.get('config', {})
            common_config = config.get('common_config', {})
            experimental_config = config.get('experimental_config', {})
            start_info = data.get('start_info', {})
            end_info = data.get('end_info', {})
            rank_id = data.get('rank_id')
            
            # Construct a structured summary
            result = {
                "file": json_path,
                "rank_id": rank_id,
                "general_config": {
                    "activities": common_config.get('activities', []),
                    "record_shapes": common_config.get('record_shapes'),
                    "profile_memory": common_config.get('profile_memory'),
                    "with_stack": common_config.get('with_stack'),
                    "with_flops": common_config.get('with_flops'),
                    "with_modules": common_config.get('with_modules'),
                },
                "scheduling": common_config.get('schedule', {}),
                "experimental_config": {
                    "profiler_level": experimental_config.get('_profiler_level'),
                    "aic_metrics": experimental_config.get('_aic_metrics'),
                    "l2_cache": experimental_config.get('_l2_cache'),
                    "data_simplification": experimental_config.get('_data_simplification'),
                    "export_type": experimental_config.get('_export_type'),
                },
                "runtime_info": {
                    "freq": start_info.get('freq'),
                    "start_cnt": start_info.get('start_cnt'),
                    "start_monotonic": start_info.get('start_monotonic'),
                    "collection_time_end": end_info.get('collectionTimeEnd'),
                    "monotonic_time_end": end_info.get('MonotonicTimeEnd'),
                }
            }
            
            # Calculate duration if possible
            if start_info.get('start_cnt') and end_info.get('collectionTimeEnd') and start_info.get('freq'):
                 # Note: Time units might vary, simple diff calculation here if applicable
                 # Usually collectionTimeEnd is nanoseconds, start_cnt is cycles.
                 # Duration calculation depends on specific format interpretation.
                 # For now, just return raw values.
                 pass

            return json.dumps(result, indent=2)
            
        except FileNotFoundError:
            return json.dumps({
                "error": "FILE_NOT_FOUND",
                "message": f"JSON file not found: {json_path}"
            }, indent=2)
        except json.JSONDecodeError:
            return json.dumps({
                "error": "INVALID_JSON",
                "message": f"File is not a valid JSON: {json_path}"
            }, indent=2)
        except Exception as e:
            logger.error(f"Error analyzing profiler info: {e}", exc_info=True)
            return json.dumps({
                "error": "ANALYSIS_FAILED",
                "message": str(e)
            }, indent=2)


class CommunicationMatrixAnalyzer:
    """
    Analyzer for communication_matrix.json files from Ascend Profiler.
    
    This tool analyzes the point-to-point (P2P) and collective communication performance.
    """
    
    def analyze_communication(self, json_path: str) -> str:
        """
        Analyze communication matrix to find bottlenecks and performance stats.
        
        SCOPE:
        - Designed for `communication_matrix.json` files.
        - Analyzes P2P and Collective communication performance.
        
        USE THIS WHEN:
        - You want to identify slow communication links between devices.
        - You need to check bandwidth utilization for collective operations (AllReduce, AllGather, etc.).
        - You want to compare transport types (HCCS vs LOCAL).
        
        PARAMETERS:
        - json_path: Absolute path to communication_matrix.json file
        
        OUTPUT:
        Returns JSON string with:
        - summary: Total operations, total data volume, etc.
        - collective_stats: Statistics for each collective operation type (count, avg throughput, etc.)
        - link_analysis: Performance analysis of communication links (bandwidth, latency)
        - bottlenecks: Identified slow operations or links
        """
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
            
            # Combine all steps
            combined_data = {"p2p": {}, "collective": {}}
            
            for step_key, step_data in data.items():
                # Merge P2P data
                p2p = step_data.get('p2p', {})
                for op_name, links in p2p.items():
                    if op_name not in combined_data['p2p']:
                        combined_data['p2p'][op_name] = {}
                    # Simple merge for now, could be more sophisticated
                    combined_data['p2p'][op_name].update(links)
                    
                # Merge Collective data
                collective = step_data.get('collective', {})
                for op_name, links in collective.items():
                    if op_name not in combined_data['collective']:
                        combined_data['collective'][op_name] = {}
                    combined_data['collective'][op_name].update(links)
            
            # Analyze Collective Communication
            collective_ops = combined_data.get('collective', {})
            collective_stats = {}
            top_slow_links = []
            
            for op_id, links in collective_ops.items():
                # Parse op name to get type (e.g., "allreduce-top1@..." -> "allreduce")
                op_type = op_id.split('-')[0].split('@')[0]
                
                if op_type not in collective_stats:
                    collective_stats[op_type] = {
                        "count": 0,
                        "total_time_ms": 0,
                        "total_size_mb": 0,
                        "avg_bandwidth_gb_s": 0,
                        "transport_types": set()
                    }
                
                stat = collective_stats[op_type]
                stat["count"] += 1
                
                # Aggregate link stats for this op
                op_total_time = 0
                op_total_size = 0
                bandwidths = []
                
                for link_id, metrics in links.items():
                    transit_time = metrics.get('Transit Time(ms)', 0)
                    transit_size = metrics.get('Transit Size(MB)', 0)
                    bandwidth = metrics.get('Bandwidth(GB/s)', 0)
                    transport_type = metrics.get('Transport Type', 'UNKNOWN')
                    
                    op_total_time += transit_time
                    op_total_size += transit_size
                    bandwidths.append(bandwidth)
                    stat["transport_types"].add(transport_type)
                    
                    # Check for bottlenecks (arbitrary threshold, e.g., < 10 GB/s for HCCS)
                    if transport_type == 'HCCS' and bandwidth < 10:
                        top_slow_links.append({
                            "op_id": op_id,
                            "link": link_id,
                            "bandwidth_gb_s": bandwidth,
                            "transit_time_ms": transit_time
                        })

                stat["total_time_ms"] += op_total_time
                stat["total_size_mb"] += op_total_size
                if bandwidths:
                    stat["avg_bandwidth_gb_s"] = (stat["avg_bandwidth_gb_s"] * (stat["count"] - 1) + (sum(bandwidths) / len(bandwidths))) / stat["count"]

            # Format transport types for JSON output
            for op_type in collective_stats:
                collective_stats[op_type]["transport_types"] = list(collective_stats[op_type]["transport_types"])
            
            # Sort slow links
            top_slow_links.sort(key=lambda x: x['bandwidth_gb_s'])
            
            result = {
                "file": json_path,
                "summary": {
                    "total_collective_ops_types": len(collective_stats),
                    "total_p2p_ops": len(combined_data.get('p2p', {}))
                },
                "collective_stats": collective_stats,
                "bottlenecks": {
                    "slow_hccs_links_count": len(top_slow_links),
                    "top_5_slowest_links": top_slow_links[:5]
                }
            }
            
            return json.dumps(result, indent=2)
            
        except FileNotFoundError:
            return json.dumps({
                "error": "FILE_NOT_FOUND",
                "message": f"JSON file not found: {json_path}"
            }, indent=2)
        except json.JSONDecodeError:
            return json.dumps({
                "error": "INVALID_JSON",
                "message": f"File is not a valid JSON: {json_path}"
            }, indent=2)
        except Exception as e:
            logger.error(f"Error analyzing communication matrix: {e}", exc_info=True)
            return json.dumps({
                "error": "ANALYSIS_FAILED",
                "message": str(e)
            }, indent=2)

class CommunicationAnalyzer:
    def analyze_communication_trace(self, json_path: str) -> str:
        """
        Analyze communication.json to extract detailed communication metrics.
        
        SCOPE:
        - Designed for `communication.json` files (distinct from communication_matrix.json).
        - Provides detailed view of communication time and bandwidth metrics per operation.
        
        USE THIS WHEN:
        - You want to study the time breakdown (wait vs. transit vs. idle) of communication ops.
        - You need to analyze bandwidth usage across different transport types (HCCS, RDMA, SDMA, etc.).
        - You want to find specific operations with high wait times or low bandwidth.
        
        PARAMETERS:
        - json_path: Absolute path to communication.json file
        
        OUTPUT:
        Returns JSON string with:
        - summary: Total ops, total time involved.
        - bandwidth_stats: Max and Average bandwidth per transport type.
        - time_stats: Aggregated time metrics (Transit, Wait, Synchronization).
        - bottlenecks: Top operations with highest wait time.
        """
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
            
            total_ops = 0
            transport_stats = {}  # key: transport_type, value: {count, total_bw, max_bw, total_size, total_transit_time}
            time_metrics = {
                "total_elapse_ms": 0,
                "total_transit_ms": 0,
                "total_wait_ms": 0,
                "total_sync_ms": 0,
                "total_idle_ms": 0
            }
            operations_list = []
            
            # Helper to update transport stats
            def update_transport_stat(t_type, bw, size, time):
                if t_type not in transport_stats:
                    transport_stats[t_type] = {
                        "count": 0, 
                        "total_bw": 0, 
                        "max_bw": 0, 
                        "total_size": 0,
                        "total_transit_time": 0
                    }
                s = transport_stats[t_type]
                s["count"] += 1
                s["total_bw"] += bw
                s["max_bw"] = max(s["max_bw"], bw)
                s["total_size"] += size
                s["total_transit_time"] += time

            for step_key, step_data in data.items():
                if not isinstance(step_data, dict):
                    continue
                # Process both p2p and collective
                for group_key in ['p2p', 'collective']:
                    group_data = step_data.get(group_key, {})
                    if not isinstance(group_data, dict):
                        continue
                    for op_name, op_info in group_data.items():
                        total_ops += 1
                        
                        # Process Time Info
                        time_info = op_info.get("Communication Time Info", {})
                        elapse_ms = time_info.get("Elapse Time(ms)", 0)
                        transit_ms = time_info.get("Transit Time(ms)", 0)
                        wait_ms = time_info.get("Wait Time(ms)", 0)
                        sync_ms = time_info.get("Synchronization Time(ms)", 0)
                        idle_ms = time_info.get("Idle Time(ms)", 0)
                        
                        time_metrics["total_elapse_ms"] += elapse_ms
                        time_metrics["total_transit_ms"] += transit_ms
                        time_metrics["total_wait_ms"] += wait_ms
                        time_metrics["total_sync_ms"] += sync_ms
                        time_metrics["total_idle_ms"] += idle_ms
                        
                        operations_list.append({
                            "op_name": op_name,
                            "group": group_key,
                            "wait_ms": wait_ms,
                            "transit_ms": transit_ms,
                            "elapse_ms": elapse_ms,
                            "bandwidth_info": {}
                        })
                        
                        # Process Bandwidth Info
                        bw_info = op_info.get("Communication Bandwidth Info", {})
                        current_op_bw = {}
                        for t_type, t_data in bw_info.items():
                            # Check if t_type was actually used (size > 0 or bandwidth > 0)
                            # Some JSONs have empty dicts or 0 values for unused transports
                            if isinstance(t_data, dict):
                                size = t_data.get("Transit Size(MB)", 0)
                                bw = t_data.get("Bandwidth(GB/s)", 0)
                                t_time = t_data.get("Transit Time(ms)", 0)
                                
                                if size > 0 or bw > 0:
                                    update_transport_stat(t_type, bw, size, t_time)
                                    current_op_bw[t_type] = {
                                        "bandwidth_gb_s": bw,
                                        "size_mb": size
                                    }
                        
                        operations_list[-1]["bandwidth_info"] = current_op_bw

            # Finalize transport stats
            final_transport_stats = {}
            for t_type, s in transport_stats.items():
                avg_bw = s["total_bw"] / s["count"] if s["count"] > 0 else 0
                final_transport_stats[t_type] = {
                    "usage_count": s["count"],
                    "avg_bandwidth_gb_s": avg_bw,
                    "max_bandwidth_gb_s": s["max_bw"],
                    "total_transit_size_mb": s["total_size"],
                    "avg_transit_time_ms": s["total_transit_time"] / s["count"] if s["count"] > 0 else 0
                }

            # Identify bottlenecks (Top 5 by wait time)
            top_wait_ops = sorted(operations_list, key=lambda x: x["wait_ms"], reverse=True)[:5]
            
            result = {
                "file": json_path,
                "summary": {
                    "total_operations": total_ops,
                    "total_elapse_time_ms": time_metrics["total_elapse_ms"],
                    "total_wait_time_ms": time_metrics["total_wait_ms"],
                    "avg_wait_time_ms": time_metrics["total_wait_ms"] / total_ops if total_ops > 0 else 0
                },
                "transport_stats": final_transport_stats,
                "time_breakdown_ms": time_metrics,
                "top_5_high_wait_ops": top_wait_ops
            }
            
            return json.dumps(result, indent=2)
            
        except FileNotFoundError:
            return json.dumps({
                "error": "FILE_NOT_FOUND",
                "message": f"JSON file not found: {json_path}"
            }, indent=2)
        except json.JSONDecodeError:
            return json.dumps({
                "error": "INVALID_JSON",
                "message": f"File is not a valid JSON: {json_path}"
            }, indent=2)
        except Exception as e:
            logger.error(f"Error analyzing communication trace: {e}", exc_info=True)
            return json.dumps({
                "error": "ANALYSIS_FAILED",
                "message": str(e)
            }, indent=2)



if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        analyzer = ProfilerInfoAnalyzer()
        print(analyzer.get_profiler_config(sys.argv[1]))
    else:
        print("Usage: python json_analyze.py <path_to_profiler_info.json>")
