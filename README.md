# msprof mcp

## 简介
msprof mcp 服务器，用于分析Ascend性能瓶颈。

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