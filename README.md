# msprof mcp

## 简介
msprof mcp 是一个基于 Model Context Protocol (MCP) 的服务器，旨在为大语言模型 (LLM) 提供分析 Ascend PyTorch Profiler 采集性能数据的能力。通过一系列内置工具，它可以帮助用户快速定位性能瓶颈、分析算子耗时、查看通信开销以及进行 Trace 数据的深度查询。

## 目录结构
```
msprof_mcp/
├── pyproject.toml            # 项目配置文件 (build-system, dependencies)
├── src/
│   └── msprof_mcp/
│       ├── __init__.py
│       ├── server.py                 # MCP 服务器入口
│       └── tools/                    # 工具包
│           ├── msprof_analyze_cmd.py
│           ├── csv_analyze.py
│           ├── json_analyze.py
│           └── trace_view/
└── README.md
```

## MCP 能力说明

本服务提供以下核心能力，支持多维度性能数据分析。您可以直接在对话中使用自然语言（如示例 Prompt）来调用这些工具。

### 1. 总体分析 （msprof-analyze）

| 工具名称 | 描述 | 示例 Prompt |
| :--- | :--- | :--- |
| `msprof_analyze_advisor` | 调用 `msprof-analyze advisor` 提供全方位性能建议（计算/调度瓶颈）。 | "分析 `/path/to/data` 目录下的性能数据，找出主要瓶颈。" |

### 2. TimeLine 分析 (trace_view)

| 工具名称 | 描述 | 示例 Prompt |
| :--- | :--- | :--- |
| `analyze_overlap` | 分析计算、通信与调度的重叠情况，判断负载特征（计算/通信密集型）。 | "分析 `/path/to/trace_view.json` 的计算和通信重叠情况。" |
| `find_slices` | 搜索 Trace 中的特定 Slice（算子/函数），支持模糊匹配和时间范围过滤。 | "在 `/path/to/trace_view.json` 中查找所有 'MatMul' 算子。" |
| `execute_sql_query` | 执行自定义 SQL 查询，支持 Slice/Thread/Process 等表的深度分析。 | "对 `/path/to/trace_view.json` 执行 SQL 查询，统计耗时超过 1ms 的 Slice 数量。" |

### 3. 算子性能分析 (CSV)

| 工具名称 | 描述 | 示例 Prompt |
| :--- | :--- | :--- |
| `analyze_kernel_details` | 分析 `kernel_details.csv`，提供耗时分布、Top N 算子、设备分布等。 | "分析 `/path/to/kernel_details.csv`，列出耗时最长的 10 个算子。" |
| `get_operator_details` | 查询特定算子（按名称或类型）的详细执行信息。 | "从 `/path/to/kernel_details.csv` 中获取 'FlashAttention' 算子的详细信息。" |
| `analyze_op_statistic` | 分析 `op_statistic.csv`，提供调用次数、总耗时及 Core 类型分布。 | "统计 `/path/to/op_statistic.csv` 中的算子调用次数和总耗时。" |
| `get_op_type_details` | 查询特定类型算子或 Core 类型算子的详细统计数据。 | "查看 `/path/to/op_statistic.csv` 中所有 'AI_CORE' 类型的算子统计。" |
| `search_csv_by_field` | 通用 CSV 字段搜索工具，支持按列值过滤。 | "在 `/path/to/file.csv` 的 'Name' 列中搜索包含 'Conv' 的行。" |

### 4. 通信性能分析 (JSON)

| 工具名称 | 描述 | 示例 Prompt |
| :--- | :--- | :--- |
| `analyze_communication` | 分析 `communication_matrix.json`，识别 P2P/集合通信瓶颈及慢链路。 | "分析 `/path/to/communication_matrix.json`，找出带宽利用率低的链路。" |
| `analyze_communication_trace` | 分析 `communication.json`，提供通信操作的时间分解（Transit, Wait）和带宽详情。 | "分析 `/path/to/communication.json`，查看通信操作的等待时间分布。" |

### 5. 配置信息查询

| 工具名称 | 描述 | 示例 Prompt |
| :--- | :--- | :--- |
| `get_profiler_config` | 获取 `profiler_info.json` 中的配置信息（版本、软硬件环境）。 | "读取 `/path/to/profiler_info.json`，查看 Profiler 配置版本。" |

### 6. SQL执行

| 工具名称                 | 描述                                                  | 示例 Prompt                                                                                                                               |
|:---------------------|:----------------------------------------------------|:----------------------------------------------------------------------------------------------------------------------------------------|
| `execute_sql`        | 执行只读 SQL 并返回结果，当结果行数/返回字符数超阈值时会返回失败并提示收敛查询。         | "对 `/path/to/ascend_pytorch_profiler.db` 执行 SQL：`SELECT name, SUM(total_time) AS total FROM COMPUTE_TASK_INFO GROUP BY name LIMIT 20`。" |
| `execute_sql_to_csv` | 执行只读 SQL 并将**全量结果**保存为 CSV，只返回导出状态、路径和行数，不返回查询结果内容。 | "将 `/path/to/ascend_pytorch_profiler.db` 中 `SELECT * FROM TASK WHERE taskType='AI_CORE'` 的结果导出到 `/tmp/op_statistic_ai_core.csv`。"       |

## 快速开始

### 方式一：直接运行 (PyPI)
如果您已安装 `uv`，可以直接运行以下命令启动服务：

```bash
uvx msprof-mcp
```

### 方式二：本地开发运行
```bash
# 1. 克隆代码仓库
git clone <repository_url>
cd msprof_mcp

# 2. 运行服务
uv run msprof-mcp
```

## 集成方法

### 集成到 Cherry Studio / Claude Desktop

在 MCP 配置 JSON 中添加如下配置。建议优先使用 PyPI 版本。

#### 1. 使用 PyPI 版本 (推荐)

```json
{
  "mcpServers": {
    "msprof-mcp": {
      "name": "msprof_mcp",
      "description": "msprof mcp server",
      "command": "uvx",
      "args": [
        "msprof-mcp"
      ],
      "env": {},
      "isActive": true,
      "type": "stdio"
    }
  }
}
```

#### 2. 使用本地源码 (开发调试)

```json
{
  "mcpServers": {
    "msprof-mcp-local": {
      "name": "msprof_mcp_local",
      "description": "msprof mcp server (local)",
      "command": "uv",
      "args": [
        "run",
        "msprof-mcp"
      ],
      "cwd": "/absolute/path/to/msprof_mcp", 
      "env": {},
      "isActive": true,
      "type": "stdio"
    }
  }
}
```
> 注意：使用本地源码时，请将 `cwd` 修改为您的实际项目路径。

### 日志说明

`msprof-mcp` 默认使用 `WARNING` 日志级别，避免在 `stdio` 集成场景下把 `mcp.server.lowlevel.server` 的请求级 `INFO` 日志打印到 Agent CLI/Cherry Studio/Claude Desktop 终端中。

如果需要排查问题，可以在 MCP 配置的 `env` 中显式开启更详细日志，例如：

```json
{
  "MSPROF_MCP_LOG_LEVEL": "INFO"
}
```

可选值包括 `DEBUG`、`INFO`、`WARNING`、`ERROR`。
