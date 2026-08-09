# 启动 ToolHive
#
# 管理面：
#   uv run python -m toolhive.management
#   或: uvicorn toolhive.main:management_app --host 0.0.0.0 --port 8101
#
# 运行面：
#   uv run python -m toolhive.runtime
#   或: uvicorn toolhive.main:runtime_app --host 127.0.0.1 --port 8100

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "toolhive.main:management_app",
        host="0.0.0.0",
        port=8101,
        reload=True,
    )
