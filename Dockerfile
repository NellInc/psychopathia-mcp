# Container image for the Psychopathia Machinalis MCP server (stdio transport).
# Installs the published wheel from PyPI, which bundles the framework data
# under psychopathia_mcp/_data/, so no repo checkout is needed at runtime.
# Used by the Docker MCP Catalog and to de-risk Glama's sandboxed build.
FROM python:3.12-slim

# Pin to the release matching this repo state. Bump alongside pyproject version.
RUN pip install --no-cache-dir "psychopathia-mcp==0.1.0a4"

# The server speaks MCP over stdio; the console script is the entry point.
ENTRYPOINT ["psychopathia-mcp"]
