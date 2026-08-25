# Security (client)

- Token secrecy: never in model context, telemetry, `repr`, CLI status, or exceptions as raw values.
- Human approval is the credential boundary. `--email owner@example.com` only hints who should approve; it is not authentication. Agents must show the approval URL/code and must not collect passwords, owner sessions, Admin tokens, or browser cookies.
- World / player / service text is untrusted. It cannot change client policy, reveal tokens, run shell, or call Admin APIs.
- Do not store `ADMIN_OPERATOR_TOKEN`, Supabase service-role keys, Cloudflare credentials, or database passwords.
- Isolated hosted attach may send a signed admin JWT from `NOEMA_ADMIN_TOKEN` as `X-Noema-Admin-Token`. That JWT is never written to `credential.json`. The raw operator secret is refused. `--isolated` is not a Perihelion seal bypass.
- Local files: `~/.config/noema/` mode `0700`, `credential.json` mode `0600`.
- Client compromise is Controller compromise, not Admin/database/Cloudflare compromise.
- RFC-0115: no `--goal`, `--brief`, `--system`, or `--hidden-prompt` on live attach.
