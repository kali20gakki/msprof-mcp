"""
CSV analysis tool for kernel_details.csv files from Ascend Profiler.
"""

import json
import logging
from typing import Dict, Any, List, Optional
import pandas as pd

logger = logging.getLogger(__name__)

# Rough cap on the size of JSON payload returned to the model.
MAX_RESULT_CHARS = 100_000


class KernelDetailsAnalyzer:
    """
    Analyzer for kernel_details.csv files from Ascend Profiler.
    
    This tool provides robust analysis of kernel execution data with flexible
    field mapping to handle CSV schema variations across different profiler versions.
    """
    
    # Field name mappings to handle variations
    FIELD_MAPPINGS = {
        'step_id': ['Step Id', 'Step ID', 'step_id', 'StepId'],
        'device_id': ['Device_id', 'Device ID', 'device_id', 'DeviceId'],
        'model_id': ['Model ID', 'model_id', 'ModelId'],
        'task_id': ['Task ID', 'task_id', 'TaskId'],
        'stream_id': ['Stream ID', 'stream_id', 'StreamId'],
        'name': ['Name', 'name', 'Operator Name'],
        'type': ['Type', 'type', 'Operator Type'],
        'op_state': ['OP State', 'Op State', 'op_state', 'OpState'],
        'accelerator_core': ['Accelerator Core', 'accelerator_core', 'AcceleratorCore'],
        'start_time': ['Start Time(us)', 'Start Time (us)', 'start_time', 'StartTime'],
        'duration': ['Duration(us)', 'Duration (us)', 'duration', 'Duration'],
        'wait_time': ['Wait Time(us)', 'Wait Time (us)', 'wait_time', 'WaitTime'],
        'block_dim': ['Block Dim', 'block_dim', 'BlockDim'],
        'mix_block_dim': ['Mix Block Dim', 'mix_block_dim', 'MixBlockDim', 'Mix Block Num'],
        'hf32_eligible': ['HF32 Eligible', 'hf32_eligible', 'HF32Eligible'],
        'input_shapes': ['Input Shapes', 'input_shapes', 'InputShapes'],
        'input_data_types': ['Input Data Types', 'input_data_types', 'InputDataTypes'],
        'input_formats': ['Input Formats', 'input_formats', 'InputFormats'],
        'output_shapes': ['Output Shapes', 'output_shapes', 'OutputShapes'],
        'output_data_types': ['Output Data Types', 'output_data_types', 'OutputDataTypes'],
        'output_formats': ['Output Formats', 'output_formats', 'OutputFormats'],
    }
    
    def _find_column(self, df: pd.DataFrame, field_key: str) -> Optional[str]:
        """Find the actual column name in the DataFrame for a given field key."""
        possible_names = self.FIELD_MAPPINGS.get(field_key, [])
        for name in possible_names:
            if name in df.columns:
                return name
        return None
    
    def _safe_get_column(self, df: pd.DataFrame, field_key: str) -> Optional[pd.Series]:
        """Safely get a column from DataFrame, returning None if not found."""
        col_name = self._find_column(df, field_key)
        if col_name:
            return df[col_name]
        return None
    
    def analyze_kernel_details(self, csv_path: str) -> str:
        """
        Analyze kernel_details.csv file and provide comprehensive performance insights.
        
        SCOPE:
        - Designed for `kernel_details.csv` files from Ascend Profiler (MSProf).
        - Handles schema variations gracefully with flexible field mapping.
        
        CAPABILITIES:
        - Summary statistics (total kernels, unique operators, time ranges)
        - Top operators by duration (identify bottlenecks)
        - Device distribution analysis
        - Operator type breakdown
        - Dynamic vs Static operator ratio (if available)
        - Missing fields report
        
        PARAMETERS:
        - csv_path: Absolute path to kernel_details.csv file
        
        OUTPUT:
        Returns JSON string with analysis results including:
        - summary: Overall statistics
        - top_operators: Top 10 operators by total duration
        - device_distribution: Breakdown by device
        - operator_types: Distribution by operator type
        - dynamic_static_ratio: Ratio of dynamic/static ops (if available)
        - missing_fields: List of expected but missing fields
        """
        try:
            # Read CSV file
            df = pd.read_csv(csv_path)
            
            # Track missing fields
            missing_fields = []
            available_fields = []
            
            for field_key in self.FIELD_MAPPINGS.keys():
                col_name = self._find_column(df, field_key)
                if col_name:
                    available_fields.append(field_key)
                else:
                    missing_fields.append(field_key)
            
            # Initialize result structure
            result = {
                "file": csv_path,
                "total_rows": len(df),
                "available_fields": available_fields,
                "missing_fields": missing_fields,
                "summary": {},
                "top_operators": [],
                "device_distribution": {},
                "operator_types": {},
                "dynamic_static_ratio": None,
            }
            
            # Summary Statistics
            duration_col = self._safe_get_column(df, 'duration')
            if duration_col is not None:
                # Convert to numeric, handling any non-numeric values
                duration_numeric = pd.to_numeric(duration_col, errors='coerce')
                result["summary"]["total_duration_us"] = float(duration_numeric.sum())
                result["summary"]["avg_duration_us"] = float(duration_numeric.mean())
                result["summary"]["max_duration_us"] = float(duration_numeric.max())
                result["summary"]["min_duration_us"] = float(duration_numeric.min())
            
            name_col = self._safe_get_column(df, 'name')
            if name_col is not None:
                result["summary"]["unique_operators"] = int(name_col.nunique())
            
            # Top Operators by Duration
            if duration_col is not None and name_col is not None:
                duration_numeric = pd.to_numeric(duration_col, errors='coerce')
                op_duration = df.groupby(name_col.name)[duration_col.name].agg(['sum', 'count', 'mean']).reset_index()
                op_duration.columns = ['operator', 'total_duration_us', 'count', 'avg_duration_us']
                op_duration = op_duration.sort_values('total_duration_us', ascending=False).head(10)
                
                result["top_operators"] = [
                    {
                        "operator": row['operator'],
                        "total_duration_us": float(row['total_duration_us']),
                        "count": int(row['count']),
                        "avg_duration_us": float(row['avg_duration_us'])
                    }
                    for _, row in op_duration.iterrows()
                ]
            
            # Device Distribution
            device_col = self._safe_get_column(df, 'device_id')
            if device_col is not None:
                device_counts = device_col.value_counts().to_dict()
                result["device_distribution"] = {str(k): int(v) for k, v in device_counts.items()}
            
            # Operator Type Distribution
            type_col = self._safe_get_column(df, 'type')
            if type_col is not None:
                type_counts = type_col.value_counts().head(10).to_dict()
                result["operator_types"] = {str(k): int(v) for k, v in type_counts.items()}
            
            # Dynamic vs Static Ratio
            op_state_col = self._safe_get_column(df, 'op_state')
            if op_state_col is not None:
                # Filter out N/A values
                valid_states = op_state_col[op_state_col.notna() & (op_state_col != 'N/A')]
                if len(valid_states) > 0:
                    state_counts = valid_states.value_counts().to_dict()
                    total_valid = sum(state_counts.values())
                    result["dynamic_static_ratio"] = {
                        str(k): {
                            "count": int(v),
                            "percentage": f"{(v/total_valid*100):.2f}%"
                        }
                        for k, v in state_counts.items()
                    }
            
            return json.dumps(result, indent=2)
            
        except FileNotFoundError:
            return json.dumps({
                "error": "FILE_NOT_FOUND",
                "message": f"CSV file not found: {csv_path}"
            }, indent=2)
        except pd.errors.EmptyDataError:
            return json.dumps({
                "error": "EMPTY_FILE",
                "message": f"CSV file is empty: {csv_path}"
            }, indent=2)
        except Exception as e:
            logger.error(f"Error analyzing kernel_details.csv: {e}", exc_info=True)
            return json.dumps({
                "error": "ANALYSIS_FAILED",
                "message": str(e)
            }, indent=2)

    def get_operator_details(
        self, 
        csv_path: str, 
        operator_name: Optional[str] = None,
        operator_type: Optional[str] = None,
        limit: int = 100
    ) -> str:
        """
        Get detailed information for specific operator(s) by name or type.
        
        SCOPE:
        - Designed for `kernel_details.csv` files from Ascend Profiler (MSProf).
        - Retrieve detailed execution information for targeted analysis.
        
        USE THIS WHEN:
        - You want to drill down into a specific operator (e.g., "hcom_allReduce__318_0_1")
        - You want to analyze all operators of a certain type (e.g., "hcom_alltoall_")
        - You need detailed execution traces for performance debugging
        
        PARAMETERS:
        - csv_path: Absolute path to kernel_details.csv file
        - operator_name: Exact operator name to filter (e.g., "GroupQuantGemmActivation")
        - operator_type: Operator type to filter (e.g., "hcom_alltoall_")
        - limit: Maximum number of records to return (default 100)
        
        NOTE: You must specify at least one of operator_name or operator_type.
        
        OUTPUT:
        Returns JSON string with:
        - filter_criteria: What was searched
        - total_matches: Number of matching records
        - summary: Aggregated statistics (count, total/avg/min/max duration)
        - details: Individual execution records with all available fields
        """
        try:
            if not operator_name and not operator_type:
                return json.dumps({
                    "error": "INVALID_PARAMETERS",
                    "message": "Must specify at least one of: operator_name or operator_type"
                }, indent=2)
            
            # Read CSV file
            df = pd.read_csv(csv_path)
            
            # Build filter criteria
            filter_mask = pd.Series([True] * len(df))
            filter_criteria = {}
            
            name_col = self._safe_get_column(df, 'name')
            type_col = self._safe_get_column(df, 'type')
            
            if operator_name and name_col is not None:
                filter_mask &= (name_col == operator_name)
                filter_criteria["operator_name"] = operator_name
            
            if operator_type and type_col is not None:
                filter_mask &= (type_col == operator_type)
                filter_criteria["operator_type"] = operator_type
            
            # Apply filter
            filtered_df = df[filter_mask]
            total_matches = len(filtered_df)
            
            if total_matches == 0:
                return json.dumps({
                    "filter_criteria": filter_criteria,
                    "total_matches": 0,
                    "message": "No matching operators found"
                }, indent=2)
            
            # Calculate summary statistics
            summary = {
                "total_matches": total_matches,
                "returned_records": min(total_matches, limit)
            }
            
            duration_col = self._safe_get_column(filtered_df, 'duration')
            if duration_col is not None:
                duration_numeric = pd.to_numeric(duration_col, errors='coerce')
                summary["total_duration_us"] = float(duration_numeric.sum())
                summary["avg_duration_us"] = float(duration_numeric.mean())
                summary["max_duration_us"] = float(duration_numeric.max())
                summary["min_duration_us"] = float(duration_numeric.min())
            
            wait_time_col = self._safe_get_column(filtered_df, 'wait_time')
            if wait_time_col is not None:
                wait_time_numeric = pd.to_numeric(wait_time_col, errors='coerce')
                summary["total_wait_time_us"] = float(wait_time_numeric.sum())
                summary["avg_wait_time_us"] = float(wait_time_numeric.mean())
            
            # Get detailed records (limit to specified number)
            limited_df = filtered_df.head(limit)
            
            # Build detailed records with field mapping
            details = []
            for _, row in limited_df.iterrows():
                record = {}
                for field_key in self.FIELD_MAPPINGS.keys():
                    col_name = self._find_column(df, field_key)
                    if col_name and col_name in row.index:
                        value = row[col_name]
                        # Convert to native Python types for JSON serialization
                        if pd.notna(value):
                            if isinstance(value, (int, float)):
                                record[field_key] = float(value) if isinstance(value, float) else int(value)
                            else:
                                record[field_key] = str(value)
                        else:
                            record[field_key] = None
                details.append(record)
            
            result = {
                "filter_criteria": filter_criteria,
                "total_matches": total_matches,
                "summary": summary,
                "details": details
            }
            
            return json.dumps(result, indent=2)
            
        except FileNotFoundError:
            return json.dumps({
                "error": "FILE_NOT_FOUND",
                "message": f"CSV file not found: {csv_path}"
            }, indent=2)
        except Exception as e:
            logger.error(f"Error getting operator details: {e}", exc_info=True)
            return json.dumps({
                "error": "ANALYSIS_FAILED",
                "message": str(e)
            }, indent=2)


class OpStatisticAnalyzer:
    """
    Analyzer for op_statistic.csv files from Ascend Profiler.
    
    This tool provides analysis of operator statistics with flexible field mapping
    to handle CSV schema variations across different profiler versions.
    """
    
    # Field name mappings to handle variations
    FIELD_MAPPINGS = {
        'device_id': ['Device_id', 'Device ID', 'device_id', 'DeviceId'],
        'model_name': ['Model Name', 'model_name', 'ModelName'],
        'op_type': ['OP Type', 'Op Type', 'op_type', 'OpType', 'Type'],
        'core_type': ['Core Type', 'core_type', 'CoreType'],
        'count': ['Count', 'count', 'Call Count'],
        'total_time': ['Total Time(us)', 'Total Time (us)', 'total_time', 'TotalTime'],
        'avg_time': ['Avg Time(us)', 'Avg Time (us)', 'avg_time', 'AvgTime'],
        'min_time': ['Min Time(us)', 'Min Time (us)', 'min_time', 'MinTime'],
        'max_time': ['Max Time(us)', 'Max Time (us)', 'max_time', 'MaxTime'],
        'ratio': ['Ratio(%)', 'Ratio (%)', 'ratio', 'Ratio'],
    }
    
    def _find_column(self, df: pd.DataFrame, field_key: str) -> Optional[str]:
        """Find the actual column name in the DataFrame for a given field key."""
        possible_names = self.FIELD_MAPPINGS.get(field_key, [])
        for name in possible_names:
            if name in df.columns:
                return name
        return None
    
    def _safe_get_column(self, df: pd.DataFrame, field_key: str) -> Optional[pd.Series]:
        """Safely get a column from DataFrame, returning None if not found."""
        col_name = self._find_column(df, field_key)
        if col_name:
            return df[col_name]
        return None
    
    def analyze_op_statistic(self, csv_path: str) -> str:
        """
        Analyze op_statistic.csv file and provide operator performance statistics.
        
        SCOPE:
        - Designed for `op_statistic.csv` files from Ascend Profiler (MSProf).
        - Provides aggregated operator statistics across the profiling session.
        
        CAPABILITIES:
        - Summary statistics (total operators, total time, core type distribution)
        - Top operators by total time (identify bottlenecks)
        - Core type analysis (AI_CORE, AI_CPU, etc.)
        - Operator type distribution
        - Time ratio analysis
        
        PARAMETERS:
        - csv_path: Absolute path to op_statistic.csv file
        
        OUTPUT:
        Returns JSON string with analysis results including:
        - summary: Overall statistics
        - top_operators: Top 10 operators by total time
        - core_type_distribution: Breakdown by core type
        - operator_type_stats: Statistics grouped by operator type
        - missing_fields: List of expected but missing fields
        """
        try:
            # Read CSV file
            df = pd.read_csv(csv_path)
            
            # Track missing fields
            missing_fields = []
            available_fields = []
            
            for field_key in self.FIELD_MAPPINGS.keys():
                col_name = self._find_column(df, field_key)
                if col_name:
                    available_fields.append(field_key)
                else:
                    missing_fields.append(field_key)
            
            # Initialize result structure
            result = {
                "file": csv_path,
                "total_rows": len(df),
                "available_fields": available_fields,
                "missing_fields": missing_fields,
                "summary": {},
                "top_operators": [],
                "core_type_distribution": {},
                "operator_type_stats": [],
            }
            
            # Summary Statistics
            total_time_col = self._safe_get_column(df, 'total_time')
            count_col = self._safe_get_column(df, 'count')
            
            if total_time_col is not None:
                total_time_numeric = pd.to_numeric(total_time_col, errors='coerce')
                result["summary"]["total_time_us"] = float(total_time_numeric.sum())
                result["summary"]["avg_total_time_us"] = float(total_time_numeric.mean())
            
            if count_col is not None:
                count_numeric = pd.to_numeric(count_col, errors='coerce')
                result["summary"]["total_operator_calls"] = int(count_numeric.sum())
            
            op_type_col = self._safe_get_column(df, 'op_type')
            if op_type_col is not None:
                result["summary"]["unique_operator_types"] = int(op_type_col.nunique())
            
            # Top Operators by Total Time
            if total_time_col is not None and op_type_col is not None:
                top_ops = df.nlargest(10, total_time_col.name)
                
                result["top_operators"] = []
                for _, row in top_ops.iterrows():
                    op_info = {
                        "op_type": str(row[op_type_col.name]) if op_type_col.name in row.index else None
                    }
                    
                    # Add all available fields
                    for field_key in ['core_type', 'count', 'total_time', 'avg_time', 'min_time', 'max_time', 'ratio']:
                        col = self._safe_get_column(df, field_key)
                        if col is not None and col.name in row.index:
                            value = row[col.name]
                            if pd.notna(value):
                                if isinstance(value, (int, float)):
                                    op_info[field_key] = float(value) if isinstance(value, float) else int(value)
                                else:
                                    op_info[field_key] = str(value)
                    
                    result["top_operators"].append(op_info)
            
            # Core Type Distribution
            core_type_col = self._safe_get_column(df, 'core_type')
            if core_type_col is not None and total_time_col is not None:
                core_stats = df.groupby(core_type_col.name).agg({
                    total_time_col.name: ['sum', 'count', 'mean']
                }).reset_index()
                
                core_stats.columns = ['core_type', 'total_time_us', 'op_count', 'avg_time_us']
                
                result["core_type_distribution"] = {}
                for _, row in core_stats.iterrows():
                    core_name = str(row['core_type'])
                    result["core_type_distribution"][core_name] = {
                        "total_time_us": float(row['total_time_us']),
                        "op_count": int(row['op_count']),
                        "avg_time_us": float(row['avg_time_us'])
                    }
            
            # Operator Type Statistics (grouped summary)
            if op_type_col is not None and total_time_col is not None and count_col is not None:
                op_stats = df.groupby(op_type_col.name).agg({
                    total_time_col.name: 'sum',
                    count_col.name: 'sum'
                }).reset_index()
                
                op_stats.columns = ['op_type', 'total_time_us', 'total_calls']
                op_stats = op_stats.sort_values('total_time_us', ascending=False).head(15)
                
                result["operator_type_stats"] = [
                    {
                        "op_type": row['op_type'],
                        "total_time_us": float(row['total_time_us']),
                        "total_calls": int(row['total_calls']),
                        "avg_time_per_call_us": float(row['total_time_us'] / row['total_calls']) if row['total_calls'] > 0 else 0
                    }
                    for _, row in op_stats.iterrows()
                ]
            
            return json.dumps(result, indent=2)
            
        except FileNotFoundError:
            return json.dumps({
                "error": "FILE_NOT_FOUND",
                "message": f"CSV file not found: {csv_path}"
            }, indent=2)
        except pd.errors.EmptyDataError:
            return json.dumps({
                "error": "EMPTY_FILE",
                "message": f"CSV file is empty: {csv_path}"
            }, indent=2)
        except Exception as e:
            logger.error(f"Error analyzing op_statistic.csv: {e}", exc_info=True)
            return json.dumps({
                "error": "ANALYSIS_FAILED",
                "message": str(e)
            }, indent=2)
    
    def get_op_type_details(
        self,
        csv_path: str,
        op_type: Optional[str] = None,
        core_type: Optional[str] = None
    ) -> str:
        """
        Get detailed statistics for specific operator type(s) or core type(s).
        
        SCOPE:
        - Designed for `op_statistic.csv` files from Ascend Profiler (MSProf).
        - Retrieve detailed statistics for targeted performance analysis.
        
        USE THIS WHEN:
        - You want to analyze a specific operator type (e.g., "MatMul", "Conv2D")
        - You want to see all operators running on a specific core (e.g., "AI_CORE")
        - You need detailed performance metrics for comparison
        
        PARAMETERS:
        - csv_path: Absolute path to op_statistic.csv file
        - op_type: Operator type to filter (e.g., "MatMul")
        - core_type: Core type to filter (e.g., "AI_CORE", "AI_CPU")
        
        NOTE: You can specify both filters to narrow down results.
        
        OUTPUT:
        Returns JSON string with:
        - filter_criteria: What was searched
        - total_matches: Number of matching records
        - summary: Aggregated statistics
        - details: Individual operator statistics
        """
        try:
            # Read CSV file
            df = pd.read_csv(csv_path)
            
            # Build filter criteria
            filter_mask = pd.Series([True] * len(df))
            filter_criteria = {}
            
            op_type_col = self._safe_get_column(df, 'op_type')
            core_type_col = self._safe_get_column(df, 'core_type')
            
            if op_type and op_type_col is not None:
                filter_mask &= (op_type_col == op_type)
                filter_criteria["op_type"] = op_type
            
            if core_type and core_type_col is not None:
                filter_mask &= (core_type_col == core_type)
                filter_criteria["core_type"] = core_type
            
            # Apply filter
            filtered_df = df[filter_mask]
            total_matches = len(filtered_df)
            
            if total_matches == 0:
                return json.dumps({
                    "filter_criteria": filter_criteria,
                    "total_matches": 0,
                    "message": "No matching operators found"
                }, indent=2)
            
            # Calculate summary statistics
            summary = {
                "total_matches": total_matches
            }
            
            total_time_col = self._safe_get_column(filtered_df, 'total_time')
            count_col = self._safe_get_column(filtered_df, 'count')
            
            if total_time_col is not None:
                total_time_numeric = pd.to_numeric(total_time_col, errors='coerce')
                summary["total_time_us"] = float(total_time_numeric.sum())
                summary["avg_total_time_us"] = float(total_time_numeric.mean())
                summary["max_total_time_us"] = float(total_time_numeric.max())
                summary["min_total_time_us"] = float(total_time_numeric.min())
            
            if count_col is not None:
                count_numeric = pd.to_numeric(count_col, errors='coerce')
                summary["total_calls"] = int(count_numeric.sum())
                summary["avg_calls"] = float(count_numeric.mean())
            
            # Build detailed records
            details = []
            for _, row in filtered_df.iterrows():
                record = {}
                for field_key in self.FIELD_MAPPINGS.keys():
                    col_name = self._find_column(df, field_key)
                    if col_name and col_name in row.index:
                        value = row[col_name]
                        if pd.notna(value):
                            if isinstance(value, (int, float)):
                                record[field_key] = float(value) if isinstance(value, float) else int(value)
                            else:
                                record[field_key] = str(value)
                        else:
                            record[field_key] = None
                details.append(record)
            
            result = {
                "filter_criteria": filter_criteria,
                "total_matches": total_matches,
                "summary": summary,
                "details": details
            }
            
            return json.dumps(result, indent=2)
            
        except FileNotFoundError:
            return json.dumps({
                "error": "FILE_NOT_FOUND",
                "message": f"CSV file not found: {csv_path}"
            }, indent=2)
        except Exception as e:
            logger.error(f"Error getting op type details: {e}", exc_info=True)
            return json.dumps({
                "error": "ANALYSIS_FAILED",
                "message": str(e)
            }, indent=2)


class GenericCsvAnalyzer:
    """
    Generic CSV file analyzer for any CSV file.
    
    This tool provides basic CSV analysis capabilities without requiring
    predefined field mappings, making it suitable for exploring unknown CSV files.
    """
    
    def get_csv_info(self, csv_path: str) -> str:
        """
        Get basic information about a CSV file including headers and sample data.
        
        SCOPE:
        - Works with any CSV file format.
        - Provides quick overview of file structure.
        
        USE THIS WHEN:
        - You want to explore an unknown CSV file.
        - You need to see available columns before detailed analysis.
        - You want to understand the data structure.
        
        PARAMETERS:
        - csv_path: Absolute path to CSV file
        
        OUTPUT:
        Returns JSON string with:
        - file: File path
        - total_rows: Number of data rows (excluding header)
        - total_columns: Number of columns
        - headers: List of column names
        - sample_data: First 5 rows as examples
        - column_types: Inferred data types for each column
        """
        try:
            # Read CSV file
            df = pd.read_csv(csv_path)
            
            # Get basic info
            result = {
                "file": csv_path,
                "total_rows": len(df),
                "total_columns": len(df.columns),
                "headers": df.columns.tolist(),
                "column_types": {},
                "sample_data": []
            }
            
            # Infer column types
            for col in df.columns:
                dtype = str(df[col].dtype)
                # Try to provide more meaningful type info
                if dtype.startswith('int'):
                    result["column_types"][col] = "integer"
                elif dtype.startswith('float'):
                    result["column_types"][col] = "float"
                elif dtype == 'object':
                    # Check if it's numeric that was read as string
                    try:
                        pd.to_numeric(df[col].dropna().head(10), errors='raise')
                        result["column_types"][col] = "numeric (as string)"
                    except:
                        result["column_types"][col] = "string"
                else:
                    result["column_types"][col] = dtype
            
            # Get sample data (first 5 rows)
            sample_df = df.head(5)
            for _, row in sample_df.iterrows():
                row_data = {}
                for col in df.columns:
                    value = row[col]
                    if pd.notna(value):
                        if isinstance(value, (int, float)):
                            row_data[col] = float(value) if isinstance(value, float) else int(value)
                        else:
                            row_data[col] = str(value)
                    else:
                        row_data[col] = None
                result["sample_data"].append(row_data)

            payload_str = json.dumps(result, ensure_ascii=False)
            if len(payload_str) > MAX_RESULT_CHARS:
                return self._error(
                    "RESULT_TOO_LARGE",
                    "Result is too large to return as JSON preview. "
                )

            return payload_str
            
        except FileNotFoundError:
            return json.dumps({
                "error": "FILE_NOT_FOUND",
                "message": f"CSV file not found: {csv_path}"
            }, indent=2)
        except pd.errors.EmptyDataError:
            return json.dumps({
                "error": "EMPTY_FILE",
                "message": f"CSV file is empty: {csv_path}"
            }, indent=2)
        except Exception as e:
            logger.error(f"Error getting CSV info: {e}", exc_info=True)
            return json.dumps({
                "error": "ANALYSIS_FAILED",
                "message": str(e)
            }, indent=2)
    
    def search_csv_by_field(
        self,
        csv_path: str,
        field_name: str,
        field_value: Optional[str] = None,
        match_mode: str = "exact",
        limit: int = 100
    ) -> str:
        """
        Search CSV file by field name and optionally filter by field value.
        
        SCOPE:
        - Works with any CSV file format.
        - Supports flexible matching modes for string values.
        
        USE THIS WHEN:
        - You want to find all rows where a field matches a specific value.
        - You need to filter data based on column criteria.
        - You want to explore data in a specific column.
        
        PARAMETERS:
        - csv_path: Absolute path to CSV file
        - field_name: Column name to search in (must match exactly)
        - field_value: Value to search for (optional, if None returns all unique values)
        - match_mode: How to match field_value:
            * "exact": Exact match (default)
            * "contains": Field contains the value (case-insensitive)
            * "starts_with": Field starts with the value
            * "ends_with": Field ends with the value
        - limit: Maximum number of matching rows to return (default 100)
        
        OUTPUT:
        Returns JSON string with:
        - field_name: The field being searched
        - field_value: The value being searched (if provided)
        - match_mode: The matching mode used
        - total_matches: Number of matching rows
        - unique_values: List of unique values in the field (if field_value not provided)
        - matches: Matching rows with all columns
        """
        try:
            # Read CSV file
            df = pd.read_csv(csv_path)
            
            # Check if field exists
            if field_name not in df.columns:
                available_fields = df.columns.tolist()
                return json.dumps({
                    "error": "FIELD_NOT_FOUND",
                    "message": f"Field '{field_name}' not found in CSV",
                    "available_fields": available_fields
                }, indent=2)
            
            # If no value provided, return unique values
            if field_value is None:
                unique_vals = df[field_name].dropna().unique().tolist()
                # Convert to native Python types
                unique_vals = [
                    float(v) if isinstance(v, (float, int)) and isinstance(v, float)
                    else int(v) if isinstance(v, (float, int))
                    else str(v)
                    for v in unique_vals
                ]
                
                return json.dumps({
                    "field_name": field_name,
                    "total_unique_values": len(unique_vals),
                    "unique_values": unique_vals[:100],  # Limit to first 100
                    "note": "Showing first 100 unique values" if len(unique_vals) > 100 else "All unique values shown"
                }, indent=2)
            
            # Apply filter based on match_mode
            field_series = df[field_name].astype(str)
            
            if match_mode == "exact":
                mask = field_series == str(field_value)
            elif match_mode == "contains":
                mask = field_series.str.contains(str(field_value), case=False, na=False)
            elif match_mode == "starts_with":
                mask = field_series.str.startswith(str(field_value), na=False)
            elif match_mode == "ends_with":
                mask = field_series.str.endswith(str(field_value), na=False)
            else:
                return json.dumps({
                    "error": "INVALID_MATCH_MODE",
                    "message": f"Invalid match_mode: {match_mode}. Use 'exact', 'contains', 'starts_with', or 'ends_with'."
                }, indent=2)
            
            # Get matching rows
            filtered_df = df[mask]
            total_matches = len(filtered_df)
            
            if total_matches == 0:
                return json.dumps({
                    "field_name": field_name,
                    "field_value": field_value,
                    "match_mode": match_mode,
                    "total_matches": 0,
                    "message": "No matching rows found"
                }, indent=2)
            
            # Limit results
            limited_df = filtered_df.head(limit)
            
            # Build result rows
            matches = []
            for _, row in limited_df.iterrows():
                row_data = {}
                for col in df.columns:
                    value = row[col]
                    if pd.notna(value):
                        if isinstance(value, (int, float)):
                            row_data[col] = float(value) if isinstance(value, float) else int(value)
                        else:
                            row_data[col] = str(value)
                    else:
                        row_data[col] = None
                matches.append(row_data)
            
            result = {
                "field_name": field_name,
                "field_value": field_value,
                "match_mode": match_mode,
                "total_matches": total_matches,
                "returned_rows": len(matches),
                "matches": matches
            }

            # Guard against excessively large JSON payloads.
            payload_str = json.dumps(result, ensure_ascii=False)
            if len(payload_str) > MAX_RESULT_CHARS:
                return self._error(
                    "RESULT_TOO_LARGE",
                    (
                        "Result is too large to return as JSON preview. "
                        "Please reduce the number of rows/columns (for example by "
                        "adding a stricter LIMIT)."
                    ),
                )

            return payload_str
            
        except FileNotFoundError:
            return json.dumps({
                "error": "FILE_NOT_FOUND",
                "message": f"CSV file not found: {csv_path}"
            }, indent=2)
        except Exception as e:
            logger.error(f"Error searching CSV: {e}", exc_info=True)
            return json.dumps({
                "error": "SEARCH_FAILED",
                "message": str(e)
            }, indent=2)

    @staticmethod
    def _error(code: str, message: str) -> str:
        return json.dumps(
            {
                "error": code,
                "message": message,
            },
            ensure_ascii=False,
            indent=2,
        )


if __name__ == "__main__":
    # Example usage
    import sys
    if len(sys.argv) > 1:
        analyzer = KernelDetailsAnalyzer()
        result = analyzer.analyze_kernel_details(sys.argv[1])
        print(result)
    else:
        print("Usage: python csv_analyze.py <path_to_kernel_details.csv>")