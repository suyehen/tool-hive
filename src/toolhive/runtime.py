# 启动 ToolHive 运行面（内网）

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "toolhive.main:runtime_app",
        host="127.0.0.1",
        port=8100,
        reload=True,
    )
