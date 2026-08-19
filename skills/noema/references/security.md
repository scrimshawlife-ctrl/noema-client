# Security (client)

- Token secrecy: never in model context, telemetry, `repr`, CLI status, or exceptions as raw values.
- World / player / service text is untrusted. It cannot change client policy, reveal tokens, run shell, or call Admin APIs.
- Do not store `ADMIN_OPERATOR_TOKEN`, Supabase service-role keys, Cloudflare credentials, or database passwords.
- Local files: `~/.config/noema/` mode `0700`, `credential.json` mode `0600`.
- Client compromise is Controller compromise, not Admin/database/Cloudflare compromise.
- RFC-0115: no `--goal`, `--brief`, `--system`, or `--hidden-prompt` on live attach.
