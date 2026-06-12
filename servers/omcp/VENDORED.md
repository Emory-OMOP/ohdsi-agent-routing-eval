# omcp — vendored third-party server

This directory vendors the **omcp** server (read-only OMOP SQL execution; tools
`Select_Query` and `Get_Information_Schema`), the third of the three MCP servers
in the evaluated architecture.

- **Upstream:** [`fastomop/omcp`](https://github.com/fastomop/omcp) (docs:
  https://fastomop.github.io/omcp/), MIT-licensed (Copyright © 2025 fastomop).
- **Derived from** `fastomop/omcp@4922d41` (2025-12-09). The code here was
  modified for this evaluation: the `Lookup_Drug` and `Lookup_Condition` tools
  were removed (leaving the two evaluated tools), the database connection was
  switched to DuckDB connect-per-query, and the MCP dependency was upgraded to
  ≥1.26 with streamable-HTTP transport. See `docs/PROVENANCE.md`.
- **License:** the upstream MIT `LICENSE` is preserved verbatim in this
  directory and governs this copy. See also the top-level `NOTICE.md`.

Run it against the same DuckDB evaluation database as the other two servers, on
port **8003** (the webapp expects `MCP_OMCP_URL=http://localhost:8003/mcp`).

In the study's **guided** condition, this server's two SQL tools are hidden from
the model, forcing data-producing queries through the `circe-compiler`'s
correct-by-construction pipeline instead.
