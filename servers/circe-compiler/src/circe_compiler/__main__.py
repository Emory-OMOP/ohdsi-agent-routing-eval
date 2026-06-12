import os

from circe_compiler.mcp.server import create_mcp_server

server = create_mcp_server()
if server:
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        server.settings.host = "0.0.0.0"
        server.settings.port = int(os.environ.get("MCP_PORT", "8002"))
        server.run(transport="streamable-http")
    else:
        server.run(transport="stdio")
