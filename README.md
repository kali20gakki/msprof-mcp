# msprof mcp

## 简介
msprof mcp 服务器，提供LLM分析Ascend Pytoch Profiler采集的性能数据的能力。

## 目录结构
```
msprof_mcp/
├── server.py # mcp 服务器入口
├── tools/
│   ├── msprof_analyze_cmd.py # msprof-analyze 命令
│   ├── csv_analyze.py # csv 文件分析
│   ├── json_analyze.py # json 文件分析
│   └── trace_view_analyze.py # trace_view.json 文件分析
└── README.md
```

## 集成方法

### 场景一：集成到cherry studio
在cherry studio MCP 配置json添加如下配置：
```json
{
  "mcpServers": {
    "msprof-mcp": {
      "name": "msprof_mcp",
      "description": "msprof mcp server",
      "baseUrl": "",
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/repo/msprof_mcp",
        "run",
        "server.py"
      ],
      "env": {},
      "isActive": true,
      "type": "stdio",
      "registryUrl": "",
      "timeout": "6000",
      "longRunning": true
    }
  }
}
```